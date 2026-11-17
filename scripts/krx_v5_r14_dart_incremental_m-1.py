#!/usr/bin/env python3
"""R14 M: bounded OpenDART incremental financial collector. Only writes data/v5_financial_m.
Annual/quarterly values in KRW; no guessed TTM or ROE; incomplete disclosures remain unverified.
"""
import csv,datetime as dt,io,json,os,pathlib,time,urllib.parse,urllib.request,zipfile,xml.etree.ElementTree as ET
ROOT=pathlib.Path(os.getenv('GITHUB_WORKSPACE','.')).resolve()
OUT=ROOT/'data/v5_financial_m'; OUT.mkdir(parents=True,exist_ok=True)
L=ROOT/'data/v5_financial_foundation_l/unified_financial_index.csv'
KEY=os.getenv('DART_API_KEY') or os.getenv('OPENDART_API_KEY') or ''
LIMIT=max(1,min(250,int(os.getenv('M_BATCH_LIMIT','80'))))
TODAY=dt.date.today(); YEAR=TODAY.year
API='https://opendart.fss.or.kr/api/'
REPORTS={'annual':'11011','q1':'11013','half':'11012','q3':'11014'}
ACCOUNTS={'profit':{'ifrs-full_ProfitLossAttributableToOwnersOfParent','ifrs_ProfitLossAttributableToOwnersOfParent'},'equity':{'ifrs-full_EquityAttributableToOwnersOfParent','ifrs_EquityAttributableToOwnersOfParent'},'revenue':{'ifrs-full_Revenue','ifrs_Revenue'},'assets':{'ifrs-full_Assets','ifrs_Assets'},'liabilities':{'ifrs-full_Liabilities','ifrs_Liabilities'}}
# DART annual accounts may use older codes or account names; no fallback by ambiguous Korean names.
def get_json(path,params):
 url=API+path+'?'+urllib.parse.urlencode(params)
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'KRX-R14-Research/1.0'}),timeout=25) as r:return json.load(r)
def load_json(p,default):
 try:return json.loads(p.read_text(encoding='utf-8'))
 except (OSError,ValueError):return default
def save_json(p,data):
 temp=p.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(p)
def corp_map():
 p=OUT/'corp_map.json';cached=load_json(p,{})
 if cached:return cached
 url=API+'corpCode.xml?'+urllib.parse.urlencode({'crtfc_key':KEY})
 with urllib.request.urlopen(url,timeout=40) as response: blob=response.read()
 with zipfile.ZipFile(io.BytesIO(blob)) as z: root=ET.fromstring(z.read(z.namelist()[0]))
 mapping={}
 for x in root.findall('.//list'):
  stock=(x.findtext('stock_code') or '').strip();corp=(x.findtext('corp_code') or '').strip()
  if len(stock)==6 and stock.isdigit() and len(corp)==8:mapping[stock]=corp
 save_json(p,mapping);return mapping
def number(s):
 try:return int(str(s).replace(',','').strip())
 except (ValueError,TypeError):return None
def parse(data,kind):
 if data.get('status')!='000':return {'status':data.get('status','UNKNOWN'),'message':data.get('message','')}
 records=data.get('list',[]); chosen={};basis='CFS' if any(r.get('fs_div')=='CFS' for r in records) else 'OFS'
 for name,ids in ACCOUNTS.items():
  rows=[r for r in records if r.get('fs_div')==basis and r.get('sj_div')==('BS' if name in ('equity','assets','liabilities') else 'IS') and r.get('account_id') in ids]
  if len(rows)==1:
   row=rows[0];chosen[name]=number(row.get('thstrm_amount'))
   if kind=='annual':chosen['previous_'+name]=number(row.get('frmtrm_amount'))
 return {'status':'000','fs_div':basis,'accounts':chosen,'report':kind}
def request(corp,year,kind):
 # OpenDART fnlttSinglAcntAll requires fs_div; prefer consolidated, then separate.
 errors=[]
 for basis in ('CFS','OFS'):
  params={'crtfc_key':KEY,'corp_code':corp,'bsns_year':str(year),
          'reprt_code':REPORTS[kind],'fs_div':basis}
  data=get_json('fnlttSinglAcntAll.json',params)
  if data.get('status')=='000' and data.get('list'):
   parsed=parse(data,kind)
   parsed['fs_div']=basis
   return parsed
  errors.append({'basis':basis,'status':data.get('status'),'message':data.get('message','')})
 return {'status':'API_UNVERIFIED','errors':errors}
def ratio(cap,profit,equity,prior):
 return {'per':round(cap/profit,4) if cap and profit and profit>0 else None,
         'pbr':round(cap/equity,4) if cap and equity and equity>0 else None,
         'roe_pct':round(100*profit/((equity+prior)/2),4) if profit is not None and equity and prior and equity>0 and prior>0 else None}
def main():
 if not L.exists():raise SystemExit('MISSING_L_INDEX: run L first')
 if not KEY:raise SystemExit('MISSING_DART_API_KEY: configure DART_API_KEY repository secret')
 with L.open(encoding='utf-8-sig',newline='') as f: base=list(csv.DictReader(f))
 # Include the full KRX market universe, not only the existing financial cache.
 market_file=ROOT/'data/v5_investment_r14_research_k/full_market_ratios_k.csv'
 if market_file.exists():
  with market_file.open(encoding='utf-8-sig',newline='') as f: market=list(csv.DictReader(f))
  indexed={r['code']:r for r in base}
  for r in market:
   code=str(r.get('ISU_CD','')).zfill(6)
   if code.isdigit() and code not in indexed:indexed[code]={'code':code,'corp_code':''}
  base=list(indexed.values())
 mapping=corp_map();cache=load_json(OUT/'dart_financial_cache.json',{})
 # Reuse previously fetched records; update missing annual statements first.
 market_date=load_json(ROOT/'data/v5_investment_r14_research_k/status.json',{}).get('market_date','')
 asof_year=int(market_date[:4]) if len(market_date)>=4 else YEAR
 annual_year=asof_year-1
 selected=[]
 for row in base:
  code=row['code'];corp=row.get('corp_code') or mapping.get(code)
  if not corp:continue
  key=f'{code}:{annual_year}:annual'
  if cache.get(key,{}).get('status')!='000':selected.append((code,corp,annual_year,'annual'))
 # After annual baseline, fill current and prior cumulative quarters for TTM.
 if not selected:
  for row in base:
   code=row['code'];corp=row.get('corp_code') or mapping.get(code)
   if not corp:continue
   for year in (annual_year,asof_year):
    for kind in ('q1','half','q3'):
     key=f'{code}:{year}:{kind}'
     if cache.get(key,{}).get('status')!='000':selected.append((code,corp,year,kind))
 selected=selected[:LIMIT];fetched=0;failed=0;api_rejected=0
 for code,corp,year,kind in selected:
  key=f'{code}:{year}:{kind}'
  try:
   record=request(corp,year,kind);record.update({'corp_code':corp,'year':year,'fetched_utc':dt.datetime.now(dt.timezone.utc).isoformat()})
   if record.get('status')=='000':
    cache[key]=record;fetched+=1
   else:
    api_rejected+=1
    print('DART_UNVERIFIED',key,str(record.get('errors',[]))[:250])
    # Preserve any earlier verified record; do not cache API errors as success.
    if cache.get(key,{}).get('status')!='000':cache.pop(key,None)
  except Exception as e:
   failed+=1;print('FETCH_FAILED',key,type(e).__name__,str(e)[:120]);continue
  if fetched%10==0:save_json(OUT/'dart_financial_cache.json',cache)
  time.sleep(.13)
 save_json(OUT/'dart_financial_cache.json',cache)
 # Provide conservative annual calculations with explicit financial year and equity denominator.
 results=[];complete=0
 for row in base:
  code=row['code'];entry=cache.get(f'{code}:{annual_year}:annual',{})
  ac=entry.get('accounts',{}) if entry.get('status')=='000' else {}
  profit=ac.get('profit');equity=ac.get('equity');prior=ac.get('previous_equity')
  results.append({'code':code,'year':annual_year,'fs_div':entry.get('fs_div',''),'annual_profit':profit,'equity':equity,'prior_equity':prior,'annual_roe_pct':ratio(None,profit,equity,prior)['roe_pct'],'source':'OpenDART fnlttSinglAcntAll' if ac else 'UNVERIFIED','ttm_profit':'','ttm_status':'NOT_YET_COMPUTED'})
  complete+=bool(ac)
 with (OUT/'annual_financial_index_m.csv').open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
 status={'version':'R14_M_DART_INCREMENTAL_FIXED_FS_DIV','generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'market_date':market_date,'base_rows':len(base),'cache_records':len(cache),'fetched_this_run':fetched,'failed_this_run':failed,'api_rejected_this_run':api_rejected,'annual_verified_rows':complete,'batch_limit':LIMIT,'ttm_calculated':0,'final_buy_signals':0,'golden_cross_used':False,'notes':['TTM not calculated: cumulative quarterly comparability must be validated','Financial statement data are sourced from OpenDART; no official KRX PER/PBR verification','Source caches and prior R14 stages are not modified']}
 save_json(OUT/'status.json',status);print(json.dumps(status,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
