#!/usr/bin/env python3
"""KRX daily discovery v2: reproducible daily snapshots and actual new-entry comparison.
Run: python scripts/build_daily_discovery_v2.py
Requires existing data/summary.json, latest.csv, daily_indicators.csv.
Optional: data/research_candidates.csv with code/name and verified financial fields.
Technical watchlist is NOT an A/B investment grade or buy recommendation.
"""
import csv, json, pathlib, datetime
ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
ARCHIVE = DATA / 'daily_discovery_archive'

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def num(v):
    try: return float(v)
    except (ValueError, TypeError): return 0.0

def main():
    summary=json.loads((DATA/'summary.json').read_text(encoding='utf-8'))
    day=str(summary['latest_trading_date'])
    datetime.datetime.strptime(day,'%Y%m%d')
    latest=read_csv(DATA/'latest.csv')
    indicators=read_csv(DATA/'daily_indicators.csv')
    if not latest or not indicators: raise RuntimeError('Empty inputs')
    if any(x.get('BAS_DD') != day for x in indicators):
        raise RuntimeError('Indicators date inconsistent with summary')
    market={x['ISU_CD']:x for x in latest if x.get('BAS_DD')==day}
    if not market: raise RuntimeError('Latest market data date inconsistent with summary')
    ARCHIVE.mkdir(parents=True,exist_ok=True)
    snapshots=sorted(p for p in ARCHIVE.glob('*.json') if p.stem.isdigit() and len(p.stem)==8 and p.stem<day)
    prev=json.loads(snapshots[-1].read_text(encoding='utf-8')) if snapshots else None
    prev_codes=set(prev['candidate_codes']) if prev else set()
    result=[]
    for row in indicators:
        code=row.get('ISU_CD',''); m=market.get(code)
        if not m or num(m.get('MKTCAP'))<100_000_000_000: continue
        name=m.get('ISU_NM','')
        if '스팩' in name or 'SPAC' in name.upper(): continue
        if row.get('UPTREND','').lower()!='true': continue
        ma5,ma10,ma20=(num(row.get(k)) for k in ('MA5','MA10','MA20'))
        close=num(m.get('TDD_CLSPRC'))
        if min(ma5,ma10,ma20,close)<=0 or not ma5>=ma10>=ma20: continue
        ratio=num(row.get('VOLUME_RATIO')); ret=num(row.get('RETURN_20D_PCT'))
        score=round(min(max(ratio,0),5)*12+max(0,min(ret,20))*1.2+(12 if close>=ma5 else 0),2)
        result.append(dict(code=code,name=name,market=m.get('MARKET'),close=int(close),
            market_cap=int(num(m.get('MKTCAP'))),volume_ratio=ratio,return_20d_pct=ret,
            signal_score=score,change_type=('NEW' if code not in prev_codes else 'CONTINUING') if prev else 'BASELINE'))
    result.sort(key=lambda x:(-x['signal_score'],x['code']))
    codes={r['code'] for r in result}
    new=[r for r in result if r['change_type']=='NEW']
    exited=sorted(prev_codes-codes) if prev else []
    output=dict(trading_date=day,previous_date=prev['trading_date'] if prev else None,
      generated_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
      classification='TECHNICAL_WATCHLIST_NOT_AB_GRADE_OR_BUY_RECOMMENDATION',
      source=['data/summary.json','data/latest.csv','data/daily_indicators.csv'],
      screened_market_rows=len(market),eligible_count=len(result),new_count=len(new) if prev else None,
      exited_count=len(exited) if prev else None,exited_codes=exited,
      candidate_codes=sorted(codes),new_entries=new,top_20=result[:20],
      note='No final financial A/B grade, fair value, or buy recommendation is asserted.')
    snapshot=ARCHIVE/(day+'.json')
    # Same-day reruns update the same dated snapshot, never overwrite the previous day.
    snapshot.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (DATA/'daily_discovery.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'trading_date':day,'eligible_count':len(result),'new_count':output['new_count'],
      'previous_date':output['previous_date'],'top_5':result[:5]},ensure_ascii=False))
if __name__=='__main__':main()
