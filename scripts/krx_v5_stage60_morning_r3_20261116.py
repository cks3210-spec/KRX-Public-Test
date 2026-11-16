#!/usr/bin/env python3
"""KRX v5 official API D-1 collector, persistent archive and optional Stage56-59 chain.
No modification to historical financial caches. Fails closed on stale/incomplete data.
"""
import csv, datetime as dt, hashlib, json, os, pathlib, re, subprocess, sys, urllib.parse, urllib.request
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'stage60_0830_output'; OUT.mkdir(parents=True,exist_ok=True)
KST=ZoneInfo('Asia/Seoul'); NOW=dt.datetime.now(KST)
STATUS={'generated_at_kst':NOW.isoformat(),'mode':'OFFICIAL_KRX_PREVIOUS_SESSION','state':'STARTED','market_verified':False,'pipeline_complete':False,'official_per_pbr_verified':False,'trade_signals_released':0}
def write_status():
 (OUT/'status.json').write_text(json.dumps(STATUS,ensure_ascii=False,indent=2),encoding='utf-8')
def fail(message):
 STATUS.update(state='BLOCKED',error=message[:500]);write_status();raise RuntimeError(message)
def previous_session():
 import exchange_calendars as xcals
 import pandas as pd
 cal=xcals.get_calendar('XKRX')
 today=pd.Timestamp(NOW.date().isoformat())
 if not cal.is_session(today):
  STATUS.update(state='SKIPPED_KRX_CLOSED');write_status();return None
 # previous_session() accounts for weekends and exchange holidays.
 return cal.previous_session(today).strftime('%Y%m%d')
def get_rows(market,url,day,key):
 request=urllib.request.Request(url+'?'+urllib.parse.urlencode({'basDd':day}),headers={'AUTH_KEY':key,'Accept':'application/json','User-Agent':'KRX-v5-stage60-0830/1.0'})
 with urllib.request.urlopen(request,timeout=40) as response:
  raw=response.read(); http_code=response.status
 payload=json.loads(raw)
 block=payload.get('OutBlock_1')
 STATUS.setdefault('api_diagnostics',{})[market]={'http_status':http_code,'row_count':len(block) if isinstance(block,list) else None,'response_keys':list(payload)[:12],'response_sha256':hashlib.sha256(raw).hexdigest(),'result':str(payload.get('RESULT',''))[:200]}
 if not isinstance(block,list) or len(block)<100:raise ValueError(f'{market}: insufficient official rows ({len(block) if isinstance(block,list) else "missing"})')
 rows=[]
 for r in block:
  if str(r.get('BAS_DD','')).strip()!=day:raise ValueError(f'{market}: mixed data date')
  code=str(r.get('ISU_CD','')).strip()
  close=str(r.get('TDD_CLSPRC','')).replace(',','').strip()
  cap=str(r.get('MKTCAP','')).replace(',','').strip()
  volume=str(r.get('ACC_TRDVOL','')).replace(',','').strip()
  if not re.fullmatch(r'[0-9A-Z]{6}',code) or not close.isdigit() or not cap.isdigit() or not volume.isdigit() or int(close)<=0 or int(cap)<=0:
   raise ValueError(f'{market}: invalid row')
  rows.append({'BAS_DD':day,'ISU_CD':code,'ISU_NM':r.get('ISU_NM',''),'TDD_CLSPRC':close,'ACC_TRDVOL':volume,'MKTCAP':cap,'MARKET':market})
 return rows
def atomic_csv(path,rows,columns):
 path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_name(path.name+'.tmp')
 with tmp.open('w',encoding='utf-8-sig',newline='') as f:
  writer=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
 tmp.replace(path)
def main():
 day=previous_session()
 if day is None:return
 STATUS['target_market_date']=day
 if NOW.hour<8 or (NOW.hour==8 and NOW.minute<30):fail('Scheduled window is 08:30 KST or later')
 key=os.environ.get('KRX_API_KEY','').strip()
 if not key:fail('KRX_API_KEY missing')
 endpoints={'KOSPI':'https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd','KOSDAQ':'https://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd'}
 rows=[]; errors={}
 for market,url in endpoints.items():
  try:rows.extend(get_rows(market,url,day,key))
  except Exception as exc:errors[market]=str(exc)[:300]
 STATUS['api_errors']=errors
 if errors:fail('Official KRX data unavailable for '+day+': '+str(errors))
 if len(rows)<1500 or len({(r['MARKET'],r['ISU_CD']) for r in rows})!=len(rows):fail('Incomplete or duplicate official market snapshot')
 existing=ROOT/'data/latest.csv'
 if existing.exists():
  with existing.open(encoding='utf-8-sig',newline='') as f:
   first=next(csv.DictReader(f),None)
  if first and str(first.get('BAS_DD',''))>day:fail('Existing market snapshot is newer; refusing regression')
 columns=['BAS_DD','ISU_CD','ISU_NM','TDD_CLSPRC','ACC_TRDVOL','MKTCAP','MARKET']
 archive=ROOT/'data/v5_official_market_archive'/f'{day}.csv'
 atomic_csv(archive,rows,columns)
 atomic_csv(existing,rows,columns)
 history=ROOT/'stage59_input/daily_prices.csv'
 old={}
 if history.exists():
  with history.open(encoding='utf-8-sig',newline='') as f:
   for r in csv.DictReader(f):
    if r.get('BAS_DD') and r.get('MARKET') and r.get('ISU_CD'):
     old[(r['BAS_DD'],r['MARKET'],r['ISU_CD'])]={k:r.get(k,'') for k in ('BAS_DD','MARKET','ISU_CD','TDD_CLSPRC')}
 for r in rows:old[(day,r['MARKET'],r['ISU_CD'])]={k:r[k] for k in ('BAS_DD','MARKET','ISU_CD','TDD_CLSPRC')}
 atomic_csv(history,[old[k] for k in sorted(old)],['BAS_DD','MARKET','ISU_CD','TDD_CLSPRC'])
 STATUS.update(state='OFFICIAL_MARKET_ARCHIVED',market_verified=True,market_date=day,market_rows=len(rows),history_rows=len(old),archive_file=str(archive.relative_to(ROOT)))
 write_status()
 if os.environ.get('RUN_EXISTING_STAGE_CHAIN','1')=='1':
  chain=ROOT/'scripts/v5_stage60_pipeline.py'
  gate=ROOT/'stage60_output/market_gate_status.json';gate.parent.mkdir(exist_ok=True)
  gate.write_text(json.dumps({'state':'FRESH_KRX_SNAPSHOT_VALIDATED','market_data_fresh':True,'target_date':day,'source':'KRX Open API','rows':len(rows)}),encoding='utf-8')
  if chain.exists():
   try:
    result=subprocess.run([sys.executable,str(chain)],cwd=ROOT,capture_output=True,text=True,timeout=900)
    STATUS['stage56_59']={'exit_code':result.returncode,'stdout_tail':result.stdout[-1200:],'stderr_tail':result.stderr[-1200:]}
    STATUS['pipeline_complete']=result.returncode==0
   except Exception as exc:STATUS['stage56_59']={'error':str(exc)[:300]}
  else:STATUS['stage56_59']={'state':'MISSING_EXISTING_ORCHESTRATOR'}
  STATUS['state']='OFFICIAL_MARKET_ARCHIVED_CHAIN_EXECUTED' if STATUS['pipeline_complete'] else 'OFFICIAL_MARKET_ARCHIVED_CHAIN_INCOMPLETE'
  write_status()
if __name__=='__main__':
 try:main()
 except Exception as exc:
  STATUS.setdefault('error',str(exc)[:500]);STATUS['state']='BLOCKED';write_status();raise
 finally:write_status();print(json.dumps(STATUS,ensure_ascii=False))
