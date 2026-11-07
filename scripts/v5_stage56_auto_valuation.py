#!/usr/bin/env python3
"""Stage56 KRX official valuation probe; fail closed on absent valuation fields."""
import csv, datetime as dt, json, os, pathlib, urllib.request, urllib.error, time
ROOT=pathlib.Path(__file__).resolve().parents[1]
CAND=ROOT/'stage56_input/provisional_ab_318_evidence_audit.csv'
OUT=ROOT/'stage56_output'
API='https://data-dbg.krx.co.kr/svc/apis/sto/'
ENDPOINTS={'KOSPI':'stk_bydd_trd','KOSDAQ':'ksq_bydd_trd'}
def rows(path):
 with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(path,data,cols):
 with path.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(data)
def main():
 OUT.mkdir(exist_ok=True)
 status={'stage':56,'mode':'OFFICIAL_KRX_API_AUTOPROBE','generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'verified':False,'final_grades':0,'buy_signals':0,'warnings':[],'markets':{}}
 try:
  if not CAND.exists():raise ValueError('318 candidate input missing')
  candidates=rows(CAND)
  dates={r.get('BAS_DD','') for r in candidates}
  if len(candidates)!=318 or len(dates)!=1 or not next(iter(dates)).isdigit():raise ValueError('candidate count/date mismatch; refuse to silently change cohort')
  date=next(iter(dates));status['candidate_count']=len(candidates);status['candidate_date']=date
  key=os.getenv('KRX_API_KEY','').strip()
  if not key:raise ValueError('KRX_API_KEY secret not configured')
  index={}
  for market,endpoint in ENDPOINTS.items():
   url=API+endpoint
   req=urllib.request.Request(url+'?basDd='+date,headers={'AUTH_KEY':key,'User-Agent':'KRX-v5-stage56/1.0','Accept':'application/json'})
   try:
    with urllib.request.urlopen(req,timeout=35) as resp: payload=json.load(resp)
    data=payload.get('OutBlock_1',[])
    if not isinstance(data,list):raise ValueError('OutBlock_1 missing or invalid')
    columns=sorted({k for r in data if isinstance(r,dict) for k in r})
    status['markets'][market]={'endpoint':url,'rows':len(data),'fields':columns,'api_status':'RECEIVED'}
    for r in data:
     code=str(r.get('ISU_SRT_CD') or r.get('ISU_CD') or '').removeprefix('A').zfill(6)
     if len(code)==6 and code.isdigit():index[(market,code)]=r
   except Exception as exc:
    status['markets'][market]={'endpoint':url,'api_status':'FAILED','error':str(exc)[:250]}
    status['warnings'].append(market+' API unavailable')
   time.sleep(0.4)
  results=[];counts={}
  for c in candidates:
   market=c.get('MARKET','').upper();code=c.get('ISU_CD','').removeprefix('A').zfill(6)
   r=index.get((market,code));m=status['markets'].get(market,{})
   per=(r or {}).get('PER');pbr=(r or {}).get('PBR')
   if m.get('api_status')!='RECEIVED':reason='API_UNAVAILABLE'
   elif r is None:reason='SECURITY_NOT_FOUND'
   elif per is None or pbr is None:reason='OFFICIAL_VALUATION_FIELDS_ABSENT'
   else:reason='OFFICIAL_FIELDS_PRESENT_REVIEW'
   counts[reason]=counts.get(reason,0)+1
   results.append({'ISU_CD':code,'ISU_NM':c.get('ISU_NM',''),'MARKET':market,'BAS_DD':date,'official_per':per if per is not None else '','official_pbr':pbr if pbr is not None else '','stage56_status':reason,'stage54_per_proxy':c.get('stage54_marketcap_to_earnings_proxy',''),'stage54_pbr_proxy':c.get('stage54_marketcap_to_book_proxy',''),'final_grade':'WITHHELD','buy_signal':'NONE'})
  write(OUT/'official_valuation_audit.csv',results,['ISU_CD','ISU_NM','MARKET','BAS_DD','official_per','official_pbr','stage56_status','stage54_per_proxy','stage54_pbr_proxy','final_grade','buy_signal'])
  status['counts']=counts;status['verified']=False
  status['warnings'].append('This is an API field-discovery probe, not completed official PER/PBR verification. Never use Stage54 proxies as official metrics.')
 except Exception as exc:status['error']=str(exc);status['warnings'].append('Execution incomplete; no investment grading permitted')
 (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(status,ensure_ascii=False,indent=2))
 if status.get('error'):raise SystemExit(1)
if __name__=='__main__':main()
