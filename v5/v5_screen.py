#!/usr/bin/env python3
"""KRX v5 phase-1: independent, fail-closed screening. Python standard library only."""
import argparse, csv, json
from pathlib import Path

CAP_MIN = 100_000_000_000

def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def num(v):
    try:
        return float(v) if v not in (None, '', 'nan', 'NaN') else None
    except (ValueError, TypeError):
        return None

def analyze(latest, fundamentals, indicators):
    f_by = {r['ISU_CD']: r for r in fundamentals}
    i_by = {r['ISU_CD']: r for r in indicators}
    out = []
    for p in latest:
        cap = num(p.get('MKTCAP'))
        if cap is None or cap < CAP_MIN:
            continue
        code = p['ISU_CD']; f = f_by.get(code); tech = i_by.get(code, {})
        missing = []
        fields = ('revenue_yoy_pct', 'operating_profit_yoy_pct', 'debt_ratio_pct', 'per_annual_est', 'pbr_yearend_est', 'roe_avg_equity_est_pct')
        if f is None:
            missing = list(fields)
            status = 'FINANCIAL_NOT_COLLECTED'
        else:
            missing = [k for k in fields if num(f.get(k)) is None]
            status = 'FINANCIAL_PARTIAL' if missing else 'FINANCIAL_ANNUAL_AVAILABLE'
        # Phase 1 does not award A/B grades: annual figures alone are insufficient
        # to validate latest earnings, industry comparability and valuation.
        out.append({
            'BAS_DD': p.get('BAS_DD', ''), 'ISU_CD': code,
            'ISU_NM': p.get('ISU_NM', ''), 'MARKET': p.get('MARKET', ''),
            'TDD_CLSPRC': p.get('TDD_CLSPRC', ''), 'MKTCAP': p.get('MKTCAP', ''),
            'RETURN_20D_PCT': tech.get('RETURN_20D_PCT', ''),
            'VOLUME_RATIO': tech.get('VOLUME_RATIO', ''),
            'MA5': tech.get('MA5', ''), 'MA10': tech.get('MA10', ''),
            'revenue_yoy_pct': f.get('revenue_yoy_pct', '') if f else '',
            'operating_profit_yoy_pct': f.get('operating_profit_yoy_pct', '') if f else '',
            'debt_ratio_pct': f.get('debt_ratio_pct', '') if f else '',
            'per_annual_est': f.get('per_annual_est', '') if f else '',
            'pbr_yearend_est': f.get('pbr_yearend_est', '') if f else '',
            'roe_avg_equity_est_pct': f.get('roe_avg_equity_est_pct', '') if f else '',
            'fiscal_year': f.get('fiscal_year', '') if f else '',
            'financial_status': status, 'missing_fields': ';'.join(missing),
            'investment_grade': 'UNVERIFIED', 'investment_action': 'HOLD_FOR_VALIDATION'
        })
    return out

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', default='data')
    parser.add_argument('--out-dir', default='v5_output')
    args = parser.parse_args()
    data = Path(args.data_dir); dest = Path(args.out_dir)
    rows = analyze(read_csv(data/'latest.csv'), read_csv(data/'fundamentals.csv'), read_csv(data/'daily_indicators.csv'))
    dest.mkdir(parents=True, exist_ok=True)
    with (dest/'v5_universe.csv').open('w', encoding='utf-8-sig', newline='') as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    counts = {status: sum(r['financial_status'] == status for r in rows) for status in ('FINANCIAL_NOT_COLLECTED', 'FINANCIAL_PARTIAL', 'FINANCIAL_ANNUAL_AVAILABLE')}
    summary = {'asof': sorted(set(r['BAS_DD'] for r in rows)), 'market_cap_min_krw': CAP_MIN,
               'universe_count': len(rows), 'financial_coverage': counts,
               'recommended_count': 0, 'phase': 'data_coverage_only',
               'warnings': ['No A/B ratings before current filings, valuation and sector checks', 'No changes to existing v4 files or automation']}
    (dest/'v5_status.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == '__main__': main()
