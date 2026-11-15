#!/usr/bin/env python3
"""KRX v5 stage 2: auditable research eligibility gate, NOT an A/B grade.
Run at repo root after daily financial bridge:
  python scripts/build_daily_grade_gate.py
Inputs: data/daily_financial_bridge.json, data/all_candidates_318.csv
Output: data/daily_grade_gate.json
"""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / 'data'

def main():
    bridge = json.loads((DATA / 'daily_financial_bridge.json').read_text(encoding='utf-8'))
    with (DATA / 'all_candidates_318.csv').open(encoding='utf-8-sig', newline='') as f:
        research = {r['code'].zfill(6): r for r in csv.DictReader(f)}
    results = []
    for candidate in bridge.get('candidates', []):
        code = str(candidate['code']).zfill(6)
        original = research.get(code)
        if original is None:
            results.append({'code': code, 'name': candidate.get('name'), 'review_status': 'MISSING_RESEARCH_RECORD', 'reasons': ['No matching research row']})
            continue
        reasons = [v.strip() for v in original.get('review_notes', '').split(';') if v.strip()]
        gate = original.get('model_gate', '').strip()
        review_class = original.get('research_review_class', '').strip()
        final_grade = original.get('final_grade', '').strip()
        if gate != 'REVIEW_ONLY' or review_class != 'NO_SCREENING_RISK_FLAG' or reasons:
            status = 'SPECIAL_REVIEW_REQUIRED'
        else:
            status = 'ELIGIBLE_FOR_GRADE_REVIEW'
        if final_grade not in ('A', 'B+', 'B'):
            reasons.append('FINAL_GRADE_NOT_VERIFIED')
        results.append({'code': code, 'name': candidate.get('name'), 'review_status': status,
                        'model_gate': gate, 'research_review_class': review_class,
                        'previous_final_grade': final_grade, 'reasons': reasons,
                        'grade': final_grade if final_grade in ('A','B+','B') and status == 'ELIGIBLE_FOR_GRADE_REVIEW' else None,
                        'fair_price': None, 'buy_signal': None})
    counts = {status: sum(r['review_status'] == status for r in results)
              for status in ('ELIGIBLE_FOR_GRADE_REVIEW','SPECIAL_REVIEW_REQUIRED','MISSING_RESEARCH_RECORD')}
    output = {'trading_date': bridge.get('trading_date'), 'generated_at_utc': datetime.now(timezone.utc).isoformat(),
              'source': ['data/daily_financial_bridge.json', 'data/all_candidates_318.csv'],
              'financial_source_date': bridge.get('financial_source_date', 'UNVERIFIED'),
              'counts': counts, 'results': results,
              'note': 'Eligibility is not an investment grade. Stale/uncorroborated growth figures must not be treated as validated. No fair price calculated.'}
    target = DATA / 'daily_grade_gate.json'
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'date': output['trading_date'], 'counts': counts, 'output': str(target)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
