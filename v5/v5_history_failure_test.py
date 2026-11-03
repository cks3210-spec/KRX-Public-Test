#!/usr/bin/env python3
"""Isolated failure-injection test for existing v5_history_merge.py; no API or production data."""
import csv, importlib.util, json, os, tempfile
from pathlib import Path

FIELDS = ('revenue','operating_profit','net_income','assets','liabilities','equity')

def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def previous(code, value):
    r={'ISU_CD':code,'ISU_NM':'TEST_'+code,'fiscal_year':'2025','report_code':'11011','statement_type':'CFS','verified_at_utc':'2026-01-01T00:00:00+00:00'}
    r.update({f+'_krw':str(value+i) for i,f in enumerate(FIELDS)})
    return r

def incoming(code, value, status='OK'):
    r={'ISU_CD':code,'ISU_NM':'TEST_'+code,'fiscal_year':'2025','report_code':'11011','statement_type':'CFS','fetch_status':status}
    for i,f in enumerate(FIELDS):r.update({f+'_krw':str(value+i) if status=='OK' else '',f+'_status':'OK' if status=='OK' else 'MISSING'})
    return r

def main():
    script=Path(__file__).resolve().with_name('v5_history_merge.py')
    if not script.exists():raise SystemExit('Copy the existing v5_history_merge.py next to this test in runner only')
    with tempfile.TemporaryDirectory(prefix='v5_failure_isolated_') as d:
        original=os.getcwd()
        try:
            os.chdir(d);Path('v5_prior').mkdir();Path('v5_output').mkdir()
            old=[previous('000001',1000),previous('000002',2000)]
            write_csv(Path('v5_prior/financial_latest.csv'),old)
            new=[incoming('000001',9999,'REQUEST_ERROR'),incoming('000002',3000),incoming('000003',7777,'DART_013')]
            write_csv(Path('v5_output/dart_validate_v2.csv'),new)
            spec=importlib.util.spec_from_file_location('v5_history_merge_tested',script)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.main()
            merged={r['ISU_CD']:r for r in read_csv(Path('v5_output/financial_latest.csv'))}
            summary=json.loads(Path('v5_output/history_summary.json').read_text(encoding='utf-8'))
            events=read_csv(Path('v5_output/financial_events.csv'))
            checks={
                'failed_collection_preserves_previous':merged['000001']['revenue_krw']=='1000',
                'valid_collection_updates':merged['000002']['revenue_krw']=='3000',
                'unverified_new_company_excluded':'000003' not in merged,
                'verified_count_stays_two':len(merged)==2,
                'old_preserved_count_one':summary['preserved_old']==1,
                'current_verified_count_one':summary['verified_current']==1,
                'change_recorded':summary['change_events_total']==6,
                'failed_new_company_marked':any(x['ISU_CD']=='000003' and x['event']=='NO_VERIFIED_SNAPSHOT' for x in events)
            }
            result={'scenario':'Synthetic failure injection; isolated temp directory; no DART API calls','checks':checks,'passed':sum(checks.values()),'total':len(checks),'status':'PASS' if all(checks.values()) else 'FAIL'}
            print(json.dumps(result,ensure_ascii=False,indent=2))
            if not all(checks.values()):raise SystemExit(1)
        finally:os.chdir(original)
if __name__=='__main__':main()
