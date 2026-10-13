#!/usr/bin/env python3
"""Read-only market archive -> candidate follow-up rows. No inferred prices or advice."""
import csv
import gzip
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent / 'data' / 'daily_70d.csv.gz'
CANDIDATES = ROOT / 'candidate_history.csv'
OUT = ROOT / 'trade_followup.csv'
HORIZONS = (5, 10, 20)
FIELDS = ['recommendation_id','evaluation_date','horizon_trading_days','entry_reference',
          'exit_close','raw_return_pct','market_return_pct','excess_return_pp',
          'max_drawdown_pct','trade_cost_pct','verified_source','status']

def number(value):
    try:
        n = float(str(value).replace(',', '').strip())
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None

def main():
    if not DATA.is_file() or not CANDIDATES.is_file():
        raise SystemExit('Missing data/daily_70d.csv.gz or trade_validation/candidate_history.csv')
    price = defaultdict(dict)
    dates = set()
    with gzip.open(DATA, 'rt', encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            d, code = r.get('BAS_DD', '').strip(), r.get('ISU_CD', '').strip().zfill(6)
            p = number(r.get('TDD_CLSPRC'))
            if len(d) != 8 or not d.isdigit():
                continue
            dates.add(d)
            if p is not None:
                price[code][d] = p
    days = sorted(dates)
    if not days:
        raise SystemExit('No valid trading days; output not changed')
    with CANDIDATES.open(encoding='utf-8-sig', newline='') as f:
        candidates = list(csv.DictReader(f))
    output = []
    seen = set()
    for c in candidates:
        day = c.get('snapshot_date', '').strip()
        code = c.get('stock_code', '').strip().zfill(6)
        if not day or not code or (day, code) in seen:
            continue
        seen.add((day, code))
        # Reference must be verified against same-day archive price.
        ref = number(c.get('close'))
        archive_ref = price[code].get(day)
        ref_ok = ref is not None and archive_ref is not None and abs(ref - archive_ref) < 0.0001
        # Trading-day index counts market sessions, not calendar days.
        start = days.index(day) if day in dates else None
        for h in HORIZONS:
            row = dict.fromkeys(FIELDS, '')
            row['recommendation_id'] = c.get('record_id', f'{day}-{code}')
            row['horizon_trading_days'] = str(h)
            row['verified_source'] = 'data/daily_70d.csv.gz'
            if not ref_ok or start is None:
                row['status'] = 'UNVERIFIED_ENTRY'
            elif start + h >= len(days):
                row['entry_reference'] = str(int(ref) if ref.is_integer() else ref)
                row['status'] = 'PENDING'
            else:
                eval_day = days[start + h]
                row['evaluation_date'] = eval_day
                row['entry_reference'] = str(int(ref) if ref.is_integer() else ref)
                closes = [price[code].get(d) for d in days[start:start + h + 1]]
                if any(p is None for p in closes):
                    row['status'] = 'MISSING_PRICE'
                else:
                    exit_price = closes[-1]
                    row['exit_close'] = str(int(exit_price) if exit_price.is_integer() else exit_price)
                    row['raw_return_pct'] = f'{(exit_price / ref - 1) * 100:.4f}'
                    # Drawdown is measured from entry and subsequent observed peaks.
                    peak, worst = ref, 0.0
                    for p in closes[1:]:
                        peak = max(peak, p)
                        worst = min(worst, (p / peak - 1) * 100)
                    row['max_drawdown_pct'] = f'{worst:.4f}'
                    row['status'] = 'VERIFIED'
            output.append(row)
    with OUT.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(output)
    stats = {s: sum(r['status'] == s for r in output) for s in sorted(set(r['status'] for r in output))}
    print(f'Latest archive day: {days[-1]}; unique candidates: {len(seen)}; followup rows: {len(output)}; status: {stats}')
    print('Market benchmark, excess returns, trading costs intentionally blank until verified sources are provided.')

if __name__ == '__main__':
    main()
