#!/usr/bin/env python3
"""R8 balanced DART annual coverage; conservative, provisional research only."""
import csv, datetime as dt, importlib.util, json, os, pathlib, re, time
from decimal import Decimal
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'data/v5_financial_r8'; NOW=dt.datetime.now(ZoneInfo('Asia/Seoul'))
spec=importlib.util.spec_from_file_location('r4',ROOT/'scripts/krx_v5_fullmarket_research_r4_20261116.py')
r4=importlib.util.module_from_spec(spec);spec.loader.exec_module(r4)
def load(p):
 if not p.exists():return {}
 v=json.loads(p.read_text(encoding='utf-8'))
 if not isinstance(v,dict):raise ValueError('Cache must be JSON object: '+str(p))
 return v
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def complete(v,year):return isinstance(v,dict) and v.get('state')=='FINANCIAL_FIELDS_FOUND' and str(v.get('year'))==str(year) and v.get('report')=='11011' and r4.num(v.get('profit')) is not None and r4.num(v.get('equity')) is not None
def main():
 status={'version':'R8','generated_kst':NOW.isoformat(),'state':'STARTED','official_per_pbr_verified':0,'final_grades':0,'buy_signals':0}
 try:
  market=r4.readcsv(ROOT/'data/latest.csv');days={r.get('BAS_DD','') for r in market}
  if len(market)<1500 or len(days)!=1:raise ValueError('Market snapshot unavailable or multiple dates')
  day=days.pop();year=int(day[:4])-1
  if not re.fullmatch(r'20\d{6}',day):raise ValueError('Bad market date')
  eligible=[m for m in market if (r4.num(m.get('MKTCAP')) or 0)>=Decimal('100000000000') and re.fullmatch(r'\d{6}',m.get('ISU_CD',''))]
  if len({m['ISU_CD'] for m in eligible})!=len(eligible):raise ValueError('Duplicate eligible codes')
  annual=load(OUT/'annual_financial_cache.json');attempts=load(OUT/'request_attempts.json')
  r7=load(ROOT/'data/v5_financial_r7/annual_financial_cache.json')
  for code,rec in r7.items():
   if complete(rec,year) and not complete(annual.get(code),year):annual[code]=rec
  mapping={};errors=[];key=os.getenv('DART_API_KEY','').strip()
  if key:
   try:mapping=r4.corp_map(key)
   except Exception as e:errors.append('CORP_MAP: '+str(e)[:140])
  else:errors.append('DART_API_KEY_MISSING')
  # Alternate markets, rather than consuming all daily requests on sorted KOSPI codes.
  groups={'KOSPI':[],'KOSDAQ':[],'OTHER':[]}
  for m in eligible:groups[m.get('MARKET','OTHER') if m.get('MARKET') in ('KOSPI','KOSDAQ') else 'OTHER'].append(m)
  for g in groups.values():g.sort(key=lambda x:x['ISU_CD'])
  ordered=[];maxlen=max(map(len,groups.values()),default=0)
  for n in range(maxlen):
   for name in ('KOSDAQ','KOSPI','OTHER'):
    if n<len(groups[name]):ordered.append(groups[name][n])
  budget=max(0,min(300,int(os.getenv('DART_MAX_REQUESTS','120'))));cooldown=max(1,int(os.getenv('R8_RETRY_DAYS','7')))
  calls=0;updated=0;skipped=0
  for m in ordered:
   if calls>=budget:break
   code=m['ISU_CD'];prior=annual.get(code,{})
   if complete(prior,year) or code not in mapping:continue
   attempt=attempts.get(code,{})
   try:age=(NOW-dt.datetime.fromisoformat(attempt['checked_at_kst'])).total_seconds()/86400
   except (KeyError,ValueError,TypeError):age=999
   if age<cooldown:skipped+=1;continue
   calls+=1;attempts[code]={'checked_at_kst':NOW.isoformat(),'year':year,'report':'11011'}
   try:
    rec=r4.financial(key,mapping[code],str(year),'11011');rec.update(corp_code=mapping[code],checked_at_kst=NOW.isoformat(),asof_market_date=day)
    if complete(rec,year):annual[code]=rec;updated+=1
    elif rec.get('state') not in ('NO_REPORT','PARTIAL'):errors.append(code+': '+str(rec.get('state')))
   except Exception as e:errors.append(code+': '+str(e)[:120])
   if calls%10==0:save(OUT/'annual_financial_cache.json',annual);save(OUT/'request_attempts.json',attempts)
  save(OUT/'annual_financial_cache.json',annual);save(OUT/'request_attempts.json',attempts)
  rows=[];watch=[];counts={}
  for m in eligible:
   code=m['ISU_CD'];rec=annual.get(code,{});ok=complete(rec,year)
   cap=r4.num(m.get('MKTCAP'));profit=r4.num(rec.get('profit')) if ok else None;equity=r4.num(rec.get('equity')) if ok else None;liab=r4.num(rec.get('liabilities')) if ok else None
   pe=cap/profit if cap is not None and profit is not None and profit>0 else None
   pb=cap/equity if cap is not None and equity is not None and equity>0 else None
   roe=profit/equity*100 if profit is not None and equity is not None and equity>0 else None
   debt=liab/equity*100 if liab is not None and equity is not None and equity>0 else None
   grade=''
   if all(v is not None for v in (pe,pb,roe,debt)):
    score=sum((roe>=12,0<pe<=18,0<pb<=Decimal('2.5'),debt<=150))
    grade='A' if score==4 else 'B+' if score==3 else 'B' if score==2 else ''
   row={'BAS_DD':day,'MARKET':m.get('MARKET',''),'ISU_CD':code,'ISU_NM':m.get('ISU_NM',''),'MKTCAP':m.get('MKTCAP',''),'TDD_CLSPRC':m.get('TDD_CLSPRC',''),'annual_year':rec.get('year',''),'annual_report':rec.get('report',''),'annual_state':rec.get('state','MISSING'),'reference_pe':str(round(pe,3)) if pe is not None else '', 'reference_pb':str(round(pb,3)) if pb is not None else '', 'reference_roe_pct':str(round(roe,3)) if roe is not None else '', 'reference_debt_pct':str(round(debt,3)) if debt is not None else '', 'provisional_grade':grade,'official_per':'','official_pbr':'','final_grade':'WITHHELD','buy_signal':'NONE','flags':'OFFICIAL_VALUATION_UNVERIFIED;SHARE_CLASS_UNVERIFIED;SECTOR_NORMALIZATION_PENDING'}
   rows.append(row)
   if grade:watch.append(row)
   counts.setdefault(m.get('MARKET','UNKNOWN'),{'eligible':0,'annual_complete':0,'provisional_ab':0});c=counts[m.get('MARKET','UNKNOWN')];c['eligible']+=1;c['annual_complete']+=int(ok);c['provisional_ab']+=int(bool(grade))
  if rows:
   fields=list(rows[0]);r4.writecsv(OUT/'full_market_annual_audit.csv',rows,fields);r4.writecsv(OUT/'provisional_ab_watchlist.csv',watch,fields)
  status.update(state='RESEARCH_ONLY_NOT_FINAL',market_date=day,market_rows=len(market),eligible_rows=len(eligible),annual_cache_entries=len(annual),annual_complete_in_universe=sum(c['annual_complete'] for c in counts.values()),pending_annual=len(eligible)-sum(c['annual_complete'] for c in counts.values()),provisional_ab_count=len(watch),market_breakdown=counts,dart_api_calls=calls,new_annual_records=updated,cooldown_skipped=skipped,error_count=len(errors),errors=errors[:40],warnings=['Official PER/PBR and share class have NOT been independently verified','Annual ratios are research estimates, not official valuation','No final grades or actionable buy signals','R8 uses existing R7 cache without modifying it'])
  save(OUT/'status.json',status);print(json.dumps(status,ensure_ascii=False,indent=2))
 except Exception as e:
  status.update(state='FAILED',error=str(e));save(OUT/'status.json',status);raise
if __name__=='__main__':main()
