#!/usr/bin/env python3
"""Stage 4: fail-closed financial lineage audit for daily KRX candidates.

This audits existing research evidence; it DOES NOT fetch or authenticate DART data.
Run after daily grade gate and valuation:
    python scripts/build_daily_financial_evidence_audit.py
Output: data/daily_financial_evidence_audit.json
Never creates financial_verification_status.json or asserts verified=true.
"""
import csv
import datetime as dt
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / 'data'
REQUIRED = ('dart_corp_code', 'financial_period', 'financial_statement_type',
            'disclosure_receipt_no', 'financial_source_url', 'financial_fetched_at_utc')
MEASURES = ('revenue_growth_pct', 'operating_profit_growth_pct', 'debt_ratio_pct',
            'operating_cashflow')

def main():
    gate = json.loads((DATA / 'daily_grade_gate.json').read_text(encoding='utf-8'))
    with (DATA / 'all_candidates_318.csv').open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        headers = set(reader.fieldnames or [])
        records = {str(r.get('code', '')).zfill(6): r for r in reader}
    findings = []
    for item in gate.get('results', []):
        code = str(item.get('code', '')).zfill(6)
        row = records.get(code)
        missing = list(REQUIRED) if row is None else [k for k in REQUIRED if not str(row.get(k) or '').strip()]
        missing_measures = list(MEASURES) if row is None else [k for k in MEASURES if not str(row.get(k) or '').strip()]
        # A populated field alone does not prove the official document was fetched and reconciled.
        findings.append({
            'code': code, 'name': item.get('name'),
            'grade_review_status': item.get('review_status'),
            'research_record_present': row is not None,
            'missing_provenance_fields': missing,
            'missing_financial_measures': missing_measures,
            'source_authenticated': False,
            'period_and_cumulative_basis_reconciled': False,
            'financial_evidence_verified': False,
            'final_grade_authorized': False,
            'next_action': 'FETCH_AND_RECONCILE_OFFICIAL_DART_FILINGS' if row else 'RESTORE_RESEARCH_RECORD'
        })
    out = {
        'trading_date': gate.get('trading_date'),
        'generated_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'input': ['data/daily_grade_gate.json', 'data/all_candidates_318.csv'],
        'research_csv_columns': sorted(headers),
        'required_provenance_columns': list(REQUIRED),
        'candidate_count': len(findings),
        'candidates_with_complete_provenance': sum(not x['missing_provenance_fields'] for x in findings),
        'officially_verified_candidates': 0,
        'status': 'OFFICIAL_SOURCE_VERIFICATION_REQUIRED',
        'note': 'This is a diagnostic only. CSV metadata cannot authenticate filings. No A/B grade or buy price is authorized.',
        'findings': findings
    }
    path = DATA / 'daily_financial_evidence_audit.json'
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(path), 'candidate_count': len(findings),
                      'complete_provenance': out['candidates_with_complete_provenance'],
                      'officially_verified': 0}, ensure_ascii=False))

if __name__ == '__main__':
    main()
