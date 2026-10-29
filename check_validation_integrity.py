#!/usr/bin/env python3
"""Read-only integrity checks for KRX trade validation outputs.
Run from repository root: python tools/check_validation_integrity.py
"""
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / 'trade_validation/candidate_history.csv'
FOLLOWUP = ROOT / 'trade_validation/trade_followup.csv'
SUMMARY = ROOT / 'data/summary.json'
HORIZONS = {'5', '10', '20'}

def read(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def main():
    errors = []
    for path in (HISTORY, FOLLOWUP, SUMMARY):
        if not path.is_file(): errors.append(f'missing file: {path.relative_to(ROOT)}')
    if errors:
        raise SystemExit('\n'.join(errors))
    hist, follow = read(HISTORY), read(FOLLOWUP)
    summary = json.loads(SUMMARY.read_text(encoding='utf-8-sig'))
    date = str(summary.get('latest_trading_date', ''))
    if len(date) != 8 or not date.isdigit(): errors.append('invalid summary latest_trading_date')
    hids = [r.get('record_id', '') for r in hist]
    duplicates = [k for k,v in Counter(hids).items() if v>1]
    if duplicates: errors.append(f'duplicate history record_id: {len(duplicates)}')
    hk = [(r.get('snapshot_date',''),r.get('stock_code','')) for r in hist]
    if len(set(hk)) != len(hk): errors.append('duplicate history date/code')
    hset = set(hids)
    fkeys = [(r.get('recommendation_id',''),r.get('horizon_trading_days','')) for r in follow]
    if len(set(fkeys)) != len(fkeys): errors.append('duplicate followup id/horizon')
    orphan = [r for r in follow if r.get('recommendation_id','') not in hset]
    if orphan: errors.append(f'orphan followup rows: {len(orphan)}')
    wrong_horizon = [r for r in follow if r.get('horizon_trading_days','') not in HORIZONS]
    if wrong_horizon: errors.append(f'invalid horizons: {len(wrong_horizon)}')
    verified = [r for r in follow if r.get('status')=='VERIFIED']
    required = ('evaluation_date','entry_reference','exit_close','raw_return_pct')
    incomplete = [r for r in verified if any(r.get(k,'') == '' for k in required)]
    if incomplete: errors.append(f'incomplete VERIFIED: {len(incomplete)}')
    unverified_with_return = [r for r in follow if r.get('status') != 'VERIFIED' and r.get('raw_return_pct','') != '']
    if unverified_with_return: errors.append(f'non-VERIFIED rows with returns: {len(unverified_with_return)}')
    print(json.dumps({'latest_trading_date':date,'candidate_rows':len(hist),'followup_rows':len(follow),
        'verified_rows':len(verified),'status_counts':dict(Counter(r.get('status','') for r in follow)),
        'errors':errors},ensure_ascii=False,indent=2))
    if errors: raise SystemExit(1)

if __name__ == '__main__': main()
