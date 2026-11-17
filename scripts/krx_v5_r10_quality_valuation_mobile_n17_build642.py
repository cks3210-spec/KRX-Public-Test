#!/usr/bin/env python3
"""KRX v5 R10: read-only R9 financial quality / valuation evidence audit.
No official PER/PBR claim without independent official evidence. No trading signals.
"""
import csv, datetime as dt, json, os, pathlib, re, sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

ROOT=pathlib.Path(__file__).resolve().parents[1]
R9=ROOT/'data/v5_financial_r9'
OUT=ROOT/'data/v5_financial_r10'
NOW=dt.datetime.now(ZoneInfo('Asia/Seoul'))
FIELDS=['stock_code','name','market','sector_proxy','financial_year','financial_report','fs_div','quality_state','quality_flags','profit_basis','equity_basis','annual_profit','annual_equity','annual_assets','annual_liabilities','annual_revenue','reference_pe','reference_pb','reference_roe_pct','reference_debt_pct','ttm_profit','ttm_state','official_per','official_pbr','official_verification','valuation_gap_pct','provisional_grade','final_grade','buy_signal']

def read_json(p):
    v=json.loads(p.read_text(encoding='utf-8'))
    if not isinstance(v,dict): raise ValueError(f'JSON must be an object: {p}')
    return v

def number(v):
    if v is None or str(v).strip() in ('','-','None','nan'): return None
    try:
        n=Decimal(str(v).replace(',','').strip())
        return n if n.is_finite() else None
    except (InvalidOperation,ValueError): return None

def fmt(n): return '' if n is None else str(round(n,4))

def read_csv(p):
    with p.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

def write_csv(p, rows, fields):
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)

def audit_one(m, rec, target_year, market_stale):
    code=m.get('ISU_CD','')
    flags=[]
    if not re.fullmatch(r'\d{6}',code): flags.append('INVALID_STOCK_CODE')
    if not isinstance(rec,dict): rec={}
    if not rec: flags.append('NO_ANNUAL_RECORD')
    if rec and rec.get('state')!='FINANCIAL_FIELDS_FOUND': flags.append('FINANCIAL_STATE_NOT_COMPLETE')
    if rec and str(rec.get('year',''))!=str(target_year): flags.append('ANNUAL_YEAR_MISMATCH')
    if rec and rec.get('report')!='11011': flags.append('NOT_ANNUAL_REPORT')
    if rec and rec.get('fs_div')!='CFS': flags.append('NOT_CONSOLIDATED')
    nums={k:number(rec.get(k)) for k in ('profit','equity','assets','liabilities','revenue')}
    if rec:
        for k in ('profit','equity','assets','liabilities'):
            if nums[k] is None: flags.append('MISSING_'+k.upper())
        if nums['equity'] is not None and nums['equity']<=0: flags.append('NONPOSITIVE_EQUITY')
        if nums['assets'] is not None and nums['liabilities'] is not None and nums['equity'] is not None:
            gap=abs(nums['assets']-nums['liabilities']-nums['equity'])
            if gap>max(Decimal('1000000'),abs(nums['assets'])*Decimal('0.02')): flags.append('BALANCE_SHEET_INCONSISTENT')
    cap=number(m.get('MKTCAP'))
    if cap is None or cap<Decimal('100000000000'): flags.append('MARKET_CAP_NOT_ELIGIBLE')
    if market_stale: flags.append('STALE_MARKET_PRICE')
    # R9's financial helper does not document owner-attributable earnings/equity.
    # Therefore all price multiples are only broad consolidated reference ratios.
    pe=cap/nums['profit'] if cap is not None and nums['profit'] is not None and nums['profit']>0 else None
    pb=cap/nums['equity'] if cap is not None and nums['equity'] is not None and nums['equity']>0 else None
    roe=nums['profit']/nums['equity']*100 if nums['profit'] is not None and nums['equity'] is not None and nums['equity']>0 else None
    debt=nums['liabilities']/nums['equity']*100 if nums['liabilities'] is not None and nums['equity'] is not None and nums['equity']>0 else None
    if pe is None: flags.append('REFERENCE_PE_UNAVAILABLE')
    if pb is None: flags.append('REFERENCE_PB_UNAVAILABLE')
    flags+=['OWNER_ATTRIBUTION_UNVERIFIED','OFFICIAL_PER_PBR_UNVERIFIED','SECTOR_CLASSIFICATION_UNVERIFIED','SHARE_CLASS_UNVERIFIED']
    # Financial institutions have different leverage meaning; do not grade using uniform debt thresholds.
    name=m.get('ISU_NM','')
    finance=bool(re.search(r'금융|은행|증권|보험|캐피탈|저축은행|지주',name))
    if finance: flags.append('FINANCIAL_SECTOR_REQUIRES_SPECIAL_MODEL')
    if m.get('MARKET') not in ('KOSPI','KOSDAQ'): flags.append('UNKNOWN_MARKET')
    if re.search(r'(?:우|우B|우C|우선주|[0-9]우)$',name): flags.append('POSSIBLE_PREFERRED_SHARE')
    core_bad={'NO_ANNUAL_RECORD','FINANCIAL_STATE_NOT_COMPLETE','ANNUAL_YEAR_MISMATCH','NOT_ANNUAL_REPORT','NOT_CONSOLIDATED','MISSING_PROFIT','MISSING_EQUITY','MISSING_ASSETS','MISSING_LIABILITIES','NONPOSITIVE_EQUITY','BALANCE_SHEET_INCONSISTENT'}
    quality='REVIEW' if core_bad.intersection(flags) else 'ANNUAL_FIELDS_PRESENT'
    grade=''
    if quality=='ANNUAL_FIELDS_PRESENT' and not finance and 'POSSIBLE_PREFERRED_SHARE' not in flags and all(x is not None for x in (pe,pb,roe,debt)):
        score=sum((roe>=12,0<pe<=18,0<pb<=Decimal('2.5'),debt<=150))
        grade='A' if score==4 else 'B+' if score==3 else 'B' if score==2 else ''
    return dict(stock_code=code,name=name,market=m.get('MARKET',''),sector_proxy='FINANCIAL_NAME_HEURISTIC' if finance else 'UNCLASSIFIED',financial_year=rec.get('year',''),financial_report=rec.get('report',''),fs_div=rec.get('fs_div',''),quality_state=quality,quality_flags=';'.join(flags),profit_basis='CONSOLIDATED_TOTAL_UNVERIFIED',equity_basis='CONSOLIDATED_TOTAL_UNVERIFIED',annual_profit=fmt(nums['profit']),annual_equity=fmt(nums['equity']),annual_assets=fmt(nums['assets']),annual_liabilities=fmt(nums['liabilities']),annual_revenue=fmt(nums['revenue']),reference_pe=fmt(pe),reference_pb=fmt(pb),reference_roe_pct=fmt(roe),reference_debt_pct=fmt(debt),ttm_profit='',ttm_state='NOT_COMPUTABLE_WITHOUT_MATCHED_YTD_PERIODS',official_per='',official_pbr='',official_verification='NOT_VERIFIED',valuation_gap_pct='',provisional_grade=grade,final_grade='WITHHELD',buy_signal='NONE')

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    status={'version':'R10','generated_kst':NOW.isoformat(),'state':'STARTED','r9_cache_modified':False,'official_per_pbr_verified':0,'final_grades':0,'buy_signals':0}
    try:
        annual=read_json(R9/'annual_financial_cache.json')
        r9status=read_json(R9/'status.json')
        market=read_csv(ROOT/'data/latest.csv')
        if not market: raise RuntimeError('data/latest.csv is empty')
        dates={r.get('BAS_DD','') for r in market}
        if len(dates)!=1: raise RuntimeError('Market date inconsistent')
        market_date=next(iter(dates))
        if not re.fullmatch(r'\d{8}',market_date): raise RuntimeError('Market date malformed')
        year=int(market_date[:4])-1
        input_date_mismatch=bool(r9status.get('market_date') and r9status['market_date']!=market_date)
        stale=bool(r9status.get('market_snapshot_stale')) or input_date_mismatch
        eligible=[m for m in market if re.fullmatch(r'\d{6}',m.get('ISU_CD','')) and (number(m.get('MKTCAP')) or 0)>=Decimal('100000000000')]
        codes=[m['ISU_CD'] for m in eligible]
        if len(codes)!=len(set(codes)): raise RuntimeError('Duplicate eligible codes')
        if not eligible: raise RuntimeError('No eligible market universe')
        rows=[audit_one(m,annual.get(m['ISU_CD'],{}),year,stale) for m in eligible]
        watch=[r for r in rows if r['provisional_grade']]
        write_csv(OUT/'financial_quality_audit.csv',rows,FIELDS)
        write_csv(OUT/'provisional_ab_research_only.csv',watch,FIELDS)
        bymarket={}
        for mk in ('KOSPI','KOSDAQ'):
            rr=[r for r in rows if r['market']==mk]
            bymarket[mk]={'eligible':len(rr),'annual_fields_present':sum(r['quality_state']=='ANNUAL_FIELDS_PRESENT' for r in rr),'provisional_ab':sum(bool(r['provisional_grade']) for r in rr)}
        issues=Counter(flag for r in rows for flag in r['quality_flags'].split(';') if flag)
        status.update(state='RESEARCH_ONLY_NOT_FINAL',market_date=market_date,market_snapshot_stale=stale,r9_status_market_date=r9status.get('market_date'),input_date_mismatch=input_date_mismatch,annual_year=year,eligible_rows=len(rows),annual_cache_entries=len(annual),annual_fields_present=sum(r['quality_state']=='ANNUAL_FIELDS_PRESENT' for r in rows),provisional_ab_count=len(watch),market_breakdown=bymarket,issue_counts=dict(issues),ttm_computable=0,official_source_used=False,limitations=['No period-matched prior-year and current-year YTD inputs; TTM withheld','Owner-attributable income and equity not identified; multiples are reference-only','No independent official PER/PBR source; comparison withheld','Sector is a name heuristic only; financial-sector grading withheld','Stale market prices cannot support current valuation or trading','Preferred-share exclusion is heuristic only; no official class verification'])
        (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(status,ensure_ascii=False,indent=2))
    except Exception as e:
        status.update(state='FAILED',error=str(e))
        (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
        raise
if __name__=='__main__': main()
