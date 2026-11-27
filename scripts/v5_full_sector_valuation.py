"""Full-scope sector valuation; reuse Stage7 model, no API or trading approvals.
KIS arithmetic-only evidence cannot enter the reviewed comparison pool.
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from decimal import Decimal as D
from v5_evaluation_scope import validate_scope, validate_stage, index, require, file_sha
from v5_full_financial_evaluation import load_sources, evaluate, csv_rows
from v5_full_kis_evaluation import evaluate_saved, reader

ELIGIBLE = 'EVALUATE_COMMON_STOCK_RESEARCH_ONLY'
QUALITY = 'GROWTH_AND_HEALTH_CRITERIA_MET_RESEARCH_ONLY'
KEYS = ('sector_id','sector_type','source_kind','accounting_basis','market_date')
REQUIRED = ('code','market_date','market','share_class','security_group','sector_id',
            'sector_type','source_kind','accounting_basis','sector_evidence_ref',
            'ratio_evidence_ref','class_evidence_ref','sector_date_reviewed',
            'ratio_date_reviewed','class_date_reviewed','basis_reviewed','close_krw',
            'per','pbr','eps','bps')


def read(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))


def reviewed_bundle(root, day):
    root = root.resolve()
    folder = root/'data/v5_stage7_reviewed'/day
    path = folder/'manifest.json'
    if not path.is_file():
        return [], 'NO_REVIEWED_SECTOR_RATIO_BUNDLE', None
    require(path.resolve().is_relative_to(root), 'MANIFEST_OUTSIDE_ROOT')
    m = read(path)
    if not (m.get('market_date') == day and m.get('public_derived_output_reviewed') is True
            and m.get('public_input_use_reviewed') is True
            and m.get('review_state') == 'MANUALLY_REVIEWED_RESEARCH_INPUT'
            and m.get('review_reference')):
        return [], 'HOLD_BUNDLE_REVIEW_OR_PUBLICATION_PERMISSION_MISSING', None
    p = (root/m['csv_path']).resolve()
    require(p.is_relative_to(folder.resolve()) and p.is_relative_to(root) and p.is_file()
            and file_sha(p) == m['csv_sha256'], 'REVIEWED_BUNDLE_HASH_OR_PATH_MISMATCH')
    rows = csv_rows(p)
    require(all(set(REQUIRED) <= set(r) for r in rows), 'REVIEWED_BUNDLE_SCHEMA_MISMATCH')
    return rows, 'REVIEWED_INPUT_ASSERTIONS_ACCEPTED_RESEARCH_ONLY', file_sha(p)


def evaluate_sector(scope, financial, kis, market_rows, reviewed_rows, input_state, model):
    universe = validate_scope(scope)
    validate_stage(scope, financial); validate_stage(scope, kis)
    require(financial.get('investment_decisions_authorized') is False and kis.get('investment_decisions_authorized') is False
            and financial.get('final_buy_signals') == kis.get('final_buy_signals') == 0, 'UNEXPECTED_UPSTREAM_APPROVAL')
    day = scope['market_date']
    market = index(market_rows, 'ISU_CD'); fin = index(financial['rows'],'code'); broker = index(kis['rows'],'code')
    require(set(market) == set(universe) and all(r['BAS_DD']==day for r in market.values()), 'MARKET_SCOPE_MISMATCH')
    reviewed = index(reviewed_rows,'code')
    require(all(set(REQUIRED)<=set(r) for r in reviewed.values()),'REVIEWED_BUNDLE_SCHEMA_MISMATCH')
    qualified = {}; groups = defaultdict(list); rejected = {}
    # The peer universe is ALL eligible stocks, not the old A/B list or quality winners.
    for code, r in reviewed.items():
        if code not in universe or universe[code]['scope_state'] != ELIGIBLE: continue
        if not model['qualify'](r,market[code],day):
            rejected[code]='HOLD_REVIEWED_RATIO_OR_CLASS_CONFLICT'; continue
        # Until the independent KIS evidence adapter binds reviewed ratios to the exact encrypted
        # observation and share/accounting evidence, do not admit broker rows to this pool.
        if r['source_kind']=='KIS_BROKER':
            rejected[code]='HOLD_KIS_INDEPENDENT_EVIDENCE_ADAPTER'; continue
        if r['sector_type']!='GENERAL':
            rejected[code]='HOLD_SPECIAL_SECTOR_MODEL_REQUIRED'; continue
        qualified[code]=r; groups[tuple(r[k] for k in KEYS)].append(r)
    rows=[]
    for code, sc in sorted(universe.items()):
        state=sc['scope_state']
        out={'code':code,'market_date':day,'state':state,'financial_state':fin[code]['state'],
             'kis_state':broker[code]['state'],'peer_count':0,'verified_fair_price':None,
             'final_grade':None,'buy_signal':False,'investment_authorized':False}
        rows.append(out)
        if state!=ELIGIBLE: continue
        if code not in qualified:
            out['state']=rejected.get(code,'HOLD_SECTOR_OR_RATIO_EVIDENCE'); continue
        target=qualified[code]
        peers=[p for p in groups[tuple(target[k] for k in KEYS)] if model['comparable'](target,p)]
        out['peer_count']=len(peers)
        # Apply existing conservative Stage7 model even to new non-A/B stocks.
        estimate=model['estimate'](target,peers); out.update(estimate)
        # Quality is tracked independently and must pass for future decision eligibility.
        out['quality_pass']=fin[code]['state']==QUALITY
    report={'market_date':day,'scope_sha256':scope['scope_sha256'],'rows':rows,
            'reviewed_input_state':input_state,'eligible_reviewed_peer_rows':len(qualified),
            'reviewed_peer_groups':len(groups),'financial_api_calls':0,
            'official_ratios_verified':False,'verified_fair_prices':0,
            'investment_decisions_authorized':False,'final_buy_signals':0,
            'notes':['Stage7 PE/PB overlap model reused, minimum eight other comparable stocks.',
                     'All eligible stocks evaluated or explicitly held; old A/B list not used.',
                     'Reviewed assertions are not independent verification; KIS broker inputs withheld pending independent binding.',
                     'Special sector models remain withheld. No raw broker values or per-stock research ranges printed.']}
    report['counts']=validate_stage(scope,report)
    return report


def evaluate_saved_sector(root,scope,financial,kis):
    root=root.resolve()
    for sources in (scope['source_sha256'],financial.get('source_sha256',{})):
        for rel,h in sources.items():
            p=(root/rel).resolve(); require(p.is_relative_to(root) and file_sha(p)==h,'SOURCE_HASH_MISMATCH')
    data,state,h=reviewed_bundle(root,scope['market_date'])
    report=evaluate_sector(scope,financial,kis,csv_rows(root/'data/latest.csv'),data,state,reader(root))
    report['reviewed_input_sha256']=h
    return report


def self_test(model):
    from v5_evaluation_scope import build_scope
    day='20261126'; codes=[f'{i:06d}' for i in range(1,14)]
    market=[{'ISU_CD':c,'BAS_DD':day,'MKTCAP':'1' if c==codes[-1] else '100000000000','MARKET':'KOSPI','TDD_CLSPRC':'1000'} for c in codes]
    cl={'market_date':day,'row_count':len(codes),'rows':[{'ISU_SRT_CD':c,'market':'KOSPI','KIND_STKCERT_TP_NM':'보통주','SECUGRP_NM':'주권'} for c in codes]}
    scope=build_scope(day,market,cl)
    def upstream(state):
        return {'market_date':day,'scope_sha256':scope['scope_sha256'],'investment_decisions_authorized':False,'final_buy_signals':0,'rows':[{'code':s['code'],'market_date':day,'state':state if s['scope_state']==ELIGIBLE else s['scope_state']} for s in scope['rows']]}
    fin=upstream(QUALITY); fin['rows'][1]['state']='REVIEW_GROWTH_OR_HEALTH_RISK'
    kis=upstream('KIS_PROVISIONAL_LINK_RESEARCH_ONLY')
    base={'market_date':day,'market':'KOSPI','share_class':'COMMON','security_group':'STOCK','sector_id':'fixture','sector_type':'GENERAL','source_kind':'KRX_OFFICIAL','accounting_basis':'TTM','close_krw':'1000','per':'10','pbr':'1','eps':'100','bps':'1000',**{k:'fixture' for k in ('sector_evidence_ref','ratio_evidence_ref','class_evidence_ref')},**{k:'YES' for k in ('sector_date_reviewed','ratio_date_reviewed','class_date_reviewed','basis_reviewed')}}
    reviewed=[{**base,'code':c} for c in codes]; reviewed[9]['sector_id']='other'; reviewed[10]['sector_type']='FINANCIAL'; reviewed[11]['source_kind']='KIS_BROKER'
    def run(rr): return evaluate_sector(scope,fin,kis,market,rr,'fixture',model)
    report=run(reviewed); rows=index(report['rows'],'code')
    assert len(rows)==13 and report['eligible_reviewed_peer_rows']==10
    assert rows[codes[0]]['state']=='PEER_RANGE_RESEARCH_ONLY' and rows[codes[0]]['peer_count']==8
    assert rows[codes[1]]['state']=='PEER_RANGE_RESEARCH_ONLY' and rows[codes[1]]['quality_pass'] is False
    assert rows[codes[0]]['research_mid_krw']=='1000'
    assert rows[codes[9]]['state']=='HOLD_INSUFFICIENT_COMPARABLE_PEERS'
    assert rows[codes[10]]['state']=='HOLD_SPECIAL_SECTOR_MODEL_REQUIRED'
    assert rows[codes[11]]['state']=='HOLD_KIS_INDEPENDENT_EVIDENCE_ADAPTER'
    assert rows[codes[12]]['state']=='EXCLUDED_MARKET_CAP'
    assert run([])['counts']['HOLD_SECTOR_OR_RATIO_EVIDENCE']==12
    assert run([{**r,'ratio_date_reviewed':'NO'} for r in reviewed])['counts']['HOLD_REVIEWED_RATIO_OR_CLASS_CONFLICT']==12
    assert all(r['verified_fair_price'] is None and not r['buy_signal'] for r in rows.values())
    try: run(reviewed+reviewed[:1])
    except ValueError: pass
    else: raise AssertionError('DUPLICATE_REVIEWED_CODE_ACCEPTED')
    print('FULL_SECTOR_SELF_TEST_PASS 12')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');ap.add_argument('--root',type=Path,default=Path.cwd());a=ap.parse_args()
    root=a.root.resolve()
    if a.self_test: self_test(reader(root)); return
    scope,metrics,links,holds,hashes=load_sources(root)
    fin=evaluate(scope,metrics,links,holds);fin['source_sha256']=hashes
    kis=evaluate_saved(root,scope,fin)
    report=evaluate_saved_sector(root,scope,fin,kis)
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False))

if __name__=='__main__': main()
