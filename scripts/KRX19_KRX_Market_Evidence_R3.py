#!/usr/bin/env python3
"""Read-only KRX market evidence collector; NOT an official PER/PBR endpoint."""
import argparse,csv,datetime,json,os,pathlib,urllib.request,urllib.error,time

URLS={'KOSPI':'https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd','KOSDAQ':'https://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd'}
FIELDS=['code','name','market','basis_date','close_krw','market_cap_krw','listed_shares','source','per_official','pbr_official','valuation_status']
def num(v):
 try:return float(str(v).replace(',','').strip())
 except (ValueError,TypeError):return None
def fetch(url,key,date):
 req=urllib.request.Request(url,data=json.dumps({'basDd':date}).encode(),headers={'AUTH_KEY':key,'Content-Type':'application/json'},method='POST')
 with urllib.request.urlopen(req,timeout=35) as response:return json.load(response)
def main():
 p=argparse.ArgumentParser();p.add_argument('--date',required=True,help='YYYYMMDD, actual trading date');p.add_argument('--output-dir',default='stage19_r3_output');p.add_argument('--universe',default='data/v5_full_market_universe.json');p.add_argument('--offline',action='store_true');a=p.parse_args()
 datetime.datetime.strptime(a.date,'%Y%m%d');out=pathlib.Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
 universe=json.loads(pathlib.Path(a.universe).read_text(encoding='utf-8'));stocks=universe.get('stocks',[])
 target={str(s['code']).strip().upper():s for s in stocks};key=os.environ.get('KRX_API_KEY','').strip()
 results=[];errors=[];market_counts={};received=0
 if not key and not a.offline:errors.append('KRX_API_KEY missing')
 if key and not a.offline:
  for market,url in URLS.items():
   try:
    payload=fetch(url,key,a.date)
    raw=payload.get('OutBlock_1')
    if not isinstance(raw,list):raise ValueError('OutBlock_1 missing; response keys: '+','.join(payload.keys()))
    market_counts[market]=len(raw);received+=len(raw)
    for e in raw:
     code=str(e.get('ISU_SRT_CD') or e.get('ISU_CD') or '').strip().upper()
     if code not in target:continue
     basis=str(e.get('BAS_DD') or '').replace('-','')
     if basis!=a.date:continue
     close=num(e.get('TDD_CLSPRC'));cap=num(e.get('MKTCAP'));shares=num(e.get('LIST_SHRS'))
     if close is None or close<=0 or cap is None or cap<=0 or shares is None or shares<=0:continue
     results.append({'code':code,'name':target[code].get('name',''),'market':market,'basis_date':basis,'close_krw':close,'market_cap_krw':cap,'listed_shares':shares,'source':'KRX_OPEN_API_DAILY_TRADING','per_official':'','pbr_official':'','valuation_status':'OFFICIAL_MARKET_DATA_ONLY_PER_PBR_UNVERIFIED'})
   except (urllib.error.URLError,ValueError,TimeoutError,KeyError) as ex:errors.append(market+': '+str(ex)[:250])
 rows=sorted({r['code']:r for r in results}.values(),key=lambda r:r['code'])
 with (out/'v5_stage19_r3_market_evidence.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
 summary={'stage':'19_R3','requested_date':a.date,'universe_count':len(target),'api_market_rows':market_counts,'api_rows_received':received,'matched_valid_market_rows':len(rows),'official_per_pbr_verified_count':0,'classification':'MARKET_EVIDENCE_ONLY_NOT_OFFICIAL_PER_PBR','errors':errors,'status':'PASS_MARKET_EVIDENCE' if rows and not errors else 'INCOMPLETE'}
 (out/'v5_stage19_r3_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
