#!/usr/bin/env python3
"""Stage56: strict KRX official valuation CSV evidence audit. No estimates become official."""
import argparse,csv,json,datetime,pathlib,re

def read(path):
 with open(path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(path,rows,fields):
 with open(path,'w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
def num(s):
 try:return float(str(s).replace(',','').strip())
 except (ValueError,TypeError):return None
def normcode(s):
 s=str(s).strip().lstrip('A');return s.zfill(6) if re.fullmatch(r'\d{1,6}',s) else ''
def main():
 p=argparse.ArgumentParser();p.add_argument('--candidates',required=True);p.add_argument('--official',required=True);p.add_argument('--out',default='stage56_output');p.add_argument('--source-url',required=True);p.add_argument('--source-date',required=True,help='YYYYMMDD official data date');a=p.parse_args()
 # Official CSV must be independently exported from KRX; do not trust unverified proxy.
 if not a.source_url.startswith('https://') or 'krx.co.kr' not in a.source_url.split('/')[2].lower():raise SystemExit('Official source must be a KRX HTTPS URL')
 if not re.fullmatch(r'\d{8}',a.source_date):raise SystemExit('Invalid source date')
 candidates=read(a.candidates);official=read(a.official)
 needed={'ISU_CD','BAS_DD','PER','PBR'}
 if not official or not needed.issubset(official[0]):raise SystemExit('Official CSV needs ISU_CD,BAS_DD,PER,PBR columns; map original KRX headers first')
 idx={};dupes=set()
 for r in official:
  code=normcode(r.get('ISU_CD'));date=re.sub(r'\D','',r.get('BAS_DD',''))
  if not code or date!=a.source_date:continue
  if code in idx:dupes.add(code)
  idx[code]=r
 out=[];counts={}
 for r in candidates:
  code=normcode(r.get('ISU_CD'));date=re.sub(r'\D','',r.get('BAS_DD',''))
  o=idx.get(code);per=num(o.get('PER')) if o else None;pbr=num(o.get('PBR')) if o else None
  if code in dupes:status='DUPLICATE_OFFICIAL_CODE'
  elif date!=a.source_date:status='DATE_MISMATCH'
  elif o is None:status='NOT_FOUND_IN_OFFICIAL_EXPORT'
  elif per is None and pbr is None:status='BOTH_METRICS_MISSING'
  elif per is not None and per<=0:status='PER_NONPOSITIVE_REVIEW'
  elif pbr is not None and pbr<=0:status='PBR_NONPOSITIVE_REVIEW'
  elif per is None or pbr is None:status='PARTIAL_OFFICIAL_METRICS'
  else:status='MATCHED_OFFICIAL_METRICS'
  counts[status]=counts.get(status,0)+1
  out.append({'ISU_CD':code,'ISU_NM':r.get('ISU_NM',''),'MARKET':r.get('MARKET',''),'candidate_date':date,'official_date':a.source_date,'official_per':o.get('PER','') if o else '', 'official_pbr':o.get('PBR','') if o else '', 'stage54_per_proxy':r.get('stage54_marketcap_to_earnings_proxy',''),'stage54_pbr_proxy':r.get('stage54_marketcap_to_book_proxy',''),'stage56_status':status,'stage56_source_url':a.source_url,'provisional_grade':r.get('stage53_financial_grade',r.get('provisional_grade','')),'final_grade':'WITHHELD','buy_signal':'NONE'})
 dest=pathlib.Path(a.out);dest.mkdir(parents=True,exist_ok=True)
 write(dest/'official_valuation_audit.csv',out,list(out[0]) if out else [])
 status={'stage':56,'mode':'OFFICIAL_CSV_EVIDENCE_AUDIT','generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'candidate_count':len(candidates),'official_rows':len(official),'source_url':a.source_url,'source_date':a.source_date,'counts':counts,'final_grades':0,'buy_signals':0,'official_export_provenance':'USER_SUPPLIED_NOT_INDEPENDENTLY_AUTHENTICATED','notes':['CSV provenance must be checked against KRX download record before calling values independently verified.','Stage54 proxies never substituted for official PER/PBR.','Share-class verification remains deferred.']}
 (dest/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(status,ensure_ascii=False))
if __name__=='__main__':main()
