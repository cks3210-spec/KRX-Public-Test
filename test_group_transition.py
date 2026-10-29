#!/usr/bin/env python3
"""Read-only regression test: V -> VG classification must not orphan followups.
Run at repository root: python test_group_transition.py
"""
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HISTORY = ROOT / 'trade_validation' / 'candidate_history.csv'
FOLLOWUP = ROOT / 'trade_validation' / 'trade_followup.csv'


def read(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def main():
    history = read(HISTORY)
    followups = read(FOLLOWUP)
    index = {(r['snapshot_date'], r['stock_code']): r for r in history}
    existing = {r['recommendation_id'] for r in followups}
    candidates = [r for r in history if r.get('source_group') in ('V', 'G') and r.get('record_id') in existing]
    if not candidates:
        raise SystemExit('INCONCLUSIVE: no V/G record with followup found')
    sample = candidates[0]
    old_group = sample['source_group']
    simulated_group = 'VG'
    old_id = sample['record_id']
    simulated_id = f"{sample['snapshot_date']}-{sample['stock_code']}-{simulated_group}"
    impacted = sum(r['recommendation_id'] == old_id for r in followups)
    report = {
        'test': 'source group change without changing snapshot date or stock code',
        'sample_date': sample['snapshot_date'],
        'sample_code': sample['stock_code'],
        'from_group': old_group,
        'to_group': simulated_group,
        'before_id': old_id,
        'after_id_under_current_formula': simulated_id,
        'linked_followup_rows_at_risk': impacted,
        'stable_identity': old_id == simulated_id,
        'result': 'PASS' if old_id == simulated_id else 'EXPECTED_FAIL',
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Exit 0 for a successful detection: this is a diagnostic test, not a fix.
    if old_id != simulated_id:
        print('DETECTED: group-dependent record_id is unstable. No files modified.')


if __name__ == '__main__':
    main()
