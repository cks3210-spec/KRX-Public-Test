#!/usr/bin/env python3
"""KRX daily technical discovery from existing repository CSVs.
Run from repository root: python scripts/build_daily_discovery.py
No financial A/B grade or buy recommendation is invented.
"""
import csv, json, pathlib
from datetime import datetime, timezone
ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def num(value):
    try: return float(value)
    except (ValueError, TypeError): return 0.0

def main():
    summary = json.loads((DATA/'summary.json').read_text(encoding='utf-8'))
    date = str(summary['latest_trading_date'])
    market_rows = read_csv(DATA/'latest.csv')
    indicators = read_csv(DATA/'daily_indicators.csv')
    if len(date)!=8 or not market_rows or not indicators:
        raise RuntimeError('Invalid or empty market inputs')
    if any(r.get('BAS_DD')!=date for r in indicators):
        raise RuntimeError('Indicators and summary dates disagree')
    market = {r['ISU_CD']:r for r in market_rows if r.get('BAS_DD')==date}
    if not market: raise RuntimeError('Market and summary dates disagree')
    output = DATA/'daily_discovery.json'
    old = json.loads(output.read_text(encoding='utf-8')) if output.exists() else {}
    prior_codes = set(old.get('candidate_codes',[])) if old.get('trading_date') != date else set()
    found=[]
    for row in indicators:
        code=row.get('ISU_CD','')
        m=market.get(code)
        if not m or num(m.get('MKTCAP'))<100_000_000_000: continue
        name=m.get('ISU_NM','')
        if '스팩' in name or 'SPAC' in name.upper(): continue
        if row.get('UPTREND','').lower()!='true': continue
        ma5,ma10,ma20=(num(row.get(k)) for k in ('MA5','MA10','MA20'))
        price=num(m.get('TDD_CLSPRC'))
        if min(ma5,ma10,ma20,price)<=0 or not (ma5>=ma10>=ma20): continue
        ratio=num(row.get('VOLUME_RATIO'))
        ret=num(row.get('RETURN_20D_PCT'))
        score=round(min(ratio,5)*12+max(0,min(ret,20))*1.2+(12 if price>=ma5 else 0),2)
        found.append(dict(code=code,name=name,market=m.get('MARKET'),close=int(price),
            market_cap=int(num(m.get('MKTCAP'))),volume_ratio=ratio,
            return_20d_pct=ret,signal_score=score,
            new_vs_previous=(code not in prior_codes) if prior_codes else None))
    found.sort(key=lambda r:(-r['signal_score'],r['code']))
    result=dict(trading_date=date,generated_at_utc=datetime.now(timezone.utc).isoformat(),
        source=['data/summary.json','data/latest.csv','data/daily_indicators.csv'],
        classification='TECHNICAL_WATCHLIST_NOT_AB_GRADE_OR_BUY_RECOMMENDATION',
        previous_date=old.get('trading_date') if prior_codes else None,
        screened_market_rows=len(market),eligible_count=len(found),
        candidate_codes=[r['code'] for r in found],top_20=found[:20])
    if old.get('trading_date')==date:
        result['previous_date']=old.get('previous_date')
        prev={r['code']:r.get('new_vs_previous') for r in old.get('top_20',[])}
        for r in result['top_20']:r['new_vs_previous']=prev.get(r['code'])
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(date=date,eligible_count=len(found),top_5=found[:5]),ensure_ascii=False))

if __name__=='__main__': main()
