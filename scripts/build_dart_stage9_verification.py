#!/usr/bin/env python3
"""Stage 9: fail-closed evidence consistency gate; not a complete amendment history check.
Reads the Stage 8 DART outputs and writes data/daily_dart_stage9_verification.json.
"""
import datetime as dt
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / 'data'
RANK = {'11013': 1, '11012': 2, '11014': 3, '11011': 4}
ACCOUNTS = {'revenue': {'ifrs-full_Revenue', 'ifrs_Revenue'},
            'operating_profit': {'dart_OperatingIncomeLoss'}}

def load(name):
    return json.loads((DATA / name).read_text(encoding='utf-8'))

def main():
    evidence = load('daily_dart_evidence.json')
    audit = load('daily_dart_latest_filing_audit.json')
    refresh = load('daily_dart_financial_refresh.json')
    reconciliation = load('daily_dart_reconciliation.json')
    indexed = lambda doc: {str(x.get('code')).zfill(6): x for x in doc.get('results', [])}
    audits, refreshes, reconciles = map(indexed, (audit, refresh, reconciliation))
    output = []
    for item in evidence.get('results', []):
        code = str(item.get('code')).zfill(6)
        a, f, c = audits.get(code), refreshes.get(code), reconciles.get(code)
        issues = []
        latest = a.get('latest_periodic') if a else None
        if not latest:
            issues.append('LATEST_FILING_MISSING')
        if not f or f.get('status') not in ('ALREADY_MATCHES_LATEST_RECEIPT', 'REFRESHED_LATEST_PERIOD'):
            issues.append('REFRESH_NOT_CONFIRMED')
        if not c or c.get('status') != 'CUMULATIVE_YOY_CALCULATED_NOT_FINAL_VERIFIED':
            issues.append('RECONCILIATION_INCOMPLETE')
        if a and a.get('errors'):
            issues.append('LATEST_AUDIT_WARNINGS')
        if latest and (latest.get('amended') or latest.get('withdrawn')):
            issues.append('LATEST_FILING_AMENDED_OR_WITHDRAWN')
        selected = []
        if latest:
            selected = [x for x in item.get('filings', [])
                        if str(x.get('year')) == str(latest.get('fiscal_year'))
                        and x.get('report_code') == latest.get('report_code')]
        if len(selected) != 1:
            issues.append('LATEST_STATEMENT_MISSING_OR_AMBIGUOUS')
        else:
            filing = selected[0]
            receipt = latest.get('receipt_no')
            if not receipt or receipt not in filing.get('receipt_numbers', []):
                issues.append('LATEST_RECEIPT_MISMATCH')
            if filing.get('fs_div') not in ('CFS', 'OFS'):
                issues.append('INVALID_STATEMENT_TYPE')
            if c and (str(c.get('report_year')) != str(filing.get('year')) or
                      c.get('report_code') != filing.get('report_code') or
                      c.get('statement_type') != filing.get('fs_div')):
                issues.append('RECONCILIATION_STATEMENT_IDENTITY_MISMATCH')
            rows = filing.get('rows') or []
            if not rows:
                issues.append('EMPTY_FINANCIAL_ROWS')
            if any(r.get('rcept_no') != receipt for r in rows):
                issues.append('ROW_RECEIPT_MISMATCH')
            if any(r.get('currency') != 'KRW' for r in rows):
                issues.append('NON_KRW_ROWS_REQUIRE_REVIEW')
            for metric, ids in ACCOUNTS.items():
                matched = [r for r in rows if r.get('account_id') in ids
                           and r.get('sj_div') in ('IS', 'CIS')
                           and r.get('account_detail') in ('-', '', None)
                           and r.get('currency') == 'KRW']
                if len(matched) != 1:
                    issues.append(metric.upper() + '_ROW_AMBIGUOUS')
                    continue
                m = (c or {}).get('metrics', {}).get(metric, {})
                try:
                    cur = int(str(matched[0]['thstrm_add_amount']).replace(',', ''))
                    prev = int(str(matched[0]['frmtrm_add_amount']).replace(',', ''))
                except (TypeError, ValueError, KeyError):
                    issues.append(metric.upper() + '_CUMULATIVE_VALUES_MISSING')
                    continue
                if prev <= 0 or m.get('current') != cur or m.get('prior') != prev:
                    issues.append(metric.upper() + '_RECONCILIATION_VALUE_MISMATCH')
        # No historical amendment lineage verification exists yet: never authorize grades.
        issues.append('FULL_AMENDMENT_HISTORY_NOT_VERIFIED')
        issues.append('FINANCIAL_GRADE_MODEL_NOT_VALIDATED')
        output.append({'code': code, 'name': item.get('name'),
                       'evidence_consistency_passed': len(issues) == 2,
                       'financial_verified': False, 'grade_authorized': False,
                       'buy_signal': None, 'issues': sorted(set(issues)),
                       'latest_receipt': latest.get('receipt_no') if latest else None})
    result = {'generated_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'trading_date': evidence.get('trading_date'),
              'candidate_count': len(output),
              'evidence_consistency_passed_count': sum(x['evidence_consistency_passed'] for x in output),
              'financial_verified_count': 0, 'final_ab_grade_count': 0,
              'note': 'Local consistency gate only. Complete amendment lineage, accounting comparability and grade model validation remain pending.',
              'results': output}
    dest = DATA / 'daily_dart_stage9_verification.json'
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'candidates': len(output), 'consistency_passed': result['evidence_consistency_passed_count'], 'financial_verified': 0}))

if __name__ == '__main__':
    main()
