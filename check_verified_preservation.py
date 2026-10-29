#!/usr/bin/env python3
"""Compare pre/post followup snapshots; reject loss or mutation of VERIFIED rows.
Usage: python check_verified_preservation.py BEFORE.csv AFTER.csv
Read-only. Exit 1 on a regression, 2 on malformed inputs.
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

KEY = ('recommendation_id', 'horizon_trading_days')
REQUIRED = KEY + ('status', 'evaluation_date', 'entry_reference', 'exit_close', 'raw_return_pct')


def load(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or any(k not in reader.fieldnames for k in REQUIRED):
            raise ValueError(f'Missing required columns in {path}')
        rows = list(reader)
    keys = [tuple(row[k].strip() for k in KEY) for row in rows]
    duplicates = [k for k, count in Counter(keys).items() if count > 1]
    if duplicates:
        raise ValueError(f'Duplicate record/horizon keys in {path}: {len(duplicates)}')
    return {tuple(row[k].strip() for k in KEY): row for row in rows}, len(rows)


def main():
    if len(sys.argv) != 3:
        print('Usage: python check_verified_preservation.py BEFORE.csv AFTER.csv', file=sys.stderr)
        return 2
    try:
        before, before_count = load(sys.argv[1])
        after, after_count = load(sys.argv[2])
    except (OSError, ValueError) as exc:
        print(f'INPUT_ERROR: {exc}', file=sys.stderr)
        return 2

    prior_verified = {key: row for key, row in before.items() if row['status'].strip() == 'VERIFIED'}
    missing, changed = [], []
    for key, original in prior_verified.items():
        updated = after.get(key)
        if updated is None:
            missing.append(key)
        elif updated != original:
            changed.append(key)

    report = {
        'before_rows': before_count,
        'after_rows': after_count,
        'before_verified': len(prior_verified),
        'after_verified': sum(row['status'].strip() == 'VERIFIED' for row in after.values()),
        'missing_verified_count': len(missing),
        'changed_verified_count': len(changed),
        'sample_missing': missing[:5],
        'sample_changed': changed[:5],
        'result': 'FAIL' if missing or changed else 'PASS',
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if missing or changed else 0


if __name__ == '__main__':
    sys.exit(main())
