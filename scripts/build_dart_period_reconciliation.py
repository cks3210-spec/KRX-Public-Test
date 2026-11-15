#!/usr/bin/env python3
"""Reconcile DART cumulative same-period revenue and operating profit.
Reads data/daily_dart_evidence.json, writes data/daily_dart_reconciliation.json.
This does NOT authenticate amended filings or authorize A/B grades.
"""
import datetime as dt
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / 'data'
REPORTS = {'11013': (1, 3), '11012': (2, 6), '11014': (3, 9), '11011': (4, 12)}
ACCOUNTS = {'revenue': {'ifrs-full_Revenue', 'ifrs_Revenue'},
            'operating_profit': {'dart_OperatingIncomeLoss'}}

def number(value):
    try:
        if value is None or str(value).strip() == '':
            return None
        return int(str(value).replace(',', '').strip())
    except ValueError:
        return None

def extract(filing, ids):
    rows = [r for r in filing.get('rows', []) if r.get('account_id') in ids
            and r.get('sj_div') in ('IS', 'CIS')
            and r.get('account_detail') in ('-', '', None)
            and r.get('currency') == 'KRW']
    if len(rows) != 1:
        return {'status': 'MISSING_OR_AMBIGUOUS_ACCOUNT', 'matching_rows': len(rows)}
    row = rows[0]
    current, prior = number(row.get('thstrm_add_amount')), number(row.get('frmtrm_add_amount'))
    if filing.get('report_code') == '11011':
        # Annual income-statement totals are not reliably encoded as add_amount.
        return {'status': 'ANNUAL_REPORT_REQUIRES_SEPARATE_HANDLING'}
    if current is None or prior is None or prior <= 0:
        return {'status': 'MISSING_CUMULATIVE_OR_NONPOSITIVE_PRIOR', 'current': current, 'prior': prior}
    return {'status': 'COMPARABLE_CUMULATIVE_VALUES', 'current': current, 'prior': prior,
            'yoy_pct': round((current / prior - 1) * 100, 3),
            'basis': 'DART_THSTRM_ADD_AMOUNT_VS_FRMTRM_ADD_AMOUNT'}

def main():
    source = json.loads((DATA / 'daily_dart_evidence.json').read_text(encoding='utf-8'))
    results = []
    for item in source.get('results', []):
        filings = [f for f in item.get('filings', []) if f.get('report_code') in REPORTS]
        filings.sort(key=lambda f: (int(f['year']), REPORTS[f['report_code']][0], f.get('fs_div') == 'CFS'), reverse=True)
        f = filings[0] if filings else None
        out = {'code': item.get('code'), 'name': item.get('name'), 'status': 'NO_FILINGS',
               'official_filing_collected': bool(f), 'financial_verified': False,
               'grade_authorized': False, 'buy_signal': None, 'issues': []}
        if f:
            quarter, month = REPORTS[f['report_code']]
            out.update({'report_year': int(f['year']), 'report_code': f['report_code'],
                        'report_quarter': quarter, 'period_end': f"{int(f['year']):04d}-{month:02d}-{(31 if month in (3, 12) else 30):02d}",
                        'statement_type': f['fs_div'], 'receipt_numbers': f.get('receipt_numbers', []),
                        'metrics': {name: extract(f, ids) for name, ids in ACCOUNTS.items()}})
            ok = all(v['status'] == 'COMPARABLE_CUMULATIVE_VALUES' for v in out['metrics'].values())
            out['status'] = 'CUMULATIVE_YOY_CALCULATED_NOT_FINAL_VERIFIED' if ok else 'INCOMPLETE_CUMULATIVE_COMPARISON'
            if not ok: out['issues'].append('REQUIRED_ACCOUNT_COMPARISON_MISSING')
            if quarter < 3 and int(f['year']) >= 2026:
                out['issues'].append('LATEST_COLLECTED_PERIOD_BEFORE_2026_Q3_CHECK_FOR_NEWER_FILINGS')
            out['issues'].append('AMENDMENT_AND_ORIGINAL_FILING_RECONCILIATION_PENDING')
            out['issues'].append('FINANCIAL_LINEAGE_AND_GRADE_MODEL_VALIDATION_PENDING')
        results.append(out)
    output = {'trading_date': source.get('trading_date'),
              'generated_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'source': 'data/daily_dart_evidence.json',
              'candidate_count': len(results),
              'cumulative_yoy_calculated_count': sum(r['status'] == 'CUMULATIVE_YOY_CALCULATED_NOT_FINAL_VERIFIED' for r in results),
              'verified_count': 0, 'final_ab_grade_count': 0,
              'note': 'Same-filing current/prior cumulative values only; amendment and filing recency not verified. Not investment advice.',
              'results': results}
    path = DATA / 'daily_dart_reconciliation.json'
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(path), 'candidates': len(results), 'calculated': output['cumulative_yoy_calculated_count'], 'verified': 0}, ensure_ascii=False))

if __name__ == '__main__':
    main()
