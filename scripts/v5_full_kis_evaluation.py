"""Connect saved KIS archives to the full-market scope, in memory only.
No API, no new grades, no publication of per-stock broker data.
"""
import argparse
import datetime as dt
import json
import os
import re
from collections import Counter
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent
from v5_evaluation_scope import build_scope, validate_scope, validate_stage, file_sha, index, require
from v5_full_financial_evaluation import load_sources, evaluate, csv_rows
from v5_valuation_crosscheck import positive, crosscheck

ELIGIBLE = 'EVALUATE_COMMON_STOCK_RESEARCH_ONLY'
WORKFLOW = '.github/workflows/v5-stage7-sector-valuation.yml'


def reader(root):
    """Reuse the existing authenticated archive reader, without running Stage7 main."""
    p = root / WORKFLOW
    lines = p.read_text(encoding='utf-8').splitlines()
    starts = [i for i, s in enumerate(lines) if s.strip() == "cat > /tmp/krx_stage7.py <<'PYTHON'"]
    require(len(starts) == 1, 'STAGE7_READER_LAYOUT_CHANGED')
    start = starts[0] + 1
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == 'PYTHON')
    ns = {'__name__': '_v5_stage7_reader'}
    exec(compile(dedent('\n'.join(lines[start:end])), str(p), 'exec'), ns)
    ns['ROOT'] = root.resolve()
    require(callable(ns.get('load_broker')) and callable(ns.get('sector_name')), 'STAGE7_READER_MISSING')
    return ns


def link(scope, financial, market_rows, archive, sector_name, reviewed=None):
    universe = validate_scope(scope)
    validate_stage(scope, financial)
    day = scope['market_date']
    market = index(market_rows, 'ISU_CD'); fin = index(financial['rows'], 'code')
    require(set(market) == set(universe) and all(r['BAS_DD'] == day for r in market.values()), 'MARKET_SCOPE_MISMATCH')
    if archive is not None:
        require(archive.get('observation_session') == day, 'ARCHIVE_DATE_MISMATCH')
        require(archive.get('state') in ('KIS_BROKER_COLLECTION_COMPLETE','KIS_BROKER_PARTIAL_CHECKPOINT'), 'ARCHIVE_STATE_MISMATCH')
    obs = archive['observations'] if archive else {}
    rows = []; peers = Counter(); reviewed = reviewed or {}
    for code, sc in sorted(universe.items()):
        state = sc['scope_state']; m = market[code]
        r = {'code':code,'market_date':day,'state':state,'financial_state':fin[code]['state'],
             'arithmetic_consistent':False,'sector_present':False,'provisional_peer_eligible':False,
             'reviewed_crosscheck_consistent':False,'official_ratios_verified':False,'buy_signal':False}
        rows.append(r)
        if state != ELIGIBLE: continue
        if not sc['numeric_provider_code']: r['state']='HOLD_KIS_IDENTIFIER_UNSUPPORTED'; continue
        if archive is None: r['state']='WAIT_FOR_SAME_DATE_KIS_ARCHIVE'; continue
        if archive['state'] != 'KIS_BROKER_COLLECTION_COMPLETE': r['state']='HOLD_PARTIAL_KIS_SESSION'; continue
        q = obs.get(code)
        if q is None: r['state']='HOLD_KIS_OBSERVATION_MISSING'; continue
        sector = sector_name(q.get('sector_name_kis')); r['sector_present'] = sector is not None
        try:
            t=dt.datetime.fromisoformat(q['observed_at_kst'])
            valid=t.tzinfo is not None and t.utcoffset()==dt.timedelta(hours=9) and t.strftime('%Y%m%d')==day
        except (ValueError,TypeError,KeyError): valid=False
        if not valid: r['state']='HOLD_KIS_OBSERVATION_DATE'; continue
        close = positive(m.get('TDD_CLSPRC')); price = positive(q.get('observed_price'))
        if close is None or price != close: r['state']='HOLD_CLOSE_MISMATCH'; continue
        per,pbr,eps,bps = [positive(q.get(k)) for k in ('per','pbr','eps','bps')]
        if None in (per,pbr,eps,bps): r['state']='HOLD_NONPOSITIVE_OR_MISSING_RATIO'; continue
        if abs(per*eps/close-1)>D('.05') or abs(pbr*bps/close-1)>D('.05'):
            r['state']='HOLD_BROKER_ARITHMETIC_MISMATCH'; continue
        r['arithmetic_consistent']=True
        if sector is None: r['state']='HOLD_SECTOR_MISSING'; continue
        r['provisional_peer_eligible']=True; peers[sector]+=1
        r['state']='KIS_PROVISIONAL_LINK_RESEARCH_ONLY'
        # A later reviewed evidence adapter can supply independent accounting/stock count evidence.
        # Never manufacture review flags from receipt links, ratios, or price arithmetic.
        ev=reviewed.get(code)
        if ev is not None:
            result=crosscheck({'code':code,'market_date':day,'share_class':'COMMON','market_cap':m['MKTCAP'],'close':m['TDD_CLSPRC']},
                {**q,'code':code,'market_date':day,'close':price},ev)
            r['reviewed_crosscheck_consistent']=result['state']=='CROSSCHECK_CONSISTENT_RESEARCH_ONLY'
        # Sector and broker values are memory-only and not included in report rows.
    report={'market_date':day,'scope_sha256':scope['scope_sha256'],'rows':rows,
            'financial_api_calls':0,'same_date_archive_loaded':archive is not None,
            'archive_observation_rows':len(obs),'provisional_sector_groups':len(peers),
            'official_ratios_verified':False,'investment_decisions_authorized':False,'final_buy_signals':0}
    report['counts']=validate_stage(scope,report)
    return report


def evaluate_saved(root,scope,financial):
    root=root.resolve(); day=scope['market_date']
    for rel,h in scope['source_sha256'].items():
        p=(root/rel).resolve(); require(p.is_relative_to(root) and file_sha(p)==h,'SCOPE_SOURCE_HASH_MISMATCH')
    for rel,h in financial.get('source_sha256',{}).items():
        p=(root/rel).resolve(); require(p.is_relative_to(root) and file_sha(p)==h,'FINANCIAL_SOURCE_HASH_MISMATCH')
    market=csv_rows(root/'data/latest.csv'); ns=reader(root)
    p=root/'data/v5_kis_valuation/sessions'/day/'observations.aes'
    archive=ns['load_broker'](p,day,os.environ.get('KIS_DATA_ARCHIVE_KEY','')) if p.is_file() else None
    report=link(scope,financial,market,archive,ns['sector_name'])
    report['archive_sha256']=file_sha(p) if archive is not None else None
    return report


def self_test():
    day='20261126'; codes=['000001','000002','000003','000004','000005','000006','000007','000008','00A009']
    market=[{'ISU_CD':c,'BAS_DD':day,'MKTCAP':'1' if c=='000008' else '100000000000','MARKET':'KOSPI','TDD_CLSPRC':'1000'} for c in codes]
    cl={'market_date':day,'row_count':len(codes),'rows':[{'ISU_SRT_CD':c,'market':'KOSPI','KIND_STKCERT_TP_NM':'보통주','SECUGRP_NM':'주권'} for c in codes]}
    scope=build_scope(day,market,cl)
    fin={'market_date':day,'scope_sha256':scope['scope_sha256'],'rows':[{'code':r['code'],'market_date':day,'state':'HOLD_ANNUAL_RECEIPT_EVIDENCE' if r['scope_state']==ELIGIBLE else r['scope_state']} for r in scope['rows']]}
    q={'observed_price':'1000','per':'10','pbr':'1','eps':'100','bps':'1000','sector_name_kis':'fixture','observed_at_kst':'2026-11-26T16:50:00+09:00'}
    obs={c:dict(q) for c in codes[:6]}; obs['000002']['observed_price']='999';obs['000003']['per']='20';obs['000004']['sector_name_kis']='';obs['000005']['observed_at_kst']='2026-11-27T16:50:00+09:00';obs['000006']['eps']='0'
    a={'observation_session':day,'state':'KIS_BROKER_COLLECTION_COMPLETE','observations':obs}
    norm=lambda v:v or None
    rep=link(scope,fin,market,a,norm); rr=index(rep['rows'],'code')
    expected=['KIS_PROVISIONAL_LINK_RESEARCH_ONLY','HOLD_CLOSE_MISMATCH','HOLD_BROKER_ARITHMETIC_MISMATCH','HOLD_SECTOR_MISSING','HOLD_KIS_OBSERVATION_DATE','HOLD_NONPOSITIVE_OR_MISSING_RATIO','HOLD_KIS_OBSERVATION_MISSING','EXCLUDED_MARKET_CAP','HOLD_KIS_IDENTIFIER_UNSUPPORTED']
    for code,state in zip(codes,expected): assert rr[code]['state']==state
    assert rr['000001']['financial_state']=='HOLD_ANNUAL_RECEIPT_EVIDENCE' and not rr['000001']['reviewed_crosscheck_consistent']
    assert link(scope,fin,market,None,norm)['counts']['WAIT_FOR_SAME_DATE_KIS_ARCHIVE']==7
    assert link(scope,fin,market,{**a,'state':'KIS_BROKER_PARTIAL_CHECKPOINT'},norm)['counts']['HOLD_PARTIAL_KIS_SESSION']==7
    for f in (lambda:link(scope,fin,market,{**a,'observation_session':'20261127'},norm),lambda:link(scope,{**fin,'rows':fin['rows'][:-1]},market,a,norm)):
        try:f()
        except ValueError:pass
        else:raise AssertionError('EXPECTED_REJECTION')
    assert all(not any(k in r for k in ('per','pbr','eps','bps','sector_name_kis')) for r in rep['rows'])
    print('FULL_KIS_SELF_TEST_PASS 15')


def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--root',type=Path,default=Path.cwd());a=p.parse_args()
    if a.self_test:self_test();return
    scope,metrics,links,holds,hashes=load_sources(a.root)
    financial=evaluate(scope,metrics,links,holds);financial['source_sha256']=hashes
    r=evaluate_saved(a.root,scope,financial)
    print(json.dumps({k:v for k,v in r.items() if k!='rows'},ensure_ascii=False))

if __name__=='__main__': main()
