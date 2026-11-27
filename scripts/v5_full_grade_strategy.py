"""Full-scope research grading and strategy gate. Offline, no orders or API.
Mirrors existing R14 grade score, separately from Stage6 quality and Stage7 valuation.
Market-cap derived ratios are research proxies, NOT official PER/PBR.
"""
import argparse, json
from decimal import Decimal as D, InvalidOperation
from pathlib import Path
from collections import Counter
from v5_evaluation_scope import validate_scope, validate_stage, index, require

ELIGIBLE='EVALUATE_COMMON_STOCK_RESEARCH_ONLY'
QUALITY='GROWTH_AND_HEALTH_CRITERIA_MET_RESEARCH_ONLY'


def dec(x):
    try:
        v=D(str(x)); return v if v.is_finite() else None
    except (InvalidOperation, ValueError): return None


def research_score(cap, annual, ttm, equity, prior, assets, liabilities):
    vals=list(map(dec,(cap,annual,ttm,equity,prior,assets,liabilities)))
    if None in vals: return None,'HOLD_SCORE_EVIDENCE_MISSING'
    cap,annual,ttm,equity,prior,assets,liabilities=vals
    if cap<D('100000000000') or min(annual,ttm,equity,prior,assets)<=0 or liabilities<0 or assets<=liabilities:
        return None,'HOLD_SCORE_NONPOSITIVE_OR_CONFLICTING_EVIDENCE'
    roe=100*annual/((equity+prior)/2); debt=100*liabilities/equity
    per=cap/ttm; pbr=cap/equity
    parts={'roe':25 if roe>=12 else 15 if roe>=8 else 0,
           'owner_equity_leverage':25 if debt<=80 else 15 if debt<=150 else 0,
           'ttm_vs_annual':25 if ttm>=annual else 15 if ttm>=annual*D('.85') else 0,
           'market_cap_ratio_proxy':25 if per<=12 and pbr<=D('1.5') else 15 if per<=20 and pbr<=3 else 0}
    score=sum(parts.values())
    return {'score':score,'research_grade':'A' if score>=85 else 'B' if score>=65 else None,
            'score_parts':parts},'RESEARCH_SCORE_COMPUTED'


def evaluate_grade(scope,financial,sector,market_rows,metrics,link):
    universe=validate_scope(scope); day=scope['market_date']
    for upstream in (financial,sector):
        validate_stage(scope,upstream)
        require(upstream.get('investment_decisions_authorized') is False and upstream.get('final_buy_signals')==0,'UPSTREAM_APPROVAL_INVALID')
    require(sector.get('verified_fair_prices')==0,'VERIFIED_PRICE_CONTRACT_NOT_IMPLEMENTED')
    f=index(financial['rows'],'code'); s=index(sector['rows'],'code'); m=index(market_rows,'ISU_CD'); mm=index(metrics,'code')
    require(set(m)==set(mm)==set(universe) and all(r['BAS_DD']==day for r in m.values()) and all(r['market_date']==day for r in mm.values()),'SOURCE_SCOPE_MISMATCH')
    inputs={}
    for k,v in link['inputs'].items(): inputs.setdefault(k.split(':')[0],[]).append(v)
    out=[]
    for code,sc in sorted(universe.items()):
        state=sc['scope_state']; fr=f[code]; sr=s[code]; mt=mm[code]
        r={'code':code,'market_date':day,'state':state,'financial_state':fr['state'],'sector_state':sr['state'],
           'research_grade':None,'score':None,'score_parts':None,'score_state':state,'strategy_state':state,
           'final_grade':None,'verified_fair_price':None,'entry_prices':None,'position_actions':None,
           'investment_authorized':False,'buy_signal':False,'sell_signal':False}
        out.append(r)
        if state!=ELIGIBLE:continue
        require(sr.get('verified_fair_price') is None and sr.get('final_grade') is None and sr.get('buy_signal') is False,'UNEXPECTED_SECTOR_APPROVAL')
        a=[x for x in inputs.get(code,[]) if x.get('period')=='annual' and x.get('receipt')==fr.get('annual_receipt') and x.get('corp_code')==mt.get('corp_code') and x.get('fs_div')==mt.get('fs_div')=='CFS']
        st=link['strict_ttm'].get(code,{})
        if fr.get('financial_evidence_state')!='ANNUAL_AND_TTM_LINKED_RESEARCH_ONLY' or len(a)!=1 or fr.get('ttm_receipts')!=st.get('receipts') or fr['state'] in ('HOLD_EVIDENCE_REVIEW','HOLD_DISCLOSURE_OR_IDENTITY'):
            score,reason=None,'HOLD_SCORE_RECEIPT_EVIDENCE'
        else:
            ac=a[0]['accounts']; t=st.get('ttm_profit')
            require(dec(t) is not None and dec(t)==dec(mt.get('ttm_owner_profit_krw')),'SCORE_TTM_CONFLICT')
            score,reason=research_score(m[code]['MKTCAP'],ac.get('profit'),t,ac.get('equity'),ac.get('previous_equity'),ac.get('assets'),ac.get('liabilities'))
        r['score_state']=reason
        if score:r.update(score)
        if not score: strategy=reason
        elif fr['state']!=QUALITY:strategy='HOLD_QUALITY_REVIEW'
        elif not r['research_grade']:strategy='BELOW_RESEARCH_B'
        else:strategy='HOLD_NO_VERIFIED_FAIR_PRICE'
        r.update(state=strategy,strategy_state=strategy)
    report={'market_date':day,'scope_sha256':scope['scope_sha256'],'rows':out,'financial_api_calls':0,
            'investment_decisions_authorized':False,'final_buy_signals':0,'final_sell_signals':0,'final_grades':0,
            'research_grade_counts':dict(Counter(r['research_grade'] for r in out if r['research_grade'])),
            'notes':['R14 scoring thresholds reused; owner-equity leverage is NOT total-equity debt ratio.',
                     'Market-cap ratios are proxies, not official ratios; research A/B is not a final grade.',
                     'No strategy price, position action or signal before a separately verified price/risk contract.']}
    report['counts']=validate_stage(scope,report)
    return report


def self_test():
    from v5_evaluation_scope import build_scope
    day='20261126'; codes=[f'{i:06d}' for i in range(1,11)]
    market=[{'ISU_CD':c,'BAS_DD':day,'MARKET':'KOSPI','MKTCAP':'100000000000' if c!=codes[-1] else '1'} for c in codes]
    cl={'market_date':day,'row_count':len(codes),'rows':[{'ISU_SRT_CD':c,'market':'KOSPI','KIND_STKCERT_TP_NM':'보통주','SECUGRP_NM':'주권'} for c in codes]}
    scope=build_scope(day,market,cl); rec=['20260319000001','20261113000001','20251113000001']; inputs={};strict={};metrics=[];fin=[];sector=[]
    for c,sc in zip(codes,scope['rows']):
        st=sc['scope_state']; eligible=st==ELIGIBLE
        inputs[c+':2025:annual']={'period':'annual','receipt':rec[0],'corp_code':'12345678','fs_div':'CFS','accounts':{'profit':10000000000,'equity':70000000000,'previous_equity':65000000000,'assets':90000000000,'liabilities':20000000000}}
        strict[c]={'receipts':rec,'ttm_profit':12000000000}
        metrics.append({'code':c,'market_date':day,'corp_code':'12345678','fs_div':'CFS','ttm_owner_profit_krw':'12000000000'})
        fin.append({'code':c,'market_date':day,'state':QUALITY if eligible else st,'financial_evidence_state':'ANNUAL_AND_TTM_LINKED_RESEARCH_ONLY','annual_receipt':rec[0],'ttm_receipts':rec})
        sector.append({'code':c,'market_date':day,'state':'PEER_RANGE_RESEARCH_ONLY' if eligible else st,'verified_fair_price':None,'final_grade':None,'buy_signal':False})
    fin[1]['state']='REVIEW_GROWTH_OR_HEALTH_RISK';fin[2]['financial_evidence_state']='ANNUAL_LINKED_RESEARCH_ONLY'
    inputs[codes[3]+':2025:annual']['accounts']['profit']=0
    def report(rows):return {'market_date':day,'scope_sha256':scope['scope_sha256'],'rows':rows,'investment_decisions_authorized':False,'final_buy_signals':0,'verified_fair_prices':0}
    def run(f=fin,s=sector):return evaluate_grade(scope,report(f),report(s),market,metrics,{'inputs':inputs,'strict_ttm':strict})
    result=run();rr=index(result['rows'],'code')
    assert len(rr)==10 and result['research_grade_counts']=={'A':7}
    assert rr[codes[0]]['score']==100 and rr[codes[0]]['strategy_state']=='HOLD_NO_VERIFIED_FAIR_PRICE'
    assert rr[codes[1]]['strategy_state']=='HOLD_QUALITY_REVIEW'
    assert rr[codes[2]]['strategy_state']=='HOLD_SCORE_RECEIPT_EVIDENCE'
    assert rr[codes[3]]['strategy_state']=='HOLD_SCORE_NONPOSITIVE_OR_CONFLICTING_EVIDENCE'
    assert rr[codes[-1]]['state']=='EXCLUDED_MARKET_CAP'
    assert all(r['final_grade'] is None and r['entry_prices'] is None and not r['buy_signal'] and not r['sell_signal'] for r in rr.values())
    assert research_score(100000000000,8000000000,8000000000,100000000000,100000000000,200000000000,100000000000)[0]['research_grade']=='B'
    assert research_score(100000000000,1,1,100,100,200,100)[0]['research_grade'] is None
    for fn in (lambda:run(fin[:-1]),lambda:run(s=[{**sector[0],'verified_fair_price':'1000'},*sector[1:]])):
        try:fn()
        except ValueError:pass
        else:raise AssertionError('EXPECTED_REJECTION')
    print('FULL_GRADE_STRATEGY_SELF_TEST_PASS 11')


def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.self_test:self_test();return
    p.error('Use evaluate_grade from the integrated workflow; no standalone live execution.')

if __name__=='__main__':main()
