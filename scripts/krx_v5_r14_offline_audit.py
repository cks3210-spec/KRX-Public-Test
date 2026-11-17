#!/usr/bin/env python3
"""Read-only R14 financial cache audit. No API, Git writes, or modification of data files."""
import argparse, csv, datetime as dt, json, pathlib, sys

def valid(r):
    return isinstance(r, dict) and r.get('status') == '000' and isinstance(r.get('accounts'), dict) and bool(r['accounts'])

def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)

def ttm(cache, code, year, kind):
    annual = cache.get(f'{code}:{year-1}:annual', {})
    current = cache.get(f'{code}:{year}:{kind}', {})
    previous = cache.get(f'{code}:{year-1}:{kind}', {})
    if not valid(annual): return None, 'NO_ANNUAL'
    if not valid(current) or not valid(previous): return None, 'MISSING_QUARTER'
    bases = [r.get('fs_div') for r in (annual, current, previous)]
    if not bases[0] or len(set(bases)) != 1: return None, 'BASIS_MISMATCH'
    values = [r['accounts'].get('profit') for r in (annual, current, previous)]
    if not all(number(v) for v in values): return None, 'MISSING_PROFIT'
    return values[0] + values[1] - values[2], 'VERIFIED_CUMULATIVE'

def self_test():
    def record(p, basis='CFS'): return {'status':'000','fs_div':basis,'accounts':{'profit':p}}
    c={'123456:2025:annual':record(100),'123456:2026:q3':record(90),'123456:2025:q3':record(70)}
    assert ttm(c,'123456',2026,'q3') == (120,'VERIFIED_CUMULATIVE')
    c['123456:2025:q3']=record(70,'OFS')
    assert ttm(c,'123456',2026,'q3')[1]=='BASIS_MISMATCH'
    del c['123456:2025:q3']
    assert ttm(c,'123456',2026,'q3')[1]=='MISSING_QUARTER'
    c['123456:2025:q3']=record(None)
    assert ttm(c,'123456',2026,'q3')[1]=='MISSING_PROFIT'
    c['123456:2025:q3']=record(70)
    c['123456:2025:annual']=record(-100)
    assert ttm(c,'123456',2026,'q3') == (-80,'VERIFIED_CUMULATIVE')
    return 5

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root', default='.', help='repository root (read only)')
    args=parser.parse_args()
    tests=self_test()
    root=pathlib.Path(args.root)
    base=root/'data/v5_financial_m'
    status_path=base/'status.json'
    cache_path=base/'dart_financial_cache.json'
    index_path=base/'annual_financial_index_m.csv'
    if not all(p.is_file() for p in (status_path,cache_path,index_path)):
        print(json.dumps({'result':'SELF_TEST_ONLY','synthetic_tests_passed':tests,'reason':'financial cache/index not found; no files changed'},ensure_ascii=False))
        return 0
    status=json.loads(status_path.read_text(encoding='utf-8-sig'))
    cache=json.loads(cache_path.read_text(encoding='utf-8-sig'))
    with index_path.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    year=int(str(status.get('market_date',''))[:4])
    kind=status.get('ttm_period')
    if kind not in ('q1','half','q3'):
        print(json.dumps({'result':'SKIPPED','reason':'no comparable quarter specified','synthetic_tests_passed':tests},ensure_ascii=False))
        return 0
    mismatch=[];computed=0;annual=0;duplicate_codes=0;seen=set()
    for r in rows:
        code=r.get('code','')
        if code in seen: duplicate_codes+=1
        seen.add(code)
        annual+=valid(cache.get(f'{code}:{year-1}:annual',{}))
        value,reason=ttm(cache,code,year,kind)
        if reason=='VERIFIED_CUMULATIVE': computed+=1
        reported=r.get('ttm_profit','').strip()
        reported_status=r.get('ttm_status','').strip()
        if reported_status=='VERIFIED_CUMULATIVE' and reason!='VERIFIED_CUMULATIVE':
            mismatch.append({'code':code,'issue':'UNSUPPORTED_TTM','reason':reason})
        elif reason=='VERIFIED_CUMULATIVE' and (reported!=str(value) or reported_status!='VERIFIED_CUMULATIVE'):
            mismatch.append({'code':code,'issue':'TTM_VALUE_OR_STATUS_MISMATCH','expected':value,'actual':reported})
    result={'result':'PASS' if not mismatch and not duplicate_codes else 'FAIL',
        'synthetic_tests_passed':tests,'market_date':status.get('market_date'),
        'cache_records':len(cache),'index_rows':len(rows),'annual_verified':annual,
        'ttm_verified_recomputed':computed,'ttm_status_claim':status.get('ttm_calculated'),
        'duplicate_codes':duplicate_codes,'mismatch_count':len(mismatch),'mismatch_samples':mismatch[:10],
        'read_only':True,'api_calls':0}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['result']=='PASS' else 1

if __name__=='__main__':sys.exit(main())
