#!/usr/bin/env python3
"""Stage 13: incremental, resumable full-market DART collection (not final grades).
One bounded batch per run; persist cache in GitHub. No unverified values are filled.
"""
import argparse,csv,datetime as dt,json,os,pathlib,re,time,urllib.parse,urllib.request
from decimal import Decimal,InvalidOperation
ROOT=pathlib.Path(__file__).resolve().parents[1]; DATA=ROOT/'data'
CACHE=DATA/'v5_stage13_financial_cache.json'; OUTPUT=DATA/'v5_stage13_full_market_financial.json'; CSV=DATA/'v5_stage13_full_market_financial.csv'
REPORTS=[('11014','09'),('11012','06'),('11013','03'),('11011','12')]
FIELDS={'revenue':('ifrs-full_Revenue','ifrs_Revenue'),'operating_profit':('dart_OperatingIncomeLoss',),'net_income':('ifrs-full_ProfitLoss','ifrs_ProfitLoss'),'assets':('ifrs-full_Assets','ifrs_Assets'),'liabilities':('ifrs-full_Liabilities','ifrs_Liabilities'),'equity':('ifrs-full_Equity','ifrs_Equity'),'operating_cashflow':('ifrs-full_CashFlowsFromUsedInOperatingActivities','ifrs_CashFlowsFromUsedInOperatingActivities')}
BALANCE={'assets','liabilities','equity'}
def load(path,default):
 try:return json.loads(path.read_text(encoding='utf-8'))
 except FileNotFoundError:return default
def decimal(x):
 try:return Decimal(str(x).replace(',','')) if x not in (None,'','-') else None
 except (InvalidOperation,ValueError):return None
def request(key,corp,year,report,fs):
 args={'crtfc_key':key,'corp_code':corp,'bsns_year':year,'reprt_code':report,'fs_div':fs}
 url='https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?'+urllib.parse.urlencode(args)
 for retry in range(3):
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'KRX-v5-stage13/1.0'}),timeout=30) as r:return json.load(r)
  except Exception:
   if retry==2:raise
   time.sleep(2**retry)
def extract(rows):
 metrics={};issues=[]
 for metric,ids in FIELDS.items():
  candidates=[r for r in rows if r.get('account_id') in ids and r.get('account_detail') in ('-',None,'') and r.get('currency')=='KRW' and r.get('sj_div') in (('BS',) if metric in BALANCE else ('CF',) if metric=='operating_cashflow' else ('IS','CIS'))]
  # Do not silently pick an ambiguous account or an absent value.
  values={str(decimal(r.get('thstrm_amount') if metric in BALANCE else r.get('thstrm_add_amount') or r.get('thstrm_amount'))) for r in candidates if decimal(r.get('thstrm_amount') if metric in BALANCE else r.get('thstrm_add_amount') or r.get('thstrm_amount')) is not None}
  if len(values)==1:metrics[metric]=next(iter(values))
  else:issues.append(metric+('_MISSING' if not values else '_AMBIGUOUS'))
 return metrics,issues
def preferred(name):
 # Fail-safe: uncertain share classes are flagged rather than called common.
 return bool(re.search(r'(?:우|우B|우C|[1-9]우|우선주|전환우선주)$',name or ''))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--batch-size',type=int,default=35);ap.add_argument('--retry-days',type=int,default=7);args=ap.parse_args()
 if not 1<=args.batch_size<=150:raise SystemExit('batch-size must be 1..150')
 universe=load(DATA/'v5_full_market_universe.json',None)
 if not universe:raise SystemExit('Stage 12 universe missing')
 mapping=load(DATA/'dart_corp_map.json',{}).get('mapping',{})
 cache=load(CACHE,{'schema':1,'entries':{}})
 if cache.get('schema')!=1:raise SystemExit('Unexpected cache schema')
 entries=cache['entries'];now=dt.datetime.now(dt.timezone.utc);today=now.date();key=os.getenv('DART_API_KEY','').strip()
 stocks=universe.get('stocks',[]);selected=[]
 for s in stocks:
  code=str(s['code']).zfill(6);e=entries.get(code,{})
  if preferred(s.get('name')):continue
  last=e.get('attempted_on')
  if last:
   try:
    if (today-dt.date.fromisoformat(last)).days<args.retry_days:continue
   except ValueError:pass
  if not re.fullmatch(r'\d{8}',str(mapping.get(code,''))):continue
  selected.append(s)
 selected.sort(key=lambda s:(bool(entries.get(str(s['code']).zfill(6),{}).get('attempted_on')),str(s['code'])))
 for s in selected[:args.batch_size]:
  code=str(s['code']).zfill(6);corp=mapping[code];issues=[];filing=None
  if not key:issues.append('DART_API_KEY_MISSING')
  else:
   # Prefer most recent available report, not necessarily current quarter.
   slots=sorted([(y,r,m) for y in (today.year,today.year-1) for r,m in REPORTS if (y<int(today.year) or int(m)<today.month)],key=lambda x:(x[0],int(x[2])),reverse=True)
   for year,report,month in slots:
    for fs in ('CFS','OFS'):
     try:resp=request(key,corp,year,report,fs)
     except Exception as exc:issues.append('DART_REQUEST_'+type(exc).__name__);continue
     if resp.get('status')=='013':continue
     if resp.get('status')!='000':issues.append('DART_STATUS_'+str(resp.get('status')));continue
     rows=resp.get('list') or []
     if not rows:continue
     metrics,miss=extract(rows)
     receipts=sorted({r.get('rcept_no') for r in rows if r.get('rcept_no')})
     if not receipts:issues.append('RECEIPT_MISSING');continue
     filing={'year':year,'report_code':report,'fs_div':fs,'receipt_numbers':receipts,'metrics':metrics,'issues':miss,'fetched_at_utc':now.isoformat(),'source':'OpenDART fnlttSinglAcntAll.json'}
     break
    if filing:break
  entries[code]={'name':s.get('name'),'corp_code':corp,'attempted_on':today.isoformat(),'status':'FETCHED_PARTIAL_NOT_VERIFIED' if filing else 'RETRY_REQUIRED','filing':filing,'issues':issues}
 cache['updated_at_utc']=now.isoformat();CACHE.write_text(json.dumps(cache,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 # Valuation is diagnostic only; do not fabricate market ratios or earnings/share count.
 market={}
 with (DATA/'latest.csv').open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   if r.get('BAS_DD')==universe['trading_date']:market[str(r.get('ISU_CD','')).zfill(6)]=r
 results=[]
 for s in stocks:
  code=str(s['code']).zfill(6);e=entries.get(code,{});p=preferred(s.get('name'));m=market.get(code,{})
  ratios={}
  for field,aliases in {'per':('PER',),'pbr':('PBR',),'roe':('ROE',)}.items():
   for alias in aliases:
    v=decimal(m.get(alias))
    if v is not None and v>0:ratios[field]=str(v);break
  results.append({'code':code,'name':s.get('name'),'market':s.get('market'),'preferred_excluded':p,'corp_code_mapped':bool(mapping.get(code)),'status':'EXCLUDED_PREFERRED' if p else e.get('status','UNFETCHED'),'filing':e.get('filing'),'valuation_indicators':ratios,'valuation_status':'INDICATIVE_UNVERIFIED' if ratios else 'MISSING','financial_verified':False,'grade':None,'fair_price':None,'buy_signal':None})
 out={'generated_at_utc':now.isoformat(),'trading_date':universe['trading_date'],'total_universe':len(stocks),'preferred_excluded_count':sum(x['preferred_excluded'] for x in results),'eligible_common_candidate_count':sum(not x['preferred_excluded'] for x in results),'corp_code_mapped_count':sum(x['corp_code_mapped'] and not x['preferred_excluded'] for x in results),'fetched_count':sum(x['filing'] is not None and not x['preferred_excluded'] for x in results),'processed_this_run':len(selected[:args.batch_size]),'unfetched_count':sum(x['status']=='UNFETCHED' for x in results),'classification':'STAGE13_INCREMENTAL_RAW_FINANCIAL_NOT_FINAL_GRADE','notes':['Preferred class name heuristic only; formal common-share confirmation pending.','Cache is committed by workflow for incremental runs; no historical corrections or fiscal-period comparability verified.','Missing fields remain missing; no A/B grades or buy signals.'],'results':results}
 OUTPUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 with CSV.open('w',encoding='utf-8-sig',newline='') as f:
  cols=['code','name','market','preferred_excluded','corp_code_mapped','status','filing_year','report_code','fs_div','revenue','operating_profit','net_income','assets','liabilities','equity','operating_cashflow','per','pbr','roe']
  w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
  for x in results:
   filing=x['filing'] or {};metrics=filing.get('metrics') or {};ratios=x['valuation_indicators']
   w.writerow({**{k:x.get(k) for k in cols if k in x},'filing_year':filing.get('year'),'report_code':filing.get('report_code'),'fs_div':filing.get('fs_div'),**metrics,**ratios})
 print(json.dumps({k:out[k] for k in ('total_universe','preferred_excluded_count','corp_code_mapped_count','fetched_count','processed_this_run','unfetched_count')},ensure_ascii=False))
if __name__=='__main__':main()
