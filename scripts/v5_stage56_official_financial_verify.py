#!/usr/bin/env python3
"""Stage56: conservative OpenDART owner-attributable financial evidence.

For frozen 318 candidates, try 2026 Q3 then H1 (same CFS endpoint).
No estimates, official PER/PBR assertions, or final investment grades.
"""
import csv
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / 'stage56_input/provisional_ab_318_evidence_audit.csv'
OUT = ROOT / 'stage56_official_output'
API = 'https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json'
PERIODS = [('2026', '11014', '2026_Q3'), ('2026', '11012', '2026_H1')]
FIELDS = {
    'owner_profit': ('ifrs-full_ProfitLossAttributableToOwnersOfParent', 'ifrs_ProfitLossAttributableToOwnersOfParent'),
    'owner_equity': ('ifrs-full_EquityAttributableToOwnersOfParent', 'ifrs_EquityAttributableToOwnersOfParent'),
}
COLS = ['ISU_CD', 'ISU_NM', 'dart_corp_code', 'source', 'fs_div', 'bsns_year',
        'reprt_code', 'financial_period', 'owner_profit', 'owner_equity',
        'owner_profit_account_id', 'owner_equity_account_id', 'status', 'detail',
        'attempts', 'account_ids_seen']


def fetch(key, corp, year, report, retries=2):
    params = urllib.parse.urlencode({'crtfc_key': key, 'corp_code': corp,
                                     'bsns_year': year, 'reprt_code': report,
                                     'fs_div': 'CFS'})
    request = urllib.request.Request(API + '?' + params,
                                     headers={'User-Agent': 'KRX-Research-Stage56/2.0'})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            if attempt == retries:
                raise
            time.sleep(1.0 * (attempt + 1))


def numeric(value):
    value = str(value if value is not None else '').replace(',', '').strip()
    if re.fullmatch(r'[+-]?\d+', value):
        return str(int(value))
    return ''


def extract(accounts):
    """Only exact standardized IDs and current-period amount; never name-match."""
    found = {}
    seen = set()
    for row in accounts:
        if row.get('fs_div') != 'CFS' or row.get('sj_div') not in ('IS', 'CIS', 'BS'):
            continue
        aid = str(row.get('account_id') or '').strip()
        if aid:
            seen.add(aid)
        for field, aliases in FIELDS.items():
            if aid not in aliases:
                continue
            expected_section = 'BS' if field == 'owner_equity' else ('IS', 'CIS')
            if row.get('sj_div') not in ((expected_section,) if isinstance(expected_section, str) else expected_section):
                continue
            amount = numeric(row.get('thstrm_amount'))
            if not amount:
                continue
            # DART can expose duplicate account rows; contradictory values block verification.
            if field in found and found[field][0] != amount:
                found[field] = ('', 'CONFLICTING_VALUES')
            elif field not in found:
                found[field] = (amount, aid)
    return found, sorted(seen)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    status = {'stage': 56, 'mode': 'DART_OWNER_ATTRIBUTABLE_VERIFICATION_V2',
              'generated_utc': datetime.now(timezone.utc).isoformat(),
              'official_per_pbr_verified': 0, 'final_grades_released': 0,
              'verified_owner_fields': 0, 'unverified': 0,
              'period_priority': [p[2] for p in PERIODS],
              'note': 'CFS owner fields only. Q3/H1 values are not annual PER/PBR inputs.'}
    try:
        with SRC.open(encoding='utf-8-sig', newline='') as file:
            rows = list(csv.DictReader(file))
        if len(rows) != 318:
            raise ValueError(f'Expected frozen 318 candidates, got {len(rows)}')
        key = os.getenv('DART_API_KEY') or os.getenv('OPENDART_API_KEY')
        if not key:
            raise ValueError('Missing DART_API_KEY or OPENDART_API_KEY secret')
        results = []
        for row in rows:
            corp = str(row.get('dart_corp_code') or '').strip()
            item = {col: '' for col in COLS}
            item.update(ISU_CD=row.get('ISU_CD', ''), ISU_NM=row.get('ISU_NM', ''),
                        dart_corp_code=corp, source='OpenDART fnlttSinglAcntAll',
                        fs_div='CFS', status='UNVERIFIED')
            if not (corp.isdigit() and len(corp) == 8):
                item['detail'] = 'DART_CORP_CODE_INVALID'
                results.append(item)
                continue
            attempts = []
            last_reason = ''
            for year, report, period in PERIODS:
                try:
                    response = fetch(key, corp, year, report)
                    code = str(response.get('status', ''))
                    attempts.append(f'{period}:{code}')
                    if code != '000':
                        last_reason = f'DART_{code}:{str(response.get("message", ""))[:80]}'
                        # Authentication/rate limit errors are not missing reports.
                        if code not in ('013',):
                            break
                        continue
                    data = response.get('list') or []
                    found, seen = extract(data)
                    item['account_ids_seen'] = ';'.join(seen[:40])
                    item['bsns_year'], item['reprt_code'], item['financial_period'] = year, report, period
                    for field in FIELDS:
                        amount, aid = found.get(field, ('', ''))
                        item[field] = amount
                        item[field + '_account_id'] = aid
                    if all(item[field] for field in FIELDS):
                        item['status'] = 'OWNER_FIELDS_VERIFIED'
                        item['detail'] = 'EXACT_STANDARD_ACCOUNT_IDS_AND_CFS_CONFIRMED'
                        break
                    last_reason = 'OWNER_ACCOUNT_IDS_MISSING_OR_CONFLICTING'
                    # A valid Q3 filing with incomplete required accounts can fall back to H1.
                except Exception as exc:
                    attempts.append(f'{period}:EXCEPTION_{type(exc).__name__}')
                    last_reason = f'FETCH_ERROR:{type(exc).__name__}:{str(exc)[:100]}'
                    break
                finally:
                    time.sleep(0.1)
            if item['status'] != 'OWNER_FIELDS_VERIFIED':
                # Do not carry over a partial amount from a different report.
                for field in FIELDS:
                    item[field] = ''
                    item[field + '_account_id'] = ''
                item['detail'] = last_reason or 'NO_VERIFIABLE_REPORT'
            item['attempts'] = ';'.join(attempts)
            results.append(item)
        with (OUT / 'owner_fields.csv').open('w', encoding='utf-8-sig', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=COLS)
            writer.writeheader()
            writer.writerows(results)
        status.update(candidate_count=len(results),
                      verified_owner_fields=sum(r['status'] == 'OWNER_FIELDS_VERIFIED' for r in results),
                      unverified=sum(r['status'] != 'OWNER_FIELDS_VERIFIED' for r in results),
                      verified_by_period=dict(Counter(r['financial_period'] for r in results if r['status'] == 'OWNER_FIELDS_VERIFIED')),
                      failure_reasons=dict(Counter(r['detail'].split(':')[0] for r in results if r['status'] != 'OWNER_FIELDS_VERIFIED')))
    except Exception as exc:
        status['error'] = str(exc)
    (OUT / 'status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(status, ensure_ascii=False))
    if 'error' in status:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
