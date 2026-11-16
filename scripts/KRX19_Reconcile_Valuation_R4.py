#!/usr/bin/env python3
"""Read-only reconciliation of Stage18 proxies and Stage19 KRX daily market evidence.
Official PER/PBR is NEVER inferred from proxies or market data.
"""
import argparse,csv,json,pathlib,collections,datetime

def read_csv(path):
 with open(path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def main():
 p=argparse.ArgumentParser()
 p.add_argument('--stage18',required=True);p.add_argument('--market',required=True)
 p.add_argument('--universe',default='data/v5_full_market_universe.json')
 p.add_argument('--output-dir',default='stage19_r4_output')
 a=p.parse_args(); out=pathlib.Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
 older=read_csv(a.stage18);newer=read_csv(a.market)
 universe=json.loads(pathlib.Path(a.universe).read_text(encoding='utf-8'))
 old={r['code'].strip().upper():r for r in older}; new={r['code'].strip().upper():r for r in newer}
 if len(old)!=len(older) or len(new)!=len(newer):raise ValueError('Duplicate stock codes in input')
 univ={str(s['code']).strip().upper():s for s in universe['stocks']}
 date=str(universe['trading_date'])
 invalid=[r['code'] for r in newer if r.get('basis_date')!=date or r.get('source')!='KRX_OPEN_API_DAILY_TRADING']
 rows=[];counts=collections.Counter()
 for code in sorted(set(old)|set(new)|set(univ)):
  a18=old.get(code,{});a19=new.get(code,{});u=univ.get(code,{})
  if code in old and code in new:category='BOTH'
  elif code in old:category='STAGE18_ONLY'
  elif code in new:category='STAGE19_ONLY'
  else:category='UNIVERSE_ONLY'
  counts[category]+=1
  rows.append({'code':code,'name':a19.get('name') or a18.get('name') or u.get('name',''), 'coverage':category,'universe_present':str(code in univ),'stage18_grade':a18.get('provisional_grade',''),'stage18_annual_comparable':a18.get('annual_comparable',''),'stage18_per_proxy':a18.get('per_proxy',''),'stage18_pbr_proxy':a18.get('pbr_proxy',''),'market_basis_date':a19.get('basis_date',''),'market_close_krw':a19.get('close_krw',''),'market_cap_krw':a19.get('market_cap_krw',''),'market_listed_shares':a19.get('listed_shares',''),'official_per':'','official_pbr':'','official_valuation_status':'UNVERIFIED_NO_OFFICIAL_PER_PBR_SOURCE'})
 fields=list(rows[0]) if rows else []
 with (out/'v5_stage19_r4_reconciliation.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 only19=[r for r in rows if r['coverage']=='STAGE19_ONLY']
 with (out/'v5_stage19_r4_new_coverage.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(only19)
 status='PASS_RECONCILIATION' if not invalid and len(new)==len(univ) and not (set(old)-set(new)) and date else 'REVIEW_REQUIRED'
 summary={'stage':'19_R4','universe_trading_date':date,'stage18_rows':len(old),'stage19_market_rows':len(new),'universe_rows':len(univ),'coverage':dict(counts),'stage19_only_codes':sorted(set(new)-set(old)),'stage18_only_codes':sorted(set(old)-set(new)),'market_date_or_source_mismatch_count':len(invalid),'market_date_or_source_mismatch_codes':invalid[:50],'official_per_pbr_verified_count':0,'valuation_classification':'PROXIES_NOT_OFFICIAL','status':status}
 (out/'v5_stage19_r4_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(summary,ensure_ascii=False,indent=2))
 if status!='PASS_RECONCILIATION':raise SystemExit(2)
if __name__=='__main__':main()
