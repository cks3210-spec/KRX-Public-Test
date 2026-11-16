#!/usr/bin/env python3
"""R7: independent annual/interim financial cache bridge. No final investment advice."""
import csv, datetime as dt, importlib.util, json, os, pathlib, re, sys
from decimal import Decimal
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'data/v5_financial_r7'
NOW=dt.datetime.now(ZoneInfo('Asia/Seoul'))
R4=ROOT/'scripts/krx_v5_fullmarket_research_r4_20261116.py'
spec=importlib.util.spec_from_file_location('r4_helpers',R4)
r4=importlib.util.module_from_spec(spec);spec.loader.exec_module(r4)

def save(path,obj):
 path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
def load(path):
 try:return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
 except (ValueError,OSError):raise RuntimeError('Invalid cache: '+str(path))
def age(x):
 try:return (NOW-dt.datetime.fromisoformat(x['checked_at_kst'])).total_seconds()/86400
 except (KeyError,ValueError,TypeError):return 99999
def valid(x):return isinstance(x,dict) and x.get('state')=='FINANCIAL_FIELDS_FOUND' and r4.num(x.get('profit')) is not None and r4.num(x.get('equity')) is not None
def main():
 status={'version':'R7','generated_kst':NOW.isoformat(),'state':'STARTED','official_per_pbr_verified':0,'final_grades':0,'buy_signals':0}
 try:
  market=r4.readcsv(ROOT/'data/latest.csv');dates={r.get('BAS_DD','') for r in market}
  if len(market)<1500 or len(dates)!=1 or not re.fullmatch(r'20\d{6}',next(iter(dates),'')):raise ValueError('Full market snapshot unavailable')
  day=next(iter(dates));year=int(day[:4]);status['market_date']=day
  eligible=[m for m in market if (r4.num(m.get('MKTCAP')) or 0)>=Decimal('100000000000') and re.fullmatch(r'\d{6}',m.get('ISU_CD',''))]
  if len({m['ISU_CD'] for m in eligible})!=len(eligible):raise ValueError('Duplicate eligible codes')
  annual_path=OUT/'annual_financial_cache.json';interim_path=OUT/'interim_financial_cache.json';attempt_path=OUT/'request_attempts.json'
  annual=load(annual_path);interim=load(interim_path);attempts=load(attempt_path)
  legacy={}
  for p in (ROOT/'data/v5_fullmarket_r4/dart_financial_cache.json',ROOT/'data/v5_financial_r6/dart_financial_cache.json'):
   for code,rec in load(p).items():
    if not isinstance(rec,dict) or not valid(rec):continue
    target=annual if rec.get('report')=='11011' else interim
    if code not in target or age(rec)<age(target[code]):target[code]=rec.copy()
  key=os.getenv('DART_API_KEY','').strip();mapping={};errors=[]
  if key:
   try:mapping=r4.corp_map(key)
   except Exception as exc:errors.append('CORP_MAP '+str(exc)[:150])
  else:errors.append('DART_API_KEY missing')
  budget=max(0,min(300,int(os.getenv('DART_MAX_REQUESTS','120'))));fresh=max(1,int(os.getenv('R7_REFRESH_DAYS','90')))
  calls=0;updated_annual=0;updated_interim=0;companies_attempted=0
  # Prioritize missing annual financials. Annual 2025 becomes available after filing, not before.
  annual_year=year-1
  # At 2026-11, latest interim Q3 (11014). Only request if market date is after statutory filing period.
  interim_report='11014' if int(day[4:6])>=11 else '11012' if int(day[4:6])>=8 else '11013' if int(day[4:6])>=5 else ''
  tasks=[]
  for m in eligible:
   code=m['ISU_CD']
   if code not in mapping:continue
   a=annual.get(code,{})
   if not (valid(a) and a.get('year')==str(annual_year) and age(a)<fresh):tasks.append((0,code,str(annual_year),'11011','annual'))
  for m in eligible:
   code=m['ISU_CD']
   if code not in mapping or not interim_report:continue
   i=interim.get(code,{})
   if not (valid(i) and i.get('year')==str(year) and i.get('report')==interim_report and age(i)<fresh):tasks.append((1,code,str(year),interim_report,'interim'))
  # Retry missing reports after 7 days; do not spend daily budget on known unavailable filings.
  tasks=[t for t in tasks if age(attempts.get('|'.join(t[1:4]),{}))>=7]
  for _,code,yr,report,kind in tasks:
   if calls>=budget:break
   calls+=1;companies_attempted+=1;akey='|'.join((code,yr,report))
   attempts[akey]={'checked_at_kst':NOW.isoformat(),'market_date':day}
   try:
    rec=r4.financial(key,mapping[code],yr,report)
    rec.update(corp_code=mapping[code],checked_at_kst=NOW.isoformat(),asof_market_date=day)
    if valid(rec):
     dest=annual if kind=='annual' else interim
     if not valid(dest.get(code,{})) or int(dest[code].get('year','0'))<=int(yr):
      dest[code]=rec
      if kind=='annual':updated_annual+=1
      else:updated_interim+=1
    elif rec.get('state') not in ('NO_REPORT','PARTIAL'):errors.append(code+' '+rec.get('state','UNKNOWN'))
   except Exception as exc:errors.append(code+' '+str(exc)[:120])
   if calls%10==0:
    save(annual_path,annual);save(interim_path,interim);save(attempt_path,attempts)
  save(annual_path,annual);save(interim_path,interim);save(attempt_path,attempts)
  rows=[];watch=[]
  for m in eligible:
   code=m['ISU_CD'];a=annual.get(code,{});i=interim.get(code,{})
   # Annual income and annual balance sheet must be from same annual filing.
   current=valid(a) and a.get('year')==str(annual_year) and a.get('report')=='11011'
   cap=r4.num(m.get('MKTCAP'));profit=r4.num(a.get('profit')) if current else None;equity=r4.num(a.get('equity')) if current else None
   liabilities=r4.num(a.get('liabilities')) if current else None
   pe=cap/profit if cap is not None and profit is not None and profit>0 else None
   pb=cap/equity if cap is not None and equity is not None and equity>0 else None
   roe=profit/equity*100 if profit is not None and equity is not None and equity>0 else None
   debt=liabilities/equity*100 if liabilities is not None and equity is not None and equity>0 else None
   grade=''
   if all(x is not None for x in (pe,pb,roe,debt)):
    score=sum((roe>=12,pe<=18,pb<=Decimal('2.5'),debt<=150))
    grade='A' if score==4 else 'B+' if score==3 else 'B' if score==2 else ''
   row={'BAS_DD':day,'MARKET':m.get('MARKET',''),'ISU_CD':code,'ISU_NM':m.get('ISU_NM',''),'MKTCAP':m.get('MKTCAP',''),'TDD_CLSPRC':m.get('TDD_CLSPRC',''),
        'annual_year':a.get('year',''),'annual_state':a.get('state','MISSING'),'annual_report':a.get('report',''),
        'interim_year':i.get('year',''),'interim_report':i.get('report',''),'interim_state':i.get('state','MISSING'),
        'annual_reference_pe':str(round(pe,3)) if pe is not None else '', 'annual_reference_pb':str(round(pb,3)) if pb is not None else '',
        'annual_reference_roe_pct':str(round(roe,3)) if roe is not None else '', 'annual_reference_debt_pct':str(round(debt,3)) if debt is not None else '',
        'provisional_grade':grade,'final_grade':'WITHHELD','buy_signal':'NONE','flags':'OFFICIAL_PER_PBR_UNVERIFIED;SHARE_CLASS_UNVERIFIED;SECTOR_CALIBRATION_PENDING;REFERENCE_RATIOS_ONLY'}
   rows.append(row)
   if grade:watch.append(row)
  fields=list(rows[0]) if rows else []
  if fields:
   r4.writecsv(OUT/'full_market_annual_audit.csv',rows,fields)
   r4.writecsv(OUT/'provisional_ab_watchlist.csv',watch,fields)
  status.update(state='R7_RESEARCH_BUILT_NOT_FINAL',market_rows=len(market),eligible_rows=len(eligible),r6_legacy_cache_entries=len(load(ROOT/'data/v5_financial_r6/dart_financial_cache.json')),
   annual_cache_entries=len(annual),interim_cache_entries=len(interim),annual_comparable_in_universe=sum(r['annual_year']==str(annual_year) and r['annual_state']=='FINANCIAL_FIELDS_FOUND' and r['annual_report']=='11011' for r in rows),
   interim_complete_in_universe=sum(r['interim_state']=='FINANCIAL_FIELDS_FOUND' for r in rows),dart_api_calls=calls,companies_attempted=companies_attempted,
   annual_records_updated=updated_annual,interim_records_updated=updated_interim,provisional_ab_count=len(watch),pending_annual=max(0,len(eligible)-sum(r['annual_year']==str(annual_year) and r['annual_state']=='FINANCIAL_FIELDS_FOUND' and r['annual_report']=='11011' for r in rows)),
   errors=errors[:30],error_count=len(errors),warnings=['Provisional reference ratios, not official PER/PBR','Owner-attributable consolidated data only; share class remains unverified','Annual profit is not mixed with interim profit','No final buy signal or verified fair value'])
  save(OUT/'status.json',status)
  print(json.dumps(status,ensure_ascii=False,indent=2))
 except Exception as exc:
  status.update(state='FAILED',error=str(exc));save(OUT/'status.json',status);raise
if __name__=='__main__':main()
