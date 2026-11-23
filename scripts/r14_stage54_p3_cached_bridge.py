#!/usr/bin/env python3
"""Stage54: promote ONLY verifiable joins from the immutable Stage53 P3 snapshot.

Does not call an API. A request-bound snapshot is not historical as-of proof.
Writes one date-scoped derived research report without modifying the source ledger.
"""
import argparse, collections, csv, datetime, hashlib, json, re, tempfile
from pathlib import Path

ROOT = Path('v5_reports/stage28')
FEED = ROOT / 'r14_eligible_research_candidates.json'
MARKET = Path('data/v5_official_market_archive')
BASIC = Path('data/v5_official_shareclass_archive')
PAT = re.compile(r'^[A-Z0-9]{6}$')
HEX = re.compile(r'^[0-9a-f]{64}$')
EXPECTED = 'KRX_V5_STAGE53_OFFICIAL_BASIC_CAPTURE_V1'
OUTPUT_VERSION = 'KRX_V5_STAGE54_P3_CACHED_EVIDENCE_BRIDGE_V1'
MATCH = 'KRX_OFFICIAL_COMMON_AND_CLASS_SPECIFIC_CAP_MATCHED'


def must(value, reason):
    if not value:
        raise ValueError('STAGE54_' + reason)


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(p):
    with p.open(encoding='utf-8-sig') as f:
        return json.load(f)


def qty(n):
    s = str(n).replace(',', '').strip()
    return int(s) if s.isdecimal() and int(s)>0 else None


def preview(feedpath=FEED, marketroot=MARKET, basicroot=BASIC):
    must(feedpath.is_file(), 'RESEARCH_FEED_MISSING')
    feed = load(feedpath)
    day = feed.get('research_market_date')
    must(isinstance(day, str) and re.fullmatch(r'20\d{6}', day), 'DATE_INVALID')
    datetime.datetime.strptime(day, '%Y%m%d')
    selected = feed.get('candidates')
    must(isinstance(selected, list) and len(selected)==feed.get('candidate_count'), 'CANDIDATE_COUNT_CONFLICT')
    must(feed.get('investment_decisions_authorized') is False and feed.get('final_buy_signals')==0, 'UNSAFE_CANDIDATE_LEDGER')
    dated_market = marketroot / (day + '.csv')
    dated_basic = basicroot / (day + '.json')
    if not dated_market.is_file() or not dated_basic.is_file():
        return None, {'state':'HOLD_DATE_INPUT_NOT_PRESENT','market_date':day,'api_calls':0,
            'market_archive_exists':dated_market.is_file(),'stock_basic_archive_exists':dated_basic.is_file()}
    snapshot = load(dated_basic)
    must(snapshot.get('version')==EXPECTED and snapshot.get('market_date')==day, 'OFFICIAL_BASIC_SOURCE_DATE')
    must(snapshot.get('source')=='KRX_OFFICIAL_OPEN_API_STOCK_BASIC', 'PROVIDER_SOURCE_INVALID')
    must(snapshot.get('api_request_count')==2 and snapshot.get('credential_logged') is False,'CAPTURE_INCOMPLETE_OR_SECRET_EXPOSED')
    must(snapshot.get('investment_decisions_authorized') is False and snapshot.get('final_buy_signals')==0,'UNSAFE_BASIC_SNAPSHOT')
    must(snapshot.get('p1_historical_financial_values_verified') is False and snapshot.get('p2_official_per_pbr_verified') is False,'BASIC_SNAPSHOT_SCOPE_CHANGED')
    rows=snapshot.get('rows')
    must(isinstance(rows,list) and snapshot.get('row_count')==len(rows),'STORED_BASIC_ROWS_INCOMPLETE')
    fingerprint=hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    must(snapshot.get('canonical_rows_sha256')==fingerprint,'STORED_BASIC_ROWS_HASH_CONFLICT')
    evidence=snapshot.get('source_provenance')
    must(isinstance(evidence,dict) and set(evidence)=={'KOSPI','KOSDAQ'},'SOURCE_PROVENANCE_INCOMPLETE')
    must(all(v.get('requested_date')==day and bool(HEX.fullmatch(str(v.get('response_sha256',''))))
        and int(v.get('raw_rows',0))==int(v.get('usable_rows',-1))>0 for v in evidence.values()),'BAD_PROVIDER_PROVENANCE')
    selfdated=all(bool(r.get('BAS_DD')==day) for r in rows)
    must(snapshot.get('all_provider_rows_effective_date_attested') is selfdated
        and snapshot.get('p3_independently_date_verified') is selfdated
        and snapshot.get('p3_research_only_if_not_self_dated') is (not selfdated),'SELF_DATING_FLAG_CONFLICT')
    must(set(snapshot.get('market_cap_comparison_states',{})).issubset({
      MATCH,'CAP_UNDER_1000UK','NON_COMMON_OR_UNKNOWN_CLASS','NON_STOCK_SECURITY_GROUP'}),'BAD_BASIC_CLASS_STATES')
    index={}; board_counts=collections.Counter(); state_counts=collections.Counter()
    for row in rows:
        code=row.get('ISU_SRT_CD')
        if isinstance(code,str) and len(code)==7 and code.startswith('A'): code=code[1:]
        market=row.get('market')
        must(isinstance(code,str) and bool(PAT.fullmatch(code)) and code not in index and market in evidence,'BAD_OR_DUPLICATE_BASIC_CODE')
        must(isinstance(row.get('SECUGRP_NM'),str) and isinstance(row.get('KIND_STKCERT_TP_NM'),str) and row.get('LIST_SHRS') is not None,'BAD_BASIC_SHARECLASS')
        state=row.get('market_cap_comparison_state')
        if state is not None:state_counts[state]+=1
        index[code]=row;board_counts[market]+=1
    must(dict(board_counts)=={k:int(v['usable_rows']) for k,v in evidence.items()},'BOARD_COUNTS_CONFLICT')
    must(dict(state_counts)==snapshot.get('market_cap_comparison_states'),'CLASS_COUNTS_CONFLICT')
    must(state_counts[MATCH]==snapshot.get('market_cap_research_matches'),'BASIC_MATCH_COUNT_CONFLICT')
    with dated_market.open(encoding='utf-8-sig',newline='') as f:
        market_rows=list(csv.DictReader(f))
    must(bool(market_rows) and len(market_rows)==snapshot.get('market_archive',{}).get('market_rows'),'MARKET_ROW_COUNT_CONFLICT')
    must(digest(dated_market)==snapshot.get('market_archive',{}).get('market_archive_sha256'),'MARKET_ARCHIVE_HASH_CHANGED')
    priced={}; mr_counts=collections.Counter()
    for r in market_rows:
        code=r.get('ISU_CD')
        must(r.get('BAS_DD')==day and bool(PAT.fullmatch(str(code))) and code not in priced,'MARKET_DATE_OR_CODE_CONFLICT')
        must(qty(r.get('TDD_CLSPRC')) is not None and qty(r.get('MKTCAP')) is not None,'BAD_MARKET_VALUE')
        mr_counts[r.get('MARKET')]+=1;priced[code]=r
    must(dict(mr_counts)==snapshot.get('market_archive',{}).get('market_row_counts'),'MARKET_BOARD_COUNT_CONFLICT')
    must(len(index)==len(priced) and set(index)==set(priced),'STOCK_BASIC_MARKET_UNIVERSE_MISMATCH')
    audits=[];used=set();missing=[];matches=0
    for c in selected:
        code=c.get('code')
        must(isinstance(code,str) and bool(PAT.fullmatch(code)) and code not in used,'BAD_OR_DUPLICATE_CANDIDATE')
        must(c.get('market_date')==day and c.get('grade') in ('A','B','B+'),'CANDIDATE_DATE_GRADE')
        must(c.get('actionable_entry_price') is False and c.get('buy_signal') is False,'UNSAFE_CANDIDATE')
        used.add(code); basic=index.get(code);price=priced.get(code)
        must(basic is not None and price is not None,'CANDIDATE_NOT_IN_ARCHIVE')
        must(basic['market']==price['MARKET'] and price['ISU_NM'].replace(' ','')==str(c.get('name','')).replace(' ',''), 'NAME_OR_MARKET_MISMATCH')
        must(qty(price['TDD_CLSPRC'])==qty(c.get('close_krw')),'CANDIDATE_CLOSE_MISMATCH')
        must(qty(price['MKTCAP'])>=100_000_000_000,'CANDIDATE_CAP_UNDER_1000UK')
        state=basic.get('market_cap_comparison_state')
        ismatch=(state==MATCH and basic['SECUGRP_NM']=='주권' and basic['KIND_STKCERT_TP_NM']=='보통주')
        matches+=int(ismatch)
        if not ismatch:missing.append(code)
        audits.append({'code':code,'market':basic['market'],'grade':c['grade'],
          'class_and_class_cap_request_bound_match':ismatch,
          'official_basic_effective_date_self_attested':selfdated,
          'p3_qualification':'PROVIDER_SELF_DATED_REVIEW_REQUIRED' if ismatch and selfdated else ('REQUEST_BOUND_RESEARCH_ONLY' if ismatch else 'NOT_VERIFIED'),
          'p1_historical_financial_asof_verified':False,'p2_official_dated_per_pbr_verified':False,
          'actionable_buy_signal':False})
    result={'version':OUTPUT_VERSION,'research_market_date':day,'candidate_count':len(selected),
        'candidate_class_cap_request_bound_matches':matches,'candidate_unverified_codes':missing,
        'official_basic_effective_date_self_attested':selfdated,
        'p3_independently_proven_asof':False, # a dated request alone is not an independent historical attestation
        'p3_state':'REQUEST_BOUND_RESEARCH_ONLY' if not selfdated else 'SELF_DATED_REVIEW_REQUIRED',
        'p1_historical_financial_asof_verified_count':0,'p2_official_dated_per_pbr_verified_count':0,
        'investment_decisions_authorized':False,'final_buy_signals':0,'new_api_requests':0,
        'source_digests':{'research_feed_sha256':digest(feedpath),'market_archive_sha256':digest(dated_market),
                          'official_basic_snapshot_sha256':digest(dated_basic)},
        'source_provenance':evidence,'candidate_checks':audits}
    return result,{'state':result['p3_state'],'market_date':day,'candidate_count':len(selected),
      'request_bound_matches':matches,'p3_independently_proven_asof':False,'p2_verified':0,
      'final_buy_signals':0,'api_calls':0}


def run(write=False):
    report,summary=preview()
    if report is None:
        print('STAGE54_CACHED_EVIDENCE_HOLD',json.dumps(summary,sort_keys=True));return
    if write:
        target=ROOT/('r14_stage54_p3_cached_evidence_'+summary['market_date']+'.json')
        if target.exists():
            must(load(target)==report,'FROZEN_EVIDENCE_CONFLICT')
        else:
            with target.open('x',encoding='utf-8') as f:
                json.dump(report,f,ensure_ascii=False,sort_keys=True,separators=(',',':'))
                f.write('\n')
        summary['saved']=True
    print('STAGE54_CACHED_EVIDENCE_LINK_PASS',json.dumps(summary,sort_keys=True))


def tests():
    n=0
    def ok(v):
        nonlocal n
        assert v;n+=1
    def fail(word,fn):
        nonlocal n
        try:fn()
        except ValueError as e:assert word in str(e),str(e)
        else:raise AssertionError('EXPECTED_'+word)
        n+=1
    with tempfile.TemporaryDirectory() as tmp:
        base=Path(tmp);fr=base/'report.json';market=base/'market';basic=base/'basic';market.mkdir();basic.mkdir()
        day='20261120'; codes=[('000050','경방','KOSPI','7530'),('000270','기아','KOSDAQ','1000')]
        path=market/(day+'.csv')
        with path.open('w',encoding='utf-8',newline='') as f:
            w=csv.writer(f);w.writerow(['BAS_DD','MARKET','ISU_CD','ISU_NM','TDD_CLSPRC','MKTCAP'])
            for code,name,board,close in codes:w.writerow([day,board,code,name,close,100_000_000_000])
        rows=[{'ISU_CD':'KR7'+code+'008','ISU_SRT_CD':code,'ISU_NM':name+'보통주','ISU_ABBRV':name,
          'SECUGRP_NM':'주권','KIND_STKCERT_TP_NM':'보통주','LIST_SHRS':'100000000',
          'market':board,'market_cap_comparison_state':MATCH} for code,name,board,close in codes]
        ref={'KOSPI':{'raw_rows':1,'usable_rows':1,'requested_date':day,'response_sha256':'a'*64},
            'KOSDAQ':{'raw_rows':1,'usable_rows':1,'requested_date':day,'response_sha256':'b'*64}}
        saved={'version':EXPECTED,'market_date':day,'source':'KRX_OFFICIAL_OPEN_API_STOCK_BASIC',
          'source_provenance':ref,'api_request_count':2,'credential_logged':False,
          'investment_decisions_authorized':False,'final_buy_signals':0,
          'p1_historical_financial_values_verified':False,'p2_official_per_pbr_verified':False,
          'all_provider_rows_effective_date_attested':False,'p3_independently_date_verified':False,
          'p3_research_only_if_not_self_dated':True,'rows':rows,'row_count':2,
          'market_archive':{'market_archive_sha256':digest(path),'market_rows':2,'market_row_counts':{'KOSPI':1,'KOSDAQ':1}},
          'market_cap_comparison_states':{MATCH:2},'market_cap_research_matches':2,
          'canonical_rows_sha256':hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
        bp=basic/(day+'.json');bp.write_text(json.dumps(saved,ensure_ascii=False))
        cands=[{'code':code,'name':name,'market_date':day,'close_krw':close,'grade':'A',
          'actionable_entry_price':False,'buy_signal':False} for code,name,board,close in codes]
        feed={'research_market_date':day,'candidates':cands,'candidate_count':2,
          'investment_decisions_authorized':False,'final_buy_signals':0}
        fr.write_text(json.dumps(feed,ensure_ascii=False))
        r,s=preview(fr,market,basic)
        ok(s['request_bound_matches']==2);ok(r['p3_state']=='REQUEST_BOUND_RESEARCH_ONLY')
        ok(r['final_buy_signals']==0 and not r['investment_decisions_authorized'])
        ok(r['p2_official_dated_per_pbr_verified_count']==0)
        ok(len(r['candidate_checks'])==2 and s['api_calls']==0)
        ok(r['source_digests']['official_basic_snapshot_sha256']==digest(bp))
        bp.unlink();z,s=preview(fr,market,basic);ok(z is None and s['state']=='HOLD_DATE_INPUT_NOT_PRESENT')
        bp.write_text(json.dumps(saved,ensure_ascii=False))
        saved['row_count']=3;bp.write_text(json.dumps(saved,ensure_ascii=False))
        fail('STORED_BASIC_ROWS_INCOMPLETE',lambda:preview(fr,market,basic))
        saved['row_count']=2;bp.write_text(json.dumps(saved,ensure_ascii=False))
        saved['all_provider_rows_effective_date_attested']=True;bp.write_text(json.dumps(saved,ensure_ascii=False))
        fail('SELF_DATING_FLAG_CONFLICT',lambda:preview(fr,market,basic))
        saved['all_provider_rows_effective_date_attested']=False;bp.write_text(json.dumps(saved,ensure_ascii=False))
        saved['source_provenance']['KOSPI']['requested_date']='20261119';bp.write_text(json.dumps(saved,ensure_ascii=False))
        fail('BAD_PROVIDER_PROVENANCE',lambda:preview(fr,market,basic))
        saved['source_provenance']['KOSPI']['requested_date']=day;bp.write_text(json.dumps(saved,ensure_ascii=False))
        changed=[dict(x) for x in saved['rows']];changed[0]['ISU_ABBRV']='변조';saved['rows']=changed;bp.write_text(json.dumps(saved,ensure_ascii=False))
        fail('STORED_BASIC_ROWS_HASH_CONFLICT',lambda:preview(fr,market,basic))
        saved['rows']=rows;bp.write_text(json.dumps(saved,ensure_ascii=False))
        feed['candidates'][0]['close_krw']='7999';fr.write_text(json.dumps(feed,ensure_ascii=False))
        fail('CANDIDATE_CLOSE_MISMATCH',lambda:preview(fr,market,basic))
        feed['candidates'][0]['close_krw']='7530';fr.write_text(json.dumps(feed,ensure_ascii=False))
        path.write_text(path.read_text(encoding='utf-8').replace('기아','기아 ')+'\n',encoding='utf-8')
        fail('MARKET_ARCHIVE_HASH_CHANGED',lambda:preview(fr,market,basic))
        ok(qty('100,000')==100000);ok(qty('-1') is None)
    print(json.dumps({'stage':54,'self_tests_passed':n,'status':'PASS'},sort_keys=True))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--check',action='store_true');p.add_argument('--publish',action='store_true')
    a=p.parse_args()
    if a.self_test:tests()
    else:run(a.publish)
