#!/usr/bin/env python3
"""R14 K: calculate auditable annual-basis PER/PBR from cached DART accounts.
Never label annual earnings as TTM or calculate ROE without opening equity.
"""
import csv,json,os,pathlib,datetime,math
from collections import Counter
R=pathlib.Path(os.getenv('GITHUB_WORKSPACE','.')).resolve()
SRC=R/'data/v5_investment_r14_research_j/full_market_research_j.csv'
OUT=R/'data/v5_investment_r14_research_k'
CANDIDATES=[R/'data/v5_financial_annual_bridge/annual_financial_cache.json',R/'data/v5_financial_annual/annual_financial_cache.json',R/'data/annual_financial_cache.json',R/'annual_financial_cache.json']
CANDIDATES+=sorted(R.glob('data/**/annual_financial_cache.json'))

def num(x):
 try:
  y=float(str(x).replace(',',''));return y if math.isfinite(y) else None
 except (TypeError,ValueError):return None

def read(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(p,rows,fields):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)

def cache():
 for p in dict.fromkeys(CANDIDATES):
  if not p.is_file():continue
  try:
   data=json.loads(p.read_text(encoding='utf-8-sig'))
   if isinstance(data,dict) and any(isinstance(v,dict) and ('profit' in v or 'equity' in v) for v in data.values()):return data,p
  except (ValueError,OSError):pass
 return {},None

def main():
 if not SRC.is_file():raise SystemExit('MISSING_J_INPUT '+str(SRC))
 rows=read(SRC)
 if not rows:raise SystemExit('EMPTY_J_INPUT')
 financial,path=cache();counts=Counter();output=[]
 for r in rows:
  x=dict(r);code=str(r.get('ISU_CD','')).zfill(6);f=financial.get(code,{})
  year=str(f.get('year',''));fs=str(f.get('fs_div',''));state=str(f.get('state',''))
  profit=num(f.get('profit'));equity=num(f.get('equity'));cap=num(r.get('MKTCAP'))
  # This bridge's annual cache stores KRW units; reject unknown or incomplete records.
  verified=(state=='FINANCIAL_FIELDS_FOUND' and year.isdigit() and len(year)==4 and fs in ('CFS','OFS') and cap is not None and cap>0)
  pe=round(cap/profit,4) if verified and profit is not None and profit>0 else ''
  pb=round(cap/equity,4) if verified and equity is not None and equity>0 else ''
  # Current cache has only year-end equity. No ROE without previous year equity.
  prior=num(f.get('prior_year_equity'))
  roe=round(profit/((equity+prior)/2)*100,4) if verified and profit is not None and equity is not None and prior is not None and equity>0 and prior>0 else ''
  reason='OK' if pe!='' and pb!='' else ('MISSING_CACHE' if not f else 'INCOMPLETE_OR_NONPOSITIVE_FINANCIALS')
  x.update(k_annual_per=pe,k_annual_pbr=pb,k_roe_pct=roe,k_financial_year=year if verified else '',k_fs_div=fs if verified else '',k_ratio_basis='ANNUAL_LAST_REPORTED_NOT_TTM' if verified else 'UNVERIFIED',k_cache_state=state,k_data_quality=reason,k_official_per_gap_pct=round((pe/num(r['j_official_per'])-1)*100,2) if pe!='' and num(r.get('j_official_per')) and num(r.get('j_official_per'))>0 else '',k_official_pbr_gap_pct=round((pb/num(r['j_official_pbr'])-1)*100,2) if pb!='' and num(r.get('j_official_pbr')) and num(r.get('j_official_pbr'))>0 else '',k_final_buy_signal='')
  output.append(x)
  counts['annual_per']+=pe!='';counts['annual_pbr']+=pb!='';counts['roe']+=roe!='';counts['cache_match']+=bool(f)
 fields=list(output[0]);write(OUT/'full_market_ratios_k.csv',output,fields)
 watch=[r for r in output if r.get('j_grade_provisional') in ('A','B+','B')];write(OUT/'provisional_ab_ratios_k.csv',watch,fields)
 status={'version':'R14_K_CACHED_ANNUAL_RATIOS','generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'market_date':rows[0].get('BAS_DD'),'rows':len(output),'provisional_ab':len(watch),'cache_path':str(path.relative_to(R)) if path else None,'cache_records':len(financial),'cache_matched':counts['cache_match'],'annual_per_calculated':counts['annual_per'],'annual_pbr_calculated':counts['annual_pbr'],'roe_calculated':counts['roe'],'official_ratios_not_fabricated':True,'golden_cross_used':False,'final_buy_signals':0,'limitations':['PER uses most recent cached ANNUAL profit, not TTM; annual earnings can be stale','ROE requires previous-year equity; absent values remain blank','Financial numerator and market capitalization must be in KRW; inspect cache provenance before investment use','No buy signal or intrinsic value is inferred from these ratios']}
 OUT.mkdir(parents=True,exist_ok=True);(OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(status,ensure_ascii=False))
if __name__=='__main__':main()
