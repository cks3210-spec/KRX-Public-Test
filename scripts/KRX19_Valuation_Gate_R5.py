#!/usr/bin/env python3
"""Stage19 R5: read-only preferred-share exclusion and official valuation evidence gate.
Never promotes estimates or user-supplied figures to independently verified official data.
"""
import argparse,csv,json,pathlib,collections,datetime,re

def load(path):
 with open(path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(path,rows,fields):
 with open(path,'w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def main():
 p=argparse.ArgumentParser();p.add_argument('--reconciliation',required=True);p.add_argument('--market',required=True);p.add_argument('--output-dir',default='stage19_r5_output');p.add_argument('--official-evidence',default='');a=p.parse_args()
 rec=load(a.reconciliation);market=load(a.market);out=pathlib.Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
 if not rec or not market:raise SystemExit('Empty input')
 codes=[r['code'].strip().upper() for r in rec];mcodes=[r['code'].strip().upper() for r in market]
 if len(set(codes))!=len(codes) or len(set(mcodes))!=len(mcodes):raise SystemExit('Duplicate code')
 dates={r['basis_date'] for r in market};sources={r['source'] for r in market}
 if len(dates)!=1 or not re.fullmatch(r'20\d{6}',next(iter(dates))) or sources!={'KRX_OPEN_API_DAILY_TRADING'}:raise SystemExit('Invalid market date/source')
 date=next(iter(dates));m={r['code'].strip().upper():r for r in market}
 extra=[r for r in rec if r['coverage']=='STAGE19_ONLY'];only18=[r for r in rec if r['coverage']=='STAGE18_ONLY']
 # R4-established rule: exclude ONLY the 28 extra preferred shares, not guessed by name suffix.
 # Any change in the 28-code set fails closed and requires explicit review.
 expected=set('000155 000157 000815 00088K 001045 00279K 003545 003547 003555 005385 005387 005389 005935 005945 006405 006805 00680K 009155 010955 011785 02826K 03473K 051905 051915 066575 071055 090435 097955'.split())
 observed={r['code'].strip().upper() for r in extra}
 if observed!=expected or only18 or set(m)!=set(codes):raise SystemExit('R4 universe differs; fail closed, do not silently exclude')
 ev={};ev_issues=[]
 if a.official_evidence:
  ep=pathlib.Path(a.official_evidence)
  if ep.exists():
   for r in load(ep):
    c=(r.get('code') or '').strip().upper()
    if not c or c in ev:ev_issues.append('missing_or_duplicate_code');continue
    ev[c]=r
 rows=[];cnt=collections.Counter()
 for r in rec:
  c=r['code'].strip().upper();excluded=c in expected; evidence=ev.get(c,{})
  provided=bool(evidence)
  source_ok=provided and evidence.get('source')=='KRX_INFORMATION_DATA_SYSTEM' and evidence.get('basis_date')==date and bool((evidence.get('source_url') or '').strip())
  numeric_ok=False
  if source_ok:
   try:
    v1=float(evidence.get('official_per',''));v2=float(evidence.get('official_pbr',''))
    numeric_ok=0<=v1<100000 and 0<=v2<100000
   except (ValueError,TypeError):pass
  # A CSV by itself is not independently authenticated official data.
  status='EXCLUDED_PREFERRED_SHARE_R4_CONFIRMED' if excluded else ('SOURCE_DOCUMENT_REVIEW_REQUIRED' if source_ok and numeric_ok else ('EVIDENCE_REJECTED' if provided else 'UNVERIFIED_NO_OFFICIAL_SOURCE'))
  cnt[status]+=1
  rows.append({'code':c,'name':r['name'],'basis_date':date,'preferred_excluded':str(excluded),'stage18_grade_provisional':r['stage18_grade'],'per_proxy_not_official':r['stage18_per_proxy'],'pbr_proxy_not_official':r['stage18_pbr_proxy'],'official_per_unverified_input':evidence.get('official_per','') if source_ok and numeric_ok and not excluded else '', 'official_pbr_unverified_input':evidence.get('official_pbr','') if source_ok and numeric_ok and not excluded else '', 'evidence_source_url':evidence.get('source_url','') if source_ok else '', 'official_verified_per_pbr':'False','valuation_status':status})
 write(out/'v5_stage19_r5_valuation_gate.csv',rows,list(rows[0]))
 write(out/'v5_stage19_r5_excluded_preferred.csv',[r for r in rows if r['preferred_excluded']=='True'],list(rows[0]))
 summary={'stage':'19_R5','market_basis_date':date,'total_market_rows':len(m),'stage18_common_stock_rows':len(rows)-len(expected),'preferred_excluded_count':len(expected),'excluded_codes':sorted(expected),'valuation_status_counts':dict(cnt),'official_per_pbr_independently_verified_count':0,'evidence_rows_supplied':len(ev),'evidence_input_issues':ev_issues,'status':'PASS_PREFERRED_EXCLUSION_AND_EVIDENCE_GATE','note':'Source CSV is not independently authenticated. Official PER/PBR never promoted without manual primary-document verification.'}
 (out/'v5_stage19_r5_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
