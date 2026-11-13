#!/usr/bin/env python3
"""Conservative v5 daily evidence archive: no experimental cohort promotion."""
import csv, json, pathlib, datetime
ROOT=pathlib.Path('data/v5_integrated'); ROOT.mkdir(parents=True,exist_ok=True)
ART=pathlib.Path('incoming'); OUT=pathlib.Path('v5_daily_out'); OUT.mkdir(exist_ok=True)
def rows(p):
 with open(p,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(p,rs,cols):
 p.parent.mkdir(parents=True,exist_ok=True)
 with open(p,'w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rs)
def load(p):return rows(p) if p.exists() else []
def latest_source(name):
 p=ART/name
 if not p.exists():raise RuntimeError('Missing artifact input '+str(p))
 return p
BASE_COL=['episode_id','entry_date','market','code','name','entry_price','provisional_grade','status','exit_date','source','final_buy_signal']
PRICE_COL=['date','market','code','close']
PERF_COL=['episode_id','entry_date','code','market','entry_price','grade','horizon','target_date','target_close','return_pct','result']
STATUS={'mode':'EVIDENCE_AND_PERFORMANCE_ARCHIVE_ONLY','final_buy_signals':0,'daily_formal_rescoring':'NOT_IMPLEMENTED','experimental_stage57_promoted':False,'state_commit':'PENDING','limitations':['Performance horizons count only archived confirmed market sessions; missing trading days can shift horizons until daily coverage is complete','Daily full-market financial regrading and candidate entry/exit are not implemented','Historical Stage55 baseline is not a live buy recommendation']}
try:
 market=json.loads(latest_source('stage50/status.json').read_text(encoding='utf-8'))
 stage55=json.loads(latest_source('stage55/status.json').read_text(encoding='utf-8'))
 day=str(market.get('market_date',''))
 if not(day.isdigit() and len(day)==8):raise RuntimeError('Missing market date')
 source=market.get('source')
 verification=market.get('verification') or {}
 counts=verification.get('counts') or {}
 total=market.get('total_market_issues')
 matches=verification.get('price_matches')
 compared=verification.get('price_compared')
 archive_verified=(source=='VERIFIED_PRIOR_STAGE50_ARTIFACT'
  and market.get('result')=='SUCCESS'
  and market.get('snapshot_is_reference_date') is True
  and isinstance(counts,dict)
  and all(isinstance(counts.get(m),int) and counts[m]>=100 for m in ('KOSPI','KOSDAQ'))
  and isinstance(total,int) and total>=2000 and sum(counts.values())==total
  and isinstance(matches,int) and isinstance(compared,int) and matches==compared==total)
 if market.get('source_dates')!=[day] or not (source=='KRX_API_both_markets' or archive_verified):
  raise RuntimeError('KRX both-market provenance not confirmed: source='+str(source)+' verified_archive='+str(archive_verified))
 STATUS.update(market_source=source,verified_archive_reused=archive_verified)
 current=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()
 d=datetime.datetime.strptime(day,'%Y%m%d').date()
 if d>current:raise RuntimeError('Future market date')
 state=ROOT/'last_market_date.txt'; prev=state.read_text().strip() if state.exists() else ''
 STATUS.update(market_date=day,previous_market_date=prev)
 if prev and day<prev:raise RuntimeError('Market date regressed')
 if prev==day:
  STATUS.update(result='NO_NEW_MARKET_DATE',state_commit='NOT_NEEDED')
 else:
  if d.weekday()>=5:raise RuntimeError('Invalid weekend market date')
  if (current-d).days>4:raise RuntimeError('Stale market snapshot: '+day)
  full=rows(latest_source('stage50/full_market_issues.csv'))
  print('full_market_columns',list(full[0]) if full else [])
  def get(r,*keys):return next((r[k] for k in keys if k in r and str(r[k]).strip()),'')
  daily=[]
  for r in full:
   date=get(r,'BAS_DD','date');market_name=get(r,'MKT_NM','MARKET','market');code=get(r,'ISU_CD','code');price=get(r,'TDD_CLSPRC','close')
   if date and date!=day:raise RuntimeError('Mixed dates in market rows')
   if not (market_name and code and price):raise RuntimeError('Missing market/code/close in Stage50')
   if market_name not in ('KOSPI','KOSDAQ'):raise RuntimeError('Unexpected market '+market_name)
   daily.append(dict(date=day,market=market_name,code=code,close=price.replace(',','').strip()))
  if len(daily)<2000 or len(set((r['market'],r['code']) for r in daily))!=len(daily):raise RuntimeError('Incomplete/duplicate daily market snapshot')
  if archive_verified:
   daily_counts={m:sum(r['market']==m for r in daily) for m in ('KOSPI','KOSDAQ')}
   if daily_counts!=counts:raise RuntimeError('Archived Stage50 row counts differ from verified provenance')
  old=load(ROOT/'daily_prices.csv'); old=[r for r in old if r['date']!=day]
  allprices=old+daily
  allprices.sort(key=lambda r:(r['date'],r['market'],r['code']))
  baseline=rows(latest_source('stage55/candidate_performance_baseline.csv'))
  episodes=load(ROOT/'episodes.csv')
  if not episodes:
   for r in baseline:
    entry=get(r,'stage55_reference_date');market_name=get(r,'stage55_reference_market');code=get(r,'stage55_reference_code');price=get(r,'stage55_reference_price');grade=get(r,'stage55_research_grade')
    if not(entry and market_name and code and price and grade in ('A','B','B+')):raise RuntimeError('Invalid Stage55 baseline')
    episodes.append(dict(episode_id=f'{entry}:{market_name}:{code}',entry_date=entry,market=market_name,code=code,name=get(r,'ISU_NM'),entry_price=price,provisional_grade=grade,status='ACTIVE_BASELINE_NOT_DAILY_REEVALUATED',exit_date='',source='STAGE55_BASELINE',final_buy_signal='NONE'))
  price_lookup={(r['date'],r['market'],r['code']):float(r['close']) for r in allprices if float(r['close'])>0}
  market_dates={}
  for r in allprices:market_dates.setdefault(r['market'],set()).add(r['date'])
  market_dates={k:sorted(v) for k,v in market_dates.items()}
  perf=[]
  for e in episodes:
   dates=market_dates.get(e['market'],[])
   for h in (5,10,20):
    later=[v for v in dates if v>e['entry_date']]
    target=later[h-1] if len(later)>=h else ''
    p=price_lookup.get((target,e['market'],e['code'])) if target else None
    start=float(e['entry_price'])
    result='DONE' if p is not None and start>0 else ('PRICE_MISSING' if target else 'PENDING')
    perf.append(dict(episode_id=e['episode_id'],entry_date=e['entry_date'],code=e['code'],market=e['market'],entry_price=e['entry_price'],grade=e['provisional_grade'],horizon=h,target_date=target,target_close=p if p is not None else '',return_pct=round((p/start-1)*100,4) if result=='DONE' else '',result=result))
  write(ROOT/'daily_prices.csv',allprices,PRICE_COL)
  write(ROOT/'episodes.csv',episodes,BASE_COL)
  write(ROOT/'performance.csv',perf,PERF_COL)
  state.write_text(day+'\n')
  STATUS.update(result='NEW_MARKET_DATE_ARCHIVED',market_rows=len(daily),price_rows=len(allprices),episodes=len(episodes),performance_completed=sum(r['result']=='DONE' for r in perf),performance_pending=sum(r['result']=='PENDING' for r in perf),state_commit='REQUIRED')
finally:
 (OUT/'status.json').write_text(json.dumps(STATUS,ensure_ascii=False,indent=2),encoding='utf-8')
