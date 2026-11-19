#!/usr/bin/env python3
"""Read-only official-vs-derived PER/PBR audit for R14 research candidates.

No web/API fetching, no official value invention, no grading changes, no buy signals.
Input official CSV must have: code, market_date, official_per, official_pbr, source.
Source must explicitly equal KRX_OFFICIAL_VERIFIED; date must equal research market_date.
"""
import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

REQUIRED = {'code', 'market_date', 'official_per', 'official_pbr', 'source'}


def number(value):
    try:
        x = float(str(value).replace(',', ''))
        return x if math.isfinite(x) and x > 0 else None
    except (TypeError, ValueError):
        return None


def audit(research, official_rows):
    if research.get('result') != 'PRELIMINARY_RESEARCH_ONLY':
        raise ValueError('RESEARCH_INPUT_NOT_PRELIMINARY')
    date = str(research.get('market_date', ''))
    if len(date) != 8 or not date.isdigit():
        raise ValueError('RESEARCH_MARKET_DATE_INVALID')
    by_code = {}
    duplicates = set()
    for row in official_rows:
        code = str(row.get('code', '')).strip()
        if code in by_code:
            duplicates.add(code)
        by_code[code] = row
    items = []
    reasons = Counter()
    for candidate in research.get('candidates', []):
        code = str(candidate['code'])
        row = by_code.get(code)
        reason = None
        if code in duplicates:
            reason = 'DUPLICATE_OFFICIAL_ROWS'
        elif row is None:
            reason = 'OFFICIAL_ROW_MISSING'
        elif str(row.get('source', '')).strip() != 'KRX_OFFICIAL_VERIFIED':
            reason = 'OFFICIAL_SOURCE_UNVERIFIED'
        elif str(row.get('market_date', '')).strip() != date:
            reason = 'MARKET_DATE_MISMATCH'
        else:
            op, ob = number(row.get('official_per')), number(row.get('official_pbr'))
            ep, eb = number(candidate.get('ttm_per_est')), number(candidate.get('pbr_est'))
            if None in (op, ob, ep, eb):
                reason = 'RATIO_MISSING_OR_NONPOSITIVE'
        item = {'code': code, 'name': candidate.get('name', ''),
                'grade_research_only': candidate.get('grade'),
                'research_market_date': date,
                'derived_per': candidate.get('ttm_per_est'),
                'derived_pbr': candidate.get('pbr_est'),
                'official_per': None, 'official_pbr': None,
                'per_difference_pct': None, 'pbr_difference_pct': None,
                'official_ratio_crosscheck': 'NOT_VERIFIED',
                'investment_decisions_authorized': False}
        if reason:
            reasons[reason] += 1
            item['reason'] = reason
        else:
            item.update({'official_per': op, 'official_pbr': ob,
                         'per_difference_pct': round(100*(ep/op-1), 2),
                         'pbr_difference_pct': round(100*(eb/ob-1), 2),
                         'official_ratio_crosscheck': 'COMPARABLE_ONLY',
                         'reason': 'DERIVED_AND_OFFICIAL_MAY_USE_DIFFERENT_ACCOUNTING_BASES'})
            reasons['COMPARABLE_ONLY'] += 1
        items.append(item)
    return {'result': 'R14_OFFICIAL_RATIO_RESEARCH_AUDIT',
            'market_date': date, 'candidate_count': len(items),
            'official_rows_supplied': len(official_rows),
            'crosschecked_count': reasons['COMPARABLE_ONLY'],
            'reason_counts': dict(reasons), 'candidates': items,
            'official_data_fetched_by_script': False,
            'research_grades_changed': False,
            'fair_value_verified': False,
            'investment_decisions_authorized': False,
            'final_buy_signals': 0,
            'limitations': ['Source label is asserted by input provider, not authenticated by this script',
                            'PER denominators may differ: TTM earnings versus official methodology',
                            'PBR may differ by share-class and accounting equity definitions',
                            'Financial filing point-in-time verification remains pending']}


def self_test():
    r={'result':'PRELIMINARY_RESEARCH_ONLY','market_date':'20261118',
       'candidates':[{'code':'000270','grade':'A','ttm_per_est':5,'pbr_est':0.6}]}
    good={'code':'000270','market_date':'20261118','source':'KRX_OFFICIAL_VERIFIED',
          'official_per':'4','official_pbr':'0.5'}
    assert audit(r,[good])['crosschecked_count']==1
    assert audit(r,[good])['final_buy_signals']==0
    assert audit(r,[])['reason_counts']['OFFICIAL_ROW_MISSING']==1
    assert audit(r,[{**good,'market_date':'20261117'}])['crosschecked_count']==0
    assert audit(r,[{**good,'source':'UNKNOWN'}])['crosschecked_count']==0
    assert audit(r,[good,good])['crosschecked_count']==0
    assert audit(r,[{**good,'official_per':'0'}])['crosschecked_count']==0
    return 7


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--research',help='grade_research.json')
    p.add_argument('--official-ratios',help='Optional independently sourced official CSV')
    p.add_argument('--output',help='Output report JSON, preferably outside repo data')
    p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    tests=self_test()
    if a.self_test:
        print(json.dumps({'result':'SELF_TEST_PASS','tests':tests}))
        return
    if not a.research:
        p.error('--research is required unless --self-test')
    research=json.loads(Path(a.research).read_text(encoding='utf-8-sig'))
    official=[]
    if a.official_ratios:
        with open(a.official_ratios,encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f)
            if not REQUIRED.issubset(reader.fieldnames or []):
                raise SystemExit('OFFICIAL_CSV_REQUIRED_COLUMNS_MISSING')
            official=list(reader)
    report=audit(research,official)
    output=json.dumps(report,ensure_ascii=False,indent=2)
    if a.output:
        Path(a.output).write_text(output,encoding='utf-8')
    else:
        print(output)

if __name__=='__main__':
    main()
