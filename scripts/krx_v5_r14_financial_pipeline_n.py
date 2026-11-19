#!/usr/bin/env python3
"""R14 N: safe incremental annual/quarter OpenDART collection and TTM rebuild.
Existing M parser and persistent cache remain authoritative. No buy signals.
"""
import csv, datetime as dt, importlib.util, json, os, pathlib, time
from collections import Counter
ROOT=pathlib.Path(os.getenv('GITHUB_WORKSPACE','.')).resolve()
OUT=ROOT/'data/v5_financial_m'
spec=importlib.util.spec_from_file_location('r14_m_existing',ROOT/'scripts/krx_v5_r14_dart_incremental_m.py')
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
 d=dt.date.fromisoformat(market_date[:4]+'-'+market_date[4:6]+'-'+market_date[6:8])
 if (d.month,d.day)>=(11,15):return 'q3'
 if (d.month,d.day)>=(8,14):return 'half'
 if (d.month,d.day)>=(5,15):return 'q1'
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
 OUT.mkdir(parents=True,exist_ok=True)
 with (OUT/'annual_financial_index_m.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
 status={'version':'R14_N_ANNUAL_QUARTER_TTM','generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
  'market_date':market_date,'base_rows':len(base),'cache_records':len(cache),
  'fetched_this_run':metrics.get('fetched',0),'failed_this_run':metrics.get('failed',0),
  'api_rejected_this_run':metrics.get('rejected',0),'annual_verified_rows':complete,
  'batch_limit':LIMIT,'ttm_calculated':ttm_count,'ttm_period':kind or '',
  'financial_snapshot_date_source':'R14_RESEARCH_STATUS' if metrics.get('date_source')=='R14_RESEARCH_STATUS' else 'EXISTING_FINANCIAL_STATUS',
  'prior_financial_snapshot_date':metrics.get('prior_date',''),
  'financial_snapshot_date_changed':metrics.get('date_changed',False),
  'financial_disclosure_asof_verified':False, 'point_in_time_financials_authorized':False,
  'unmapped_corp_codes':metrics.get('unmapped',0), 'pending_annual':metrics.get('pending_annual',0),
  'pending_quarters':metrics.get('pending_quarters',0),'selected_annual':metrics.get('selected_annual',0),
  'selected_quarters':metrics.get('selected_quarters',0),
  'final_buy_signals':0,'golden_cross_used':False,
  'financial_disclosure_asof_verified':False,'investment_decisions_authorized':False,
  'notes':['TTM requires annual and matching cumulative quarter with same CFS/OFS basis',
   'Financial cache market_date is not proof of actual disclosure date',
   'Official PER/PBR and point-in-time disclosure verification pending; no buy signals',
   'Previously verified cache records are preserved; failures use retry cooldown']}
 m.save_json(OUT/'status.json',status)
 print(json.dumps(status,ensure_ascii=False,indent=2))

def main():
 rebuild_only=os.getenv('R14_REBUILD_ONLY')=='1'
 if not m.KEY and not rebuild_only:raise SystemExit('MISSING_DART_API_KEY')
 if not m.L.exists():raise SystemExit('MISSING_L_INDEX')
 with m.L.open(encoding='utf-8-sig',newline='') as f:base=list(csv.DictReader(f))
 market_file=ROOT/'data/v5_investment_r14_research_k/full_market_ratios_k.csv'
 if market_file.exists():
  with market_file.open(encoding='utf-8-sig',newline='') as f:market=list(csv.DictReader(f))
  indexed={r['code']:r for r in base}
  for r in market:
   code=str(r.get('ISU_CD','')).zfill(6)
   if code.isdigit() and code not in indexed:indexed[code]={'code':code,'corp_code':''}
  base=list(indexed.values())
 cache=m.load_json(OUT/'dart_financial_cache.json',{})
 prior=m.load_json(OUT/'status.json',{})
 if rebuild_only:
  market_date=str(prior.get('market_date',''))
 else:
  # Keep financial snapshot date separate from official market evaluation date.
  market_date=str(m.load_json(ROOT/'data/v5_investment_r14_research_k/status.json',{}).get('market_date',''))
 if len(market_date)!=8 or not market_date.isdigit():raise SystemExit('INVALID_FINANCIAL_MARKET_DATE')
 try: dt.datetime.strptime(market_date,'%Y%m%d')
 except ValueError: raise SystemExit('INVALID_FINANCIAL_MARKET_DATE')
 previous_date=str(prior.get('market_date',''))
 if previous_date and len(previous_date)==8 and previous_date.isdigit() and market_date<previous_date:
  raise SystemExit('BLOCKED_FINANCIAL_DATE_REGRESSION: prior='+previous_date+' candidate='+market_date)
 print('R14_DATE_AUDIT',json.dumps({'financial_snapshot_date':market_date,'previous_financial_snapshot_date':previous_date,'date_changed':market_date!=previous_date,'date_source':'EXISTING_FINANCIAL_STATUS' if rebuild_only else 'R14_RESEARCH_STATUS','official_krx_evaluation_date_verified_here':False,'disclosure_asof_verified':False}))
 asof_year=int(market_date[:4]);annual_year=asof_year-1;kind=qkind(market_date)
 metrics={'fetched':0,'failed':0,'rejected':0,'date_source':'EXISTING_FINANCIAL_STATUS' if rebuild_only else 'R14_RESEARCH_STATUS','prior_date':previous_date,'date_changed':market_date!=previous_date}
 if rebuild_only:
  rebuild(cache,base,annual_year,asof_year,kind,market_date,metrics)
  return
 mapping=m.corp_map();now=dt.datetime.now(dt.timezone.utc)
 annual=[];quarters=[];unmapped=0
 for row in base:
  code=row['code'];corp=row.get('corp_code') or mapping.get(code)
  if not corp:
   unmapped+=1;continue
  annual_key=f'{code}:{annual_year}:annual'
  annual_ok=valid(cache.get(annual_key))
  if not annual_ok and retryable(cache.get(annual_key),now):annual.append((code,corp,annual_year,'annual'))
  if kind and annual_ok:
   for year in (asof_year,annual_year):
    key=f'{code}:{year}:{kind}'
    if retryable(cache.get(key),now):quarters.append((code,corp,year,kind))
 # Alternate missing annual and quarters; preserve order and bounded API budget.
 selected=[];ai=qi=0
 while len(selected)<LIMIT and (ai<len(annual) or qi<len(quarters)):
  if ai<len(annual):selected.append(annual[ai]);ai+=1
  if len(selected)<LIMIT and qi<len(quarters):selected.append(quarters[qi]);qi+=1
 metrics.update(unmapped=unmapped,pending_annual=len(annual),pending_quarters=len(quarters),
                selected_annual=ai,selected_quarters=qi)
 print('R14_SELECTION',json.dumps({k:metrics[k] for k in ('unmapped','pending_annual','pending_quarters','selected_annual','selected_quarters')}))
 for code,corp,year,report in selected:
  key=f'{code}:{year}:{report}'
  try:
   record=m.request(corp,year,report)
   record.update(corp_code=corp,year=year,fetched_utc=dt.datetime.now(dt.timezone.utc).isoformat())
   if valid(record):cache[key]=record;metrics['fetched']+=1
   else:
    metrics['rejected']+=1
    if not valid(cache.get(key)):
     cache[key]={'status':'UNVERIFIED','reason':record.get('status','UNKNOWN'),
      'api_status':record.get('api_status'),'fetched_utc':now.isoformat(),
      'retry_after_utc':(now+dt.timedelta(days=COOLDOWN_DAYS)).isoformat()}
  except Exception as exc:
   metrics['failed']+=1;print('FETCH_FAILED',key,type(exc).__name__,str(exc)[:150])
   if not valid(cache.get(key)):
    cache[key]={'status':'FETCH_FAILED','fetched_utc':now.isoformat(),
     'retry_after_utc':(now+dt.timedelta(days=1)).isoformat()}
  if sum(metrics[k] for k in ('fetched','failed','rejected'))%10==0:
   m.save_json(OUT/'dart_financial_cache.json',cache)
  time.sleep(.13)
 m.save_json(OUT/'dart_financial_cache.json',cache)
 rebuild(cache,base,annual_year,asof_year,kind,market_date,metrics)

if __name__=='__main__':main()
