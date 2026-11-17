#!/usr/bin/env python3
"""Official KRX previous-session snapshot -> R14 market input and dated archive.
Never fabricates prices or advances dates on an incomplete API response.
"""
import csv,datetime as dt,json,os,pathlib,re,sys,time,urllib.request,urllib.parse
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]
DATA=ROOT/'data'; OUT=DATA/'v5_r14_market_bridge'; OUT.mkdir(parents=True,exist_ok=True)
NOW=dt.datetime.now(ZoneInfo('Asia/Seoul'))
FIELDS=['BAS_DD','ISU_CD','ISU_NM','TDD_CLSPRC','ACC_TRDVOL','MKTCAP','MARKET']
def readcsv(p):
 if not p.exists():return []
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def writecsv(p,rows,fields):
 p.parent.mkdir(parents=True,exist_ok=True);temp=p.with_suffix('.tmp')
 with temp.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
 temp.replace(p)
def n(v):
 try:return int(str(v).replace(',','').strip())
 except (ValueError,TypeError):return -1
def target_day():
 d=NOW.date()-dt.timedelta(days=1)
 while d.weekday()>4:d-=dt.timedelta(days=1)
 return d.strftime('%Y%m%d')
def get_krx(endpoint,day,key):
 url='https://data-dbg.krx.co.kr/svc/apis/sto/'+endpoint+'?'+urllib.parse.urlencode({'basDd':day})
 req=urllib.request.Request(url,headers={'AUTH_KEY':key,'User-Agent':'KRX-v5/1.0','Accept':'application/json'})
 with urllib.request.urlopen(req,timeout=60) as res: obj=json.load(res)
 if not isinstance(obj,dict) or not isinstance(obj.get('OutBlock_1'),list):raise RuntimeError('Unexpected KRX API response: '+endpoint)
 return obj['OutBlock_1']
def main():
 day=os.environ.get('KRX_TARGET_DATE') or target_day()
 if not re.fullmatch(r'20\d{6}',day):raise RuntimeError('Invalid target date')
 key=os.environ.get('KRX_API_KEY') or os.environ.get('AUTH_KEY')
 if not key:raise RuntimeError('KRX_API_KEY GitHub secret is missing')
 result=[];counts={}
 for market,ep in [('KOSPI','stk_bydd_trd'),('KOSDAQ','ksq_bydd_trd')]:
  raw=[]
  for attempt in range(3):
   try:
    raw=get_krx(ep,day,key)
    if raw:break
   except Exception as e:
    if attempt==2:raise
   time.sleep(15)
  counts[market]=len(raw)
  for r in raw:
   code=str(r.get('ISU_CD','')).strip();close=n(r.get('TDD_CLSPRC'));cap=n(r.get('MKTCAP'))
   if not re.fullmatch(r'\d{6}',code) or close<=0 or cap<=0:continue
   result.append(dict(BAS_DD=day,ISU_CD=code,ISU_NM=str(r.get('ISU_NM','')),TDD_CLSPRC=close,ACC_TRDVOL=max(0,n(r.get('ACC_TRDVOL'))),MKTCAP=cap,MARKET=market))
 # Avoid a partial market being silently accepted as current.
 if counts.get('KOSPI',0)<700 or counts.get('KOSDAQ',0)<1000 or len(result)<2000:
  raise RuntimeError(f'KRX snapshot incomplete or not published for {day}: raw={counts}, valid={len(result)}; prior data preserved')
 old=readcsv(DATA/'latest.csv')
 oldday=max((r.get('BAS_DD','') for r in old),default='')
 if oldday>day:raise RuntimeError(f'Refusing to overwrite newer market snapshot {oldday} with {day}')
 result.sort(key=lambda r:(r['MARKET'],r['ISU_CD']))
 writecsv(DATA/'latest.csv',result,FIELDS)
 # Independent archive is keyed by (date, code), so reruns are idempotent.
 archive=OUT/'official_daily_prices.csv';rows=readcsv(archive)
 index={(r.get('BAS_DD'),r.get('ISU_CD')):r for r in rows if re.fullmatch(r'20\d{6}',r.get('BAS_DD','')) and re.fullmatch(r'\d{6}',r.get('ISU_CD',''))}
 for r in result:index[(day,r['ISU_CD'])]=r
 writecsv(archive,[index[k] for k in sorted(index)],FIELDS)
 status={'version':'R14_KRX_0800_BRIDGE_E','run_kst':NOW.isoformat(),'target_market_date':day,'previous_latest_date':oldday,'latest_market_date':day,'raw_market_counts':counts,'valid_market_rows':len(result),'archive_rows':len(index),'archive_dates':len({k[0] for k in index}),'golden_cross_used':False,'source':'KRX Open API stk_bydd_trd + ksq_bydd_trd','official_per_pbr_verified':False}
 (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(status,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
