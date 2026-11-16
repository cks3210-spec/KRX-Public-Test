#!/usr/bin/env python3
"""Stage18 R4: read-only secondary audit of Stage18 R3 CSV and summary."""
import argparse,csv,hashlib,json,pathlib,re,collections,datetime

VALID_CODE=re.compile(r'^[0-9A-Z]{6}$')
FLAGS=('CURRENT_ANNUAL_MISSING','PRIOR_ANNUAL_MISSING','ACCOUNT_EXTRACTION_ISSUES','FS_BASIS_MISMATCH','CURRENT_METRICS_MISSING','PRIOR_REVENUE_MISSING','NONPOSITIVE_EQUITY','BALANCE_SHEET_MISMATCH','MARKET_CAP_UNAVAILABLE','SECURITY_CODE_UNVERIFIED')
def main():
 p=argparse.ArgumentParser();p.add_argument('--input-dir',default='data');p.add_argument('--output-dir',default='stage18_r4_output');a=p.parse_args()
 root=pathlib.Path(a.input_dir);out=pathlib.Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
 csvpath=root/'v5_stage18_financial_audit.csv'; summarypath=root/'v5_stage18_financial_audit_summary.json'
 src=json.loads(summarypath.read_text(encoding='utf-8-sig'))
 with csvpath.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
 if not rows or len(rows)!=src['analyzed_count']:raise SystemExit('FAIL: R3 row count differs from summary')
 seen=set();details=[];flag_counts=collections.Counter();status_counts=collections.Counter();grade_counts=collections.Counter();codes_fixed=[]
 for r in rows:
  code=r['code'].strip().upper(); flags=set(filter(None,r['issues'].split(';')))
  if code in seen:flags.add('DUPLICATE_SECURITY_CODE')
  seen.add(code)
  if 'SECURITY_CODE_UNVERIFIED' in flags and VALID_CODE.fullmatch(code):
   flags.remove('SECURITY_CODE_UNVERIFIED');codes_fixed.append(code)
  if not VALID_CODE.fullmatch(code):flags.add('SECURITY_CODE_FORMAT_REVIEW')
  comparable=r['annual_comparable'].strip().lower()=='true'
  if comparable and any(x in flags for x in ('CURRENT_ANNUAL_MISSING','PRIOR_ANNUAL_MISSING','FS_BASIS_MISMATCH','ACCOUNT_EXTRACTION_ISSUES')):flags.add('COMPARABILITY_INCONSISTENCY')
  if comparable and not r['fs_div']:flags.add('FS_BASIS_EMPTY')
  if r['official_per_verified'].lower()=='true' or r['official_pbr_verified'].lower()=='true':flags.add('UNEXPECTED_OFFICIAL_VERIFICATION')
  if r['provisional_grade'] in ('A','B+','B'):grade_counts[r['provisional_grade']]+=1
  for x in flags:flag_counts[x]+=1
  if 'COMPARABILITY_INCONSISTENCY' in flags or 'DUPLICATE_SECURITY_CODE' in flags:category='DATA_INTEGRITY_REVIEW'
  elif 'CURRENT_ANNUAL_MISSING' in flags or 'PRIOR_ANNUAL_MISSING' in flags:category='ANNUAL_SOURCE_MISSING'
  elif 'ACCOUNT_EXTRACTION_ISSUES' in flags or 'CURRENT_METRICS_MISSING' in flags or 'PRIOR_REVENUE_MISSING' in flags:category='ACCOUNT_EXTRACTION_REVIEW'
  elif 'FS_BASIS_MISMATCH' in flags:category='FS_BASIS_REVIEW'
  elif 'NONPOSITIVE_EQUITY' in flags or 'BALANCE_SHEET_MISMATCH' in flags:category='FINANCIAL_RISK_REVIEW'
  elif flags:category='OTHER_REVIEW'
  else:category='NO_RECORDED_ISSUE'
  status_counts[category]+=1
  details.append({'code':code,'name':r['name'],'annual_comparable':comparable,'provisional_grade':r['provisional_grade'],'review_category':category,'review_flags':';'.join(sorted(flags)),'per_proxy':r['per_proxy'],'pbr_proxy':r['pbr_proxy'],'roe_proxy_pct':r['roe_proxy_pct'],'official_valuation_verified':False})
 def write_csv(path,items):
  with path.open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,fieldnames=list(items[0]));w.writeheader();w.writerows(items)
 write_csv(out/'v5_stage18_r4_diagnostic.csv',details)
 write_csv(out/'v5_stage18_r4_review_only.csv',[x for x in details if x['review_category']!='NO_RECORDED_ISSUE'] or details[:0])
 comparable_count=sum(x['annual_comparable'] for x in details)
 report={'schema':1,'generated_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'classification':'OFFLINE_DIAGNOSTIC_UNVERIFIED_NO_INVESTMENT_SIGNAL','source_r3_csv_sha256':hashlib.sha256(csvpath.read_bytes()).hexdigest(),'source_annual_cache_sha256':src.get('source_annual_cache_sha256'),'analyzed_count':len(details),'annual_comparable_count':comparable_count,'provisional_grade_counts':dict(grade_counts),'corrected_alphanumeric_code_warnings':len(codes_fixed),'corrected_codes':codes_fixed,'review_category_counts':dict(status_counts),'remaining_flag_counts':dict(flag_counts),'official_per_pbr_verified_count':0,'passed':comparable_count==src['annual_comparable_count'] and len(details)==src['analyzed_count'] and not flag_counts['COMPARABILITY_INCONSISTENCY'] and not flag_counts['DUPLICATE_SECURITY_CODE']}
 (out/'v5_stage18_r4_summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2))
 if not report['passed']:raise SystemExit('FAIL: Stage18 R4 integrity check')
if __name__=='__main__':main()
