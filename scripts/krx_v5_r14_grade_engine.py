#!/usr/bin/env python3
"""R14 independent, read-only grading prototype. Never writes to repository data."""
import argparse, csv, json, math, pathlib

MIN_CAP=100_000_000_000
def num(x):
    try:
        if x is None or str(x).strip()=='' : return None
        n=float(str(x).replace(',',''))
        return n if math.isfinite(n) else None
    except (ValueError,TypeError): return None

def grade(fin,market):
    """No grade unless all essential financial and market inputs are verified."""
    cap=num(market.get('market_cap_krw'))
    p=num(fin.get('annual_profit')); t=num(fin.get('ttm_profit'))
    eq=num(fin.get('equity')); prev=num(fin.get('prior_equity'))
    assets=num(market.get('assets_krw')); liabilities=num(market.get('liabilities_krw'))
    if cap is None or cap<MIN_CAP:return None,'MARKET_CAP_MISSING_OR_BELOW_100B'
    if fin.get('source')!='OpenDART fnlttSinglAcntAll':return None,'UNVERIFIED_FINANCIALS'
    if fin.get('ttm_status')!='VERIFIED_CUMULATIVE':return None,'TTM_UNVERIFIED'
    if None in (p,t,eq,prev) or eq<=0 or prev<=0:return None,'INSUFFICIENT_EQUITY_OR_PROFIT'
    if assets is None or liabilities is None or assets<=0 or liabilities<0:
        return None,'BALANCE_SHEET_NOT_VERIFIED'
    if p<=0 or t<=0:return None,'NON_POSITIVE_EARNINGS'
    roe=100*p/((eq+prev)/2)
    debt=100*liabilities/eq
    per=cap/t; pbr=cap/eq
    # Preliminary, transparent thresholds; not a buy recommendation.
    score=(25 if roe>=12 else 15 if roe>=8 else 0)
    score+=(25 if debt<=80 else 15 if debt<=150 else 0)
    score+=(25 if t>=p else 15 if t>=p*.85 else 0)
    score+=(25 if per<=12 and pbr<=1.5 else 15 if per<=20 and pbr<=3 else 0)
    result='A' if score>=85 else 'B' if score>=65 else None
    return ({'grade':result,'score':score,'roe_pct':round(roe,2),
             'debt_pct':round(debt,2),'ttm_per_est':round(per,2),
             'pbr_est':round(pbr,2),'ttm_to_annual':round(t/p,3),
             'valuation_basis':'derived, NOT official KRX PER/PBR',
             'buy_signal':False} if result else None), ('CANDIDATE' if result else 'BELOW_B')

def self_test():
    f={'source':'OpenDART fnlttSinglAcntAll','ttm_status':'VERIFIED_CUMULATIVE',
       'annual_profit':'150','ttm_profit':'180','equity':'1000','prior_equity':'900'}
    m={'market_cap_krw':'1500','assets_krw':'2000','liabilities_krw':'500'}
    assert grade(f,m)[1]=='MARKET_CAP_MISSING_OR_BELOW_100B'
    scale=1_000_000_000
    f.update({k:str(int(float(f[k])*scale)) for k in ('annual_profit','ttm_profit','equity','prior_equity')})
    m.update({k:str(int(float(m[k])*scale)) for k in ('market_cap_krw','assets_krw','liabilities_krw')})
    assert grade(f,m)[0]['grade']=='A'
    assert grade({**f,'ttm_status':'MISSING_QUARTER'},m)[0] is None
    assert grade({**f,'equity':'-1'},m)[0] is None
    assert grade({**f,'ttm_profit':'-1'},m)[0] is None
    assert grade(f,{**m,'assets_krw':''})[0] is None
    return 6

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--financial',help='R14 annual_financial_index_m.csv')
    ap.add_argument('--market',help='explicitly normalized market CSV: code,market_cap_krw,assets_krw,liabilities_krw')
    ap.add_argument('--output',help='optional output path, outside repository data recommended')
    a=ap.parse_args()
    count=self_test()
    if not a.financial or not a.market:
        print(json.dumps({'result':'SELF_TEST_PASS','tests':count,'note':'no market data assumed; no grades issued'}))
        return
    with open(a.financial,encoding='utf-8-sig',newline='') as f: fins=list(csv.DictReader(f))
    with open(a.market,encoding='utf-8-sig',newline='') as f:
        mr=csv.DictReader(f)
        required={'code','market_cap_krw','assets_krw','liabilities_krw'}
        if not required.issubset(mr.fieldnames or []):raise SystemExit('MISSING_EXPLICIT_MARKET_COLUMNS')
        markets={r['code'].zfill(6):r for r in mr}
    candidates=[];excluded={}
    for f in fins:
        code=f.get('code','').zfill(6)
        result,reason=grade(f,markets.get(code,{}))
        if result:candidates.append({'code':code,**result})
        else:excluded[reason]=excluded.get(reason,0)+1
    report={'result':'PRELIMINARY_RESEARCH_ONLY','self_tests':count,'financial_rows':len(fins),
            'market_rows':len(markets),'candidates':candidates,'excluded_by_reason':excluded,
            'limitations':['No preferred-share verification in this prototype',
                           'Growth proxy is TTM vs prior annual, not YoY TTM growth',
                           'PER/PBR derived, not official KRX values',
                           'No fair buy price or buy recommendation']}
    text=json.dumps(report,ensure_ascii=False,indent=2)
    if a.output:pathlib.Path(a.output).write_text(text,encoding='utf-8')
    else:print(text)
if __name__=='__main__':main()
