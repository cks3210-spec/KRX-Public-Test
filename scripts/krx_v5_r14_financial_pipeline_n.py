#!/usr/bin/env python3
"""R14 N: bounded incremental annual + cumulative-quarter collection, strict TTM.
Imports the existing M OpenDART API/parser; preserves verified cache and its schema.
"""
import csv, datetime as dt, importlib.util, json, os, pathlib, time
ROOT=pathlib.Path(os.getenv('GITHUB_WORKSPACE','.')).resolve()
OUT=ROOT/'data/v5_financial_m'
SCRIPT=ROOT/'scripts/krx_v5_r14_dart_incremental_m.py'
spec=importlib.util.spec_from_file_location('r14_m_existing',SCRIPT)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
LIMIT=max(1,min(250,int(os.getenv('M_BATCH_LIMIT','80'))))
COOLDOWN_DAYS=max(1,int(os.getenv('R14_RETRY_DAYS','7')))
FIELDS=['code','year','fs_div','annual_profit','equity','prior_equity','annual_roe_pct','source','ttm_profit','ttm_status']

def valid(r):
 return isinstance(r,dict) and r.get('status')=='000' and bool(r.get('accounts'))

def retryable(r,now):
 if valid(r):return False
 return not isinstance(r,dict) or str(r.get('retry_after_utc',''))<=now.isoformat()

def qkind(market_date):
 # Only periods whose statutory reporting deadline is past are considered.
 d=dt.date.fromisoformat(market_date[:4]+'-'+market_date[4:6]+'-'+market_date[6:8]) if len(market_date)==8 else dt.date.today()
 if d.month>=11 or (d.month==11 and d.day>=15):return 'q3'
 if d.month>=8:return 'half'
 if d.month>=5:return 'q1'
 return None

def ttm(cache,code,annual_year,asof_year,kind):
 annual=cache.get(f'{code}:{annual_year}:annual',{})
 if not valid(annual):return None,'NO_ANNUAL'
 if not kind:return None,'NO_REPORT_DUE'
 curr=cache.get(f'{code}:{asof_year}:{kind}',{})
 prev=cache.get(f'{code}:{annual_year}:{kind}',{})
 if not valid(curr) or not valid(prev):return None,'MISSING_QUARTER'
 if len({annual.get('fs_div'),curr.get('fs_div'),prev.get('fs_div')})!=1:return None,'BASIS_MISMATCH'
 vals=[annual['accounts'].get('profit'),curr['accounts'].get('profit'),prev['accounts'].get('profit')]
 if any(not isinstance(v,(int,float)) or isinstance(v,bool) for v in vals):return None,'MISSING_PROFIT'
 return vals[0]+vals[1]-vals[2],'VERIFIED_CUMULATIVE'

def rebuild(cache,base,annual_year,asof_year,kind,market_date,metrics):
 rows=[];complete=0;ttm_count=0
 for row in base:
  code=row['code'];entry=cache.get(f'{code}:{annual_year}:annual',{})
  ac=entry.get('accounts',{}) if valid(entry) else {}
  p,e,pe=ac.get('profit'),ac.get('equity'),ac.get('previous_equity')
  annual_roe=m.ratio(None,p,e,pe)['roe_pct']
  tp,ts=ttm(cache,code,annual_year,asof_year,kind)
  complete+=bool(ac);ttm_count+=ts=='VERIFIED_CUMULATIVE'
  rows.append({'code':code,'year':annual_year,'fs_div':entry.get('fs_div','') if ac else '',
   'annual_profit':p if p is not None else '', 'equity':e if e is not None else '',
   'prior_equity':pe if pe is not None else '', 'annual_roe_pct':annual_roe if annual_roe is not None else '',
   'source':'OpenDART fnlttSinglAcntAll' if ac else 'UNVERIFIED',
   'ttm_profit':tp if tp is not None else '', 'ttm_status':ts})
 with (OUT/'annual_financial_index_m.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
 status={'version':'R14_N_ANNUAL_QUARTER_TTM','generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
  'market_date':market_date,'base_rows':len(base),'cache_records':len(cache),
  'fetched_this_run':metrics['fetched'],'failed_this_run':metrics['failed'],
  'api_rejected_this_run':metrics['rejected'],'annual_verified_rows':complete,
  'batch_limit':LIMIT,'ttm_calculated':ttm_count,'ttm_period':kind or '',
  'final_buy_signals':0,'golden_cross_used':False,
  'notes':['TTM uses annual plus current cumulative minus prior-year matching cumulative; identical CFS/OFS basis required',
   'No official KRX PER/PBR verification; no investment buy signal computed',
   'Existing verified financial cache retained; unverified API responses have a retry cooldown']}
 m.save_json(OUT/'status.json',status)
 print(json.dumps(status,ensure_ascii=False,indent=2))

def main():
 if not m.KEY and os.getenv('R14_REBUILD_ONLY')!='1':raise SystemExit('MISSING_DART_API_KEY')
 if not m.L.exists():raise SystemExit('MISSING_L_INDEX')
 with m.L.open(encoding='utf-8-sig',newline='') as f:base=list(csv.DictReader(f))
 market_file=ROOT/'data/v5_investment_r14_research_k/full_market_ratios_k.csv'
 if market_file.exists():
  with market_file.open(encoding='utf-8-sig',newline='') as f: market=list(csv.DictReader(f))
  indexed={r['code']:r for r in base}
  for r in market:
   code=str(r.get('ISU_CD','')).zfill(6)
   if code.isdigit() and code not in indexed:indexed[code]={'code':code,'corp_code':''}
  base=list(indexed.values())
 cache=m.load_json(OUT/'dart_financial_cache.json',{})
 if os.getenv('R14_REBUILD_ONLY')=='1':
  market_date=m.load_json(OUT/'status.json',{}).get('market_date','')
  asof_year=int(market_date[:4]) if len(market_date)>=4 else dt.date.today().year
  st=m.load_json(OUT/'status.json',{})
  rebuild(cache,base,asof_year-1,asof_year,qkind(market_date),market_date,
   {'fetched':st.get('fetched_this_run',0),'failed':st.get('failed_this_run',0),'rejected':st.get('api_rejected_this_run',0)})
  return
 mapping=m.corp_map()
 market_date=m.load_json(ROOT/'data/v5_investment_r14_research_k/status.json',{}).get('market_date','')
 asof_year=int(market_date[:4]) if len(market_date)>=4 else dt.date.today().year
 annual_year=asof_year-1;kind=qkind(market_date)
 now=dt.datetime.now(dt.timezone.utc);annual=[];quarters=[]
 for row in base:
  code=row['code'];corp=row.get('corp_code') or mapping.get(code)
  if not corp:continue
  a=(code,corp,annual_year,'annual')
  if retryable(cache.get(f'{code}:{annual_year}:annual'),now):annual.append(a)
  if kind and valid(cache.get(f'{code}:{annual_year}:annual')):
   for year in (asof_year,annual_year):
    key=f'{code}:{year}:{kind}'
    if retryable(cache.get(key),now):quarters.append((code,corp,year,kind))
 # Alternate annual/quarterly tasks to prevent quarterly starvation.
 selected=[]
 while len(selected)<LIMIT and (annual or quarters):
  if annual:selected.append(annual.pop(0))
  if len(selected)<LIMIT and quarters:selected.append(quarters.pop(0))
 metrics={'fetched':0,'failed':0,'rejected':0}
 for code,corp,year,report in selected:
  key=f'{code}:{year}:{report}'
  try:
   record=m.request(corp,year,report)
   record.update(corp_code=corp,year=year,fetched_utc=dt.datetime.now(dt.timezone.utc).isoformat())
   if valid(record):
    cache[key]=record;metrics['fetched']+=1
   else:
    metrics['rejected']+=1
    if not valid(cache.get(key)):
     cache[key]={'status':'UNVERIFIED','reason':record.get('status','UNKNOWN'),
       'api_status':record.get('api_status'), 'fetched_utc':now.isoformat(),
       'retry_after_utc':(now+dt.timedelta(days=COOLDOWN_DAYS)).isoformat()}
  except Exception as exc:
   metrics['failed']+=1;print('FETCH_FAILED',key,type(exc).__name__,str(exc)[:150])
   if not valid(cache.get(key)):
    cache[key]={'status':'FETCH_FAILED','fetched_utc':now.isoformat(),
      'retry_after_utc':(now+dt.timedelta(days=1)).isoformat()}
  if sum(metrics.values())%10==0:m.save_json(OUT/'dart_financial_cache.json',cache)
  time.sleep(.13)
 m.save_json(OUT/'dart_financial_cache.json',cache)
 rebuild(cache,base,annual_year,asof_year,kind,market_date,metrics)

if __name__=='__main__':main()
