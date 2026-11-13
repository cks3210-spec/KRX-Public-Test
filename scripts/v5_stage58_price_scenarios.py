#!/usr/bin/env python3
"""Stage58: illustrative price-sensitivity engine, NOT a verified fair-value/buy signal.
Reuses frozen Stage54/56 evidence. No external requests or changes to prior stages.
"""
import csv
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'stage56_input' / 'provisional_ab_318_evidence_audit.csv'
OUT = ROOT / 'stage58_output'
PE_MULTIPLES = ('8', '12', '16')
PB_MULTIPLES = ('0.8', '1.0', '1.2')

def dec(value):
    try:
        n = Decimal(str(value).strip().replace(',', ''))
        return n if n.is_finite() else None
    except (InvalidOperation, ValueError):
        return None

def money(n):
    return str(n.quantize(Decimal('1'), rounding=ROUND_HALF_UP)) if n is not None else ''

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    status = {'stage': 58, 'mode': 'ILLUSTRATIVE_SENSITIVITY_ONLY',
              'generated_utc': datetime.now(timezone.utc).isoformat(),
              'verified_fair_values': 0, 'actionable_buy_signals': 0,
              'scenario_pe_multiples': PE_MULTIPLES, 'scenario_pb_multiples': PB_MULTIPLES,
              'warnings': [
                  'Illustrative assumptions only: multiples are not sector-calibrated fair value.',
                  'FY2025 net income/equity may not be owner-attributable; share class unverified.',
                  'Implied share count from market cap / close is not official shares outstanding.',
                  'No verified PER/PBR, no final grade and no executable buy-price recommendation.'
              ]}
    try:
        with SOURCE.open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
        if len(rows) != 318 or {r.get('BAS_DD') for r in rows} != {'20261106'}:
            raise ValueError('Frozen cohort size or date mismatch')
        seen = set()
        result = []
        for r in rows:
            code = r.get('ISU_CD', '').strip()
            market = r.get('MARKET', '').strip()
            key = (market, code)
            if key in seen:
                raise ValueError(f'Duplicate security: {key}')
            seen.add(key)
            cap, close, profit, equity = (dec(r.get(k)) for k in ('MKTCAP', 'TDD_CLSPRC', 'net_income', 'total_equity'))
            valid_market = cap is not None and cap > 0 and close is not None and close > 0
            shares = cap / close if valid_market else None
            eps = profit / shares if shares is not None and profit is not None and profit > 0 else None
            bps = equity / shares if shares is not None and equity is not None and equity > 0 else None
            flags = ['UNVERIFIED_SHARECLASS', 'UNVERIFIED_OWNER_ATTRIBUTABLE_FIGURES', 'STALE_FY2025_VS_20261106', 'MULTIPLES_HYPOTHETICAL']
            if r.get('financial_statement_type') == 'OFS':
                flags.append('SEPARATE_FINANCIAL_STATEMENT')
            if eps is None: flags.append('POSITIVE_EPS_NOT_AVAILABLE')
            if bps is None: flags.append('POSITIVE_BPS_NOT_AVAILABLE')
            item = {'BAS_DD': r.get('BAS_DD',''), 'MARKET': market, 'ISU_CD': code,
                    'ISU_NM': r.get('ISU_NM',''), 'reference_close': r.get('TDD_CLSPRC',''),
                    'financial_period': r.get('financial_period',''),
                    'financial_statement_type': r.get('financial_statement_type',''),
                    'reference_eps_implied': money(eps), 'reference_bps_implied': money(bps)}
            for m in PE_MULTIPLES:
                item[f'illustrative_pe_{m}_price'] = money(eps * Decimal(m)) if eps is not None else ''
            for m in PB_MULTIPLES:
                item[f'illustrative_pb_{m}_price'] = money(bps * Decimal(m)) if bps is not None else ''
            item.update({'scenario_only': 'YES', 'verified_fair_price': '', 'buy_price': '',
                         'final_grade': 'WITHHELD', 'buy_signal': 'NONE', 'review_flags': ';'.join(flags)})
            result.append(item)
        with (OUT / 'price_sensitivity_scenarios.csv').open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(result[0]))
            writer.writeheader()
            writer.writerows(result)
        status.update({'candidate_count': len(result), 'market_date': '20261106',
                       'positive_eps_scenarios': sum(bool(r['reference_eps_implied']) for r in result),
                       'positive_bps_scenarios': sum(bool(r['reference_bps_implied']) for r in result)})
    except Exception as exc:
        status['error'] = str(exc)
    (OUT / 'status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(status, ensure_ascii=False, indent=2))
    if 'error' in status:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
