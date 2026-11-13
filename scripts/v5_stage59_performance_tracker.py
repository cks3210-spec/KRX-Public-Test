#!/usr/bin/env python3
"""Stage59: immutable cohort signal register and 5/10/20 trading-session follow-up.
No trading recommendation; missing sessions remain pending. No external dependencies.
"""
import csv, json, pathlib, datetime as dt, os
from decimal import Decimal, InvalidOperation
ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCE=ROOT/'stage56_input/provisional_ab_318_evidence_audit.csv'
OUT=ROOT/'stage59_output'
HISTORY=ROOT/'stage59_input'/'daily_prices.csv' # append-only external KRX verified daily rows
HORIZONS=(5,10,20)
def number(x):
    try:
        d=Decimal(str(x).strip().replace(',',''))
        return d if d.is_finite() and d>0 else None
    except (ValueError,InvalidOperation):return None
def read(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(p,records,fields):
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(records)
def main():
    OUT.mkdir(exist_ok=True)
    status={'stage':59,'generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'mode':'FROZEN_COHORT_FORWARD_TRACKING','warnings':[],'final_trade_signals':0}
    try:
        cohort=read(SOURCE)
        if len(cohort)!=318 or {r.get('BAS_DD') for r in cohort}!={'20261106'}:raise ValueError('Frozen 318 cohort/date mismatch')
        history=read(HISTORY) if HISTORY.exists() else []
        if not history:status['warnings'].append('No verified multi-day KRX price history supplied; horizons remain PENDING')
        prices={}; duplicates=0
        for r in history:
            date=r.get('BAS_DD','');market=r.get('MARKET','');code=r.get('ISU_CD','')
            if len(date)!=8 or not date.isdigit():continue
            price=number(r.get('TDD_CLSPRC'))
            if price is None:continue
            key=(market,code,date)
            if key in prices and prices[key]!=price:raise ValueError('Conflicting daily price for '+str(key))
            if key in prices:duplicates+=1
            prices[key]=price
        by_security={}
        for (market,code,date),price in prices.items():by_security.setdefault((market,code),[]).append((date,price))
        for rows in by_security.values():rows.sort()
        seen=set();out=[];counts={f'{h}d_completed':0 for h in HORIZONS}
        for r in cohort:
            market=r.get('MARKET','');code=r.get('ISU_CD','');base=r.get('BAS_DD','');key=(market,code)
            if key in seen:raise ValueError('Duplicate cohort security '+str(key))
            seen.add(key)
            entry=number(r.get('TDD_CLSPRC'))
            if entry is None:raise ValueError('Missing cohort close '+str(key))
            later=[(date,price) for date,price in by_security.get(key,[]) if date>base]
            row={'BAS_DD':base,'MARKET':market,'ISU_CD':code,'ISU_NM':r.get('ISU_NM',''),'entry_close':str(entry),'provisional_grade':r.get('provisional_grade',''),'final_grade':'WITHHELD','signal_type':'RESEARCH_COHORT_NOT_BUY_SIGNAL'}
            for h in HORIZONS:
                row[f'day_{h}_date']='';row[f'day_{h}_close']='';row[f'day_{h}_return_pct']='';row[f'day_{h}_status']='PENDING_VERIFIED_PRICE_HISTORY'
                if len(later)>=h:
                    day,close=later[h-1]
                    row[f'day_{h}_date']=day;row[f'day_{h}_close']=str(close)
                    row[f'day_{h}_return_pct']=str(round((close/entry-1)*100,3))
                    row[f'day_{h}_status']='OBSERVED_UNADJUSTED';counts[f'{h}d_completed']+=1
            out.append(row)
        fields=list(out[0]);write(OUT/'forward_returns.csv',out,fields)
        status.update({'candidate_count':len(out),'base_date':'20261106','history_rows':len(history),'unique_price_points':len(prices),'duplicate_identical_price_points':duplicates,'counts':counts,'source':'stage56_input/provisional_ab_318_evidence_audit.csv','history_source':str(HISTORY.relative_to(ROOT)) if HISTORY.exists() else 'NOT_PROVIDED'})
        status['warnings'].extend(['Trading-day horizons use each security\'s available verified daily closes; missing sessions, suspensions and delistings require manual handling.','Returns exclude dividends, splits, fees and taxes; corporate-action adjustment and official share-class verification remain pending.','No buy/sell signals or validated strategy backtest are produced.'])
    except Exception as exc:status['error']=str(exc)
    (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(status,ensure_ascii=False,indent=2))
    if 'error' in status:raise SystemExit(1)
if __name__=='__main__':main()
