#!/usr/bin/env python3
"""Stage57 read-only official PER/PBR source-route readiness audit.

No API request, website scraping, or publishing KRX provider ratio rows.
An HTTP link, downloaded CSV, filename, source string, or operator manifest
alone is NOT proof of provider origin nor historical point-in-time dates.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path('v5_reports/stage28')
VERSION = 'KRX_V5_STAGE57_AUTHORIZED_P2_ROUTE_AUDIT_V1'
CATALOG_URL = 'https://openapi.krx.co.kr/contents/OPP/INFO/service/OPPINFO004.cmd'
MARKETPLACE_URL = 'https://data.krx.co.kr/'
KIND_URL = 'https://kind.krx.co.kr/valueup/invstindicstocks.do?method=valueupInvstIndicRankIsuMain'


def insist(test, msg):
    if not test:
        raise ValueError('STAGE57_' + msg)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evaluate(feed, p3, p2, cap, acquisition, hashes):
    """Return a public-safe route status with no source rows or stock-level ratios."""
    day = feed.get('research_market_date')
    insist(isinstance(day, str) and re.fullmatch(r'20\d{6}', day), 'DATE_FORMAT')
    candidates = feed.get('candidates')
    insist(isinstance(candidates, list) and len(candidates) == feed.get('candidate_count'), 'FEED_COUNT')
    insist(feed.get('investment_decisions_authorized') is False and feed.get('final_buy_signals') == 0,
           'RESEARCH_FEED_HAS_BUY_SIGNAL')
    code = [c.get('code') for c in candidates]
    insist(all(isinstance(c, str) and re.fullmatch(r'[A-Z0-9]{6}', c) for c in code)
           and len(set(code)) == len(code), 'DUPLICATE_OR_INVALID_CODES')
    insist(p3.get('research_market_date') == day and p3.get('candidate_count') == len(code),
           'STAGE54_DATE_OR_COUNT')
    insist(p3.get('p3_state') == 'REQUEST_BOUND_RESEARCH_ONLY' and
           p3.get('p3_independently_proven_asof') is False and
           p3.get('candidate_class_cap_request_bound_matches') == len(code), 'STAGE54_P3_NOT_RESEARCH_ONLY')
    insist(p3.get('new_api_requests') == 0 and p3.get('final_buy_signals') == 0 and
           p3.get('investment_decisions_authorized') is False, 'STAGE54_MUTATION')
    p3_codes = [c.get('code') for c in p3.get('candidate_checks', [])]
    insist(sorted(p3_codes) == sorted(code), 'STAGE54_CANDIDATES_CHANGED')
    insist(p2.get('research_market_date') == day and p2.get('candidate_count') == len(code),
           'STAGE55_DATE_OR_COUNT')
    insist(p2.get('p2_status') == 'BLOCKED_AUTHENTICATED_DATED_PROVIDER_SOURCE_NOT_AVAILABLE'
           and p2.get('p2_official_per_verified_count') == 0
           and p2.get('p2_official_pbr_verified_count') == 0
           and p2.get('p2_provider_origin_independently_authenticated') is False
           and p2.get('p2_historical_market_date_independently_authenticated') is False,
           'STAGE55_P2_PROOF_NOT_BLOCKED')
    insist(p2.get('final_buy_signals') == 0 and p2.get('authorized_trade_decisions') is False,
           'STAGE55_TRADE_PROMOTION')
    p2_codes = [c.get('code') for c in p2.get('candidate_states', [])]
    insist(sorted(p2_codes) == sorted(code), 'STAGE55_CANDIDATES_CHANGED')
    insist(cap.get('research_market_date') == day and cap.get('upstream_filtered_candidate_count') == len(code),
           'CAPABILITY_AUDIT_DATE_OR_COUNT')
    insist(cap.get('krx_open_api_per_pbr_capability') == 'NOT_LISTED_AS_AVAILABLE_API_SERVICE',
           'API_CATALOG_CAPABILITY_CHANGED_REVIEW_NEEDED')
    insist(cap.get('independently_authenticated_official_per') == 0 and
           cap.get('independently_authenticated_official_pbr') == 0, 'CAPABILITY_AUDIT_OVERCLAIM')
    insist(acquisition.get('research_market_date') == day and
           acquisition.get('research_candidates_preserved') == len(code), 'ACQUISITION_PLAN_DATE_OR_COUNT')
    insist(acquisition.get('official_feed_ready') is False and
           acquisition.get('official_per_pbr_verified') == 0 and
           acquisition.get('investment_decisions_authorized') is False, 'ACQUISITION_PLAN_OVERCLAIM')
    for name in ('feed', 'p3', 'p2', 'cap', 'acquisition'):
        insist(re.fullmatch(r'[0-9a-f]{64}', str(hashes.get(name, ''))) is not None,
               'MISSING_SOURCE_SHA256_' + name.upper())
    insist(p3.get('source_digests', {}).get('research_feed_sha256') == hashes['feed'],
           'P3_RESEARCH_DIGEST_DRIFT')
    insist(p2.get('source_integrity', {}).get('stage54_p3_report_sha256') == hashes['p3'] and
           p2.get('source_integrity', {}).get('feed_sha256') == hashes['feed'],
           'P2_UPSTREAM_DIGEST_DRIFT')
    return {
        'version': VERSION, 'research_market_date': day,
        'candidate_count': len(code), 'p3_request_bound_research_matches': len(code),
        'route_state': 'AWAITING_AUTHORIZED_OFFICIAL_DATED_RATIO_DISTRIBUTION',
        'source_routes': [
            {'route': 'KRX_OPEN_API', 'url': CATALOG_URL, 'official_dated_per_pbr_available': False,
             'status': 'NO_PUBLISHED_STOCK_PER_PBR_ENDPOINT_IN_REVIEWED_CATALOG',
             'discovery_only': True},
            {'route': 'KRX_DATA_MARKETPLACE', 'url': MARKETPLACE_URL,
             'status': 'WEB_STATISTICS_ACCESS_NOT_EQUIVALENT_TO_APPROVED_PROGRAMMATIC_FEED',
             'provider_permission_documented': False, 'independent_date_proof_present': False},
            {'route': 'KIND_VALUEUP_INDICATORS', 'url': KIND_URL,
             'status': 'SEPARATE_QUARTERLY_BASED_INDICATORS_NOT_INTERCHANGEABLE_WITH_MARKETPLACE_DAILY_RATIOS',
             'provider_permission_documented': False, 'independent_date_proof_present': False}
        ],
        'stage56_accepted_source': 'USER_SUPPLIED_RESEARCH_ONLY_UNTIL_PROVIDER_PROVENANCE_VERIFIED',
        'required_proof_for_future_official_approval': [
            'DOCUMENTED_DISTRIBUTION_PERMISSION_AND_PUBLICATION_SCOPE',
            'AUTHENTIC_PROVIDER_ORIGIN_OR_LICENSED_FEED_CONTRACT',
            'PROVIDER_ATTESTED_ROW_EFFECTIVE_DATE_FOR_TARGET_MARKET_DATE',
            'MATCHED_STOCK_CODE_MARKET_AND_UNMODIFIED_SOURCE_DIGEST',
            'KNOWN_VALUATION_FORMULA_AND_FINANCIAL_REPORTING_BASIS'
        ],
        'published_raw_ratio_data': False,
        'per_stock_ratio_values_in_public_report': False,
        'source_digests_sha256': dict(sorted(hashes.items())),
        'p1_historical_financial_asof_verified_count': 0,
        'p2_official_per_verified_count': 0,
        'p2_official_pbr_verified_count': 0,
        'p3_historical_asof_independently_verified': False,
        'investment_decisions_authorized': False, 'final_buy_signals': 0,
        'new_krx_api_requests': 0, 'new_dart_api_requests': 0,
        'new_unapproved_web_requests': 0,
        'next_step': 'OBTAIN_AUTHORIZED_KRX_P2_SOURCE_ACCESS_AND_EFFECTIVE_DATE_EVIDENCE; THEN_RUN_STAGE56'
    }


def run(publish=False, root=ROOT):
    root = Path(root)
    paths = {
        'feed': root/'r14_eligible_research_candidates.json',
        'cap': root/'r14_official_ratio_source_capability_audit.json',
        'acquisition': root/'r14_official_ratio_acquisition_plan.json'
    }
    for label, path in paths.items():
        insist(path.is_file(), 'MISSING_'+label.upper())
    feed = load(paths['feed'])
    day = feed.get('research_market_date')
    insist(isinstance(day, str) and re.fullmatch(r'20\d{6}', day), 'DATE_FORMAT')
    paths['p3'] = root/('r14_stage54_p3_cached_evidence_'+day+'.json')
    paths['p2'] = root/('r14_stage55_p2_provenance_gate_'+day+'.json')
    for label, path in paths.items():
        insist(path.is_file(), 'MISSING_'+label.upper())
    inputs = {label: load(path) for label, path in paths.items()}
    hashes = {label: digest(path) for label, path in paths.items()}
    report = evaluate(inputs['feed'], inputs['p3'], inputs['p2'], inputs['cap'],inputs['acquisition'], hashes)
    target = root/('r14_stage57_official_ratio_route_'+day+'.json')
    if publish:
        if target.exists():
            insist(load(target) == report, 'IMMUTABLE_REPORT_CONFLICT')
        else:
            with target.open('x', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, sort_keys=True, indent=2)
                f.write('\n')
    print('STAGE57_RATIO_SOURCE_ROUTE_RESEARCH_ONLY', json.dumps({
        'asof': day, 'candidates': len(inputs['feed']['candidates']),
        'official_per_pbr_verified': 0, 'final_buy_signals': 0,
        'new_api_requests': 0, 'report_saved': publish}, sort_keys=True))
    return report


def self_test():
    d='20261120'; codes=['000050','000270']; h=lambda n: (str(n)*64)
    feed={'research_market_date':d,'candidate_count':2,'candidates':[{'code':x} for x in codes],
          'investment_decisions_authorized':False,'final_buy_signals':0}
    p3={'research_market_date':d,'candidate_count':2,'p3_state':'REQUEST_BOUND_RESEARCH_ONLY',
        'p3_independently_proven_asof':False,'candidate_class_cap_request_bound_matches':2,
        'new_api_requests':0,'final_buy_signals':0,'investment_decisions_authorized':False,
        'candidate_checks':[{'code':x} for x in codes],
        'source_digests':{'research_feed_sha256':h(1)}}
    p2={'research_market_date':d,'candidate_count':2,
        'p2_status':'BLOCKED_AUTHENTICATED_DATED_PROVIDER_SOURCE_NOT_AVAILABLE',
        'p2_official_per_verified_count':0,'p2_official_pbr_verified_count':0,
        'p2_provider_origin_independently_authenticated':False,
        'p2_historical_market_date_independently_authenticated':False,
        'final_buy_signals':0,'authorized_trade_decisions':False,
        'candidate_states':[{'code':x} for x in codes],
        'source_integrity':{'stage54_p3_report_sha256':h(2),'feed_sha256':h(1)}}
    cap={'research_market_date':d,'upstream_filtered_candidate_count':2,
         'krx_open_api_per_pbr_capability':'NOT_LISTED_AS_AVAILABLE_API_SERVICE',
         'independently_authenticated_official_per':0,'independently_authenticated_official_pbr':0}
    acq={'research_market_date':d,'research_candidates_preserved':2,
         'official_feed_ready':False,'official_per_pbr_verified':0,'investment_decisions_authorized':False}
    hashes={'feed':h(1),'p3':h(2),'p2':h(3),'cap':h(4),'acquisition':h(5)}
    import copy
    total=0
    def succeeds(test):
        nonlocal total
        assert test; total+=1
    def rejects(changes, expected):
        nonlocal total
        args = [copy.deepcopy(x) for x in (feed,p3,p2,cap,acq,hashes)]
        changes(*args)
        try:evaluate(*args)
        except ValueError as err:assert expected in str(err),str(err)
        else:raise AssertionError('NOT_REJECTED_'+expected)
        total+=1
    r=evaluate(feed,p3,p2,cap,acq,hashes)
    succeeds(r['candidate_count']==2)
    succeeds(r['final_buy_signals']==0)
    succeeds(r['p2_official_per_verified_count']==0)
    succeeds(r['new_krx_api_requests']==0)
    succeeds(r['published_raw_ratio_data'] is False)
    succeeds(len(r['source_routes'])==3)
    succeeds(len(r['required_proof_for_future_official_approval'])==5)
    rejects(lambda f,*a:f.update(final_buy_signals=1),'RESEARCH_FEED_HAS_BUY_SIGNAL')
    rejects(lambda f,*a:f['candidates'].append({'code':'123456'}),'FEED_COUNT')
    rejects(lambda f,*a:f['candidates'][0].update(code='000270'),'DUPLICATE_OR_INVALID_CODES')
    rejects(lambda f,p,*a:p.update(p3_independently_proven_asof=True),'STAGE54_P3_NOT_RESEARCH_ONLY')
    rejects(lambda f,p,*a:p['candidate_checks'][0].update(code='111111'),'STAGE54_CANDIDATES_CHANGED')
    rejects(lambda f,p,q,*a:q.update(p2_official_per_verified_count=1),'STAGE55_P2_PROOF_NOT_BLOCKED')
    rejects(lambda f,p,q,*a:q.update(p2_historical_market_date_independently_authenticated=True),'STAGE55_P2_PROOF_NOT_BLOCKED')
    rejects(lambda f,p,q,*a:q['candidate_states'][0].update(code='111111'),'STAGE55_CANDIDATES_CHANGED')
    rejects(lambda f,p,q,c,*a:c.update(krx_open_api_per_pbr_capability='PRESENT'),'API_CATALOG_CAPABILITY_CHANGED_REVIEW_NEEDED')
    rejects(lambda f,p,q,c,a,*z:a.update(official_feed_ready=True),'ACQUISITION_PLAN_OVERCLAIM')
    rejects(lambda f,p,q,c,a,s:s.update(feed=h(6)),'P3_RESEARCH_DIGEST_DRIFT')
    rejects(lambda f,p,q,c,a,s:s.update(p3=h(6)),'P2_UPSTREAM_DIGEST_DRIFT')
    # Publication is deterministic and idempotent: no API and no historical overwrite.
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='krx_stage57_') as t:
        base=Path(t)
        f=copy.deepcopy(feed)
        q=copy.deepcopy(p3)
        z=copy.deepcopy(p2)
        def store(name,obj):
            path=base/name
            path.write_text(json.dumps(obj,ensure_ascii=False,sort_keys=True)+'\n',encoding='utf-8')
            return digest(path)
        fh=store('r14_eligible_research_candidates.json',f)
        q['source_digests']['research_feed_sha256']=fh
        qh=store('r14_stage54_p3_cached_evidence_'+d+'.json',q)
        z['source_integrity']['feed_sha256']=fh
        z['source_integrity']['stage54_p3_report_sha256']=qh
        store('r14_stage55_p2_provenance_gate_'+d+'.json',z)
        store('r14_official_ratio_source_capability_audit.json',cap)
        store('r14_official_ratio_acquisition_plan.json',acq)
        first=run(publish=True,root=base)
        second=run(publish=True,root=base)
        succeeds(first==second)
        target=base/('r14_stage57_official_ratio_route_'+d+'.json')
        succeeds(target.is_file() and load(target)['final_buy_signals']==0)
        target.write_text('{}\n',encoding='utf-8')
        try:run(publish=True,root=base)
        except ValueError as err:
            assert 'IMMUTABLE_REPORT_CONFLICT' in str(err);total+=1
        else:raise AssertionError('STAGE57_FROZEN_REPORT_WAS_OVERWRITTEN')
    print('STAGE57_SELF_TEST_PASS',total)
    return total


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if args.self_test:self_test()
    else:run(publish=args.publish)
