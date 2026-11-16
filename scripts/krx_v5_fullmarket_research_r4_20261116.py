#!/usr/bin/env python3
"""Stage60 R4: full-market incremental DART financial research. Never issues final buy signals.
Consumes a verified Stage60 08:30 snapshot; does not mutate historical financial caches.
"""
import csv, datetime as dt, io, json, os, pathlib, re, urllib.parse, urllib.request, zipfile, xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]; BASE=ROOT/'data/v5_fullmarket_r4'; BASE.mkdir(parents=True,exist_ok=True)
NOW=dt.datetime.now(ZoneInfo('Asia/Seoul')); STATE={'version':'R4','run_at_kst':NOW.isoformat(),'mode':'INCREMENTAL_FINANCIAL_RESEARCH','final_buy_signals':0,'official_per_pbr_verified':False}
def save(): (BASE/'status.json').write_text(json.dumps(STATE,ensure_ascii=False,indent=2),encoding='utf-8')
def readcsv(p):
 if not p.exists():return []
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def writecsv(p,rows,fields):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp')
 with tmp.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
 tmp.replace(p)
def num(v):
 try:
  d=Decimal(str(v).replace(',','').strip());return d if d.is_finite() else None
 except (InvalidOperation,ValueError,TypeError):return None
def fetch(url,params,timeout=40):
 q=urllib.parse.urlencode(params);req=urllib.request.Request(url+'?'+q,headers={'User-Agent':'KRX-v5-research/1.0'})
 with urllib.request.urlopen(req,timeout=timeout) as f:return f.read()
def corp_map(key):
 path=BASE/'dart_corp_map.json'
 if path.exists() and (NOW.date()-dt.date.fromtimestamp(path.stat().st_mtime)).days<30:
  return json.loads(path.read_text(encoding='utf-8'))
 raw=fetch('https://opendart.fss.or.kr/api/corpCode.xml',{'crtfc_key':key},timeout=90)
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  with z.open('CORPCODE.xml') as f: root=ET.parse(f).getroot()
 mapping={}
 for x in root.findall('list'):
  code=(x.findtext('stock_code') or '').strip();corp=(x.findtext('corp_code') or '').strip()
  if re.fullmatch(r'\d{6}',code) and re.fullmatch(r'\d{8}',corp):mapping[code]=corp
 if len(mapping)<1000:raise ValueError('DART corporation mapping unexpectedly small')
 path.write_text(json.dumps(mapping,ensure_ascii=False),encoding='utf-8');return mapping
def financial(key,corp,year,report):
 raw=fetch('https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json',{'crtfc_key':key,'corp_code':corp,'bsns_year':year,'reprt_code':report,'fs_div':'CFS'})
 data=json.loads(raw)
 if data.get('status')=='013':return {'state':'NO_REPORT','year':year,'report':report}
 if data.get('status')!='000':return {'state':'API_'+str(data.get('status')),'year':year,'report':report}
 records=data.get('list') or []
 # Only explicit consolidated, owner-attributable accounts. Do not substitute total consolidated figures.
 aliases={'profit':['ifrs-full_ProfitLossAttributableToOwnersOfParent','ifrs_ProfitLossAttributableToOwnersOfParent'],
          'equity':['ifrs-full_EquityAttributableToOwnersOfParent','ifrs_EquityAttributableToOwnersOfParent'],
          'revenue':['ifrs-full_Revenue','ifrs_Revenue','ifrs-full_RevenueFromContractsWithCustomers'],
          'assets':['ifrs-full_Assets','ifrs_Assets'],'liabilities':['ifrs-full_Liabilities','ifrs_Liabilities']}
 result={'state':'PARTIAL','year':year,'report':report,'fs_div':'CFS'}
 for name,ids in aliases.items():
  candidates=[r for r in records if r.get('account_id') in ids and r.get('sj_div') in ('BS','IS','CIS')]
  for r in candidates:
   value=num(r.get('thstrm_amount'))
   if value is not None:result[name]=str(value);break
 if result.get('profit') is not None and result.get('equity') is not None:result['state']='FINANCIAL_FIELDS_FOUND'
 return result
def main():
 import exchange_calendars as xcals
 import pandas as pd
 cal=xcals.get_calendar('XKRX');today=pd.Timestamp(NOW.date().isoformat())
 if not cal.is_session(today):STATE['state']='SKIPPED_KRX_CLOSED';save();return
 day=cal.previous_session(today).strftime('%Y%m%d');STATE['target_market_date']=day
 market=readcsv(ROOT/'data/latest.csv')
 if len(market)<1500 or {r.get('BAS_DD') for r in market}!={day}:
  STATE.update(state='BLOCKED_MARKET_NOT_CURRENT',market_rows=len(market),market_dates=sorted({r.get('BAS_DD') for r in market})[:4]);save();raise RuntimeError('Stage60 08:30 verified market snapshot missing')
 if len({(r.get('MARKET'),r.get('ISU_CD')) for r in market})!=len(market):raise ValueError('Duplicate market securities')
 eligible=[r for r in market if (num(r.get('MKTCAP')) or 0)>=100_000_000_000 and re.fullmatch(r'\d{6}',r.get('ISU_CD',''))]
 # Conservative common-stock filter: unresolved share class remains unverified, never label verified.
 STATE.update(market_rows=len(market),eligible_rows=len(eligible),share_class='UNVERIFIED_FOR_ALL')
 key=os.environ.get('DART_API_KEY','').strip();cachepath=BASE/'dart_financial_cache.json';cache=json.loads(cachepath.read_text(encoding='utf-8')) if cachepath.exists() else {}
 mapping={};errors=[];refreshed=0
 if key:
  try:mapping=corp_map(key)
  except Exception as e:errors.append('DART_CORP_MAP: '+str(e)[:150])
 else:errors.append('DART_API_KEY missing')
 # Incremental round-robin: at most 120 requests per run, preserve previous verified financial entries.
 year=str(NOW.year);reports=[(str(NOW.year),'11014'),(str(NOW.year),'11012'),(str(NOW.year),'11013'),(str(NOW.year-1),'11011')]
 # Q3 report code 11014, half-year 11012, Q1 11013, annual 11011.
 # Future-year reports are safely rejected by API; first successful report is selected.
 pending=[r for r in eligible if r['ISU_CD'] in mapping and (r['ISU_CD'] not in cache or cache[r['ISU_CD']].get('asof_market_date')!=day)]
 pending.sort(key=lambda r:(r['ISU_CD'] in cache, r['ISU_CD']))
 budget=int(os.environ.get('DART_MAX_REQUESTS','120'));budget=max(0,min(300,budget));calls=0
 for r in pending:
  if calls>=budget:break
  code=r['ISU_CD'];corp=mapping[code];best=None
  for yr,report in reports:
   if calls>=budget:break
   calls+=1
   try:
    obj=financial(key,corp,yr,report)
    if obj['state']=='FINANCIAL_FIELDS_FOUND':best=obj;break
    if best is None and obj['state']=='PARTIAL':best=obj
   except Exception as e:errors.append(code+': '+str(e)[:90]);break
  if best:
   best.update(corp_code=corp,checked_at_kst=NOW.isoformat(),asof_market_date=day)
   # Preserve a prior complete record rather than replacing with partial.
   if best['state']=='FINANCIAL_FIELDS_FOUND' or code not in cache:cache[code]=best;refreshed+=1
 # Atomic financial cache, never overwrite Stage15/Stage50 historical evidence.
 tmp=cachepath.with_suffix('.tmp');tmp.write_text(json.dumps(cache,ensure_ascii=False),encoding='utf-8');tmp.replace(cachepath)
 result=[];candidates=[]
 for r in eligible:
  code=r['ISU_CD'];f=cache.get(code,{})
  cap=num(r.get('MKTCAP'));profit=num(f.get('profit'));equity=num(f.get('equity'));assets=num(f.get('assets'));liab=num(f.get('liabilities'))
  pe=cap/profit if cap and profit and profit>0 else None
  pb=cap/equity if cap and equity and equity>0 else None
  roe=profit/equity*100 if profit is not None and equity and equity>0 else None
  debt=liab/equity*100 if liab is not None and equity and equity>0 else None
  flags=[]
  if f.get('state')!='FINANCIAL_FIELDS_FOUND':flags.append('FINANCIAL_DATA_INCOMPLETE')
  if not f.get('year'):flags.append('FINANCIAL_PERIOD_UNKNOWN')
  flags+=['OFFICIAL_PER_PBR_NOT_VERIFIED','SHARE_CLASS_NOT_VERIFIED','PER_PBR_ARE_ESTIMATES','PERIOD_COMPARABILITY_NOT_VERIFIED']
  score=0;components=0
  for ok in [roe is not None and roe>=12,pe is not None and 0<pe<=18,pb is not None and 0<pb<=2.5,debt is not None and debt<=150]:
   components+=1;score+=int(ok)
  provisional='A' if score==4 else 'B+' if score==3 else 'B' if score==2 else ''
  if f.get('state')!='FINANCIAL_FIELDS_FOUND':provisional=''
  row={'BAS_DD':day,'MARKET':r['MARKET'],'ISU_CD':code,'ISU_NM':r.get('ISU_NM',''),'MKTCAP':r['MKTCAP'],'TDD_CLSPRC':r['TDD_CLSPRC'],'financial_year':f.get('year',''),'financial_report':f.get('report',''),'financial_state':f.get('state','MISSING'),'reference_pe':str(round(pe,3)) if pe is not None else '', 'reference_pb':str(round(pb,3)) if pb is not None else '', 'reference_roe_pct':str(round(roe,3)) if roe is not None else '', 'reference_debt_ratio_pct':str(round(debt,3)) if debt is not None else '', 'research_score':score if f.get('state')=='FINANCIAL_FIELDS_FOUND' else '', 'provisional_grade':provisional,'final_grade':'WITHHELD','buy_signal':'NONE','flags':';'.join(flags)}
  result.append(row)
  if provisional:candidates.append(row)
 fields=list(result[0]) if result else []
 if fields:
  writecsv(BASE/'full_market_research.csv',result,fields)
  writecsv(BASE/'provisional_ab_watchlist.csv',candidates,fields)
 STATE.update(state='RESEARCH_OUTPUT_BUILT_NOT_FINAL',dart_api_calls=calls,dart_records_refreshed=refreshed,financial_cache_entries=len(cache),financial_complete_in_universe=sum(r['financial_state']=='FINANCIAL_FIELDS_FOUND' for r in result),provisional_ab_count=len(candidates),official_valuation_verified=0,errors=errors[:20],error_count=len(errors),warnings=['Provisional screening only; 2025/2026 annual and interim results are not directly comparable','No verified official PER/PBR, share-class, owner-share-count or investment-grade price targets','DART financials are refreshed incrementally; full market coverage requires multiple runs'])
 save()
if __name__=='__main__':
 try:main()
 except Exception as e:STATE.update(state='FAILED',error=str(e)[:500]);save();raise
