#!/usr/bin/env python3
"""KRX trading-day gate + verified fresh daily snapshot for Stage60.
Never silently reuse a stale snapshot as current. No trading recommendation.
"""
import csv, datetime as dt, json, os, pathlib, sys
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'stage60_output'; OUT.mkdir(exist_ok=True)
KST=ZoneInfo('Asia/Seoul')
now=dt.datetime.now(KST)
today=now.date()
status={'stage':60,'component':'market_gate','kst_now':now.isoformat(),'target_date':today.strftime('%Y%m%d'),'state':'UNKNOWN','market_data_fresh':False}
def save(code=0):
 (OUT/'market_gate_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(status,ensure_ascii=False));return code
try:
 import exchange_calendars as xcals
 import pandas as pd
 cal=xcals.get_calendar('XKRX')
 day=pd.Timestamp(today.isoformat())
 is_session=bool(cal.is_session(day))
except Exception as exc:
 status.update(state='CALENDAR_UNAVAILABLE',error=str(exc));sys.exit(save(1))
if not is_session:
 status.update(state='KRX_CLOSED',reason='KRX calendar marks a non-trading day')
 sys.exit(save(0))
# The KRX daily snapshot should not be fetched before close; fail closed.
if now.hour < 18:
 status.update(state='BEFORE_VERIFIED_CLOSE_WINDOW',reason='Run at or after 18:00 KST')
 sys.exit(save(1))
try:
 from pykrx import stock
 target=today.strftime('%Y%m%d')
 rows=[]
 for market in ('KOSPI','KOSDAQ'):
  ohlcv=stock.get_market_ohlcv_by_ticker(target,market=market)
  caps=stock.get_market_cap_by_ticker(target,market=market)
  if ohlcv is None or caps is None or len(ohlcv)<100 or len(caps)<100:
   raise RuntimeError(f'KRX returned insufficient {market} rows')
  for code,rec in ohlcv.iterrows():
   if code not in caps.index:continue
   close=int(rec['종가']);volume=int(rec['거래량']);cap=int(caps.loc[code,'시가총액'])
   if close<=0 or cap<=0:continue
   rows.append({'BAS_DD':target,'ISU_CD':str(code).zfill(6),'ISU_NM':stock.get_market_ticker_name(code),'TDD_CLSPRC':close,'ACC_TRDVOL':volume,'MKTCAP':cap,'MARKET':market})
 if len(rows)<1500:raise RuntimeError(f'Insufficient combined validated rows: {len(rows)}')
 if len({(r['MARKET'],r['ISU_CD']) for r in rows})!=len(rows):raise RuntimeError('Duplicate market/ticker rows')
 # Verify data date using the actual OHLCV day request; never accept an empty or older response.
 dest=ROOT/'data'/'latest.csv';dest.parent.mkdir(exist_ok=True)
 temp=OUT/'fresh_latest.csv'
 with temp.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 # Stage59 needs a persistent, date-keyed history, not just one day's snapshot.
 history=ROOT/'stage59_input'/'daily_prices.csv';history.parent.mkdir(exist_ok=True)
 old=[]
 if history.exists():
  with history.open(encoding='utf-8-sig',newline='') as f:old=list(csv.DictReader(f))
 known={}
 for r in old:
  key=(r.get('BAS_DD'),r.get('MARKET'),r.get('ISU_CD'))
  if key[0] and key[1] and key[2]:known[key]=r
 for r in rows:
  known[(target,r['MARKET'],r['ISU_CD'])]={k:r[k] for k in ('BAS_DD','MARKET','ISU_CD','TDD_CLSPRC')}
 temp_history=OUT/'fresh_daily_prices.csv'
 with temp_history.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['BAS_DD','MARKET','ISU_CD','TDD_CLSPRC']);w.writeheader();w.writerows(sorted(known.values(),key=lambda r:(r['BAS_DD'],r['MARKET'],r['ISU_CD'])))
 # Replace only after both outputs validate.
 os.replace(temp,dest);os.replace(temp_history,history)
 status.update(state='FRESH_KRX_SNAPSHOT_VALIDATED',market_data_fresh=True,rows=len(rows),history_rows=len(known),source='pykrx KRX daily OHLCV and market cap')
 sys.exit(save(0))
except Exception as exc:
 status.update(state='REFRESH_FAILED',error=str(exc));sys.exit(save(1))
