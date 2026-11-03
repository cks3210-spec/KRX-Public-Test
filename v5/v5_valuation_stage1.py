#!/usr/bin/env python3
"""Conservative, separate valuation diagnostic. No edits to other screening pipelines."""
import argparse,csv,json,math
from datetime import datetime,timezone
from pathlib import Path

def num(v):
    try:
        if v is None or str(v).strip()=='':return None
        x=float(str(v).replace(',',''))
        return x if math.isfinite(x) else None
    except (ValueError,TypeError):return None

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--financial',default='v5_state/financial_latest.json')
    p.add_argument('--market',default='data/latest.csv')
    p.add_argument('--output',default='v5_valuation_output')
    a=p.parse_args()
    fin=json.loads(Path(a.financial).read_text(encoding='utf-8'))
    with open(a.market,encoding='utf-8-sig',newline='') as f: market={r['ISU_CD']:r for r in csv.DictReader(f)}
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for code,s in sorted(fin.items()):
        if not isinstance(s,dict):continue
        m=market.get(code,{})
        cap=num(m.get('MKTCAP'));price=num(m.get('TDD_CLSPRC'))
        equity=num(s.get('equity_krw')) if s.get('equity_status')=='OK' else None
        net=num(s.get('net_income_krw')) if s.get('net_income_status')=='OK' else None
        market_date=m.get('BAS_DD','')
        flags=[]
        if not m:flags.append('MARKET_ROW_MISSING')
        if not market_date:flags.append('MARKET_DATE_MISSING')
        if s.get('statement_type') not in ('CFS','OFS'):flags.append('FINANCIAL_STATEMENT_UNKNOWN')
        pbr=round(cap/equity,4) if cap and cap>0 and equity and equity>0 and market_date else None
        if pbr is None:flags.append('PBR_UNAVAILABLE')
        # FY is annual, while Q1/H1/Q3 net income may be a quarter or cumulative.
        # Never annualize a partial period by multiplying by 2 or 4.
        annual=s.get('report_code')=='11011'
        per=round(cap/net,4) if annual and cap and cap>0 and net and net>0 and market_date else None
        if per is None:flags.append('PER_NEEDS_POSITIVE_ANNUAL_NET_INCOME')
        # Proper ROE requires annual attributable earnings and comparable beginning/end equity.
        flags.append('ROE_NOT_CALCULATED_NEEDS_AVERAGE_EQUITY')
        rows.append({'ISU_CD':code,'ISU_NM':s.get('ISU_NM',''),'market_date':market_date,
          'financial_period':s.get('period',''),'statement_type':s.get('statement_type',''),
          'close_krw':price,'market_cap_krw':cap,'equity_krw':equity,
          'net_income_krw':net,'PBR_diagnostic':pbr,'PER_FY_diagnostic':per,
          'ROE':None,'flags':';'.join(flags),'valuation_grade':'NOT_SCORED'})
    fields=list(rows[0]) if rows else []
    with (out/'valuation_diagnostics.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    summary={'asof_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
       'financial_count':len(rows),'market_matched':sum(bool(r['market_date']) for r in rows),
       'pbr_calculated':sum(r['PBR_diagnostic'] is not None for r in rows),
       'per_annual_calculated':sum(r['PER_FY_diagnostic'] is not None for r in rows),
       'roe_calculated':0,'market_dates':sorted({r['market_date'] for r in rows if r['market_date']}),
       'caution':'Diagnostic only. PBR mixes market-date cap with latest filed book equity; PER only for positive FY net income. ROE requires average equity. No valuation score or investment grade yet. No modifications to v4/GC/v5 collector.'}
    (out/'valuation_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
