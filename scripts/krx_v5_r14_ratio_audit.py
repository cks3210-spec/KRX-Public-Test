#!/usr/bin/env python3
"""R14 read-only ROE and official-ratio provenance audit.

Official PER/PBR are never inferred from daily price/market-cap data.
A supplied ratio CSV is compared only when the user asserts verified provenance;
this program does not independently authenticate the CSV.
"""
import argparse
import collections
import csv
import json
import math
from pathlib import Path

REQUIRED = {'code', 'market_date', 'official_per', 'official_pbr', 'source'}


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
        elif row.get('source') != 'KRX_OFFICIAL_VERIFIED':
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
            'reason_counts': dict(counts), 'candidates': results,
            'official_data_fetched_by_script': False,
            'official_source_independently_authenticated': False,
            'research_grades_changed': False, 'fair_value_verified': False,
            'investment_decisions_authorized': False, 'final_buy_signals': 0,
            'limitations': ['Source provenance asserted by input provider, not independently authenticated',
                            'Derived TTM PER and official PER may have different earnings bases',
                            'Financial disclosure point-in-time validation pending']}


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
    return 9


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--financial', help='Legacy ROE audit financial CSV')
    p.add_argument('--market', help='Optional market CSV for legacy audit')
    p.add_argument('--research', help='R14 grade_research.json')
    p.add_argument('--official-ratios', help='Optional independently sourced official ratio CSV')
    p.add_argument('--output', help='JSON report output path')
    p.add_argument('--self-test', action='store_true')
    a = p.parse_args()
    tests = selftest()
    if a.self_test or not (a.research or a.financial):
        print(json.dumps({'result': 'SELF_TEST_PASS', 'tests': tests}))
        return
    if a.research:
        research = json.loads(Path(a.research).read_text(encoding='utf-8-sig'))
        official = []
        if a.official_ratios:
            with open(a.official_ratios, encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                if not REQUIRED.issubset(reader.fieldnames or []):
                    raise SystemExit('OFFICIAL_CSV_REQUIRED_COLUMNS_MISSING')
                official = list(reader)
        result = ratio_audit(research, official)
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
