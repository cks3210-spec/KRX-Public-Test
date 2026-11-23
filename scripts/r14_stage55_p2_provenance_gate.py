#!/usr/bin/env python3
"""KRX v5 Stage55: read-only P2 provenance gate after Stage54 cached P3 join.

Never calls a network API. Never promotes a KRX-attributed, unsigned CSV to
independently authenticated historical official PER/PBR. Never updates Stage27.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile

ROOT = Path('v5_reports/stage28')
FEED = ROOT / 'r14_eligible_research_candidates.json'
CAPABILITY = ROOT / 'r14_official_ratio_source_capability_audit.json'
SOURCE_DIR = Path('data/v5_official_ratio_exports')
VERSION = 'KRX_V5_STAGE55_P2_P3_PROVENANCE_GATE_V1'
P3_VERSION = 'KRX_V5_STAGE54_P3_CACHED_EVIDENCE_BRIDGE_V1'
CAPABILITY_VERSION = 'R14_KRX_OFFICIAL_RATIO_SOURCE_CONTRACT_V1'


def must(ok, error):
    if not ok:
        raise ValueError('STAGE55_' + error)


def read(path):
    with path.open(encoding='utf-8-sig') as f:
        return json.load(f)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(feed, p3, capability, feed_sha, p3_sha, capability_sha, csv_present=False):
    day = feed.get('research_market_date')
    must(isinstance(day, str) and bool(re.fullmatch(r'20\d{6}', day)), 'RESEARCH_DATE_INVALID')
    rows = feed.get('candidates')
    must(isinstance(rows, list) and len(rows) == feed.get('candidate_count'), 'FEED_COUNT_INVALID')
    must(feed.get('investment_decisions_authorized') is False and feed.get('final_buy_signals') == 0,
         'FEED_TRADE_BLOCK_MISSING')
    must(p3.get('version') == P3_VERSION and p3.get('research_market_date') == day,
         'P3_VERSION_OR_DATE_MISMATCH')
    checks = p3.get('candidate_checks')
    must(isinstance(checks, list) and len(checks) == len(rows) == p3.get('candidate_count'),
         'P3_CANDIDATE_COUNT_MISMATCH')
    must(p3.get('source_digests', {}).get('research_feed_sha256') == feed_sha,
         'P3_UPSTREAM_FEED_HASH_MISMATCH')
    must(p3.get('p3_state') in ('REQUEST_BOUND_RESEARCH_ONLY','SELF_DATED_REVIEW_REQUIRED')
         and p3.get('p3_independently_proven_asof') is False,
         'P3_INDEPENDENT_DATE_PROOF_INVALID')
    must(p3.get('p1_historical_financial_asof_verified_count') == 0
         and p3.get('p2_official_dated_per_pbr_verified_count') == 0
         and p3.get('investment_decisions_authorized') is False
         and p3.get('final_buy_signals') == 0, 'P3_PROMOTION_FORBIDDEN')
    feed_index = {}
    for r in rows:
        code = r.get('code')
        must(isinstance(code,str) and bool(re.fullmatch(r'[A-Z0-9]{6}',code)) and code not in feed_index,
             'FEED_DUPLICATE_OR_BAD_CODE')
        must(r.get('market_date') == day and r.get('grade') in ('A','B','B+')
             and r.get('buy_signal') is False and r.get('actionable_entry_price') is False,
             'FEED_GRADE_OR_DATE_INVALID')
        feed_index[code]=r
    p3_index = {}
    for row in checks:
        code = row.get('code')
        must(code in feed_index and code not in p3_index
             and row.get('grade') == feed_index[code].get('grade'), 'P3_ROW_MISMATCH_OR_DUPLICATE')
        must(row.get('p2_official_dated_per_pbr_verified') is False
             and row.get('p1_historical_financial_asof_verified') is False
             and row.get('actionable_buy_signal') is False,
             'P3_ROW_FALSE_OFFICIAL_PROMOTION')
        p3_index[code]=row
    must(set(feed_index)==set(p3_index), 'P3_CANDIDATE_UNIVERSE_MISMATCH')
    must(sum(bool(r.get('class_and_class_cap_request_bound_match')) for r in checks)
         == p3.get('candidate_class_cap_request_bound_matches'), 'P3_CLASS_COUNT_MISMATCH')
    must(capability.get('version') == CAPABILITY_VERSION, 'P2_SOURCE_CONTRACT_UNRECOGNIZED')
    must(capability.get('research_market_date') == day, 'P2_SOURCE_REPORT_DATE_STALE')
    must(capability.get('upstream_filtered_candidate_count') == len(rows), 'P2_UNIVERSE_STALE')
    must(capability.get('independently_authenticated_official_per') == 0
         and capability.get('independently_authenticated_official_pbr') == 0
         and capability.get('official_verified_candidate_count') == 0
         and capability.get('final_buy_signals') == 0
         and capability.get('investment_decisions_authorized') is False,
         'P2_SOURCE_REPORT_UNSAFE')
    source = capability.get('source_import', {})
    must(isinstance(source,dict) and source.get('independent_source_authentication') is False,
         'P2_SOURCE_IDENTITY_UNPROVEN')
    must(capability.get('krx_open_api_per_pbr_capability') == 'NOT_LISTED_AS_AVAILABLE_API_SERVICE',
         'P2_KRX_API_CATALOGUE_STATE_CHANGED_RECHECK_REQUIRED')
    # For any newly supplied CSV, the stored Stage32 provenance audit must be rerun
    # in a separately authorized source-review step, never silently trusted here.
    csv_state = 'UPLOADED_EXPORT_REQUIRES_FRESH_AUDIT' if csv_present else 'NO_DATE_MATCHED_PROVIDER_EXPORT'
    return {'version': VERSION, 'research_market_date':day,
      'source_contract': 'KRX_MARKETPLACE_EXPORT_SEPARATE_FROM_KRX_OPEN_API',
      'candidate_count': len(rows),
      'p3_request_bound_common_cap_matches': p3['candidate_class_cap_request_bound_matches'],
      'p3_historical_asof_verified': False,
      'p3_state': p3['p3_state'],
      'p2_source_import_last_audit_state': source.get('status','UNKNOWN'),
      'p2_source_file_state': csv_state,
      'p2_provider_origin_independently_authenticated': False,
      'p2_historical_market_date_independently_authenticated': False,
      'p2_official_per_verified_count': 0, 'p2_official_pbr_verified_count':0,
      'p1_historical_financial_asof_verified_count':0,
      'p2_status':'BLOCKED_AUTHENTICATED_DATED_PROVIDER_SOURCE_NOT_AVAILABLE',
      'authorized_trade_decisions':False, 'final_buy_signals':0,
      'new_krx_api_requests':0, 'new_dart_api_requests':0,
      'source_integrity': {'feed_sha256': feed_sha,
           'stage54_p3_report_sha256':p3_sha,'prior_ratio_capability_report_sha256':capability_sha},
      'candidate_states': [{'code': code,
            'grade_research_only':feed_index[code]['grade'],
            'p3':p3_index[code]['p3_qualification'],
            'p2':'NO_INDEPENDENTLY_AUTHENTICATED_DATED_RATIO',
            'buy_signal':False} for code in sorted(feed_index)],
      'next_step':'VERIFY_AUTHORIZED_OFFICIAL_PER_PBR_DISTRIBUTION_CHANNEL_AND_DATE_EVIDENCE',
      'no_stock_price_or_ratio_estimate_automatically_promoted':True}


def run(publish=False):
    must(FEED.is_file(), 'RESEARCH_FEED_MISSING')
    feed = read(FEED); day = feed.get('research_market_date')
    must(isinstance(day,str) and bool(re.fullmatch(r'20\d{6}',day)), 'RESEARCH_DATE_INVALID')
    p3path = ROOT / ('r14_stage54_p3_cached_evidence_'+day+'.json')
    must(p3path.is_file(), 'CACHED_P3_OUTPUT_MISSING')
    must(CAPABILITY.is_file(), 'P2_SOURCE_CAPABILITY_AUDIT_MISSING')
    report = build(feed,read(p3path),read(CAPABILITY),digest(FEED),digest(p3path),digest(CAPABILITY),
                   csv_present=(SOURCE_DIR/(day+'.csv')).is_file())
    out = ROOT/('r14_stage55_p2_provenance_gate_'+day+'.json')
    if publish:
        if out.exists():
            must(read(out)==report, 'PREVIOUS_DATE_REPORT_IMMUTABLE_CONFLICT')
        else:
            with out.open('x',encoding='utf-8') as f:
                json.dump(report,f,ensure_ascii=False,sort_keys=True,separators=(',',':'))
                f.write('\n')
    print('STAGE55_P2_PROVENANCE_BLOCKED_AS_EXPECTED',json.dumps({
        'market_date':day,'candidates':report['candidate_count'],
        'p3_request_bound_matches':report['p3_request_bound_common_cap_matches'],
        'p2_verified':0,'final_buy_signals':0,'new_api_requests':0,
        'saved':publish},sort_keys=True))


def tests():
    date='20261120';sha='a'*64
    feed={'research_market_date':date,'candidate_count':2,
      'investment_decisions_authorized':False,'final_buy_signals':0,
      'candidates':[{'code':'000270','market_date':date,'grade':'A','buy_signal':False,'actionable_entry_price':False},
                    {'code':'000050','market_date':date,'grade':'B','buy_signal':False,'actionable_entry_price':False}]}
    checks=[{'code':r['code'],'grade':r['grade'],'p3_qualification':'REQUEST_BOUND_RESEARCH_ONLY',
      'p2_official_dated_per_pbr_verified':False,'p1_historical_financial_asof_verified':False,
      'actionable_buy_signal':False,'class_and_class_cap_request_bound_match':True} for r in feed['candidates']]
    p3={'version':P3_VERSION,'research_market_date':date,'candidate_count':2,
      'candidate_checks':checks,'candidate_class_cap_request_bound_matches':2,
      'source_digests':{'research_feed_sha256':sha},'p3_state':'REQUEST_BOUND_RESEARCH_ONLY',
      'p3_independently_proven_asof':False,'p1_historical_financial_asof_verified_count':0,
      'p2_official_dated_per_pbr_verified_count':0,'final_buy_signals':0,
      'investment_decisions_authorized':False}
    capability={'version':CAPABILITY_VERSION,'research_market_date':date,'upstream_filtered_candidate_count':2,
      'independently_authenticated_official_per':0,'independently_authenticated_official_pbr':0,
      'official_verified_candidate_count':0,'final_buy_signals':0,
      'investment_decisions_authorized':False,
      'krx_open_api_per_pbr_capability':'NOT_LISTED_AS_AVAILABLE_API_SERVICE',
      'source_import':{'independent_source_authentication':False,'status':'DATE_MATCHED_FILE_NOT_SUPPLIED'}}
    def b(f=feed,p=p3,c=capability,h=sha,uploaded=False):
        return build(f,p,c,h,sha,sha,csv_present=uploaded)
    n=0
    def yes(ok):
        nonlocal n
        assert ok;n+=1
    def rejects(fn,token):
        nonlocal n
        try:fn()
        except ValueError as e:assert token in str(e),str(e)
        else:raise AssertionError('FAILED_TO_BLOCK_'+token)
        n+=1
    good=b();yes(good['candidate_count']==2);yes(good['p3_request_bound_common_cap_matches']==2)
    yes(good['p2_official_per_verified_count']==0);yes(good['final_buy_signals']==0)
    yes(good['new_krx_api_requests']==0);yes(len(good['candidate_states'])==2)
    yes(b(uploaded=True)['p2_source_file_state']=='UPLOADED_EXPORT_REQUIRES_FRESH_AUDIT')
    c=copy.deepcopy(capability);c['independently_authenticated_official_per']=1
    rejects(lambda:b(c=c),'P2_SOURCE_REPORT_UNSAFE')
    c=copy.deepcopy(capability);c['source_import']['independent_source_authentication']=True
    rejects(lambda:b(c=c),'P2_SOURCE_IDENTITY_UNPROVEN')
    c=copy.deepcopy(capability);c['research_market_date']='20261119'
    rejects(lambda:b(c=c),'P2_SOURCE_REPORT_DATE_STALE')
    c=copy.deepcopy(capability);c['upstream_filtered_candidate_count']=1
    rejects(lambda:b(c=c),'P2_UNIVERSE_STALE')
    c=copy.deepcopy(capability);c['krx_open_api_per_pbr_capability']='AVAILABLE'
    rejects(lambda:b(c=c),'P2_KRX_API_CATALOGUE_STATE_CHANGED_RECHECK_REQUIRED')
    p=copy.deepcopy(p3);p['source_digests']['research_feed_sha256']='b'*64
    rejects(lambda:b(p=p),'P3_UPSTREAM_FEED_HASH_MISMATCH')
    p=copy.deepcopy(p3);p['p3_independently_proven_asof']=True
    rejects(lambda:b(p=p),'P3_INDEPENDENT_DATE_PROOF_INVALID')
    p=copy.deepcopy(p3);p['candidate_checks'][0]['p2_official_dated_per_pbr_verified']=True
    rejects(lambda:b(p=p),'P3_ROW_FALSE_OFFICIAL_PROMOTION')
    p=copy.deepcopy(p3);p['candidate_checks'].append(copy.deepcopy(p['candidate_checks'][0]))
    rejects(lambda:b(p=p),'P3_CANDIDATE_COUNT_MISMATCH')
    p=copy.deepcopy(p3);p['candidate_checks'][0]['code']='999999'
    rejects(lambda:b(p=p),'P3_ROW_MISMATCH_OR_DUPLICATE')
    f=copy.deepcopy(feed);f['candidates'][0]['buy_signal']=True
    rejects(lambda:b(f=f),'FEED_GRADE_OR_DATE_INVALID')
    f=copy.deepcopy(feed);f['candidates'][0]['grade']='C'
    rejects(lambda:b(f=f),'FEED_GRADE_OR_DATE_INVALID')
    f=copy.deepcopy(feed);f['final_buy_signals']=1
    rejects(lambda:b(f=f),'FEED_TRADE_BLOCK_MISSING')
    p=copy.deepcopy(p3);p['candidate_class_cap_request_bound_matches']=1
    rejects(lambda:b(p=p),'P3_CLASS_COUNT_MISMATCH')
    return n


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--self-test',action='store_true')
    ap.add_argument('--publish',action='store_true')
    opts=ap.parse_args()
    if opts.self_test:
        print('STAGE55_SELF_TEST_PASS',tests())
    else:run(publish=opts.publish)
