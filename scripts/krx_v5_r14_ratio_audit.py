#!/usr/bin/env python3
"""R14 read-only ROE and official-ratio provenance audit.

Official PER/PBR are never inferred from daily price/market-cap data.
A supplied ratio CSV or manual KRX portal CSV is compared without claiming independent verification;
this program does not independently authenticate the CSV.
"""
import argparse
import collections
import csv
import json
import math
import hashlib
import re
from pathlib import Path

REQUIRED = {'code', 'market_date', 'official_per', 'official_pbr', 'source'}
# KRX Open API service list does not include PER/PBR (verified 2026-11-19).
# Manual export is a fallback; self-declared provenance is NOT authentication.
KRX_EXPORT_SOURCE = 'KRX_DATA_MARKETPLACE_EXPORT_USER_SUPPLIED'
CODE_HEADERS = ('종목코드', '단축코드', 'ISU_SRT_CD', 'ISU_CD', 'code', '종목코드(단축)')
PER_HEADERS = ('PER', 'PER(배)', 'PER(배수)', 'PER(배)', '주가수익비율', 'official_per')
PBR_HEADERS = ('PBR', 'PBR(배)', 'PBR(배수)', '주가순자산비율', 'official_pbr')
DATE_HEADERS = ('기준일', '일자', '날짜', 'BAS_DD', 'market_date')



def number(v, positive=False):
    try:
        if v is None or str(v).strip() == '':
            return None
        n = float(str(v).replace(',', ''))
        return n if math.isfinite(n) and (not positive or n > 0) else None
    except (ValueError, TypeError):
        return None


def rows(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))



def normal_code(v):
    """Six-position short code; never substitute a 12-char ISIN or a company name."""
    c = str(v or '').strip().upper()
    if re.fullmatch(r'A[0-9A-Z]{6}', c):
        c = c[1:]
    if re.fullmatch(r'\d{1,6}', c):
        c = c.zfill(6)
    return c if re.fullmatch(r'[0-9A-Z]{6}', c) else ''


def clean_header(s):
    return re.sub(r'\s+', '', str(s or '')).strip()


def header_value(record, names):
    lookup = {clean_header(k).upper(): v for k, v in record.items() if k is not None}
    for name in names:
        key = clean_header(name).upper()
        if key in lookup:
            return lookup[key]
    return None


def csv_export_rows(path):
    raw = Path(path).read_bytes()
    decoded = None
    for encoding in ('utf-8-sig', 'cp949', 'euc-kr'):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeError:
            continue
    if decoded is None:
        raise ValueError('KRX_EXPORT_CSV_ENCODING_UNSUPPORTED')
    # Some exports contain one or more banner lines before the actual header.
    lines = decoded.splitlines()
    for start in range(min(12, len(lines))):
        reader = csv.DictReader(lines[start:])
        fieldnames = reader.fieldnames or []
        names = {clean_header(c).upper() for c in fieldnames}
        if (any(clean_header(c).upper() in names for c in CODE_HEADERS)
                and any(clean_header(c).upper() in names for c in PER_HEADERS)
                and any(clean_header(c).upper() in names for c in PBR_HEADERS)):
            return list(reader), hashlib.sha256(raw).hexdigest()
    raise ValueError('KRX_EXPORT_REQUIRED_STOCK_CODE_PER_PBR_COLUMNS_MISSING')


def normalize_krx_export(path, declared_date):
    """Normalizes a KRX-attributed CSV, but never authenticates its origin/date."""
    if not re.fullmatch(r'\d{8}', str(declared_date or '')):
        raise ValueError('KRX_EXPORT_AS_OF_DATE_REQUIRED_YYYYMMDD')
    data, sha256 = csv_export_rows(path)
    converted = []
    issues = collections.Counter()
    for raw in data:
        code = normal_code(header_value(raw, CODE_HEADERS))
        if not code:
            issues['invalid_or_missing_short_code'] += 1
            continue
        row_date = str(header_value(raw, DATE_HEADERS) or '').strip()
        row_date = re.sub(r'[./-]', '', row_date)
        if row_date and row_date != declared_date:
            issues['row_date_disagrees_with_declared_date'] += 1
        date = row_date or declared_date
        converted.append({'code': code, 'market_date': date,
                          'official_per': header_value(raw, PER_HEADERS),
                          'official_pbr': header_value(raw, PBR_HEADERS),
                          'source': KRX_EXPORT_SOURCE,
                          'date_basis': 'FILE_ROW' if row_date else 'OPERATOR_DECLARED'})
    return converted, {'source_file_sha256': sha256,
                       'source_provenance': 'USER_SUPPLIED_NOT_AUTHENTICATED',
                       'date_is_independently_authenticated': False,
                       'source_rows': len(data), 'usable_codes': len(converted),
                       'import_issues': dict(issues)}


def roe_audit(financial, market=None):
    fin = rows(financial)
    bycode = {}
    issues = collections.Counter()
    calculated = matched = 0
    for r in fin:
        code = str(r.get('code', '')).zfill(6)
        if code in bycode:
            issues['duplicate_financial_code'] += 1
        bycode[code] = r
        p, e, prev = (number(r.get(k)) for k in ('annual_profit', 'equity', 'prior_equity'))
        stored = number(r.get('annual_roe_pct'))
        if p is None or e is None or prev is None or e <= 0 or prev <= 0:
            issues['roe_inputs_missing_or_invalid'] += 1
            continue
        calculated += 1
        computed = 100 * p / ((e + prev) / 2)
        if stored is None:
            issues['roe_stored_missing'] += 1
        elif abs(stored - computed) <= 0.011:
            matched += 1
        else:
            issues['roe_mismatch'] += 1
    result = {'result': 'ROE_RESEARCH_AUDIT', 'financial_rows': len(fin),
              'roe_recomputed': calculated, 'roe_matched': matched,
              'issues': dict(issues), 'official_per_verified': 0,
              'official_pbr_verified': 0, 'final_buy_signals': 0,
              'investment_decisions_authorized': False}
    if market:
        m = rows(market)
        result['market_rows'] = len(m)
        result['market_columns'] = list(m[0]) if m else []
        result['market_financial_code_matches'] = sum(
            str(r.get('code', r.get('ISU_CD', ''))).zfill(6) in bycode for r in m)
    return result


def ratio_audit(research, official):
    if research.get('result') != 'PRELIMINARY_RESEARCH_ONLY':
        raise ValueError('RESEARCH_INPUT_NOT_PRELIMINARY')
    date = str(research.get('market_date', ''))
    if len(date) != 8 or not date.isdigit():
        raise ValueError('RESEARCH_MARKET_DATE_INVALID')
    bycode = {}
    duplicates = set()
    for row in official:
        code = str(row.get('code', '')).strip()
        if code in bycode:
            duplicates.add(code)
        bycode[code] = row
    counts = collections.Counter()
    results = []
    for c in research.get('candidates', []):
        code = str(c.get('code', '')).strip()
        row = bycode.get(code)
        item = {'code': code, 'name': c.get('name', ''),
                'grade_research_only': c.get('grade'),
                'research_market_date': date,
                'derived_per': c.get('ttm_per_est'), 'derived_pbr': c.get('pbr_est'),
                'official_per': None, 'official_pbr': None,
                'per_difference_pct': None, 'pbr_difference_pct': None,
                'investment_decisions_authorized': False}
        if code in duplicates:
            reason = 'DUPLICATE_OFFICIAL_ROWS'
        elif row is None:
            reason = 'OFFICIAL_ROW_MISSING'
        elif row.get('source') not in ('KRX_OFFICIAL_VERIFIED', KRX_EXPORT_SOURCE):
            reason = 'OFFICIAL_SOURCE_UNVERIFIED'
        elif str(row.get('market_date', '')).strip() != date:
            reason = 'MARKET_DATE_MISMATCH'
        else:
            op, ob = number(row.get('official_per'), True), number(row.get('official_pbr'), True)
            ep, eb = number(c.get('ttm_per_est'), True), number(c.get('pbr_est'), True)
            reason = 'COMPARABLE_ONLY' if None not in (op, ob, ep, eb) else 'RATIO_MISSING_OR_NONPOSITIVE'
        if reason == 'COMPARABLE_ONLY':
            item.update({'official_per': op, 'official_pbr': ob,
                         'per_difference_pct': round(100 * (ep / op - 1), 2),
                         'pbr_difference_pct': round(100 * (eb / ob - 1), 2)})
        item['reason'] = reason
        counts[reason] += 1
        results.append(item)
    return {'result': 'R14_OFFICIAL_RATIO_RESEARCH_AUDIT', 'market_date': date,
            'candidate_count': len(results), 'official_rows_supplied': len(official),
            'crosschecked_count': counts['COMPARABLE_ONLY'],
            'independently_verified_ratio_count': 0,
            'reason_counts': dict(counts), 'candidates': results,
            'official_data_fetched_by_script': False,
            'official_source_independently_authenticated': False,
            'research_grades_changed': False, 'fair_value_verified': False,
            'investment_decisions_authorized': False, 'final_buy_signals': 0,
            'limitations': ['Source provenance asserted by input provider, not independently authenticated',
                            'Derived TTM PER and official PER may have different earnings bases',
                            'Financial disclosure point-in-time validation pending',
                            'User-supplied KRX export source and as-of date not independently authenticated']}


def selftest():
    assert number('1,234') == 1234 and number('nan') is None
    assert number('0', True) is None
    r = {'result': 'PRELIMINARY_RESEARCH_ONLY', 'market_date': '20261118',
         'candidates': [{'code': '000270', 'grade': 'A', 'ttm_per_est': 5, 'pbr_est': .6}]}
    good = {'code': '000270', 'market_date': '20261118',
            'source': 'KRX_OFFICIAL_VERIFIED', 'official_per': 4, 'official_pbr': .5}
    assert ratio_audit(r, [good])['crosschecked_count'] == 1
    assert ratio_audit(r, [good])['final_buy_signals'] == 0
    assert ratio_audit(r, [])['reason_counts']['OFFICIAL_ROW_MISSING'] == 1
    assert ratio_audit(r, [{**good, 'market_date': '20261117'}])['crosschecked_count'] == 0
    assert ratio_audit(r, [{**good, 'source': 'UNKNOWN'}])['crosschecked_count'] == 0
    assert ratio_audit(r, [good, good])['crosschecked_count'] == 0
    assert ratio_audit(r, [{**good, 'official_per': 0}])['crosschecked_count'] == 0
    assert normal_code('A000270') == '000270' and normal_code('0001A0') == '0001A0'
    assert normal_code('KR7000270009') == ''
    assert clean_header(' PER (배) ') == 'PER(배)'
    assert header_value({'PER (배)': '7.1'}, PER_HEADERS) == '7.1'
    assert ratio_audit(r, [{**good, 'source': KRX_EXPORT_SOURCE}])['crosschecked_count'] == 1
    return 14


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--financial', help='Legacy ROE audit financial CSV')
    p.add_argument('--market', help='Optional market CSV for legacy audit')
    p.add_argument('--research', help='R14 grade_research.json')
    p.add_argument('--official-ratios', help='Optional normalized official ratio CSV (provenance still not authenticated)')
    p.add_argument('--krx-export', help='KRX Data Marketplace user-downloaded CSV with short code, PER, PBR')
    p.add_argument('--as-of-date', help='YYYYMMDD date declared for --krx-export; MUST match research market date')
    p.add_argument('--output', help='JSON report output path')
    p.add_argument('--self-test', action='store_true')
    a = p.parse_args()
    tests = selftest()
    if a.self_test or not (a.research or a.financial):
        print(json.dumps({'result': 'SELF_TEST_PASS', 'tests': tests}))
        return
    if a.research:
        if a.krx_export and a.official_ratios:
            raise SystemExit('USE_ONLY_ONE_OFFICIAL_INPUT_FORMAT')
        if a.krx_export and not a.as_of_date:
            raise SystemExit('KRX_EXPORT_AS_OF_DATE_REQUIRED')
        research = json.loads(Path(a.research).read_text(encoding='utf-8-sig'))
        official = []
        import_metadata = None
        if a.krx_export:
            official, import_metadata = normalize_krx_export(a.krx_export, a.as_of_date)
        if a.official_ratios:
            with open(a.official_ratios, encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                if not REQUIRED.issubset(reader.fieldnames or []):
                    raise SystemExit('OFFICIAL_CSV_REQUIRED_COLUMNS_MISSING')
                official = list(reader)
        result = ratio_audit(research, official)
        if import_metadata is not None:
            result['krx_export_import'] = import_metadata
            result['official_data_fetched_by_script'] = False
            result['official_source_independently_authenticated'] = False
    else:
        result = roe_audit(a.financial, a.market)
    result['self_tests'] = tests
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if a.output:
        dest = Path(a.output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(output, encoding='utf-8')
    else:
        print(output)
    if result.get('issues', {}).get('roe_mismatch') or result.get('issues', {}).get('duplicate_financial_code'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
