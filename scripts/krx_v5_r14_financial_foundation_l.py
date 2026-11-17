#!/usr/bin/env python3
"""R14 L: non-destructive financial cache inventory, reconciliation, and incremental valuation.
No network calls, no synthetic ROE/TTM, no writes to upstream caches.
"""
import csv, json, os, pathlib, datetime, math, hashlib, collections
ROOT=pathlib.Path(os.getenv('GITHUB_WORKSPACE','.')).resolve()
OUT=ROOT/'data/v5_financial_foundation_l'
MARKET=ROOT/'data/v5_investment_r14_research_k/full_market_ratios_k.csv'
FIELDS=('profit','equity','revenue','assets','liabilities','prior_year_equity')
def numeric(v):
 try:
  x=float(str(v).replace(',',''))
  return x if math.isfinite(x) else None
 except (ValueError,TypeError): return None
def csvread(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def csvwrite(p,rows,columns):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');w.writeheader();w.writerows(rows)
def score(x):
 return (str(x.get('state'))=='FINANCIAL_FIELDS_FOUND',sum(numeric(x.get(k)) is not None for k in FIELDS),str(x.get('year','')),str(x.get('fs_div',''))=='CFS')
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 candidates=sorted(set(ROOT.glob('data/**/annual_financial_cache.json')) | set(ROOT.glob('data/**/financial_cache.json')))
 # Do not import results from this output directory or guess the schema of arbitrary JSON files.
 candidates=[p for p in candidates if OUT not in p.parents]
 merged={}; inventory=[]; conflicts=[]; input_hashes={}
 for p in candidates:
  try:
   raw=p.read_bytes(); data=json.loads(raw.decode('utf-8-sig'))
  except (OSError,UnicodeError,ValueError) as e:
   inventory.append({'path':str(p.relative_to(ROOT)),'records':0,'usable':0,'error':type(e).__name__});continue
  input_hashes[str(p.relative_to(ROOT))]=hashlib.sha256(raw).hexdigest()
  if not isinstance(data,dict):continue
  usable=0
  for code,entry in data.items():
   if not isinstance(entry,dict) or not str(code).isdigit() or len(str(code))>6:continue
   if not any(k in entry for k in ('profit','equity','revenue')):continue
   usable+=1; code=str(code).zfill(6); record=dict(entry);record['_source']=str(p.relative_to(ROOT))
   if code in merged:
    old=merged[code]
    if any(str(old.get(k,''))!=str(record.get(k,'')) for k in ('year','profit','equity','fs_div')):
     conflicts.append({'code':code,'kept_source':old['_source'],'other_source':record['_source']})
    if score(record)>score(old):merged[code]=record
   else:merged[code]=record
  inventory.append({'path':str(p.relative_to(ROOT)),'records':len(data),'usable':usable,'error':''})
 csvwrite(OUT/'source_inventory.csv',inventory,['path','records','usable','error'])
 csvwrite(OUT/'source_conflicts.csv',conflicts,['code','kept_source','other_source'])
 financial=[]
 for code,rec in sorted(merged.items()):
  row={'code':code,'source':rec['_source'],'year':rec.get('year',''),'fs_div':rec.get('fs_div',''),'state':rec.get('state',''),'corp_code':rec.get('corp_code','')}
  for field in FIELDS:row[field]=rec.get(field,'')
  financial.append(row)
 csvwrite(OUT/'unified_financial_index.csv',financial,['code','source','year','fs_div','state','corp_code',*FIELDS])
 market=csvread(MARKET) if MARKET.is_file() else []
 ratios=[];counts=collections.Counter()
 for r in market:
  code=str(r.get('ISU_CD','')).zfill(6);f=merged.get(code)
  cap=numeric(r.get('MKTCAP'))
  valid=bool(f and f.get('state')=='FINANCIAL_FIELDS_FOUND' and str(f.get('year','')).isdigit() and f.get('fs_div') in ('CFS','OFS') and cap is not None and cap>0)
  profit=numeric(f.get('profit')) if f else None;equity=numeric(f.get('equity')) if f else None;prev=numeric(f.get('prior_year_equity')) if f else None
  per=round(cap/profit,4) if valid and profit is not None and profit>0 else ''
  pbr=round(cap/equity,4) if valid and equity is not None and equity>0 else ''
  roe=round(100*profit/((equity+prev)/2),4) if valid and profit is not None and equity is not None and prev is not None and equity>0 and prev>0 else ''
  counts['matched']+=bool(f);counts['per']+=per!='';counts['pbr']+=pbr!='';counts['roe']+=roe!=''
  ratios.append({'code':code,'market_date':r.get('BAS_DD',''),'financial_year':f.get('year','') if f else '', 'financial_source':f['_source'] if f else '', 'annual_per':per,'annual_pbr':pbr,'annual_roe_pct':roe,'basis':'ANNUAL_NOT_TTM' if valid else 'UNVERIFIED','provisional_grade':r.get('j_grade_provisional','')})
 cols=['code','market_date','financial_year','financial_source','annual_per','annual_pbr','annual_roe_pct','basis','provisional_grade']
 csvwrite(OUT/'market_ratios_l.csv',ratios,cols)
 csvwrite(OUT/'ab_ratios_l.csv',[r for r in ratios if r['provisional_grade'] in ('A','B+','B')],cols)
 status={'version':'R14_L_FINANCIAL_FOUNDATION','generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'market_input_present':MARKET.is_file(),'market_rows':len(market),'cache_sources':len(inventory),'unique_financial_codes':len(merged),'conflicts':len(conflicts),'matched':counts['matched'],'annual_per_calculated':counts['per'],'annual_pbr_calculated':counts['pbr'],'annual_roe_calculated':counts['roe'],'ttm_calculated':0,'official_verified':0,'final_buy_signals':0,'upstream_caches_modified':False,'notes':['Read-only inventory of existing annual caches; no DART API collection in L','Annual PER is not TTM; no investment signal generated','A/B are provisional grades from K, not new valuation grades'],'input_sha256':input_hashes}
 (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in status.items() if k not in ('input_sha256','notes')},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
