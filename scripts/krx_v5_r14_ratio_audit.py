#!/usr/bin/env python3
"""Read-only R14 ratio provenance/ROE audit. Never treats estimated PER/PBR as official."""
import argparse,csv,json,math,pathlib,collections

def number(v):
    try:
        if v is None or str(v).strip()=="":return None
        n=float(str(v).replace(',',''))
        return n if math.isfinite(n) else None
    except (TypeError,ValueError):return None

def rows(path):
    with open(path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def audit(financial,market=None):
    fin=rows(financial); bycode={}; issues=collections.Counter(); calculated=0; matched=0
    for r in fin:
        code=str(r.get('code','')).zfill(6)
        if code in bycode:issues['duplicate_financial_code']+=1
        bycode[code]=r
        p,e,prev=map(number,(r.get('annual_profit'),r.get('equity'),r.get('prior_equity')))
        stored=number(r.get('annual_roe_pct'))
        if p is None or e is None or prev is None or e<=0 or prev<=0:
            issues['roe_inputs_missing_or_invalid']+=1
            continue
        calculated+=1; computed=100*p/((e+prev)/2)
        if stored is None:issues['roe_stored_missing']+=1
        elif abs(stored-computed)<=0.011:matched+=1
        else:issues['roe_mismatch']+=1
    report={'result':'AUDIT_COMPLETE','financial_rows':len(fin),'roe_recomputed':calculated,'roe_matched':matched,'issues':dict(issues),'official_per_verified':0,'official_pbr_verified':0,'final_buy_signals':0,'note':'No official ratio verified without explicit official KRX values and matching as-of dates; no investment grade issued.'}
    if market:
        m=rows(market);report['market_rows']=len(m);report['market_columns']=list(m[0]) if m else []
        report['market_financial_code_matches']=sum(str(r.get('code','')).zfill(6) in bycode for r in m)
        report['market_cap_columns_present']=[k for k in report['market_columns'] if any(s in k.lower() for s in ('cap','market_value','시가총액'))]
        report['official_ratio_columns_present']=[k for k in report['market_columns'] if 'official' in k.lower() and ('per' in k.lower() or 'pbr' in k.lower())]
    return report

def selftest():
    assert number('1,234')==1234 and number('') is None
    assert number('nan') is None and number('bad') is None
    assert round(100*10/((100+100)/2),2)==10
    return 4

def main():
    p=argparse.ArgumentParser();p.add_argument('--financial');p.add_argument('--market');p.add_argument('--output');a=p.parse_args()
    tests=selftest()
    if not a.financial:print(json.dumps({'result':'SELF_TEST_PASS','tests':tests}));return
    report=audit(a.financial,a.market);report['self_tests']=tests
    out=json.dumps(report,ensure_ascii=False,indent=2)
    if a.output:pathlib.Path(a.output).write_text(out,encoding='utf-8')
    print(out)
    if report['issues'].get('roe_mismatch') or report['issues'].get('duplicate_financial_code'):raise SystemExit(1)
if __name__=='__main__':main()
