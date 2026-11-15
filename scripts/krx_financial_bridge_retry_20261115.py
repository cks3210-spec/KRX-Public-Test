#!/usr/bin/env python3
"""Join daily technical discoveries to prior research evidence; never invent A/B grades.
Usage: python scripts/build_daily_financial_bridge.py --financial data/all_candidates_318.csv
"""
import argparse,csv,json,pathlib,datetime
ROOT=pathlib.Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
def load(path):
 with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def num(x):
 try:return float(x)
 except (TypeError,ValueError):return None
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--financial',required=True,type=pathlib.Path);a=ap.parse_args()
 discovery=json.loads((DATA/'daily_discovery.json').read_text(encoding='utf-8'))
 financial={r['code'].zfill(6):r for r in load(a.financial)}
 market={r['ISU_CD'].zfill(6):r for r in load(DATA/'latest.csv') if r.get('BAS_DD')==discovery['trading_date']}
 results=[]
 for code in discovery.get('candidate_codes',[]):
  code=code.zfill(6);f=financial.get(code);m=market.get(code)
  if not f or not m:continue
  risks=int(num(f.get('risk_flag_count')) or 0)
  growth=num(f.get('revenue_growth_pct'));op=num(f.get('operating_profit_growth_pct'))
  debt=num(f.get('debt_ratio_pct'));cash=num(f.get('operating_cashflow'))
  per=num(f.get('official_per'));pbr=num(f.get('official_pbr'))
  qualified=(risks==0 and growth is not None and growth>0 and op is not None and op>0 and debt is not None and debt<150 and cash is not None and cash>0)
  if not qualified:continue
  results.append({'code':code,'name':m.get('ISU_NM') or f.get('name'),'close':m.get('TDD_CLSPRC'),
    'revenue_growth_pct':growth,'operating_profit_growth_pct':op,'debt_ratio_pct':debt,
    'operating_cashflow':cash,'official_per':per,'official_pbr':pbr,
    'prior_final_grade':f.get('final_grade','WITHHELD'),
    'status':'FINANCIAL_SCREEN_PASS_NOT_INVESTMENT_GRADE',
    'fair_price':None,'buy_signal':None})
 result={'trading_date':discovery['trading_date'],'source_financial':str(a.financial),
  'financial_source_date':'UNVERIFIED_FROM_INPUT','matched_financial_screen_count':len(results),
  'classification':'RESEARCH_WATCHLIST_NOT_FINAL_AB_OR_BUY_ADVICE',
  'candidates':results,'note':'Financial evidence may be stale or have cumulative-report issues. No A/B grade or fair price inferred.'}
 out=DATA/'daily_financial_bridge.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'date':result['trading_date'],'matched':len(results),'output':str(out)},ensure_ascii=False))
if __name__=='__main__':main()
