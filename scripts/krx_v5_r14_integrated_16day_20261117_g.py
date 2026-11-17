#!/usr/bin/env python3
"""R14 downstream integration of verified daily closes and existing fundamental research.
No DART/API requests, no golden cross, no artificial price histories.
"""
import csv, json, math, pathlib, datetime as dt
from collections import defaultdict
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
HISTORY=DATA/'v5_investment_r14_history_link'/'daily_close_archive_linked.csv'
RESEARCH=DATA/'v5_investment_r14_fundamental'/'full_market_research_enriched.csv'
OUT=DATA/'v5_investment_r14_integrated_g'

def read(path):
 with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def number(v):
 try:
  n=float(str(v).replace(',',''))
  return n if math.isfinite(n) else None
 except (ValueError,TypeError):return None
def pct(a,b):return round((a/b-1)*100,3) if a is not None and b and b>0 else ''
def write(path,rows,cols):
 with path.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)
def main():
 if not HISTORY.exists() or not RESEARCH.exists():
  raise SystemExit('Missing history or R14 research. Run history-link F and R14 upstream first.')
 history=read(HISTORY); research=read(RESEARCH)
 series=defaultdict(dict); dates=set(); rejected=0
 for r in history:
  day=r.get('BAS_DD','').strip();code=r.get('ISU_CD','').strip();close=number(r.get('close'))
  if len(day)!=8 or not day.isdigit() or len(code)!=6 or not code.isdigit() or not close or close<=0:
   rejected+=1;continue
  series[code][day]=close;dates.add(day)
 days=sorted(dates)
 if not days:raise SystemExit('No valid daily close history')
 latest=days[-1];latest_research=max((r.get('BAS_DD','') for r in research),default='')
 if latest_research!=latest:
  raise SystemExit(f'Stale R14 research {latest_research}; historical close latest {latest}. Run upstream R14 first.')
 # Market-wide chronological returns only when the immediately preceding N market sessions are present.
 output=[];covered={5:0,10:0,20:0};growth=0
 for r in research:
  row={k:v for k,v in r.items() if 'golden_cross' not in k.lower()}
  code=r.get('ISU_CD','').strip();date=r.get('BAS_DD','').strip();s=series.get(code,{})
  if date not in days:continue
  ix=days.index(date);close=s.get(date)
  row['verified_close']=close if close else ''
  row['price_history_sessions']=sum(d<=date for d in s)
  for n in (5,10,20):
   value=pct(close,s.get(days[ix-n])) if ix>=n and all(d in s for d in days[ix-n:ix+1]) else ''
   row[f'actual_return_{n}d_pct']=value
   if value!='':covered[n]+=1
  vals=[number(r.get(k)) for k in ('revenue_yoy_pct','operating_profit_yoy_pct','owner_profit_yoy_pct')]
  row['verified_growth_metrics']=sum(x is not None for x in vals)
  row['reference_valuation_metrics']=sum(number(r.get(k)) is not None for k in ('reference_per','reference_pbr','reference_roe_pct'))
  row['investment_status']='PROVISIONAL_RESEARCH_ONLY'
  row['official_valuation_verified']='NO'
  row['final_buy_signal']='NONE'
  if row['verified_growth_metrics']:growth+=1
  output.append(row)
 OUT.mkdir(parents=True,exist_ok=True)
 fields=list(output[0]) if output else ['BAS_DD','ISU_CD']
 write(OUT/'full_market_integrated.csv',output,fields)
 shortlist=[r for r in output if r.get('eligible') in ('1','True','true') and r.get('provisional_grade') in ('A','B+','B')]
 write(OUT/'provisional_ab_integrated.csv',shortlist,fields)
 status={'version':'R14_INTEGRATED_16DAY_G','generated_kst':dt.datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
  'latest_date':latest,'historical_sessions':len(days),'first_date':days[0],
  'historical_rows':len(history),'invalid_history_rows':rejected,'market_research_rows':len(output),
  'provisional_ab_rows':len(shortlist),'growth_rows':growth,'return_coverage':{str(k):v for k,v in covered.items()},
  'official_per_pbr_verified':False,'final_buy_signals':0,'golden_cross_used':False,
  'note':'16 real sessions used without fabricating prices; no official valuation verification or confirmed buy signals.'}
 (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(status,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
