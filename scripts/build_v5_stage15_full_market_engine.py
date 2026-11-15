#!/usr/bin/env python3
"""Stage15: resumable DART annual evidence, code-type audit, valuation and provisional grade gate.
Run after Stage14. Standard library only. Never promotes a provisional grade to verified.
"""
import argparse,csv,datetime as dt,json,os,pathlib,re,subprocess,sys,time
from decimal import Decimal,InvalidOperation
ROOT=pathlib.Path(__file__).resolve().parents[1];DATA=ROOT/'data'
sys.path.insert(0,str(ROOT/'scripts'))
import build_v5_stage14_full_market_integration as s14
ANNUAL=DATA/'v5_stage15_annual_cache.json'
REPORT=DATA/'v5_stage15_full_market.json'
CSV=DATA/'v5_stage15_full_market.csv'
PROGRESS=DATA/'v5_stage15_progress.json'
REQUIRED=('revenue','operating_profit','net_income','assets','liabilities','equity','operating_cashflow')
def read(p,default):
 try:return json.loads(p.read_text(encoding='utf-8'))
 except FileNotFoundError:return default
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def dec(x):return s14.dec(x)
def ratio(n,d):return str((n/d).quantize(Decimal('.0001'))) if n is not None and d is not None and d!=0 else None
def code_type(code,name):
 if re.fullmatch(r'\d{6}',code):return 'NUMERIC_6_DART_ELIGIBLE'
 if re.fullmatch(r'[0-9A-Z]{6}',code):return 'ALPHANUMERIC_6_CLASSIFICATION_REQUIRED'
 return 'OTHER_CODE_MANUAL_REVIEW'
def annual_fetch(key,corp,year):
 errors=[]
 for fs in ('CFS','OFS'):
  try:r=s14.api(key,'fnlttSinglAcntAll.json',corp_code=corp,bsns_year=year,reprt_code='11011',fs_div=fs)
  except Exception as e:errors.append(type(e).__name__);continue
  status=str(r.get('status',''))
  if status=='013':continue
  if status!='000':
   errors.append('DART_'+status)
   if status in ('010','011','012','020','021'):return None,errors,True
   continue
  rows=r.get('list') or []
  receipts=sorted({x.get('rcept_no') for x in rows if x.get('rcept_no')})
  if not receipts:errors.append('RECEIPT_MISSING');continue
  metrics,issues=s14.extract(rows)
  if not metrics:errors.append('METRICS_MISSING');continue
  return {'year':year,'report_code':'11011','fs_div':fs,'receipts':receipts,'metrics':metrics,'issues':issues,'source':'OpenDART fnlttSinglAcntAll.json','retrieved_at':dt.datetime.now(dt.timezone.utc).isoformat()},errors,False
 return None,errors,False

def main():
 p=argparse.ArgumentParser();p.add_argument('--extra-batches',type=int,default=1);p.add_argument('--batch-size',type=int,default=50);p.add_argument('--annual-limit',type=int,default=15);p.add_argument('--retry-days',type=int,default=3);p.add_argument('--no-network',action='store_true');a=p.parse_args()
 if not 0<=a.extra_batches<=4 or not 1<=a.batch_size<=100 or not 0<=a.annual_limit<=100:raise SystemExit('Invalid limits')
 key='' if a.no_network else os.getenv('DART_API_KEY','').strip()
 universe=read(DATA/'v5_full_market_universe.json',{});stocks=universe.get('stocks') or []
 if not stocks:raise SystemExit('Stage12 universe missing')
 # Stage14 already runs in the workflow. Additional bounded batches reuse its persisted cache.
 batch_errors=[]
 if key:
  for _ in range(a.extra_batches):
   cmd=[sys.executable,str(ROOT/'scripts'/'build_v5_stage14_full_market_integration.py'),'--batch-size',str(a.batch_size)]
   try:
    r=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=1200,check=False)
    if r.returncode:batch_errors.append('STAGE14_BATCH_FAILED:'+r.stderr[-300:]);break
    info=json.loads(r.stdout.strip().splitlines()[-1]);
    if info.get('new_fetched_this_run',0)==0 or info.get('error_counts'):break
   except Exception as e:batch_errors.append('STAGE14_BATCH_'+type(e).__name__);break
 mapping=read(DATA/'dart_corp_map.json',{}).get('mapping',{})
 cache=read(DATA/'v5_stage13_financial_cache.json',{}).get('entries',{})
 annual=read(ANNUAL,{'schema':1,'entries':{}})
 if annual.get('schema')!=1 or not isinstance(annual.get('entries'),dict):raise SystemExit('Invalid annual cache')
 entries=annual['entries'];today=dt.date.today();current_year=today.year-1
 # Annual report for preceding fiscal year should not be assumed available before its statutory filing window.
 if today.month<4:current_year-=1
 target_years=(current_year,current_year-1)
 candidates=[];type_counts={};excluded=0
 for s in stocks:
  code=str(s['code']).zfill(6);typ=code_type(code,s.get('name',''));type_counts[typ]=type_counts.get(typ,0)+1
  if s14.preferred(s.get('name','')):excluded+=1;continue
  if typ!='NUMERIC_6_DART_ELIGIBLE' or not mapping.get(code):continue
  if not cache.get(code,{}).get('filing'):continue
  for year in target_years:
   k=code+':'+str(year);item=entries.get(k,{})
   if item.get('filing'):continue
   try:recent=item.get('attempted_on') and (today-dt.date.fromisoformat(item['attempted_on'])).days<a.retry_days
   except ValueError:recent=False
   if not recent:candidates.append((code,year,mapping[code]))
 candidates.sort(key=lambda t:(t[0],-t[1]))
 fetched=0;attempted=0;api_halted=False
 for code,year,corp in candidates[:a.annual_limit] if key else []:
  filing,errors,halt=annual_fetch(key,corp,year);attempted+=1
  entries[code+':'+str(year)]={'attempted_on':today.isoformat(),'filing':filing,'errors':errors,'status':'FETCHED' if filing else 'RETRY_REQUIRED'}
  if filing:fetched+=1
  if halt:api_halted=True;break
 annual['updated_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat();annual['target_years']=target_years
 write(ANNUAL,annual)
 results=[];grades={'A':0,'B+':0,'B':0,'WITHHELD':0};annual_pairs=0;ratio_counts={'per':0,'pbr':0,'roe':0}
 for s in stocks:
  code=str(s['code']).zfill(6);typ=code_type(code,s.get('name',''));preferred=s14.preferred(s.get('name',''))
  recent=cache.get(code,{}).get('filing') or {};recent_metrics=recent.get('metrics') or {}
  a1=(entries.get(code+':'+str(target_years[0])) or {}).get('filing') or {}
  a0=(entries.get(code+':'+str(target_years[1])) or {}).get('filing') or {}
  m1=a1.get('metrics') or {};m0=a0.get('metrics') or {};issues=[];ratios={};score=None;grade='WITHHELD'
  if typ!='NUMERIC_6_DART_ELIGIBLE':issues.append('ALPHANUMERIC_SECURITY_TYPE_UNVERIFIED')
  if preferred:issues.append('PREFERRED_HEURISTIC_EXCLUSION')
  if not mapping.get(code):issues.append('CORP_MAPPING_UNAVAILABLE')
  if not a1:issues.append('ANNUAL_CURRENT_MISSING')
  if not a0:issues.append('ANNUAL_PRIOR_MISSING')
  if a1 and a0:
   if a1.get('fs_div')!=a0.get('fs_div'):issues.append('ANNUAL_FS_BASIS_MISMATCH')
   if a1.get('issues') or a0.get('issues'):issues.append('ANNUAL_ACCOUNT_EXTRACTION_ISSUES')
   annual_pairs+=1
  if recent and a1 and recent.get('fs_div')!=a1.get('fs_div'):issues.append('INTERIM_ANNUAL_FS_BASIS_MISMATCH')
  cap=dec(s.get('market_cap_krw'));profit=dec(m1.get('net_income'));equity=dec(m1.get('equity'))
  # Approximation only: consolidated profit/equity may contain noncontrolling interests.
  if cap and profit and profit>0 and a1 and a0 and a1.get('fs_div')==a0.get('fs_div'):
   ratios['per_proxy']=ratio(cap,profit);ratio_counts['per']+=1
  if cap and equity and equity>0:
   ratios['pbr_proxy']=ratio(cap,equity);ratio_counts['pbr']+=1
  if profit is not None and equity and equity>0 and a1 and a0 and a1.get('fs_div')==a0.get('fs_div'):
   ratios['roe_proxy_pct']=ratio(profit*100,equity);ratio_counts['roe']+=1
  # Candidate gate only: require comparable annual evidence and positive fundamentals.
  if not preferred and typ=='NUMERIC_6_DART_ELIGIBLE' and a1 and a0 and not a1.get('issues') and not a0.get('issues') and a1.get('fs_div')==a0.get('fs_div'):
   rev=dec(m1.get('revenue'));rev0=dec(m0.get('revenue'));op=dec(m1.get('operating_profit'));debt=dec(m1.get('liabilities'));cash=dec(m1.get('operating_cashflow'))
   if all(x is not None for x in (rev,rev0,op,profit,debt,equity,cash)) and rev0>0 and equity>0:
    growth=(rev/rev0-1)*100;leverage=debt/equity*100
    score=sum((growth>0,growth>10,op>0,profit>0,cash>0,leverage<150,leverage<80))
    grade='A' if score>=7 else 'B+' if score==6 else 'B' if score==5 else 'WITHHELD'
    ratios['revenue_growth_yoy_pct']=str(growth.quantize(Decimal('.01')))
    ratios['debt_to_equity_pct']=str(leverage.quantize(Decimal('.01')))
   else:issues.append('INCOMPLETE_COMPARABLE_ANNUAL_METRICS')
  grades[grade]+=1
  results.append({'code':code,'name':s.get('name'),'market':s.get('market'),'security_type':typ,'preferred_excluded_heuristic':preferred,'dart_corp_mapped':bool(mapping.get(code)),'latest_filing':recent or None,'annual_current':a1 or None,'annual_prior':a0 or None,'ratios':ratios,'annual_basis_issues':issues,'provisional_grade':grade,'verified_grade':None,'financial_verified':False,'fair_price':None,'buy_signal':None})
 total=len(stocks)-excluded;cached=sum(bool(cache.get(str(s['code']).zfill(6),{}).get('filing')) for s in stocks if not s14.preferred(s.get('name','')))
 progress={'trading_date':universe.get('trading_date'),'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'market_universe':len(stocks),'preferred_excluded_heuristic':excluded,'eligible_count':total,'security_type_counts':type_counts,'dart_mapped':sum(bool(mapping.get(str(s['code']).zfill(6))) for s in stocks if not s14.preferred(s.get('name',''))),'financial_cached':cached,'financial_coverage_pct':round(cached/total*100,2) if total else 0,'annual_target_years':target_years,'annual_filing_pairs':annual_pairs,'annual_fetched_this_run':fetched,'annual_attempted_this_run':attempted,'annual_cached_filings':sum(bool(x.get('filing')) for x in entries.values()),'ratio_counts':ratio_counts,'provisional_grade_counts':grades,'verified_grade_count':0,'api_halted':api_halted,'batch_errors':batch_errors,'classification':'PROVISIONAL_ONLY_NOT_VERIFIED_INVESTMENT_GRADES'}
 write(PROGRESS,progress);write(REPORT,{'progress':progress,'results':results})
 with CSV.open('w',encoding='utf-8-sig',newline='') as f:
  cols=['code','name','market','security_type','preferred_excluded_heuristic','dart_corp_mapped','annual_current_year','annual_prior_year','per_proxy','pbr_proxy','roe_proxy_pct','revenue_growth_yoy_pct','debt_to_equity_pct','provisional_grade','verified_grade','financial_verified','issues']
  w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
  for r in results:
   w.writerow({'code':r['code'],'name':r['name'],'market':r['market'],'security_type':r['security_type'],'preferred_excluded_heuristic':r['preferred_excluded_heuristic'],'dart_corp_mapped':r['dart_corp_mapped'],'annual_current_year':(r['annual_current'] or {}).get('year'),'annual_prior_year':(r['annual_prior'] or {}).get('year'),**r['ratios'],'provisional_grade':r['provisional_grade'],'verified_grade':'','financial_verified':False,'issues':';'.join(r['annual_basis_issues'])})
 print(json.dumps(progress,ensure_ascii=False))
if __name__=='__main__':main()
