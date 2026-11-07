#!/usr/bin/env python3
"""Stage56: audit 318 provisional candidates using existing financial evidence.
No network calls. Never labels calculated ratios as official KRX PER/PBR.
"""
import csv
import datetime as dt
import json
import pathlib
from decimal import Decimal, InvalidOperation

ROOT = pathlib.Path(__file__).resolve().parents[1]
INPUT = ROOT / 'stage56_input' / 'provisional_ab_318_evidence_audit.csv'
OUT = ROOT / 'stage56_output'


def decimal(row, field):
    try:
        value = Decimal(str(row.get(field, '')).strip().replace(',', ''))
        return value if value.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    status = {
        'stage': 56,
        'mode': 'EXISTING_EVIDENCE_VALUATION_AUDIT',
        'generated_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'official_krx_per_pbr_verified': False,
        'final_grades_released': 0,
        'buy_signals_released': 0,
        'warnings': [],
    }
    try:
        with INPUT.open('r', encoding='utf-8-sig', newline='') as stream:
            candidates = list(csv.DictReader(stream))
        if len(candidates) != 318:
            raise ValueError(f'Expected 318 candidates; got {len(candidates)}')
        dates = {r.get('BAS_DD', '') for r in candidates}
        if len(dates) != 1 or not next(iter(dates)).isdigit():
            raise ValueError('Invalid or mixed market dates')
        status['market_date'] = next(iter(dates))
        status['candidate_count'] = len(candidates)
        counts = {}
        results = []
        seen = set()
        for row in candidates:
            market = row.get('MARKET', '').upper()
            code = row.get('ISU_CD', '').strip()
            key = (market, code)
            if key in seen:
                raise ValueError(f'Duplicate security: {key}')
            seen.add(key)
            cap = decimal(row, 'MKTCAP')
            income = decimal(row, 'net_income')
            equity = decimal(row, 'total_equity')
            period = row.get('financial_period', '')
            statement = row.get('financial_statement_type', '')
            flags = []
            if cap is None or cap <= 0:
                flags.append('MARKET_CAP_MISSING_OR_INVALID')
            if income is None:
                flags.append('NET_INCOME_MISSING')
            elif income <= 0:
                flags.append('NONPOSITIVE_NET_INCOME_NO_MEANINGFUL_POSITIVE_PE')
            if equity is None or equity <= 0:
                flags.append('EQUITY_MISSING_OR_NONPOSITIVE')
            if statement not in ('CFS', 'OFS'):
                flags.append('STATEMENT_TYPE_UNRECOGNIZED')
            if statement == 'OFS':
                flags.append('SEPARATE_STATEMENT_NOT_COMPARABLE_TO_CFS')
            if period != '2025_FY':
                flags.append('UNEXPECTED_FINANCIAL_PERIOD')
            flags.append('FY2025_VS_20261106_DATE_MISMATCH')
            flags.append('NET_INCOME_EQUITY_MAY_INCLUDE_NONCONTROLLING_INTERESTS')
            flags.append('SHARE_CLASS_UNVERIFIED')
            pe = cap / income if cap is not None and cap > 0 and income is not None and income > 0 else None
            pb = cap / equity if cap is not None and cap > 0 and equity is not None and equity > 0 else None
            reason = 'PROVISIONAL_CALCULATED_NOT_OFFICIAL' if pe is not None and pb is not None else 'INCOMPLETE_OR_NOT_MEANINGFUL'
            counts[reason] = counts.get(reason, 0) + 1
            results.append({
                'BAS_DD': row.get('BAS_DD', ''),
                'ISU_CD': code,
                'ISU_NM': row.get('ISU_NM', ''),
                'MARKET': market,
                'financial_period': period,
                'financial_statement_type': statement,
                'net_income': row.get('net_income', ''),
                'total_equity': row.get('total_equity', ''),
                'MKTCAP': row.get('MKTCAP', ''),
                'calculated_marketcap_to_net_income': str(pe.quantize(Decimal('0.001'))) if pe is not None else '',
                'calculated_marketcap_to_total_equity': str(pb.quantize(Decimal('0.001'))) if pb is not None else '',
                'official_krx_per': '',
                'official_krx_pbr': '',
                'audit_status': reason,
                'review_flags': ';'.join(flags),
                'provisional_grade': row.get('provisional_grade', ''),
                'final_grade': 'WITHHELD',
                'buy_signal': 'NONE',
            })
        output = OUT / 'existing_evidence_valuation_audit.csv'
        with output.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(results)
        status['counts'] = counts
        status['financial_statement_counts'] = {s: sum(r['financial_statement_type'] == s for r in results) for s in ('CFS', 'OFS')}
        status['warnings'].extend([
            'Ratios are market-cap / total net income and market-cap / total equity, not official KRX PER/PBR.',
            'FY2025 accounting figures are compared with 2026-11-06 market capitalization.',
            'Consolidated profit/equity may include non-controlling interests; official EPS/BPS not checked.',
            'Share class is unverified; no final A/B investment grade or buy signal is released.',
        ])
    except Exception as exc:
        status['error'] = str(exc)
        status['warnings'].append('Audit failed closed; do not infer investment grades')
    (OUT / 'status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(status, ensure_ascii=False, indent=2))
    if status.get('error'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
