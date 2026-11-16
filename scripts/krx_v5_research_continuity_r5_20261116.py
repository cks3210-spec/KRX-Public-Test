#!/usr/bin/env python3
"""R5 independent evidence archive, report-period gate, illustrative valuation and 5/10/20-session tracking.
Runs AFTER R4. Never releases a final grade, official PER/PBR or executable buy signal.
"""
import csv, datetime as dt, json, os, pathlib, shutil
from decimal import Decimal, InvalidOperation
ROOT=pathlib.Path(__file__).resolve().parents[1]
BASE=ROOT/'data/v5_fullmarket_r4'
OUT=ROOT/'data/v5_research_r5'
OUT.mkdir(parents=True,exist_ok=True)

def readcsv(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def writecsv(p,rows,cols):
 p.parent.mkdir(parents=True,exist_ok=True)
 tmp=p.with_suffix('.tmp')
 with tmp.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)
 tmp.replace(p)
def dec(v):
 try:
  x=Decimal(str(v).replace(',',''));return x if x.is_finite() else None
 except (InvalidOperation,ValueError,TypeError):return None
def main():
 status={'version':'R5','generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'final_grades':0,'buy_signals':0,'official_per_pbr_verified':0}
 try:
  src=BASE/'full_market_research.csv';records=readcsv(src)
  r4=json.loads((BASE/'status.json').read_text(encoding='utf-8'))
  if r4.get('state')!='RESEARCH_OUTPUT_BUILT_NOT_FINAL' or len(records)<1000:raise ValueError('R4 research output incomplete')
  dates={r.get('BAS_DD') for r in records}
  if len(dates)!=1:raise ValueError('Mixed market dates')
  day=dates.pop()
  if not day or len(day)!=8 or r4.get('target_market_date')!=day:raise ValueError('R4 date mismatch')
  cache=json.loads((BASE/'dart_financial_cache.json').read_text(encoding='utf-8'))
  archive=OUT/'snapshots'/day
  archive.mkdir(parents=True,exist_ok=True)
  # Never silently overwrite historical evidence; repeat runs of same date are explicitly versioned.
  stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
  snapshot=archive/f'research_{stamp}.csv'
  shutil.copy2(src,snapshot)
  assessment=[];prices=[]
  for r in records:
   code=r['ISU_CD'];f=cache.get(code,{})
   report=f.get('report','');year=f.get('year','')
   # DART interim profit is year-to-date, not TTM. Never divide market cap by interim profit as official PER.
   annual=report=='11011';complete=f.get('state')=='FINANCIAL_FIELDS_FOUND'
   reference_pe=dec(r.get('reference_pe'));reference_pb=dec(r.get('reference_pb'));roe=dec(r.get('reference_roe_pct'))
   close=dec(r.get('TDD_CLSPRC'))
   blockers=['OFFICIAL_VALUATION_UNVERIFIED','SHARECLASS_UNVERIFIED']
   if not complete:blockers.append('FINANCIAL_INCOMPLETE')
   if not annual:blockers.append('INTERIM_PROFIT_NOT_TTM')
   if f.get('asof_market_date')!=day:blockers.append('FINANCIAL_CACHE_NOT_REFRESHED_TODAY')
   if not year:blockers.append('REPORT_YEAR_MISSING')
   # Treat all R4 grades as provisional, including A/B; no validated final A/B.
   provisional=r.get('provisional_grade','') if complete else ''
   assessment.append({'BAS_DD':day,'MARKET':r['MARKET'],'ISU_CD':code,'ISU_NM':r.get('ISU_NM',''),
    'financial_year':year,'report_code':report,'period_type':'ANNUAL' if annual else 'INTERIM_YTD' if report else 'UNKNOWN',
    'financial_state':f.get('state','MISSING'),'reference_pe_from_r4':r.get('reference_pe',''),
    'reference_pb_from_r4':r.get('reference_pb',''),'reference_roe_from_r4':r.get('reference_roe_pct',''),
    'r4_provisional_grade':provisional,'final_grade':'WITHHELD','buy_signal':'NONE',
    'blockers':';'.join(blockers)})
   # Hypothetical sensitivities, NOT sector-calibrated fair value or an actionable buy zone.
   price={'BAS_DD':day,'ISU_CD':code,'ISU_NM':r.get('ISU_NM',''),'reference_close':r.get('TDD_CLSPRC',''),
          'scenario_only':'YES','verified_fair_value':'','buy_price':'','buy_signal':'NONE'}
   for pct in ('0.85','0.90','0.95'):
    price['illustrative_'+pct+'_of_close']=str(int(close*Decimal(pct))) if close and close>0 else ''
   prices.append(price)
  writecsv(OUT/'financial_period_audit.csv',assessment,list(assessment[0]))
  writecsv(OUT/'illustrative_price_scenarios.csv',prices,list(prices[0]))
  # Persist a unique daily closing snapshot and calculate forward returns by distinct observed trading dates.
  hist=OUT/'daily_close_history.csv'
  old=readcsv(hist) if hist.exists() else []
  lookup={(r['BAS_DD'],r['MARKET'],r['ISU_CD']):r for r in old}
  for r in records:
   key=(day,r['MARKET'],r['ISU_CD'])
   lookup[key]={'BAS_DD':day,'MARKET':r['MARKET'],'ISU_CD':r['ISU_CD'],'ISU_NM':r.get('ISU_NM',''),
                'close':r.get('TDD_CLSPRC','')}
  allrows=sorted(lookup.values(),key=lambda r:(r['BAS_DD'],r['MARKET'],r['ISU_CD']))
  writecsv(hist,allrows,['BAS_DD','MARKET','ISU_CD','ISU_NM','close'])
  bycode={}
  for r in allrows:bycode.setdefault((r['MARKET'],r['ISU_CD']),[]).append(r)
  performance=[]
  for group,items in bycode.items():
   for i,r in enumerate(items):
    base=dec(r['close']);out={'BAS_DD':r['BAS_DD'],'MARKET':group[0],'ISU_CD':group[1],'entry_close':r['close']}
    for n in (5,10,20):
     future=dec(items[i+n]['close']) if i+n<len(items) else None
     out[f'return_{n}_sessions_pct']=str(round((future/base-1)*100,4)) if base and base>0 and future is not None else ''
     out[f'exit_date_{n}_sessions']=items[i+n]['BAS_DD'] if future is not None else ''
    performance.append(out)
  writecsv(OUT/'forward_returns_5_10_20.csv',performance,list(performance[0]))
  status.update(state='R5_EVIDENCE_BUILT_NOT_FINAL',market_date=day,market_eligible_rows=len(records),
   financial_complete=sum(r['financial_state']=='FINANCIAL_FIELDS_FOUND' for r in assessment),
   interim_ytd_rows=sum(r['period_type']=='INTERIM_YTD' for r in assessment),
   r4_provisional_ab=sum(bool(r['r4_provisional_grade']) for r in assessment),
   historical_sessions=len({r['BAS_DD'] for r in allrows}),
   measured_5_session=sum(bool(r['return_5_sessions_pct']) for r in performance),
   measured_10_session=sum(bool(r['return_10_sessions_pct']) for r in performance),
   measured_20_session=sum(bool(r['return_20_sessions_pct']) for r in performance),
   snapshot_path=str(snapshot.relative_to(ROOT)),
   limitations=['R4 PER from interim YTD earnings is not a trailing-twelve-month PER.',
                'No official KRX PER/PBR, shareclass, sector multiples or final investment grade.',
                'Forward returns require 5/10/20 later observed trading-session snapshots; do not extrapolate.'])
 except Exception as exc:
  status.update(state='FAILED',error=str(exc))
 (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(status,ensure_ascii=False,indent=2))
 if status['state']=='FAILED':raise SystemExit(1)
if __name__=='__main__':main()
