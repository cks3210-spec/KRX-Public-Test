#!/usr/bin/env python3
"""Combine independently verified v5 financial and YoY growth results.
Provisional diagnostics only, not investment advice. No v4/GC writes.
"""
import argparse,csv,json,sys
from pathlib import Path
from datetime import datetime,timezone
from v5_financial_score import evaluate,scale

GROWTH_WEIGHTS={'revenue_growth_pct':12,'operating_profit_growth_pct':12,'net_income_growth_pct':6}

def score_growth(item,snapshot):
    scores={}; flags=[]
    if not isinstance(item,dict):return scores,['GROWTH_RECORD_MISSING']
    identity=item.get('identity',[])
    expected=[str(snapshot.get('fiscal_year')),snapshot.get('report_code'),snapshot.get('statement_type'),snapshot.get('verified_at_utc')]
    if identity!=expected:return scores,['GROWTH_IDENTITY_MISMATCH']
    raw=item.get('raw_comparatives') or {}
    metrics=item.get('metrics') or {}
    specs=[('revenue','revenue_growth_pct'),('operating_profit','operating_profit_growth_pct'),('net_income','net_income_growth_pct')]
    for field,key in specs:
        pair=raw.get(field)
        if not isinstance(pair,dict):continue
        now=pair.get('current_krw');prev=pair.get('previous_year_same_period_krw')
        if not isinstance(now,(int,float)) or not isinstance(prev,(int,float)):continue
        # Revenue must have positive denominator; profit uses turnaround logic.
        if field=='revenue':
            if prev>0 and isinstance(metrics.get(key),(int,float)):
                scores[key]=scale(metrics[key],-10,30)
        elif prev>0 and isinstance(metrics.get(key),(int,float)):
            scores[key]=scale(metrics[key],-30,50)
        elif prev<=0 and now>0 and metrics.get(field+'_turnaround') is True:
            scores[key]=85.0
            flags.append(field.upper()+'_TURNAROUND')
        elif prev<=0 and now<=0:
            # Do not score undefined negative-denominator growth.
            flags.append(field.upper()+'_NEGATIVE_BASE_UNSCORED')
    return scores,flags

def combine(snapshot,growth):
    base=evaluate(snapshot)
    scores,flags=score_growth(growth,snapshot)
    # Recover exact available base submetric weights from the original evaluator's metrics.
    metrics=base['metrics']; parts=[('operating_margin_pct',15,-5,20,False),('roa_pct',10,-3,10,False),('debt_to_equity_pct',10,50,300,True),('equity_ratio_pct',10,10,70,False)]
    earned=0.0;possible=0
    for key,weight,low,high,invert in parts:
        if key not in metrics:continue
        val=scale(metrics[key],low,high)
        if invert:val=round(100-val,2)
        earned+=weight*val/100;possible+=weight
    for key,weight in GROWTH_WEIGHTS.items():
        if key in scores:earned+=weight*scores[key]/100;possible+=weight
    grade_score=round(earned/possible*100,2) if possible else None
    grade=('A' if grade_score>=80 else 'B' if grade_score>=65 else 'C') if grade_score is not None else 'UNRATED'
    # Finance-sector industry handling needs classification data not in snapshots.
    return {**base,'provisional_score':grade_score,'provisional_grade':grade,'coverage_pct':possible,
            'growth_metrics':(growth or {}).get('metrics',{}) if isinstance(growth,dict) else {},
            'growth_subscores':scores,'growth_flags':flags,
            'missing_categories':','.join(k for k,available in [('growth',bool(scores)),('profitability',any(k in metrics for k in ('operating_margin_pct','roa_pct'))),('stability',any(k in metrics for k in ('debt_to_equity_pct','equity_ratio_pct'))),('valuation',False),('cashflow',False)] if not available),
            'grade_status':'PROVISIONAL' if possible else 'UNRATED','buy_signal':'NOT_EVALUATED'}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--financial',default='v5_state/financial_latest.json')
    p.add_argument('--growth',default='v5_growth_output/growth_comparatives.json')
    p.add_argument('--output',default='v5_integrated_output')
    a=p.parse_args()
    financial=json.loads(Path(a.financial).read_text(encoding='utf-8'))
    growth=json.loads(Path(a.growth).read_text(encoding='utf-8'))
    if not isinstance(financial,dict) or not financial or not isinstance(growth,dict):raise SystemExit('Invalid input data')
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    rows=[combine({**v,'ISU_CD':code},growth.get(code)) for code,v in sorted(financial.items()) if isinstance(v,dict)]
    columns=['ISU_CD','ISU_NM','period','statement_type','provisional_score','provisional_grade','coverage_pct','grade_status','missing_categories','buy_signal','metrics','growth_metrics','growth_subscores','growth_flags','notes']
    def export(path,subset):
        with path.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=columns);w.writeheader()
            for r in subset:w.writerow({k:json.dumps(r[k],ensure_ascii=False) if isinstance(r.get(k),(dict,list)) else r.get(k,'') for k in columns})
    export(out/'all_integrated_scores.csv',rows)
    export(out/'ab_provisional_watchlist.csv',[r for r in rows if r['provisional_grade'] in ('A','B')])
    summary={'asof_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),'financial_count':len(rows),
             'growth_record_count':len(growth),'growth_matched':sum('GROWTH_RECORD_MISSING' not in r['growth_flags'] and 'GROWTH_IDENTITY_MISMATCH' not in r['growth_flags'] for r in rows),
             'growth_scored':sum(bool(r['growth_subscores']) for r in rows),
             'A':sum(r['provisional_grade']=='A' for r in rows),'B':sum(r['provisional_grade']=='B' for r in rows),
             'coverage_max_pct':75,'caution':'Provisional, not investment advice; valuation and cash flow unavailable. Financial sector not yet separately modeled.'}
    (out/'integrated_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
