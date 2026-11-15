#!/usr/bin/env python3
"""Stage17: independent scheduled continuation of Stage16 financial collection.
No market-day freshness gate; preserves Stage12-16 files and verified-grade withholding.
"""
import argparse, datetime as dt, json, os, pathlib, subprocess, sys, time
ROOT=pathlib.Path(__file__).resolve().parents[1]
DATA=ROOT/'data'

def load(name, default=None):
    try: return json.loads((DATA/name).read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError): return default

def atomic(name, obj):
    DATA.mkdir(parents=True, exist_ok=True)
    target=DATA/name
    temp=target.with_suffix(target.suffix+'.tmp')
    temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(target)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--max-seconds',type=int,default=4500)
    p.add_argument('--basic-batches',type=int,default=3)
    p.add_argument('--basic-batch-size',type=int,default=70)
    p.add_argument('--annual-limit',type=int,default=120)
    p.add_argument('--retry-days',type=int,default=3)
    p.add_argument('--offline',action='store_true')
    a=p.parse_args()
    if not 300<=a.max_seconds<=7800 or not 0<=a.basic_batches<=12 or not 1<=a.basic_batch_size<=150 or not 0<=a.annual_limit<=500:
        p.error('invalid limits')
    uni=load('v5_full_market_universe.json',{})
    if not uni.get('stocks'):
        raise SystemExit('Missing Stage12 universe; run daily workflow once first')
    if not (ROOT/'scripts/build_v5_stage16_continuous_financial.py').exists():
        raise SystemExit('Stage16 script missing')
    now=dt.datetime.now(dt.timezone.utc)
    key=bool(os.getenv('DART_API_KEY','').strip()) and not a.offline
    command=[sys.executable,str(ROOT/'scripts/build_v5_stage16_continuous_financial.py'),
             '--max-seconds',str(a.max_seconds),'--basic-batches',str(a.basic_batches),
             '--basic-batch-size',str(a.basic_batch_size),'--annual-limit',str(a.annual_limit),
             '--retry-days',str(a.retry_days)]
    if a.offline:command.append('--no-network')
    started=time.monotonic()
    status={'schema':1,'run_started_utc':now.isoformat(),'source_trading_date':uni.get('trading_date'),
            'mode':'OFFLINE' if a.offline else 'SCHEDULED_CONTINUATION',
            'api_key_configured':key,'collector':'STAGE16','result':'NOT_STARTED'}
    atomic('v5_stage17_status.json',status)
    if not key and not a.offline:
        status.update(result='CONFIGURATION_ERROR',reason='DART_API_KEY missing')
        atomic('v5_stage17_status.json',status)
        raise SystemExit('DART_API_KEY missing; no network collection attempted')
    try:
        result=subprocess.run(command,cwd=ROOT,timeout=a.max_seconds+240,check=False,text=True,capture_output=True)
        status['collector_exit_code']=result.returncode
        status['collector_stdout_tail']=result.stdout[-1200:]
        status['collector_stderr_tail']=result.stderr[-1200:]
        status['result']='SUCCESS' if result.returncode==0 else 'COLLECTOR_FAILED'
    except subprocess.TimeoutExpired:
        status['result']='COLLECTOR_TIMEOUT'
    progress=load('v5_stage16_progress.json',{}) or {}
    status.update(run_finished_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                  elapsed_seconds=round(time.monotonic()-started,1),
                  eligible_count=progress.get('eligible_count'),basic_cached=progress.get('basic_cached'),
                  basic_missing=progress.get('basic_missing'),annual_comparable_count=progress.get('annual_comparable_count'),
                  annual_filing_counts=progress.get('annual_filing_counts'),
                  provisional_grade_counts=progress.get('provisional_grade_counts'),
                  verified_ab_count=0,events=progress.get('events',[]),
                  caveat='Collection continues across runs; provisional grades are not investment recommendations.')
    atomic('v5_stage17_status.json',status)
    print(json.dumps(status,ensure_ascii=False))
    if status['result']!='SUCCESS':sys.exit(1)

if __name__=='__main__':main()
