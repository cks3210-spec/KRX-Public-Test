"""Offline full-universe financial adapter. Existing archives only; no API calls.
Does not change legacy Stage6 reports or authorize valuation/trades.
"""
import argparse, csv, json, re
from collections import Counter
from pathlib import Path
from decimal import Decimal as D, InvalidOperation
from v5_evaluation_scope import (build_scope, validate_scope, validate_stage,
                                 file_sha, require, valid_day, index)

ELIGIBLE = 'EVALUATE_COMMON_STOCK_RESEARCH_ONLY'
BASE = 'data/v5_financial_m/filing_refresh/'
METRIC_KEYS = ('revenue_yoy_pct','owner_profit_yoy_pct','operating_profit_yoy_pct',
               'annual_owner_roe_pct','operating_margin_pct','liabilities_to_total_equity_pct')


def read(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))


def csv_rows(p):
    with p.open(encoding='utf-8-sig', newline='') as f:
        rd = csv.DictReader(f)
        require(rd.fieldnames and len(set(rd.fieldnames)) == len(rd.fieldnames), 'INVALID_HEADER')
        result = list(rd)
        require(all(None not in r and None not in r.values() for r in result), 'INVALID_CSV_ROW')
        return result


def dec(x):
    try:
        v = D(str(x)); return v if v.is_finite() else None
    except (InvalidOperation, ValueError): return None


def receipt_ok(r, day):
    return isinstance(r,str) and bool(re.fullmatch(r'\d{14}',r)) and r[:8] <= day


def load_sources(root):
    root = root.resolve(); hashes = {}
    def bound(rel, expected=None):
        p = (root / rel).resolve()
        require(p.is_relative_to(root) and p.is_file(), 'SOURCE_MISSING_OR_OUTSIDE_ROOT')
        h = file_sha(p)
        if expected is not None: require(h == expected, 'SOURCE_HASH_MISMATCH '+str(rel))
        hashes[str(p.relative_to(root))] = h
        return p
    sp=bound('data/summary.json'); mp=bound('data/latest.csv')
    summary=read(sp); day=valid_day(summary['latest_trading_date']); market=csv_rows(mp)
    require(len(market)==summary['kospi_rows_latest']+summary['kosdaq_rows_latest'],'MARKET_COUNT_MISMATCH')
    paths=sorted(p for p in (root/'data/v5_official_shareclass_archive').glob('*.json') if re.fullmatch(r'20\d{6}',p.stem) and p.stem<=day)
    cl=None
    if paths:
        cl=read(bound(paths[-1].relative_to(root)));require(cl['market_date']==paths[-1].stem,'CLASS_DATE_MISMATCH')
    scope=build_scope(day,market,cl,dict(hashes))
    ms=read(bound(BASE+'metrics/latest_status.json'))
    qs=read(bound(BASE+'candidate_regrade/latest_status.json'))
    require(ms['market_date']==qs['market_date']==day and ms['state']=='FINANCIAL_METRICS_PERSISTED' and qs['state']=='CANDIDATE_RESEARCH_REGRADE_PERSISTED','UPSTREAM_DATE_OR_STATE_MISMATCH')
    for status in (ms,qs):
        require(status['market_rows']==len(market) and status['investment_decisions_authorized'] is False and status['final_buy_signals']==0,'UPSTREAM_SCOPE_OR_APPROVAL')
        require(status['source_sha256']['data/latest.csv']==hashes['data/latest.csv'],'MARKET_HASH_MISMATCH')
    metrics=csv_rows(bound(ms['csv_path'],ms['csv_sha256']))
    require(qs['source_sha256'][ms['csv_path']]==ms['csv_sha256'],'METRICS_CHAIN_MISMATCH')
    link_path=BASE+'analysis_link.json'
    require(ms['source_sha256'][link_path]==qs['source_sha256'][link_path],'LINK_HASH_CONFLICT')
    link=read(bound(link_path,ms['source_sha256'][link_path]))
    hold=read(bound(qs['hold_path'],qs['hold_sha256']))
    require(link['market_date']==hold['market_date']==day,'FINANCIAL_LINK_DATE_MISMATCH')
    require(link['investment_decisions_authorized'] is False and link['final_buy_signals']==0,'UNEXPECTED_LINK_APPROVAL')
    require(all(file_sha(root/p)==h for p,h in hashes.items()),'SOURCE_CHANGED')
    return scope,metrics,link,hold['holds'],hashes


def evaluate(scope, metrics, link, holds):
    universe=validate_scope(scope); day=scope['market_date']; met=index(metrics,'code'); held=index(holds,'code')
    require(set(met)==set(universe) and all(r['market_date']==day for r in met.values()),'METRICS_SCOPE_MISMATCH')
    require(set(held)<=set(universe),'HELD_SCOPE_MISMATCH')
    inputs=link['inputs']; decisions=link['decisions']; strict=link['strict_ttm']
    by_code={}
    for key,x in inputs.items():
        code=key.split(':')[0]; by_code.setdefault(code,[]).append((key,x))
    rows=[]
    for code,s in sorted(universe.items()):
        m=met[code]; reason=held.get(code,{}).get('reason'); state=s['scope_state']
        row={'code':code,'market_date':day,'state':state,'legacy_hold_reason':reason,
             'available_metric_fields':[], 'growth_state':state,'health_state':state,
             'financial_evidence_state':state,'missing_evidence':[], 'risk_flags':[],
             'annual_receipt':None,'ttm_receipts':[], 'final_grade':None,'buy_signal':False}
        rows.append(row)
        if state!=ELIGIBLE: continue
        require(m.get('investment_authorized')=='NO' and m.get('financial_disclosure_asof_verified')=='NO','UNEXPECTED_METRIC_APPROVAL')
        vals={k:dec(m.get(k)) for k in METRIC_KEYS}
        row['available_metric_fields']=[k for k,v in vals.items() if v is not None]
        if reason in ('EXISTING_CORRECTION_EXCLUSION','IDENTITY_REVIEW') or m.get('annual_state')=='IDENTITY_REVIEW':
            row.update(state='HOLD_DISCLOSURE_OR_IDENTITY',growth_state='HOLD_DISCLOSURE_OR_IDENTITY',health_state='HOLD_DISCLOSURE_OR_IDENTITY',financial_evidence_state='HOLD_DISCLOSURE_OR_IDENTITY');continue
        annual=[]
        for key,x in by_code.get(code,[]):
            if x.get('receipt')==m.get('annual_receipt') and x.get('period')=='annual' and str(x.get('year'))==m.get('year') and x.get('corp_code')==m.get('corp_code') and x.get('fs_div')==m.get('fs_div')=='CFS' and x.get('amount_basis')=='ANNUAL' and receipt_ok(x.get('receipt'),day) and decisions.get(key,{}).get('receipt')==x.get('receipt'):
                annual.append(x)
        if len(annual)!=1 or m.get('annual_source')!='RECEIPT_BOUND_ARCHIVE_RESEARCH_ONLY':
            row.update(state='HOLD_ANNUAL_RECEIPT_EVIDENCE',growth_state='HOLD_ANNUAL_RECEIPT_EVIDENCE',health_state='HOLD_ANNUAL_RECEIPT_EVIDENCE',financial_evidence_state='HOLD_ANNUAL_RECEIPT_EVIDENCE',missing_evidence=['receipt_bound_annual']);continue
        a=annual[0]; ac=a['accounts']; row['annual_receipt']=a['receipt']; row['financial_evidence_state']='ANNUAL_LINKED_RESEARCH_ONLY'
        st=strict.get(code,{}); rec=st.get('receipts',[]); matched=[]
        if isinstance(rec,list) and len(rec)==3 and len(set(rec))==3 and rec[0]==a['receipt'] and st.get('fs_div')=='CFS' and all(receipt_ok(x,day) for x in rec):
            for receipt in rec[1:]:
                hits=[x for k,x in by_code.get(code,[]) if x.get('receipt')==receipt and x.get('corp_code')==m.get('corp_code') and x.get('fs_div')=='CFS' and x.get('amount_basis')=='CUMULATIVE_INTERIM_IS_CIS' and decisions.get(k,{}).get('receipt')==receipt]
                if len(hits)==1: matched.append(hits[0])
        annual_profit=dec(ac.get('profit')); ttm=None
        if len(matched)==2:
            cur,prior=matched; p1=dec(cur['accounts'].get('profit'));p0=dec(prior['accounts'].get('profit'))
            if cur.get('period')==prior.get('period') and cur.get('year')==a['year']+1 and prior.get('year')==a['year'] and None not in (annual_profit,p1,p0):
                calc=annual_profit+p1-p0
                if calc==dec(st.get('ttm_profit'))==dec(m.get('ttm_owner_profit_krw')) and m.get('ttm_state')=='RECEIPT_BOUND_CUMULATIVE_RESEARCH_ONLY':
                    ttm=calc;row['ttm_receipts']=rec;row['financial_evidence_state']='ANNUAL_AND_TTM_LINKED_RESEARCH_ONLY'
        # Same existing Stage6 criteria; prior A/B score is not an input.
        if m.get('operating_profit_source')!='RECEIPT_BOUND_ANNUAL': vals['operating_profit_yoy_pct']=None
        growth=[vals[k] for k in METRIC_KEYS[:3]]; miss=[]; risk=[]; health_risk=[]; conflicts=[]; warnings=[]
        for k,v in zip(METRIC_KEYS[:3],growth):
            if v is None: miss.append(k)
            elif v<0: risk.append(k.upper()+'_NEGATIVE')
        if ttm is None: miss.append('receipt_bound_ttm')
        if annual_profit is None: miss.append('annual_profit')
        elif annual_profit<=0: health_risk.append('ANNUAL_NONPOSITIVE_PROFIT')
        if ttm is not None and ttm<=0: health_risk.append('TTM_NONPOSITIVE_PROFIT')
        if ttm is not None and annual_profit is not None and ttm<annual_profit: risk.append('TTM_BELOW_ANNUAL_NOT_YOY')
        assets,liab,owner,prev=[dec(ac.get(k)) for k in ('assets','liabilities','equity','previous_equity')]
        for k,v in [('assets',assets),('liabilities',liab),('owner_equity',owner),('prior_owner_equity',prev),*[(k,vals[k]) for k in METRIC_KEYS[3:]]]:
            if v is None: miss.append(k)
        debt=vals['liabilities_to_total_equity_pct']; roe=vals['annual_owner_roe_pct']; margin=vals['operating_margin_pct']
        if assets is not None and assets<=0: conflicts.append('NONPOSITIVE_ASSETS')
        if liab is not None and liab<0: conflicts.append('NEGATIVE_LIABILITIES')
        if assets is not None and liab is not None:
            total=assets-liab
            if total<=0: health_risk.append('NONPOSITIVE_TOTAL_EQUITY')
            elif debt is not None and abs(liab/total*100-debt)>D('.10'): conflicts.append('TOTAL_EQUITY_DEBT_RATIO_MISMATCH')
        if debt is not None:
            if debt<0: conflicts.append('NEGATIVE_DEBT_RATIO')
            elif debt>=200: health_risk.append('HIGH_TOTAL_EQUITY_DEBT_RATIO')
        if owner is not None and owner<=0: health_risk.append('NONPOSITIVE_OWNER_EQUITY')
        if owner is not None and prev is not None and prev>0 and owner<prev: health_risk.append('OWNER_EQUITY_DECLINE')
        if roe is not None:
            if roe<=0: health_risk.append('NONPOSITIVE_OWNER_ROE')
            elif roe<5: warnings.append('LOW_OWNER_ROE_REVIEW')
        if margin is not None and margin<=0: risk.append('NONPOSITIVE_OPERATING_MARGIN');health_risk.append('NONPOSITIVE_OPERATING_MARGIN')
        gs='REVIEW_GROWTH_RISK' if risk else 'REVIEW_MISSING_EVIDENCE' if any(v is None for v in growth) or ttm is None or annual_profit is None or debt is None else 'CONSISTENT_GROWTH_RESEARCH_ONLY' if all(v>0 for v in growth) and ttm>=annual_profit else 'REVIEW_FLAT_GROWTH'
        hs='HOLD_FINANCIAL_EVIDENCE_CONFLICT' if conflicts else 'REVIEW_FINANCIAL_HEALTH_RISK' if health_risk else 'REVIEW_MISSING_HEALTH_EVIDENCE' if miss else 'REVIEW_FINANCIAL_HEALTH_WARNING' if warnings else 'HEALTH_CRITERIA_MET_RESEARCH_ONLY'
        combined='HOLD_EVIDENCE_REVIEW' if conflicts else 'REVIEW_GROWTH_OR_HEALTH_RISK' if risk or health_risk else 'REVIEW_INCOMPLETE_OR_WEAK_QUALITY' if miss or warnings or gs!='CONSISTENT_GROWTH_RESEARCH_ONLY' else 'GROWTH_AND_HEALTH_CRITERIA_MET_RESEARCH_ONLY'
        row.update(state=combined,growth_state=gs,health_state=hs,missing_evidence=sorted(set(miss)),risk_flags=sorted(set(risk+health_risk+conflicts+warnings)))
    report={'market_date':day,'scope_sha256':scope['scope_sha256'],'rows':rows,'financial_api_calls':0,'investment_decisions_authorized':False,'final_buy_signals':0,'financial_disclosure_asof_verified':False,'notes':['Existing receipt-linked research data only; no independent as-of verification.','Legacy metrics are inventoried but not promoted. Prior A/B grade is not an eligibility gate.','All market codes retained; no KIS data or final valuation.']}
    report['counts']=validate_stage(scope,report)
    return report


def self_test():
    day='20261126'; codes=['000001','000002','000003','000004','000005']
    market=[{'ISU_CD':k,'BAS_DD':day,'MKTCAP':'100000000000' if k!='000005' else '1','MARKET':'KOSPI'} for k in codes]
    cl={'market_date':day,'row_count':5,'rows':[{'ISU_SRT_CD':k,'market':'KOSPI','KIND_STKCERT_TP_NM':'보통주','SECUGRP_NM':'주권'} for k in codes]}
    scope=build_scope(day,market,cl); inputs={}; decisions={}; strict={}; metrics=[]
    for k in codes:
        rec=['20260319000001','20261113000001','20251113000001']; base={'corp_code':'12345678','fs_div':'CFS'}
        for y,p,r,ac in [(2025,'annual',rec[0],{'profit':100,'assets':1500,'liabilities':500,'equity':950,'previous_equity':900}),(2026,'q3',rec[1],{'profit':90}),(2025,'q3',rec[2],{'profit':70})]:
            key=f'{k}:{y}:{p}';inputs[key]={**base,'year':y,'period':p,'receipt':r,'amount_basis':'ANNUAL' if p=='annual' else 'CUMULATIVE_INTERIM_IS_CIS','accounts':ac};decisions[key]={'receipt':r}
        strict[k]={'fs_div':'CFS','receipts':rec,'ttm_profit':120}
        metrics.append({**base,'code':k,'market_date':day,'year':'2025','annual_receipt':rec[0],'annual_source':'RECEIPT_BOUND_ARCHIVE_RESEARCH_ONLY','ttm_state':'RECEIPT_BOUND_CUMULATIVE_RESEARCH_ONLY','ttm_owner_profit_krw':'120','investment_authorized':'NO','financial_disclosure_asof_verified':'NO','operating_profit_source':'RECEIPT_BOUND_ANNUAL',**{x:'10' for x in METRIC_KEYS},'liabilities_to_total_equity_pct':'50'})
    metrics[1]['annual_source']='LEGACY_CACHE_RESEARCH_ONLY';metrics[2]['ttm_owner_profit_krw']='119';metrics[3]['liabilities_to_total_equity_pct']='51'
    link={'inputs':inputs,'decisions':decisions,'strict_ttm':strict}
    r=evaluate(scope,metrics,link,[]); rr=index(r['rows'],'code')
    assert len(rr)==5
    assert rr[codes[0]]['state']=='GROWTH_AND_HEALTH_CRITERIA_MET_RESEARCH_ONLY'
    assert rr[codes[1]]['state']=='HOLD_ANNUAL_RECEIPT_EVIDENCE'
    assert rr[codes[2]]['state']=='REVIEW_INCOMPLETE_OR_WEAK_QUALITY'
    assert rr[codes[3]]['state']=='HOLD_EVIDENCE_REVIEW'
    assert rr[codes[4]]['state']=='EXCLUDED_MARKET_CAP'
    assert evaluate(scope,metrics,link,[{'code':codes[0],'reason':'EXISTING_CORRECTION_EXCLUSION'}])['rows'][0]['state']=='HOLD_DISCLOSURE_OR_IDENTITY'
    try: evaluate(scope,metrics[:-1],link,[])
    except ValueError: pass
    else: raise AssertionError('MISSING_CODE_ACCEPTED')
    assert all(x['final_grade'] is None and not x['buy_signal'] for x in rr.values())
    print('FULL_FINANCIAL_SELF_TEST_PASS 9')


def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--root',type=Path,default=Path.cwd());p.add_argument('--out',type=Path);a=p.parse_args()
    if a.self_test:self_test();return
    require(a.out is not None,'OUTPUT_REQUIRED')
    scope,metrics,link,holds,hashes=load_sources(a.root)
    report=evaluate(scope,metrics,link,holds);report['source_sha256']=hashes
    a.out.mkdir(parents=True,exist_ok=True)
    for name,data in [('scope.json',scope),('financial_report.json',report)]: (a.out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'market_date':report['market_date'],'scope_counts':scope['counts'],'financial_counts':report['counts'],'financial_api_calls':0},ensure_ascii=False))

if __name__=='__main__':main()
