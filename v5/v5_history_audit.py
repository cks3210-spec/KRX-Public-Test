#!/usr/bin/env python3
"""Read-only arithmetic and identity audit of v5 historical financial diagnostics.
Does not certify accounting classification or create investment grades.
"""
import argparse,csv,json,math
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

def number(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def audit(code,s,h):
    flags=[]
    identity=[str(s.get('fiscal_year')),s.get('report_code'),s.get('statement_type'),s.get('verified_at_utc')]
    if h.get('identity')!=identity:flags.append('IDENTITY_MISMATCH')
    if h.get('status') not in ('COMPLETE','PARTIAL'):flags.append('NOT_VERIFIED')
    fy=s.get('report_code')=='11011'
    if s.get('statement_type') not in ('CFS','OFS'):flags.append('STATEMENT_UNKNOWN')
    def check(result,parts,label):
        if not number(result):return
        if not all(number(x) for x in parts):flags.append(label+'_INPUT_MISSING');return
        expected=parts[0] if fy else parts[0]+parts[1]-parts[2]
        if abs(result-expected)>max(1,abs(expected)*1e-10):flags.append(label+'_ARITHMETIC_MISMATCH')
    check(h.get('ttm_net_income_krw'),[h.get('current_ytd_net_income_krw')] if fy else [h.get('prior_fy_net_income_krw'),h.get('current_ytd_net_income_krw'),h.get('previous_ytd_net_income_krw')],'NET_INCOME')
    check(h.get('cfo_ttm_krw'),[h.get('current_ytd_cfo_krw')] if fy else [h.get('prior_fy_cfo_krw'),h.get('current_ytd_cfo_krw'),h.get('previous_ytd_cfo_krw')],'CFO')
    if not fy and h.get('cfo_source_basis') not in ('CF_YTD_amount','CF_YTD_add_amount'):flags.append('CFO_BASIS_UNCONFIRMED')
    eq0,eq1=h.get('equity_start_krw'),h.get('equity_end_krw')
    roe=h.get('roe_ttm_pct_diagnostic');ni=h.get('ttm_net_income_krw')
    if number(roe):
        if not (number(eq0) and number(eq1) and eq0>0 and eq1>0 and number(ni)):flags.append('ROE_INPUT_MISSING')
        elif abs(roe-100*ni/((eq0+eq1)/2))>0.002:flags.append('ROE_ARITHMETIC_MISMATCH')
    if number(eq0) and eq0<=0 or number(eq1) and eq1<=0:flags.append('NONPOSITIVE_EQUITY')
    # Existing ROE uses prior FY equity, not the equity exactly 12 months earlier.
    # It must NOT be represented as verified TTM ROE until accounting basis is reconciled.
    flags.append('ROE_PERIOD_ALIGNMENT_NOT_VERIFIED')
    flags.append('ATTRIBUTABLE_EARNINGS_EQUITY_NOT_VERIFIED')
    flags.append('RESTATEMENT_NOT_VERIFIED')
    flags.append('INDUSTRY_RULES_NOT_VERIFIED')
    return {'ISU_CD':code,'ISU_NM':s.get('ISU_NM',''),'period':s.get('period',''),
            'statement_type':s.get('statement_type',''),'ttm_net_income_krw':ni,
            'cfo_ttm_krw':h.get('cfo_ttm_krw'),'roe_diagnostic_pct':roe,
            'identity_matched':'IDENTITY_MISMATCH' not in flags,
            'arithmetic_ok':not any('ARITHMETIC_MISMATCH' in f or 'INPUT_MISSING' in f for f in flags),
            'flags':';'.join(flags),'investment_grade':'NOT_SCORED'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--financial',default='v5_state/financial_latest.json');p.add_argument('--history',default='v5_history_output/history_metrics.json');p.add_argument('--output',default='v5_history_audit_output');a=p.parse_args()
    fin=json.loads(Path(a.financial).read_text(encoding='utf-8'));hist=json.loads(Path(a.history).read_text(encoding='utf-8'))
    if not isinstance(fin,dict) or not isinstance(hist,dict):raise SystemExit('Invalid input')
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    rows=[audit(code,fin[code],h) for code,h in sorted(hist.items()) if code in fin and isinstance(h,dict) and isinstance(fin[code],dict)]
    with (out/'history_audit.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['ISU_CD','ISU_NM','period','statement_type','ttm_net_income_krw','cfo_ttm_krw','roe_diagnostic_pct','identity_matched','arithmetic_ok','flags','investment_grade'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    reasons=Counter(f for r in rows for f in r['flags'].split(';') if f)
    summary={'audited_at_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),'financial_count':len(fin),'history_count':len(hist),'audited_count':len(rows),'identity_matched':sum(r['identity_matched'] for r in rows),'arithmetic_ok':sum(r['arithmetic_ok'] for r in rows),'ttm_net_income_available':sum(number(r['ttm_net_income_krw']) for r in rows),'cfo_ttm_available':sum(number(r['cfo_ttm_krw']) for r in rows),'roe_diagnostic_available':sum(number(r['roe_diagnostic_pct']) for r in rows),'flag_counts':dict(reasons),'conclusion':'Arithmetic and snapshot identity diagnostics only; NOT independently validated against filings. ROE period and attributable ownership remain unverified; no investment grades.'}
    (out/'history_audit_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
