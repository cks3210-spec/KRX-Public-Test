#!/usr/bin/env python3
"""Stage 11: compare receipt-specific archived financial snapshots, fail closed.

OpenDART fnlttSinglAcntAll is period-based and does not accept a historical
receipt number as a selector. Never label current API values as original values.
Optional immutable snapshots: data/dart_receipt_snapshots/<receipt>.json, with
receipt_no, corp_code, year, report_code, fs_div, source_document_receipt,
source_kind ('archived_dart_response' or 'receipt_document_extract'), rows.
"""
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / 'data'
METRICS = {
    'revenue': {'ifrs-full_Revenue', 'ifrs_Revenue'},
    'operating_profit': {'dart_OperatingIncomeLoss'},
    'net_income': {'ifrs-full_ProfitLoss', 'ifrs_ProfitLoss'},
    'assets': {'ifrs-full_Assets', 'ifrs_Assets'},
    'liabilities': {'ifrs-full_Liabilities', 'ifrs_Liabilities'},
    'equity': {'ifrs-full_Equity', 'ifrs_Equity'},
}
FIELDS = ('thstrm_amount', 'thstrm_add_amount', 'frmtrm_amount', 'frmtrm_add_amount')
ALLOWED_SOURCES = {'archived_dart_response', 'receipt_document_extract'}

def read(name):
    return json.loads((DATA / name).read_text(encoding='utf-8'))

def number(value):
    if value is None or str(value).strip() in ('', '-'):
        return None
    return int(str(value).replace(',', '').strip())

def extract(snapshot):
    found = defaultdict(list)
    for row in snapshot.get('rows', []):
        if row.get('account_detail') not in (None, '', '-') or row.get('currency') != 'KRW':
            continue
        if row.get('sj_div') not in ('BS', 'IS', 'CIS'):
            continue
        for metric, ids in METRICS.items():
            if row.get('account_id') in ids:
                if metric in ('assets', 'liabilities', 'equity') and row.get('sj_div') != 'BS':
                    continue
                if metric not in ('assets', 'liabilities', 'equity') and row.get('sj_div') not in ('IS', 'CIS'):
                    continue
                found[metric].append(row)
    values, problems = {}, []
    for metric in METRICS:
        rows = found[metric]
        if len(rows) != 1:
            problems.append(metric.upper() + '_MISSING_OR_AMBIGUOUS')
            continue
        try:
            values[metric] = {k: number(rows[0].get(k)) for k in FIELDS}
        except ValueError:
            problems.append(metric.upper() + '_NON_NUMERIC')
    return values, problems

def snapshot(receipt, item, period):
    if not receipt or not str(receipt).isdigit():
        return None, 'INVALID_RECEIPT'
    path = DATA / 'dart_receipt_snapshots' / (str(receipt) + '.json')
    if not path.is_file():
        return None, 'RECEIPT_SNAPSHOT_UNAVAILABLE'
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None, 'RECEIPT_SNAPSHOT_UNREADABLE'
    expected = {'receipt_no': str(receipt), 'corp_code': str(item.get('corp_code')),
                'year': str(period.get('year')), 'report_code': str(period.get('report_code')),
                'fs_div': str(period.get('statement_type')),
                'source_document_receipt': str(receipt)}
    if any(str(doc.get(k)) != v for k, v in expected.items()):
        return None, 'SNAPSHOT_PROVENANCE_MISMATCH'
    if doc.get('source_kind') not in ALLOWED_SOURCES:
        return None, 'SNAPSHOT_SOURCE_UNVERIFIED'
    if not isinstance(doc.get('rows'), list) or not doc['rows']:
        return None, 'SNAPSHOT_ROWS_MISSING'
    if any(str(r.get('rcept_no')) != str(receipt) for r in doc['rows']):
        return None, 'SNAPSHOT_ROW_RECEIPT_MISMATCH'
    return doc, None

def compare(original, amended):
    old, old_issues = extract(original)
    new, new_issues = extract(amended)
    differences, unavailable = [], []
    for metric in METRICS:
        if metric not in old or metric not in new:
            unavailable.append(metric)
            continue
        for field in FIELDS:
            a, b = old[metric][field], new[metric][field]
            if a is None or b is None:
                continue
            if a != b:
                differences.append({'metric': metric, 'field': field,
                                    'original': a, 'amended': b, 'delta': b-a})
    return differences, sorted(set(unavailable)), old_issues + new_issues

def main():
    history = read('daily_dart_stage10_amendment_history.json')
    evidence = read('daily_dart_evidence.json')
    indexed = {str(x.get('code')).zfill(6): x for x in evidence.get('results', [])}
    results = []
    for item in history.get('results', []):
        code = str(item.get('code')).zfill(6)
        source = indexed.get(code, {})
        output = {'code': code, 'name': item.get('name'), 'status': 'NOT_VERIFIED',
                  'financial_verified': False, 'grade_authorized': False,
                  'buy_signal': None, 'periods': [], 'issues': []}
        if not item.get('history_search_complete'):
            output['issues'].append('STAGE10_HISTORY_INCOMPLETE')
        for period in item.get('periods', []):
            chain = sorted(period.get('history') or [], key=lambda x: (x.get('receipt_date') or '', x.get('receipt_no') or ''))
            amended = [x for x in chain if x.get('amended')]
            p = {'year': period.get('year'), 'report_code': period.get('report_code'),
                 'statement_type': period.get('statement_type'),
                 'amendment_count': len(amended), 'comparisons': [], 'status': 'NOT_VERIFIED'}
            if not period.get('latest_receipt_matches') or not chain:
                p['status'] = 'HISTORY_MISSING_OR_MISMATCHED'
            elif any(x.get('withdrawn') for x in chain):
                p['status'] = 'WITHDRAWN_FILING_REVIEW_REQUIRED'
            elif not amended:
                p['status'] = 'NO_AMENDMENT_IN_SEARCH_WINDOW'
            else:
                for idx in range(1, len(chain)):
                    current = chain[idx]
                    if not current.get('amended'):
                        continue
                    prior = chain[idx-1]
                    a, ae = snapshot(prior.get('receipt_no'), source, period)
                    b, be = snapshot(current.get('receipt_no'), source, period)
                    comparison = {'original_receipt': prior.get('receipt_no'),
                                  'amended_receipt': current.get('receipt_no'),
                                  'status': 'NOT_VERIFIED', 'differences': [], 'issues': []}
                    for err in (ae, be):
                        if err:
                            comparison['issues'].append(err)
                    if a is not None and b is not None:
                        diff, missing, errors = compare(a, b)
                        comparison['differences'] = diff
                        comparison['issues'].extend(errors)
                        if missing:
                            comparison['issues'].append('METRICS_UNAVAILABLE_' + '_'.join(missing))
                        if not comparison['issues']:
                            comparison['status'] = 'CHANGED' if diff else 'NO_DIFFERENCE_IN_COMPARABLE_FIELDS'
                    p['comparisons'].append(comparison)
                p['status'] = ('COMPARISON_COMPLETE' if p['comparisons'] and
                               all(x['status'] != 'NOT_VERIFIED' for x in p['comparisons'])
                               else 'RECEIPT_SPECIFIC_FINANCIAL_SNAPSHOTS_REQUIRED')
            output['periods'].append(p)
        if any(p['status'] in ('RECEIPT_SPECIFIC_FINANCIAL_SNAPSHOTS_REQUIRED',
                              'HISTORY_MISSING_OR_MISMATCHED', 'WITHDRAWN_FILING_REVIEW_REQUIRED')
               for p in output['periods']):
            output['issues'].append('AMENDMENT_FINANCIAL_COMPARISON_INCOMPLETE')
        output['issues'].append('FULL_ACCOUNTING_AND_GRADE_VALIDATION_PENDING')
        output['status'] = ('AMENDMENT_DIFF_REVIEW_COMPLETE_NOT_FINAL_VERIFIED'
                            if item.get('history_search_complete') and
                            all(p['status'] in ('NO_AMENDMENT_IN_SEARCH_WINDOW', 'COMPARISON_COMPLETE')
                                for p in output['periods'])
                            else 'REVIEW_REQUIRED')
        results.append(output)
    result = {'generated_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'trading_date': history.get('trading_date'), 'candidate_count': len(results),
              'review_complete_count': sum(x['status'] == 'AMENDMENT_DIFF_REVIEW_COMPLETE_NOT_FINAL_VERIFIED' for x in results),
              'financial_verified_count': 0, 'final_ab_grade_count': 0,
              'note': 'Receipt-specific comparison uses only archived, provenance-tagged financial snapshots. OpenDART period APIs do not retrieve original historical receipts. No final grades or buy signals.',
              'results': results}
    out = DATA / 'daily_dart_stage11_financial_diff.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'candidates': len(results), 'review_complete': result['review_complete_count'],
                      'financial_verified': 0}, ensure_ascii=False))

if __name__ == '__main__':
    main()
