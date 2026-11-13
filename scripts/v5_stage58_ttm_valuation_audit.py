#!/usr/bin/env python3
"""Stage58 TTM valuation evidence audit. Research ratios, NOT official KRX PER/PBR.
Input: Stage57 linked evidence ZIP; frozen 2026-11-06 market-cap CSV.
Output: per-stock audit CSV + status JSON. No trading signals.
Requires DART_API_KEY (or OPENDART_API_KEY) and network access.
"""
import argparse,csv,io,json,os,time,urllib.parse,urllib.request,zipfile
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path

IDS={
 'profit':{'ifrs-full_ProfitLossAttributableToOwnersOfParent','ifrs_ProfitLossAttributableToOwnersOfParent'},
 'equity':{'ifrs-full_EquityAttributableToOwnersOfParent','ifrs_EquityAttributableToOwnersOfParent'}
}
PERIOD={'2026_Q3':'11014','2026_H1':'11012'}

def num(v):
 try:
  n=Decimal(str(v).replace(',','').strip())
  return n if n.is_finite() else None
 except (InvalidOperation,TypeError,ValueError):return None

def get(key,corp,year,report):
 q=urllib.parse.urlencode({'crtfc_key':key,'corp_code':corp,'bsns_year':year,'reprt_code':report,'fs_div':'CFS'})
 req=urllib.request.Request('https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?'+q,headers={'User-Agent':'KRX-Research-Valuation-Audit/1.0'})
 with urllib.request.urlopen(req,timeout=30) as f:return json.load(f)

def extract(data,field):
 if str(data.get('status'))!='000':return None,'DART_'+str(data.get('status'))
 section={'IS','CIS'} if field=='profit' else {'BS'}
 values=set()
 for r in data.get('list') or []:
  if r.get('fs_div') not in (None,'','CFS') or r.get('sj_div') not in section or r.get('account_id') not in IDS[field]:continue
  n=num(r.get('thstrm_amount'))
  if n is not None:values.add(n)
 if len(values)!=1:return None,'MISSING_OR_CONFLICTING_'+field.upper()
 return values.pop(),'OK'

def readzip(z,name):
 return list(csv.DictReader(io.StringIO(z.read(name).decode('utf-8-sig'))))

def main():
 a=argparse.ArgumentParser();a.add_argument('--evidence-zip',required=True);a.add_argument('--market-csv',required=True);a.add_argument('--output-dir',default='stage58_ttm_output');a.add_argument('--sleep',type=float,default=.12);args=a.parse_args()
 out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
 status={'mode':'TTM_OWNER_ATTRIBUTABLE_VALUATION_AUDIT','created_utc':datetime.now(timezone.utc).isoformat(),'official_krx_per_pbr_verified':False,'final_buy_signals':0}
 try:
  key=os.getenv('DART_API_KEY') or os.getenv('OPENDART_API_KEY')
  if not key:raise ValueError('Missing DART_API_KEY / OPENDART_API_KEY')
  with zipfile.ZipFile(args.evidence_zip) as z:
   linked=readzip(z,'stage57_output/stage56_linked_candidates.csv');owners=readzip(z,'stage56_official_output/owner_fields.csv')
  if len(linked)!=318 or len(owners)!=318:raise ValueError('Frozen cohort size mismatch')
  byowner={r['ISU_CD']:r for r in owners}
  with open(args.market_csv,encoding='utf-8-sig',newline='') as f:market=list(csv.DictReader(f))
  # Market cap must match the frozen candidate's exact date; never mix market dates.
  caps={(r['BAS_DD'],r['ISU_CD']):r for r in market}
  cache={};rows=[]
  for r in linked:
   code=r['ISU_CD'];owner=byowner.get(code,{});period=owner.get('financial_period','');report=PERIOD.get(period)
   item={'ISU_CD':code,'ISU_NM':r['ISU_NM'],'provisional_grade':r['stage57_provisional_grade'],'financial_period':period,'market_date':r['BAS_DD'],'owner_profit_ttm':'','owner_equity_latest':'','market_cap':'','research_per_ttm':'','research_pbr':'','state':'BLOCKED','reason':''}
   if item['provisional_grade'] not in ('A','A+','B','B+') or owner.get('status')!='OWNER_FIELDS_VERIFIED' or not report:
    item['reason']='NOT_IN_VERIFIED_AB_COHORT';rows.append(item);continue
   caprow=caps.get((r['BAS_DD'],code));cap=num(caprow.get('MKTCAP')) if caprow else None
   if cap is None or cap<=0:item['reason']='SAME_DATE_MARKET_CAP_MISSING';rows.append(item);continue
   corp=owner.get('dart_corp_code','')
   if not (corp.isdigit() and len(corp)==8):item['reason']='INVALID_CORP_CODE';rows.append(item);continue
   latest_profit=num(owner.get('owner_profit'));equity=num(owner.get('owner_equity'))
   if latest_profit is None or equity is None or equity<=0:item['reason']='LATEST_OWNER_FIELDS_INVALID';rows.append(item);continue
   try:
    for year,rep in [('2025','11011'),('2025',report)]:
     k=(corp,year,rep)
     if k not in cache:cache[k]=get(key,corp,year,rep);time.sleep(args.sleep)
    annual,reason1=extract(cache[(corp,'2025','11011')],'profit')
    prior_ytd,reason2=extract(cache[(corp,'2025',report)],'profit')
    if annual is None or prior_ytd is None:item['reason']='TTM_COMPONENT_UNVERIFIED:'+reason1+','+reason2;rows.append(item);continue
    ttm=annual+latest_profit-prior_ytd
    item['owner_profit_ttm']=str(ttm);item['owner_equity_latest']=str(equity);item['market_cap']=str(cap)
    if ttm<=0:item['reason']='TTM_PROFIT_NONPOSITIVE';rows.append(item);continue
    item['research_per_ttm']=str(round(cap/ttm,4));item['research_pbr']=str(round(cap/equity,4))
    item['state']='RESEARCH_RATIOS_COMPUTED';item['reason']='NOT_OFFICIAL_KRX_MULTIPLES'
   except Exception as e:item['reason']='DART_ERROR:'+type(e).__name__
   rows.append(item)
  with (out/'valuation_audit.csv').open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
  status.update(candidate_count=len(rows),counts=dict(Counter(r['state'] for r in rows)),block_reasons=dict(Counter(r['reason'].split(':')[0] for r in rows if r['state']=='BLOCKED')),note='Ratios are research estimates from DART owner-attributable CFS and same-date archived market cap; not official KRX PER/PBR or recommendations.')
 except Exception as e:status['error']=str(e)
 (out/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(status,ensure_ascii=False))
 if 'error' in status:raise SystemExit(1)
if __name__=='__main__':main()
