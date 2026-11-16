#!/usr/bin/env python3
"""R6 independent financial-coverage collector. Preserves R3-R5 and R4 cache.
Only provisional research ratios; no official PER/PBR or investment grades.
"""
import csv,datetime as dt,importlib.util,json,os,pathlib,re,sys
from decimal import Decimal
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'data/v5_financial_r6';OUT.mkdir(parents=True,exist_ok=True)
NOW=dt.datetime.now(ZoneInfo('Asia/Seoul'))
R4=ROOT/'scripts/krx_v5_fullmarket_research_r4_20261116.py'
spec=importlib.util.spec_from_file_location('krx_r4_helpers',R4)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
readcsv,writecsv,num=mod.readcsv,mod.writecsv,mod.num

def dump(path,obj):
 tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
def main():
 status={'version':'R6','generated_kst':NOW.isoformat(),'state':'STARTED','official_per_pbr_verified':0,'final_grades':0,'buy_signals':0}
 try:
  market=readcsv(ROOT/'data/latest.csv')
  dates={r.get('BAS_DD','') for r in market}
  if len(market)<1500 or len(dates)!=1 or not re.fullmatch(r'20\d{6}',next(iter(dates),'') ):
   raise ValueError('No consistent full-market latest.csv; existing caches untouched')
  day=next(iter(dates));status['market_date']=day
  eligible=[r for r in market if (num(r.get('MKTCAP')) or 0)>=Decimal('100000000000') and re.fullmatch(r'\d{6}',r.get('ISU_CD',''))]
  unique={r['ISU_CD'] for r in eligible}
  if len(unique)!=len(eligible):raise ValueError('Duplicate stock codes in eligible universe')
  key=os.environ.get('DART_API_KEY','').strip()
  r4path=ROOT/'data/v5_fullmarket_r4/dart_financial_cache.json'
  r4=json.loads(r4path.read_text(encoding='utf-8')) if r4path.exists() else {}
  r6path=OUT/'dart_financial_cache.json'
  cache=json.loads(r6path.read_text(encoding='utf-8')) if r6path.exists() else {}
  # Bootstrap only: R4 cache is read-only. Existing R6 records take precedence.
  imported=0
  for code,record in r4.items():
   if code not in cache and isinstance(record,dict):cache[code]=dict(record);imported+=1
  status.update(market_rows=len(market),eligible_rows=len(eligible),r4_imported=imported,cache_before_collection=len(cache))
  mapping={};errors=[]
  if key:
   try:mapping=mod.corp_map(key)
   except Exception as e:errors.append('DART mapping: '+str(e)[:180])
  else:errors.append('DART_API_KEY missing; collection skipped')
  # Fresh complete records are not requested again daily; failures are retried later.
  max_calls=max(0,min(300,int(os.environ.get('DART_MAX_REQUESTS','120'))))
  freshness=max(1,int(os.environ.get('DART_REFRESH_DAYS','30')))
  def age_days(record):
   try:return (NOW-dt.datetime.fromisoformat(record['checked_at_kst'])).total_seconds()/86400
   except (ValueError,TypeError,KeyError):return 9999
  pending=[]
  for row in eligible:
   code=row['ISU_CD'];record=cache.get(code,{})
   if code not in mapping:continue
   if record.get('state')=='FINANCIAL_FIELDS_FOUND' and age_days(record)<freshness:continue
   if record.get('state')!='FINANCIAL_FIELDS_FOUND' and age_days(record)<7:continue
   pending.append(row)
  pending.sort(key=lambda r:(cache.get(r['ISU_CD'],{}).get('state')=='FINANCIAL_FIELDS_FOUND',r['ISU_CD']))
  # Never request a report from a year later than the market snapshot.
  market_year=int(day[:4]);quarter=int(day[4:6]);reports=[]
  if quarter>=11:reports.append((str(market_year),'11014'))
  if quarter>=8:reports.append((str(market_year),'11012'))
  if quarter>=5:reports.append((str(market_year),'11013'))
  reports.append((str(market_year-1),'11011'))
  calls=0;updated=0;attempted=0
  for row in pending:
   if calls>=max_calls:break
   code=row['ISU_CD'];attempted+=1;best=None
   for year,report in reports:
    if calls>=max_calls:break
    calls+=1
    try:
     obj=mod.financial(key,mapping[code],year,report)
     if obj.get('state')=='FINANCIAL_FIELDS_FOUND':best=obj;break
     if best is None and obj.get('state')=='PARTIAL':best=obj
     if obj.get('state','').startswith('API_') and obj['state'] not in ('API_013',):
      errors.append(code+' '+obj['state']);break
    except Exception as e:errors.append(code+': '+str(e)[:120]);break
   if best:
    best.update(corp_code=mapping[code],checked_at_kst=NOW.isoformat(),asof_market_date=day)
    prior=cache.get(code,{})
    if best['state']=='FINANCIAL_FIELDS_FOUND' or prior.get('state')!='FINANCIAL_FIELDS_FOUND':
     cache[code]=best;updated+=1
  # Preserve financial cache independently even when market date is unchanged.
  dump(r6path,cache)
  rows=[];watch=[]
  for m in eligible:
   code=m['ISU_CD'];f=cache.get(code,{})
   cap=num(m.get('MKTCAP'));profit=num(f.get('profit'));equity=num(f.get('equity'));liab=num(f.get('liabilities'))
   complete=f.get('state')=='FINANCIAL_FIELDS_FOUND'
   # FY and interim YTD cannot be compared as if equivalent.
   report=f.get('report','');is_annual=report=='11011'
   pe=cap/profit if complete and is_annual and profit is not None and profit>0 else None
   pb=cap/equity if complete and equity is not None and equity>0 else None
   roe=profit/equity*100 if complete and is_annual and profit is not None and equity is not None and equity>0 else None
   debt=liab/equity*100 if complete and liab is not None and equity is not None and equity>0 else None
   grade=''
   if pe is not None and pb is not None and roe is not None and debt is not None:
    score=sum((roe>=12,pe<=18,pb<=Decimal('2.5'),debt<=150))
    grade='A' if score==4 else 'B+' if score==3 else 'B' if score==2 else ''
   row={'BAS_DD':day,'MARKET':m.get('MARKET',''),'ISU_CD':code,'ISU_NM':m.get('ISU_NM',''),
    'MKTCAP':m.get('MKTCAP',''),'TDD_CLSPRC':m.get('TDD_CLSPRC',''),'financial_state':f.get('state','MISSING'),
    'financial_year':f.get('year',''),'financial_report':report,'financial_statement_type':f.get('fs_div',''),
    'reference_annual_pe':str(round(pe,3)) if pe is not None else '',
    'reference_pb':str(round(pb,3)) if pb is not None else '',
    'reference_annual_roe_pct':str(round(roe,3)) if roe is not None else '',
    'reference_debt_pct':str(round(debt,3)) if debt is not None else '',
    'provisional_grade':grade,'final_grade':'WITHHELD','buy_signal':'NONE',
    'limitations':'OFFICIAL_VALUATION_UNVERIFIED;SHARE_CLASS_UNVERIFIED;REPORT_PERIOD_NOT_COMPARABLE' }
   rows.append(row)
   if grade:watch.append(row)
  fields=list(rows[0]) if rows else []
  if fields:
   writecsv(OUT/'full_market_research.csv',rows,fields)
   writecsv(OUT/'provisional_ab_watchlist.csv',watch,fields)
  status.update(state='R6_PROVISIONAL_RESEARCH_BUILT',dart_api_calls=calls,dart_companies_attempted=attempted,
   financial_records_updated=updated,financial_cache_total=len(cache),financial_complete_in_universe=sum(r['financial_state']=='FINANCIAL_FIELDS_FOUND' for r in rows),
   annual_comparable_count=sum(bool(r['reference_annual_pe']) for r in rows),provisional_ab_count=len(watch),
   pending_companies=len(pending)-attempted,error_count=len(errors),errors=errors[:25],
   warnings=['Only provisional screening; not official PER/PBR or verified share class',
   'Annual PE/ROE computed only from annual profit; interim YTD is not annualized',
   'R4 and historical caches remain untouched; no final buy signals'])
 except Exception as e:status.update(state='FAILED',error=str(e))
 dump(OUT/'status.json',status)
 print(json.dumps(status,ensure_ascii=False,indent=2))
 if status['state']=='FAILED':sys.exit(1)
if __name__=='__main__':main()
