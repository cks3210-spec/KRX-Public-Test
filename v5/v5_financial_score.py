#!/usr/bin/env python3
"""Independent, conservative v5 financial score (partial data allowed).
Reads v5-state financial_latest.json; never edits v4, GC or collector state.
No buy recommendation; scores are provisional when metrics are missing.
"""
import argparse,csv,json,math
from pathlib import Path
from datetime import datetime,timezone

WEIGHTS={'growth':30,'profitability':25,'stability':20,'valuation':15,'cashflow':10}
# Available snapshot fields support profitability (operating margin, ROA) and stability (debt/equity, equity/assets).
# Growth, valuation and cashflow require historical series, market price and cashflow statements, respectively.

def number(row,key):
    if row.get(key.replace('_krw','_status')) not in (None,'OK'):return None
    v=row.get(key)
    if v is None or v=='':return None
    try:
        n=float(v)
        return n if math.isfinite(n) else None
    except (TypeError,ValueError):return None

def scale(v,low,high):
    return round(max(0,min(1,(v-low)/(high-low)))*100,2)

def evaluate(row):
    rev=number(row,'revenue_krw');op=number(row,'operating_profit_krw')
    net=number(row,'net_income_krw');assets=number(row,'assets_krw')
    debt=number(row,'liabilities_krw');equity=number(row,'equity_krw')
    metrics={}; scores={}; available={}; notes=[]
    if rev is not None and rev>0 and op is not None:
        metrics['operating_margin_pct']=round(op/rev*100,2)
        scores['operating_margin']=scale(metrics['operating_margin_pct'],-5,20)
    if assets is not None and assets>0 and net is not None:
        metrics['roa_pct']=round(net/assets*100,2)
        scores['roa']=scale(metrics['roa_pct'],-3,10)
    if equity is not None and equity>0 and debt is not None and debt>=0:
        metrics['debt_to_equity_pct']=round(debt/equity*100,2)
        scores['debt_to_equity']=round(100-scale(metrics['debt_to_equity_pct'],50,300),2)
    if assets is not None and assets>0 and equity is not None and 0<=equity<=assets:
        metrics['equity_ratio_pct']=round(equity/assets*100,2)
        scores['equity_ratio']=scale(metrics['equity_ratio_pct'],10,70)
    # Sub-metric weights preserve missingness within each category.
    parts={'profitability':[('operating_margin',15),('roa',10)],'stability':[('debt_to_equity',10),('equity_ratio',10)]}
    earned=0; possible=0
    for category,items in parts.items():
        eligible=[(scores[k],w) for k,w in items if k in scores]
        available[category]=sum(w for _,w in eligible)
        if eligible:
            earned+=sum(v*w/100 for v,w in eligible)
            possible+=available[category]
    for category in ('growth','valuation','cashflow'):available[category]=0
    coverage=round(possible,2)
    provisional=round(earned/possible*100,2) if possible else None
    # Financial sector requires sector-specific ratios. Do not silently treat as comparable.
    if row.get('sector') in ('금융','금융업','은행','보험','증권'):
        notes.append('FINANCIAL_SECTOR_NEEDS_SEPARATE_MODEL')
    if possible<60:notes.append('LOW_COVERAGE_PROVISIONAL_ONLY')
    if possible==0:notes.append('NO_SCORABLE_METRICS')
    grade=('A' if provisional>=80 else 'B' if provisional>=65 else 'C') if provisional is not None else 'UNRATED'
    # Do not publish A/B as a fully validated investment rating at low coverage.
    return {'ISU_CD':row.get('ISU_CD',''),'ISU_NM':row.get('ISU_NM',''),
            'fiscal_year':row.get('fiscal_year',''),'period':row.get('period',''),
            'statement_type':row.get('statement_type',''),'verified_at_utc':row.get('verified_at_utc',''),
            'provisional_score':provisional,'provisional_grade':grade,
            'coverage_pct':coverage,'grade_status':'PROVISIONAL' if possible else 'UNRATED',
            'missing_categories':','.join(k for k,v in available.items() if v==0),
            'metrics':metrics,'notes':notes,'buy_signal':'NOT_EVALUATED'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',default='v5_state/financial_latest.json');p.add_argument('--output',default='v5_score_output');args=p.parse_args()
    src=Path(args.input);out=Path(args.output)
    if not src.exists():raise SystemExit('Input snapshot missing; no score generated')
    data=json.loads(src.read_text(encoding='utf-8'))
    if not isinstance(data,dict) or not data:raise SystemExit('Input snapshot empty or invalid')
    out.mkdir(parents=True,exist_ok=True)
    results=[evaluate({**v,'ISU_CD':k}) for k,v in sorted(data.items()) if isinstance(v,dict)]
    cols=['ISU_CD','ISU_NM','fiscal_year','period','statement_type','verified_at_utc','provisional_score','provisional_grade','coverage_pct','grade_status','missing_categories','buy_signal','metrics','notes']
    with (out/'all_provisional_scores.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for r in results:w.writerow({**r,'metrics':json.dumps(r['metrics'],ensure_ascii=False),'notes':';'.join(r['notes'])})
    # A/B watchlist is NOT a buy list, and is intentionally separated from the full diagnostic CSV.
    with (out/'ab_watchlist.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for r in results:
            if r['provisional_grade'] in ('A','B'):w.writerow({**r,'metrics':json.dumps(r['metrics'],ensure_ascii=False),'notes':';'.join(r['notes'])})
    summary={'asof_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),'input_count':len(results),
             'provisional_A':sum(r['provisional_grade']=='A' for r in results),
             'provisional_B':sum(r['provisional_grade']=='B' for r in results),
             'coverage_max_pct':40,'caution':'Only operating margin, ROA and leverage/equity metrics are available. Scores are preliminary and not investment recommendations. Growth, PER/PBR and cash flow not scored.',
             'no_v4_or_gc_changes':True}
    (out/'score_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
