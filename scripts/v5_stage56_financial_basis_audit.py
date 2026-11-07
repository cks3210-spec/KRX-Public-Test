#!/usr/bin/env python3
"""Stage56 financial basis audit: conservative checks on the frozen 318-stock cohort.
No API requests, no official PER/PBR claims, no final trading grades.
"""
import csv
import datetime as dt
import json
from pathlib import Path
from decimal import Decimal, InvalidOperation

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'stage56_input' / 'provisional_ab_318_evidence_audit.csv'
OUT = ROOT / 'stage56_financial_basis_output'

def number(v):
    try:
        n = Decimal(str(v).replace(',', '').strip())
        return n if n.is_finite() else None
    except (InvalidOperation, ValueError):
        return None

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    status = {'stage': 56, 'mode': 'FINANCIAL_BASIS_AND_FRESHNESS_AUDIT',
              'generated_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'official_per_pbr_verified': 0, 'final_grades_released': 0,
              'notes': ['Existing data only; not an OpenDART refresh.',
                        'FY2025 income and equity are not proven owner-attributable.',
                        'Share class and official valuation remain unverified.']}
    try:
        with SRC.open(encoding='utf-8-sig', newline='') as f:
            records = list(csv.DictReader(f))
        if len(records) != 318:
            raise ValueError(f'Expected 318 records, found {len(records)}')
        dates = {r.get('BAS_DD') for r in records}
        if dates != {'20261106'}:
            raise ValueError(f'Unexpected market dates: {dates}')
        output = []
        seen = set()
        for r in records:
            code = r.get('ISU_CD', '').strip()
            market = r.get('MARKET', '').strip()
            key = (market, code)
            if key in seen:
                raise ValueError(f'Duplicate: {key}')
            seen.add(key)
            income, equity, cap = (number(r.get(k)) for k in ('net_income', 'total_equity', 'MKTCAP'))
            flags = ['OWNER_ATTRIBUTABLE_NET_INCOME_UNVERIFIED',
                     'OWNER_ATTRIBUTABLE_EQUITY_UNVERIFIED',
                     'OFFICIAL_SHARECLASS_UNVERIFIED', 'OFFICIAL_PER_PBR_UNVERIFIED']
            if r.get('financial_period') != '2025_FY':
                flags.append('FINANCIAL_PERIOD_UNEXPECTED')
            else:
                flags.append('FY2025_STALE_RELATIVE_TO_20261106_MARKET')
            if r.get('financial_statement_type') == 'OFS':
                flags.append('SEPARATE_STATEMENT_ONLY')
            elif r.get('financial_statement_type') != 'CFS':
                flags.append('STATEMENT_TYPE_UNKNOWN')
            if not r.get('dart_corp_code', '').strip():
                flags.append('DART_CORP_CODE_MISSING')
            if income is None or income <= 0:
                flags.append('NET_INCOME_MISSING_OR_NONPOSITIVE')
            if equity is None or equity <= 0:
                flags.append('EQUITY_MISSING_OR_NONPOSITIVE')
            if cap is None or cap <= 0:
                flags.append('MARKET_CAP_MISSING_OR_NONPOSITIVE')
            reference_pe = cap / income if cap is not None and cap > 0 and income is not None and income > 0 else None
            reference_pb = cap / equity if cap is not None and cap > 0 and equity is not None and equity > 0 else None
            output.append({'ISU_CD': code, 'ISU_NM': r.get('ISU_NM',''), 'MARKET': market,
                           'BAS_DD': r.get('BAS_DD',''), 'dart_corp_code': r.get('dart_corp_code',''),
                           'financial_period': r.get('financial_period',''),
                           'financial_statement_type': r.get('financial_statement_type',''),
                           'reference_marketcap_over_income': str(round(reference_pe, 3)) if reference_pe is not None else '',
                           'reference_marketcap_over_equity': str(round(reference_pb, 3)) if reference_pb is not None else '',
                           'official_per': '', 'official_pbr': '', 'final_grade': 'WITHHELD',
                           'next_action': 'DART_LATEST_OWNER_ATTRIBUTABLE_FIELDS_AND_MARKET_DATE_VERIFY',
                           'flags': ';'.join(flags)})
        path = OUT / 'financial_basis_audit.csv'
        with path.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(output[0]))
            writer.writeheader(); writer.writerows(output)
        status.update({'candidate_count': len(output), 'market_date': '20261106',
                       'statement_counts': {k: sum(r['financial_statement_type'] == k for r in output) for k in ('CFS','OFS')},
                       'reference_ratio_both_available': sum(bool(r['reference_marketcap_over_income'] and r['reference_marketcap_over_equity']) for r in output),
                       'nonpositive_or_missing_income': sum('NET_INCOME_MISSING_OR_NONPOSITIVE' in r['flags'] for r in output),
                       'owner_attributable_fields_verified': 0})
    except Exception as exc:
        status['error'] = str(exc)
    (OUT / 'status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(status, ensure_ascii=False, indent=2))
    if 'error' in status:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
