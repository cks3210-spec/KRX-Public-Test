#!/usr/bin/env python3
"""Stage56: audited, read-only intake of a *user supplied* KRX-attributed PER/PBR export.

This is NOT a provider-authentication engine. No network/API; no retrospective
promotion of raw exports, unproven provider dates, or trade instructions.
Only redacted counts/hash metadata may be published to a public repository.
"""
import argparse
import hashlib
import json
import re
from collections import Counter
import importlib.util
from pathlib import Path

ROOT = Path('v5_reports/stage28')
EXPORTS = Path('data/v5_official_ratio_exports')
VERSION = 'KRX_V5_STAGE56_P2_RATIO_EXPORT_INTAKE_V1'


def require(condition, reason):
    if not condition:
        raise ValueError('STAGE56_' + reason)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ratio_audit_module():
    path = Path('scripts/krx_v5_r14_ratio_audit.py')
    require(path.is_file(), 'EXISTING_KRX_RATIO_PARSER_MISSING')
    spec = importlib.util.spec_from_file_location('krx_v5_r14_ratio_audit', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_check(feed, p3, p2, decoded_rows, source_sha, imported, metadata=None):
    date = feed.get('research_market_date')
    require(isinstance(date, str) and re.fullmatch(r'20\d{6}', date), 'BAD_MARKET_DATE')
    candidates = feed.get('candidates')
    require(isinstance(candidates, list) and len(candidates) == feed.get('candidate_count'), 'BAD_CANDIDATES')
    require(feed.get('final_buy_signals') == 0 and feed.get('investment_decisions_authorized') is False,
            'FEED_BUY_GUARD')
    require(p3.get('research_market_date') == date and p3.get('p3_independently_proven_asof') is False,
            'P3_HISTORICAL_DATE_UNPROVEN')
    require(p3.get('candidate_count') == len(candidates) and p3.get('final_buy_signals') == 0,
            'P3_UNIVERSE_INVALID')
    require(p2.get('research_market_date') == date and p2.get('candidate_count') == len(candidates),
            'P2_DATE_OR_UNIVERSE_INVALID')
    require(p2.get('p2_official_per_verified_count') == 0 and
            p2.get('p2_official_pbr_verified_count') == 0 and
            p2.get('final_buy_signals') == 0 and
            p2.get('authorized_trade_decisions') is False,
            'P2_PROMOTION_FORBIDDEN')
    require(isinstance(source_sha, str) and bool(re.fullmatch(r'[0-9a-f]{64}', source_sha)),
            'EXPORT_SHA_INVALID')
    metadata = metadata or {}
    if metadata:
        require(isinstance(metadata, dict), 'MANIFEST_INVALID')
        require(str(metadata.get('as_of_date', '')) == date, 'MANIFEST_DATE_MISMATCH')
        require(str(metadata.get('source_file_sha256', '')).lower() == source_sha,
                'MANIFEST_EXPORT_HASH_MISMATCH')
    issues = imported.get('import_issues', {})
    require(not issues.get('row_date_disagrees_with_declared_date'), 'EXPORT_ROW_DATE_MISMATCH')
    require(not issues.get('invalid_or_missing_short_code'), 'EXPORT_BAD_SHORT_CODE')
    require(imported.get('source_file_sha256') == source_sha, 'PARSER_RAW_SHA_MISMATCH')
    require(imported.get('date_is_independently_authenticated') is False,
            'PARSER_CLAIMED_INDEPENDENT_AUTHENTICATION')
    require(imported.get('source_provenance') == 'USER_SUPPLIED_NOT_AUTHENTICATED',
            'PARSER_SOURCE_CLAIM_INVALID')

    candidate_ids = [r.get('code') for r in candidates]
    require(len(candidate_ids) == len(set(candidate_ids)) and
            all(isinstance(code, str) and bool(re.fullmatch(r'[A-Z0-9]{6}', code)) for code in candidate_ids),
            'CANDIDATE_CODES_INVALID')
    by_code = {}
    duplicate_codes = set()
    row_date_basis = Counter()
    for row in decoded_rows:
        code = row.get('code')
        if code in by_code:
            duplicate_codes.add(code)
        by_code[code] = row
        row_date_basis[row.get('date_basis', 'UNKNOWN')] += 1
        require(row.get('market_date') == date, 'EXPORT_ROW_DATE_MISMATCH')
        require(row.get('source') == 'KRX_DATA_MARKETPLACE_EXPORT_USER_SUPPLIED',
                'EXPORT_ROW_SOURCE_MISMATCH')
    require(not duplicate_codes, 'EXPORT_DUPLICATED_SHORT_CODES')

    number = ratio_audit_module().number
    outcome = Counter()
    for code in candidate_ids:
        row = by_code.get(code)
        if row is None:
            outcome['no_matching_row'] += 1
        elif number(row.get('official_per'), True) is None or number(row.get('official_pbr'), True) is None:
            outcome['missing_or_nonpositive_value'] += 1
        else:
            outcome['matched_numeric_research_only'] += 1
    require(sum(outcome.values()) == len(candidates), 'CANDIDATE_COUNT_DRIFT')
    return {
        'version': VERSION, 'research_market_date': date,
        'result': 'USER_SUPPLIED_KRX_ATTRIBUTED_EXPORT_RESEARCH_ONLY',
        'candidate_count': len(candidates),
        'source_rows': len(decoded_rows),
        'candidate_result_counts': dict(sorted(outcome.items())),
        'date_basis_counts': dict(sorted(row_date_basis.items())),
        'source_file_sha256': source_sha,
        'source_manifest_provided': bool(metadata),
        'source_manifest_is_operator_asserted_not_independently_authenticated': True,
        'independent_provider_origin_authenticated': False,
        'independent_historical_market_date_authenticated': False,
        'official_per_verified_count': 0,
        'official_pbr_verified_count': 0,
        'historical_p1_verified_count': 0,
        'final_buy_signals': 0,
        'investment_decisions_authorized': False,
        'new_krx_api_requests': 0, 'new_dart_api_requests': 0,
        'raw_ratio_values_published': False,
        'safety_note': 'Raw user export and per-stock ratios are not written in public report; check data licence before publishing source.',
        'next_step': 'OBTAIN_INDEPENDENT_KRX_PROVIDER_DATE_PROOF_BEFORE_P2_OFFICIAL_APPROVAL'
    }


def main(publish=False):
    feed_path = ROOT / 'r14_eligible_research_candidates.json'
    require(feed_path.is_file(), 'MISSING_RESEARCH_FEED')
    feed = read_json(feed_path)
    date = feed.get('research_market_date')
    require(isinstance(date, str) and re.fullmatch(r'20\d{6}', date), 'BAD_MARKET_DATE')
    csv_path = EXPORTS / (date+'.csv')
    if not csv_path.is_file():
        print('STAGE56_WAITING_FOR_AUTHORIZED_RATIO_EXPORT',json.dumps({'research_market_date':date,
              'source_csv_present':False,'official_p2_verified':0,'buy_signals':0}))
        return
    p3_path = ROOT/('r14_stage54_p3_cached_evidence_'+date+'.json')
    p2_path = ROOT/('r14_stage55_p2_provenance_gate_'+date+'.json')
    require(p3_path.is_file() and p2_path.is_file(), 'MISSING_STORED_STAGE54_STAGE55_AUDIT')
    parsed, imported = ratio_audit_module().normalize_krx_export(csv_path, date)
    manifest = EXPORTS/(date+'.source.json')
    metadata = read_json(manifest) if manifest.is_file() else None
    report = run_check(feed, read_json(p3_path), read_json(p2_path), parsed, sha(csv_path), imported, metadata)
    report['input_digest_sha256'] = {
        'research_feed': sha(feed_path), 'stage54_p3': sha(p3_path),
        'stage55_p2': sha(p2_path)}
    target = ROOT/('r14_stage56_ratio_intake_'+date+'.json')
    if publish:
        if target.exists():
            require(read_json(target)==report, 'IMMUTABLE_REPORT_CONFLICT')
        else:
            target.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print('STAGE56_RATIO_EXPORT_AUDITED_RESEARCH_ONLY',json.dumps({
        'research_market_date':date,'candidates':report['candidate_count'],
        'research_only_value_matches':report['candidate_result_counts'].get('matched_numeric_research_only',0),
        'official_verified':0,'buy_signals':0,'saved':publish}))


def self_test():
    feed={'research_market_date':'20261120','candidate_count':2,
        'final_buy_signals':0,'investment_decisions_authorized':False,
        'candidates':[{'code':'000270'},{'code':'000050'}]}
    p3={'research_market_date':'20261120','p3_independently_proven_asof':False,
        'candidate_count':2,'final_buy_signals':0}
    p2={'research_market_date':'20261120','candidate_count':2,
        'p2_official_per_verified_count':0,'p2_official_pbr_verified_count':0,
        'final_buy_signals':0,'authorized_trade_decisions':False}
    sha256='a'*64
    rows=[{'code':'000270','market_date':'20261120',
           'official_per':'9.2','official_pbr':'0.8',
           'date_basis':'FILE_ROW','source':'KRX_DATA_MARKETPLACE_EXPORT_USER_SUPPLIED'},
          {'code':'000050','market_date':'20261120',
           'official_per':'-', 'official_pbr':'0.4',
           'date_basis':'OPERATOR_DECLARED','source':'KRX_DATA_MARKETPLACE_EXPORT_USER_SUPPLIED'}]
    imp={'source_file_sha256':sha256,'date_is_independently_authenticated':False,
         'source_provenance':'USER_SUPPLIED_NOT_AUTHENTICATED',
         'import_issues':{}}
    from copy import deepcopy
    tests=0
    def check(yes):
        nonlocal tests
        assert yes;tests+=1
    def reject(fn,reason):
        nonlocal tests
        try:fn()
        except ValueError as e: assert reason in str(e),str(e)
        else:raise AssertionError('FAILED_TO_REJECT_'+reason)
        tests+=1
    def build(f=feed,p3v=p3,p2v=p2,rr=rows,ss=sha256, ii=imp,meta=None):
        return run_check(f,p3v,p2v,rr,ss,ii,meta)
    result=build()
    check(result['candidate_count']==2)
    check(result['candidate_result_counts']['matched_numeric_research_only']==1)
    check(result['candidate_result_counts']['missing_or_nonpositive_value']==1)
    check(result['official_per_verified_count']==0)
    check(result['final_buy_signals']==0)
    check(result['raw_ratio_values_published'] is False)
    check('candidate_states' not in result)
    check(result['new_krx_api_requests']==0)
    check(result['source_manifest_provided'] is False)
    check(build(meta={'as_of_date':'20261120','source_file_sha256':sha256})['source_manifest_provided'])
    f=deepcopy(feed);f['final_buy_signals']=1;reject(lambda:build(f=f),'FEED_BUY_GUARD')
    f=deepcopy(feed);f['candidates'].append({'code':'111111'});reject(lambda:build(f=f),'BAD_CANDIDATES')
    f=deepcopy(feed);f['candidates'][0]['code']='000050';reject(lambda:build(f=f),'CANDIDATE_CODES_INVALID')
    f=deepcopy(feed);f['research_market_date']='20261119';reject(lambda:build(f=f),'P3_HISTORICAL_DATE_UNPROVEN')
    p=deepcopy(p3);p['p3_independently_proven_asof']=True;reject(lambda:build(p3v=p),'P3_HISTORICAL_DATE_UNPROVEN')
    p=deepcopy(p2);p['p2_official_per_verified_count']=1;reject(lambda:build(p2v=p),'P2_PROMOTION_FORBIDDEN')
    p=deepcopy(p2);p['final_buy_signals']=1;reject(lambda:build(p2v=p),'P2_PROMOTION_FORBIDDEN')
    r=deepcopy(rows);r.append(deepcopy(rows[0]));reject(lambda:build(rr=r),'EXPORT_DUPLICATED_SHORT_CODES')
    r=deepcopy(rows);r[0]['market_date']='20261119';reject(lambda:build(rr=r),'EXPORT_ROW_DATE_MISMATCH')
    r=deepcopy(rows);r[0]['source']='UNKNOWN';reject(lambda:build(rr=r),'EXPORT_ROW_SOURCE_MISMATCH')
    i=deepcopy(imp);i['import_issues']={'row_date_disagrees_with_declared_date':1};reject(lambda:build(ii=i),'EXPORT_ROW_DATE_MISMATCH')
    i=deepcopy(imp);i['source_file_sha256']='b'*64;reject(lambda:build(ii=i),'PARSER_RAW_SHA_MISMATCH')
    i=deepcopy(imp);i['date_is_independently_authenticated']=True;reject(lambda:build(ii=i),'PARSER_CLAIMED_INDEPENDENT_AUTHENTICATION')
    reject(lambda:build(meta={'as_of_date':'20261119','source_file_sha256':sha256}),'MANIFEST_DATE_MISMATCH')
    reject(lambda:build(meta={'as_of_date':'20261120','source_file_sha256':'b'*64}),'MANIFEST_EXPORT_HASH_MISMATCH')
    print('STAGE56_SELF_TEST_PASS',tests)


if __name__ == '__main__':
    a=argparse.ArgumentParser()
    a.add_argument('--self-test',action='store_true')
    a.add_argument('--publish',action='store_true')
    args=a.parse_args()
    if args.self_test:self_test()
    else:main(publish=args.publish)
