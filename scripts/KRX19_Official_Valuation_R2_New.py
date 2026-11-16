#!/usr/bin/env python3
"""Stage19 evidence-gated valuation audit. Never treats derived proxies as official values."""
import argparse,csv,json,hashlib,pathlib,datetime,re
from decimal import Decimal,InvalidOperation

FIELDS=['code','name','provisional_grade','annual_comparable','per_proxy','pbr_proxy','official_per','official_pbr','official_source','official_date','official_per_verified','official_pbr_verified','verification_status','notes']

def decimal(x):
 try:
  d=Decimal(str(x).strip().replace(',',''))
  return d if d.is_finite() and d>0 else None
 except (InvalidOperation,ValueError):return None

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input-dir',default='data');ap.add_argument('--output-dir',default='stage19_output');ap.add_argument('--official-csv',default='');args=ap.parse_args()
 root=pathlib.Path(args.input_dir);out=pathlib.Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
 r3=root/'v5_stage18_financial_audit.csv';r4=root/'v5_stage18_r4_diagnostic.csv';s4=root/'v5_stage18_r4_summary.json'
 with r3.open(encoding='utf-8-sig',newline='') as f: base=list(csv.DictReader(f))
 if r4.exists():
  with r4.open(encoding='utf-8-sig',newline='') as f: diag=list(csv.DictReader(f))
  if len(diag)!=len(base):raise SystemExit('Stage18 R3/R4 row mismatch')
  if {x['code'] for x in diag}!={x['code'] for x in base}:raise SystemExit('Stage18 R3/R4 security code mismatch')
 if s4.exists():
  s=json.loads(s4.read_text(encoding='utf-8-sig'))
  if not s.get('passed') or s.get('analyzed_count')!=len(base):raise SystemExit('Stage18 R4 verification invalid')
 evidence={}; evidence_path=pathlib.Path(args.official_csv) if args.official_csv else None
 if evidence_path:
  if not evidence_path.is_file():raise SystemExit('Official evidence CSV not found')
  with evidence_path.open(encoding='utf-8-sig',newline='') as f:
   for e in csv.DictReader(f):
    code=(e.get('code') or '').strip().upper()
    if code in evidence:raise SystemExit('Duplicate official evidence code: '+code)
    evidence[code]=e
 rows=[]; counts={'FULL':0,'PARTIAL':0,'UNVERIFIED':0}; verified_ab=0
 for b in base:
  code=b['code'].strip().upper(); e=evidence.get(code,{})
  source=(e.get('source') or '').strip(); date=(e.get('date') or '').strip(); name=(e.get('name') or '').strip()
  # Explicitly require source identity, exact date and security match. No evidence => never verified.
  valid_meta=bool(source and re.fullmatch(r'20\d{2}-\d{2}-\d{2}',date) and (not name or name==b['name']))
  if valid_meta:
   try:datetime.date.fromisoformat(date)
   except ValueError:valid_meta=False
  per=decimal(e.get('per'));pbr=decimal(e.get('pbr'))
  per_ok=bool(valid_meta and per is not None);pbr_ok=bool(valid_meta and pbr is not None)
  status='FULL' if per_ok and pbr_ok else 'PARTIAL' if per_ok or pbr_ok else 'UNVERIFIED'
  counts[status]+=1
  if status=='FULL' and b.get('provisional_grade') in ('A','B+','B'):verified_ab+=1
  rows.append(dict(code=code,name=b['name'],provisional_grade=b.get('provisional_grade',''),annual_comparable=b.get('annual_comparable',''),per_proxy=b.get('per_proxy',''),pbr_proxy=b.get('pbr_proxy',''),official_per=str(per) if per_ok else '',official_pbr=str(pbr) if pbr_ok else '',official_source=source if valid_meta else '',official_date=date if valid_meta else '',official_per_verified=per_ok,official_pbr_verified=pbr_ok,verification_status=status,notes='EXTERNAL_EVIDENCE_REQUIRES_SOURCE_AUTHENTICATION' if status!='UNVERIFIED' else 'NO_VALID_OFFICIAL_EVIDENCE'))
 with (out/'v5_stage19_valuation_audit.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
 summary={'schema':1,'generated_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'classification':'EVIDENCE_GATED_DIAGNOSTIC_NOT_INVESTMENT_SIGNAL','analyzed_count':len(rows),'annual_comparable_count':sum(str(r['annual_comparable']).lower()=='true' for r in rows),'provisional_ab_count':sum(r['provisional_grade'] in ('A','B+','B') for r in rows),'official_evidence_supplied':bool(evidence_path),'official_evidence_rows':len(evidence),'verification_counts':counts,'fully_evidenced_provisional_ab_count':verified_ab,'source_stage18_csv_sha256':hashlib.sha256(r3.read_bytes()).hexdigest(),'warning':'Evidence source authenticity is not independently verified. FULL means provided fields passed format/identity checks only. No official KRX verification is claimed.'}
 (out/'v5_stage19_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
