#!/usr/bin/env python3
"""KRX v5 Stage14: resumable full-market DART mapping, collection and diagnostic valuation.
Uses Stage12 universe, Stage13 cache; no unverified final grades or buy signals.
Stdlib only. Designed for GitHub Actions with persisted data/v5_stage13_financial_cache.json.
"""
import argparse, csv, datetime as dt, io, json, os, pathlib, re, time, urllib.parse, urllib.request, zipfile
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

ROOT=pathlib.Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
CACHE=DATA/'v5_stage13_financial_cache.json'
MAP=DATA/'dart_corp_map.json'
OUT=DATA/'v5_stage14_full_market_financial.json'
CSV=DATA/'v5_stage14_full_market_financial.csv'
PROGRESS=DATA/'v5_stage14_progress.json'
REPORTS=[('11013',11,14),('11012',8,14),('11014',5,15),('11011',3,31)]
IDS={
 'revenue':('ifrs-full_Revenue','ifrs_Revenue'),
 'operating_profit':('dart_OperatingIncomeLoss',),
 'net_income':('ifrs-full_ProfitLoss','ifrs_ProfitLoss'),
 'assets':('ifrs-full_Assets','ifrs_Assets'),
 'liabilities':('ifrs-full_Liabilities','ifrs_Liabilities'),
 'equity':('ifrs-full_Equity','ifrs_Equity'),
 'operating_cashflow':('ifrs-full_CashFlowsFromUsedInOperatingActivities','ifrs_CashFlowsFromUsedInOperatingActivities')}

def read_json(p,default):
 try:return json.loads(p.read_text(encoding='utf-8'))
 except FileNotFoundError:return default

def dec(v):
 try:
  if v is None or str(v).strip() in ('','-','None'):return None
  return Decimal(str(v).replace(',','').strip())
 except (InvalidOperation,ValueError):return None

def val(v):
 return str(v.quantize(Decimal('.0001'))) if v is not None else None

def fetch(url,tries=3):
 for n in range(tries):
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'KRX-v5-stage14/1.0'})
   with urllib.request.urlopen(req,timeout=35) as f:return f.read()
  except Exception:
   if n==tries-1:raise
   time.sleep(2**n)

def api(key,endpoint,**kwargs):
 url='https://opendart.fss.or.kr/api/'+endpoint+'?'+urllib.parse.urlencode({'crtfc_key':key,**kwargs})
 return json.loads(fetch(url))

def refresh_mapping(key,old,force=False):
 mapping=old.get('mapping',{})
 stamp=old.get('fetched_date','')
 try:age=(dt.date.today()-dt.date.fromisoformat(stamp)).days
 except ValueError:age=9999
 if not key:return mapping,'NO_API_KEY'
 if mapping and age<14 and not force:return mapping,'CACHED'
 try:
  url='https://opendart.fss.or.kr/api/corpCode.xml?'+urllib.parse.urlencode({'crtfc_key':key})
  with zipfile.ZipFile(io.BytesIO(fetch(url))) as z:
   xml=next(n for n in z.namelist() if n.lower().endswith('.xml'))
   root=ET.fromstring(z.read(xml))
  fresh={}
  for item in root.findall('.//list'):
   stock=(item.findtext('stock_code') or '').strip()
   corp=(item.findtext('corp_code') or '').strip()
   if re.fullmatch(r'\d{6}',stock) and re.fullmatch(r'\d{8}',corp):fresh[stock]=corp
  if not fresh:raise ValueError('EMPTY_CORP_MAP')
  mapping={**mapping,**fresh}
  MAP.write_text(json.dumps({'fetched_date':dt.date.today().isoformat(),'mapping':mapping},ensure_ascii=False)+'\n',encoding='utf-8')
  return mapping,'REFRESHED'
 except Exception as e:return mapping,'REFRESH_FAILED_'+type(e).__name__

def slots(today):
 result=[]
 for y in (today.year,today.year-1):
  for report,month,day in REPORTS:
   deadline=dt.date(y,month,day)
   if deadline<=today:
    # Annual statements for fiscal year y are generally filed in y+1.
    fiscal=y-1 if report=='11011' else y
    result.append((deadline,fiscal,report))
 return [(year,report) for _,year,report in sorted(result,reverse=True)]

def extract(rows):
 metrics={};issues=[]
 for field,ids in IDS.items():
  sj=('BS',) if field in ('assets','liabilities','equity') else ('CF',) if field=='operating_cashflow' else ('IS','CIS')
  found=[]
  for r in rows:
   if r.get('account_id') not in ids or r.get('sj_div') not in sj:continue
   if r.get('account_detail') not in (None,'','-') or r.get('currency')!='KRW':continue
   raw=r.get('thstrm_amount') if field in ('assets','liabilities','equity') else (r.get('thstrm_add_amount') or r.get('thstrm_amount'))
   x=dec(raw)
   if x is not None:found.append(x)
  unique=set(found)
  if len(unique)==1:metrics[field]=str(unique.pop())
  else:issues.append(field+('_MISSING' if not unique else '_AMBIGUOUS'))
 return metrics,issues

def preferred(name):
 return bool(re.search(r'(?:우|우B|우C|[1-9]우|우선주|전환우선주)$',name or ''))

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--batch-size',type=int,default=70)
 parser.add_argument('--retry-days',type=int,default=3)
 parser.add_argument('--force-map-refresh',action='store_true')
 args=parser.parse_args()
 if not 1<=args.batch_size<=150:raise SystemExit('batch-size must be 1..150')
 universe=read_json(DATA/'v5_full_market_universe.json',None)
 if not universe or not universe.get('stocks'):raise SystemExit('STAGE12_UNIVERSE_MISSING')
 day=universe['trading_date'];now=dt.datetime.now(dt.timezone.utc);today=now.date()
 key=os.getenv('DART_API_KEY','').strip()
 cache=read_json(CACHE,{'schema':1,'entries':{}})
 if cache.get('schema')!=1 or not isinstance(cache.get('entries'),dict):raise SystemExit('UNSUPPORTED_STAGE13_CACHE')
 entries=cache['entries'];oldmap=read_json(MAP,{'mapping':{}})
 mapping,map_status=refresh_mapping(key,oldmap,args.force_map_refresh)
 stocks=universe['stocks']
 eligible=[s for s in stocks if not preferred(s.get('name'))]
 unmapped=[s for s in eligible if not re.fullmatch(r'\d{8}',str(mapping.get(str(s['code']).zfill(6),'')))]
 # Refresh missing mapping even when a recent map is cached; at most once per run.
 if unmapped and map_status=='CACHED':
  mapping,map_status=refresh_mapping(key,oldmap,True)
  unmapped=[s for s in eligible if not re.fullmatch(r'\d{8}',str(mapping.get(str(s['code']).zfill(6),'')))]
 todo=[];skipped_recent=0
 for s in eligible:
  code=str(s['code']).zfill(6)
  if code in {str(x['code']).zfill(6) for x in unmapped}:continue
  e=entries.get(code,{})
  if e.get('filing') and e.get('status')=='FETCHED_PARTIAL_NOT_VERIFIED':continue
  attempted=e.get('attempted_on')
  if attempted:
   try:
    if (today-dt.date.fromisoformat(attempted)).days<args.retry_days:
     skipped_recent+=1;continue
   except ValueError:pass
  todo.append(s)
 todo.sort(key=lambda s:(bool(entries.get(str(s['code']).zfill(6),{}).get('attempted_on')),str(s['code'])))
 selected=todo[:args.batch_size] if key else []
 error_counts={};fetched_this_run=0
 for s in selected:
  code=str(s['code']).zfill(6);corp=mapping[code];issues=[];filing=None
  for year,report in slots(today):
   for fs in ('CFS','OFS'):
    try:response=api(key,'fnlttSinglAcntAll.json',corp_code=corp,bsns_year=year,reprt_code=report,fs_div=fs)
    except Exception as e:issues.append('REQUEST_'+type(e).__name__);continue
    status=str(response.get('status',''))
    if status=='013':continue
    if status!='000':
     issues.append('DART_STATUS_'+status)
     # API key / quota failures: stop this run rather than hammering API.
     if status in ('010','011','012','020','021'):
      error_counts[status]=error_counts.get(status,0)+1
      selected=selected[:selected.index(s)+1]
     continue
    rows=response.get('list') or []
    if not rows:continue
    receipts=sorted({r.get('rcept_no') for r in rows if r.get('rcept_no')})
    if not receipts:issues.append('RECEIPT_MISSING');continue
    metrics,missing=extract(rows)
    filing={'year':year,'report_code':report,'fs_div':fs,'receipt_numbers':receipts,'metrics':metrics,'issues':missing,'fetched_at_utc':now.isoformat(),'source':'OpenDART fnlttSinglAcntAll.json'}
    break
   if filing:break
  if filing:fetched_this_run+=1
  for issue in issues:error_counts[issue]=error_counts.get(issue,0)+1
  entries[code]={'name':s.get('name'),'corp_code':corp,'attempted_on':today.isoformat(),
    'status':'FETCHED_PARTIAL_NOT_VERIFIED' if filing else 'RETRY_REQUIRED','filing':filing,'issues':issues}
  if any(x.startswith('DART_STATUS_0') and x[-3:] in ('010','011','012','020','021') for x in issues):break
 cache['updated_at_utc']=now.isoformat()
 CACHE.write_text(json.dumps(cache,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 market={}
 with (DATA/'latest.csv').open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   if r.get('BAS_DD')==day:market[str(r.get('ISU_CD','')).zfill(6)]=r
 results=[]
 for s in stocks:
  code=str(s['code']).zfill(6);p=preferred(s.get('name'));e=entries.get(code,{})
  filing=e.get('filing') or {};metrics=filing.get('metrics') or {};m=market.get(code,{})
  cap=dec(m.get('MKTCAP'));equity=dec(metrics.get('equity'));income=dec(metrics.get('net_income'))
  ratios={};sources={};issues=[]
  # PBR proxy from consolidated equity is NOT official per-share PBR; label explicitly.
  if cap is not None and equity is not None and equity>0:
   ratios['pbr_proxy']=val(cap/equity);sources['pbr_proxy']='market_cap / DART_equity; consolidated equity may include minority interest'
  if filing.get('report_code')=='11011' and cap is not None and income is not None and income>0 and equity is not None and equity>0:
   ratios['per_proxy']=val(cap/income);ratios['roe_proxy_pct']=val(income/equity*100)
   sources['per_proxy']='market_cap / annual DART_net_income; not official per-share PER'
   sources['roe_proxy_pct']='annual DART_net_income / equity; non-average equity, unverified'
  else:issues.append('ANNUAL_COMPARABLE_PER_ROE_NOT_AVAILABLE')
  # Official ratios only when supplied as a verified market source; latest.csv fields are absent in current dataset.
  for field in ('PER','PBR','ROE'):
   v=dec(m.get(field))
   if v is not None and v>0:
    ratios[field.lower()+'_market_unverified']=val(v)
    sources[field.lower()+'_market_unverified']='latest.csv '+field+'; provenance not independently verified'
  results.append({'code':code,'name':s.get('name'),'market':s.get('market'),'preferred_excluded':p,
   'corp_code':mapping.get(code),'mapping_status':'MISSING' if not mapping.get(code) else 'MAPPED',
   'collection_status':'EXCLUDED_PREFERRED' if p else e.get('status','UNFETCHED') if mapping.get(code) else 'MAPPING_MISSING',
   'filing':filing or None,'ratios':ratios,'ratio_sources':sources,'ratio_issues':issues,
   'financial_verified':False,'grade':None,'fair_price':None,'buy_signal':None})
 counts={}
 for r in results:counts[r['collection_status']]=counts.get(r['collection_status'],0)+1
 total=len(eligible);fetched=sum(r['filing'] is not None and not r['preferred_excluded'] for r in results)
 mapped=total-len(unmapped)
 progress={'trading_date':day,'generated_at_utc':now.isoformat(),'total_market_cap_universe':len(stocks),
  'preferred_excluded_heuristic':len(stocks)-total,'eligible_candidates':total,'dart_mapped':mapped,
  'dart_unmapped':len(unmapped),'unmapped_codes':[str(s['code']).zfill(6) for s in unmapped],
  'fetched_cached':fetched,'remaining_without_filing':total-fetched,'coverage_percent':round(100*fetched/total,2) if total else 0,
  'new_fetched_this_run':fetched_this_run,'selected_batch_size':len(selected),'retry_wait_count':skipped_recent,
  'mapping_refresh_status':map_status,'collection_status_counts':counts,'error_counts':error_counts,
  'valuation_pbr_proxy_count':sum('pbr_proxy' in r['ratios'] for r in results),
  'valuation_annual_per_roe_proxy_count':sum('per_proxy' in r['ratios'] for r in results),
  'verified_ab_grade_count':0,'note':'Raw financial data and valuation proxies only; not official ratios or final grades.'}
 OUT.write_text(json.dumps({'classification':'STAGE14_FULL_MARKET_UNVERIFIED_RESEARCH','progress':progress,'results':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 PROGRESS.write_text(json.dumps(progress,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 with CSV.open('w',encoding='utf-8-sig',newline='') as f:
  cols=['code','name','market','preferred_excluded','corp_code','mapping_status','collection_status','filing_year','report_code','fs_div',*IDS.keys(),'pbr_proxy','per_proxy','roe_proxy_pct','financial_verified','grade','fair_price','buy_signal']
  writer=csv.DictWriter(f,fieldnames=cols);writer.writeheader()
  for r in results:
   filing=r['filing'] or {}
   writer.writerow({'code':r['code'],'name':r['name'],'market':r['market'],'preferred_excluded':r['preferred_excluded'],
    'corp_code':r['corp_code'],'mapping_status':r['mapping_status'],'collection_status':r['collection_status'],
    'filing_year':filing.get('year'),'report_code':filing.get('report_code'),'fs_div':filing.get('fs_div'),
    **(filing.get('metrics') or {}),**r['ratios'],'financial_verified':False})
 print(json.dumps(progress,ensure_ascii=False))
if __name__=='__main__':main()
