#!/usr/bin/env python3
"""R14 bridge: reuse existing technical indicators and incrementally fetch comparable DART figures.
Never modifies R9/R14 inputs. Research only; no final buy signals.
"""
import csv,datetime as dt,json,os,pathlib,re,subprocess,sys,urllib.parse,urllib.request
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'data/v5_investment_r14_bridge';OUT.mkdir(parents=True,exist_ok=True)
R14=ROOT/'data/v5_investment_r14';NOW=dt.datetime.now(ZoneInfo('Asia/Seoul'))
FIELDS={'revenue':['ifrs-full_Revenue','ifrs_Revenue','ifrs-full_RevenueFromContractsWithCustomers'], 'operating_profit':['dart_OperatingIncomeLoss','ifrs-full_ProfitLossFromOperatingActivities','ifrs_ProfitLossFromOperatingActivities'], 'owner_profit':['ifrs-full_ProfitLossAttributableToOwnersOfParent','ifrs_ProfitLossAttributableToOwnersOfParent']}
def readcsv(p):
 if not p.exists():return []
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def readjson(p):
 try:return json.loads(p.read_text(encoding='utf-8'))
 except (OSError,ValueError):return {}
def writecsv(p,rows,fields):
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
def num(v):
 try:return float(str(v).replace(',','').strip())
 except (TypeError,ValueError):return None
def growth(now,prior):
 a,b=num(now),num(prior)
 return round((a/b-1)*100,3) if a is not None and b is not None and b>0 else ''
def fetch_dart(key,corp,year):
 url='https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?'+urllib.parse.urlencode(dict(crtfc_key=key,corp_code=corp,bsns_year=year,reprt_code='11011',fs_div='CFS'))
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'KRX-v5-research/1.0'}),timeout=35) as f:data=json.load(f)
 if data.get('status')!='000':return {'state':'DART_'+str(data.get('status')),'year':year}
 records=data.get('list') or [];result={'state':'OK','year':year,'fs_div':'CFS','report':'11011'}
 for metric,ids in FIELDS.items():
  for r in records:
   if r.get('account_id') in ids and r.get('sj_div') in ('IS','CIS'):
    current=num(r.get('thstrm_amount'));prior=num(r.get('frmtrm_amount'))
    if current is not None:result[metric+'_current']=current
    if prior is not None:result[metric+'_prior']=prior
    break
 return result

def main():
 # Reuse the existing R14 engine, not an alternative reimplementation.
 subprocess.run([sys.executable,str(ROOT/'scripts/krx_v5_r14_full_investment_pipeline_mobile_1117_672.py')],check=True)
 rows=readcsv(R14/'full_market_research.csv');indicators=readcsv(ROOT/'data/daily_indicators.csv')
 index={(r.get('BAS_DD','').strip(),r.get('ISU_CD','').strip()):r for r in indicators}
 annual=readjson(ROOT/'data/v5_financial_r9/annual_financial_cache.json')
 cachepath=OUT/'dart_annual_comparatives.json';cache=readjson(cachepath)
 key=os.environ.get('DART_API_KEY','').strip();budget=max(0,min(int(os.environ.get('DART_GROWTH_MAX_CALLS','60')),150))
 candidates=[]
 for r in rows:
  if r.get('eligible')!='1':continue
  f=annual.get(r['ISU_CD'],{})
  if f.get('state')!='FINANCIAL_FIELDS_FOUND' or not str(f.get('year','')).isdigit() or not f.get('corp_code'):continue
  ck=r['ISU_CD']+':'+str(f['year'])
  if ck not in cache:candidates.append((r['ISU_CD'],str(f['year']),f['corp_code'],ck))
 calls=0;errors=[]
 for code,year,corp,ck in candidates:
  if not key or calls>=budget:break
  calls+=1
  try:
   result=fetch_dart(key,corp,year)
   if result.get('state')=='OK':cache[ck]=result
   else:errors.append(code+':'+result.get('state','UNKNOWN'))
  except Exception as e:errors.append(code+':'+type(e).__name__)
 cachepath.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding='utf-8')
 technical=0;growth_count=0;op_count=0;date_mismatch=0
 indicator_codes={x.get('ISU_CD') for x in indicators}
 for r in rows:
  flags=[x for x in r.get('flags','').split(';') if x]
  t=index.get((r['BAS_DD'],r['ISU_CD']))
  r['technical_source']=''
  if t:
   for col,source in [('ma5','MA5'),('ma10','MA10'),('ma20','MA20'),('MA60','MA60'),('volume_ratio_20d','VOLUME_RATIO'),('return_20d_pct','RETURN_20D_PCT')]:
    if num(t.get(source)) is not None:r[col]=t[source]
   if num(t.get('MA5')) is not None and num(t.get('MA10')) is not None and num(t.get('MA20')) is not None:
    technical+=1;r['technical_source']='daily_indicators_same_date'
    flags=[x for x in flags if x!='HISTORY_LT_21']
   # A single snapshot cannot prove a crossing event; keep golden_cross unverified.
   r['golden_cross']='';r['golden_cross_state']='NEEDS_PREVIOUS_SESSION_MA'
  else:
   r['golden_cross_state']='INDICATOR_DATE_OR_CODE_MISSING'
   if r['ISU_CD'] in indicator_codes:date_mismatch+=1
  f=annual.get(r['ISU_CD'],{});ck=r['ISU_CD']+':'+str(f.get('year',''))
  comp=cache.get(ck,{})
  r['revenue_yoy_pct']=growth(comp.get('revenue_current'),comp.get('revenue_prior'))
  r['owner_profit_yoy_pct']=growth(comp.get('owner_profit_current'),comp.get('owner_profit_prior'))
  r['operating_profit_yoy_pct']=growth(comp.get('operating_profit_current'),comp.get('operating_profit_prior'))
  r['growth_source']='DART_SAME_REPORT_PRIOR_YEAR_CFS' if comp.get('state')=='OK' else ''
  if r['revenue_yoy_pct']!='':growth_count+=1;flags=[x for x in flags if x!='YOY_NOT_VERIFIED']
  if r['operating_profit_yoy_pct']!='':op_count+=1
  r['flags']=';'.join(flags)
  # Existing R14 grade remains provisional; never upgrade to final based on new fields.
  r['final_grade']='WITHHELD';r['buy_signal']='NONE'
 fields=list(rows[0]) if rows else []
 writecsv(OUT/'full_market_research_enriched.csv',rows,fields)
 writecsv(OUT/'provisional_ab_enriched.csv',[r for r in rows if r.get('provisional_grade')],fields)
 status=dict(version='R14_HISTORY_GROWTH_BRIDGE',generated_kst=NOW.isoformat(),market_date=rows[0]['BAS_DD'] if rows else '',market_rows=len(rows),technical_indicators_joined=technical,indicator_date_mismatch=date_mismatch,revenue_yoy_computed=growth_count,operating_profit_yoy_computed=op_count,dart_calls=calls,dart_key_present=bool(key),dart_cache_entries=len(cache),dart_errors=errors[:30],official_per_pbr_verified=0,final_buy_signals=0,notes=['Same-date MA values reused; no fabricated golden-cross events','Prior-year figures taken from same DART annual report CFS','R9 and R14 upstream caches untouched','Daily snapshots needed for forward performance tracking'])
 (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(status,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
