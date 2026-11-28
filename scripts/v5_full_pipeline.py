"""One full-scope research pipeline. Existing sources only; no financial API.
Public output is aggregate-only. Per-stock snapshots are authenticated and encrypted.
"""
import argparse, csv, datetime as dt, gzip, json, os, re
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from v5_evaluation_scope import require, file_sha, validate_stage, index, valid_day
from v5_full_financial_evaluation import load_sources, evaluate, csv_rows
from v5_full_kis_evaluation import reader, link as link_kis
from v5_full_share_evidence import plan_scope, load_cache, reusable, CACHE_REL
from v5_full_sector_valuation import reviewed_bundle, evaluate_sector
from v5_full_ratio_evidence import diagnose
from v5_full_grade_strategy import evaluate_grade
from v5_full_performance_briefing import make_snapshot, validate_snapshot, track, briefing, positive

REL=Path('data/v5_full_research/snapshots')
MAGIC=b'V5SNAP1\x00'
DOMAIN=b'KRX-V5-FULL-RESEARCH-SNAPSHOT-V1'


def cipher(key):
    require(isinstance(key,str) and re.fullmatch(r'[a-fA-F0-9]{64}',key),'MISSING_OR_INVALID_ARCHIVE_KEY')
    return AESGCM(HKDF(algorithm=hashes.SHA256(),length=32,salt=None,info=DOMAIN).derive(bytes.fromhex(key)))


def aad(day):
    return DOMAIN+b':'+valid_day(day).encode()


def read_snapshot(p,key):
    raw=p.read_bytes();require(raw.startswith(MAGIC) and len(raw)>36,'INVALID_SNAPSHOT_ARCHIVE')
    try: s=json.loads(cipher(key).decrypt(raw[8:20],raw[20:],aad(p.stem)))
    except Exception: raise ValueError('SNAPSHOT_AUTHENTICATION_FAILED') from None
    validate_snapshot(s);require(s['market_date']==p.stem,'SNAPSHOT_DATE_MISMATCH');return s


def write_snapshot(p,s,key):
    validate_snapshot(s);require(s['market_date']==p.stem,'SNAPSHOT_DATE_MISMATCH')
    p.parent.mkdir(parents=True,exist_ok=True);nonce=os.urandom(12)
    raw=MAGIC+nonce+cipher(key).encrypt(nonce,json.dumps(s,ensure_ascii=False).encode(),aad(p.stem))
    with p.open('xb') as f:f.write(raw)


def share_coverage(scope,metrics,links,holds,entries):
    report,tasks=plan_scope(scope,metrics,links,holds);validate_stage(scope,report)
    counts=Counter(); complete=0
    for row in report['rows']:
        ids=row['task_ids']; n=sum(reusable(entries.get(t),tasks[t]) for t in ids)
        if ids and n==len(ids):complete+=1
        counts.update({'planned_tasks':len(ids),'cached_tasks':n,'pending_tasks':len(ids)-n})
    return {**dict(counts),'stocks_all_planned_tasks_cached':complete,'plan_states':report['counts'],
            'share_counts_independently_verified':False,'financial_api_calls':0}


def run_stages(scope,metrics,links,holds,market,model,archive,reviewed,review_state,entries,source_hashes=None):
    financial=evaluate(scope,metrics,links,holds)
    financial['source_sha256']=source_hashes or {}
    kis=link_kis(scope,financial,market,archive,model['sector_name'])
    share=share_coverage(scope,metrics,links,holds,entries)
    ratio=diagnose(scope,financial,kis,metrics,links,holds,market,archive,entries)
    sector=evaluate_sector(scope,financial,kis,market,reviewed,review_state,model)
    grade=evaluate_grade(scope,financial,sector,market,metrics,links)
    snapshot=make_snapshot(scope,financial,kis,sector,grade)
    return snapshot,share,{'financial':financial['counts'],'kis':kis['counts'],'sector':sector['counts'],'grade':grade['counts'],'ratio_evidence':ratio['counts'],'ratio_numeric_matches':ratio['numeric_match_counts']}


def sessions_between(start,end):
    import exchange_calendars as xc
    start=dt.datetime.strptime(start,'%Y%m%d').date();end=dt.datetime.strptime(end,'%Y%m%d').date()
    cal=xc.get_calendar('XKRX',start=str(start-dt.timedelta(days=10)),end=str(end+dt.timedelta(days=10)))
    return [x.strftime('%Y%m%d') for x in cal.sessions if start<=x.date()<=end]


def history(root,day,market,snapshots):
    """Research-only rolling prices, never impute missing prices; archived official CSVs take precedence."""
    wanted={r['code'] for s in snapshots for r in s['rows'] if r['research_grade'] in ('A','B')}
    earliest=min([day]+[s['market_date'] for s in snapshots]);sessions=sessions_between(earliest,day)
    require(day in sessions,'NON_SESSION_MARKET_DATE');allowed=set(sessions)
    p=root/'data/daily_70d.csv.gz';prices={};source={};seen=set()
    if p.is_file():
        source[str(p.relative_to(root))]=file_sha(p)
        with gzip.open(p,'rt',encoding='utf-8-sig',newline='') as f:
            rd=csv.DictReader(f);fields=rd.fieldnames or []
            df=next((x for x in ('BAS_DD','date','Date') if x in fields),None);cf=next((x for x in ('ISU_CD','code','Code') if x in fields),None);pf=next((x for x in ('TDD_CLSPRC','close','Close') if x in fields),None)
            require(df and cf and pf,'HISTORY_SCHEMA')
            for r in rd:
                d=valid_day(r[df].replace('-',''));require(d<=day,'FUTURE_HISTORY_DATE');seen.add(d)
                if r[cf] not in wanted or d not in allowed:continue
                v=positive(r[pf]);k=(r[cf],d)
                if v is None:continue
                require(k not in prices or prices[k]==v,'HISTORY_PRICE_CONFLICT');prices[k]=v
    # Rolling history can lag; exact-day live closes and official archives fill available sessions.
    for d in sessions:
        ap=root/'data/v5_official_market_archive'/f'{d}.csv'
        if not ap.is_file():continue
        source[str(ap.relative_to(root))]=file_sha(ap);rr=csv_rows(ap)
        require(all(r['BAS_DD']==d for r in rr),'OFFICIAL_ARCHIVE_DATE_MISMATCH')
        for c,r in index(rr,'ISU_CD').items():
            if c not in wanted:continue
            v=positive(r.get('TDD_CLSPRC'));k=(c,d)
            if v is None:continue
            require(k not in prices or prices[k]==v,'ARCHIVE_HISTORY_CONFLICT');prices[k]=v
    for r in market:
        if r['ISU_CD'] not in wanted:continue
        v=positive(r.get('TDD_CLSPRC'));k=(r['ISU_CD'],day)
        if v is None:continue
        require(k not in prices or prices[k]==v,'LATEST_HISTORY_CONFLICT');prices[k]=v
    return sessions,prices,{'rolling_history_latest':max(seen) if seen else None,'source_sha256':source,'independent_price_provenance_verified':False}


def run(root,out,persist=False):
    root=root.resolve();scope,metrics,links,holds,hashes_=load_sources(root);day=scope['market_date']
    market=csv_rows(root/'data/latest.csv');model=reader(root);key=os.environ.get('KIS_DATA_ARCHIVE_KEY','')
    p=root/'data/v5_kis_valuation/sessions'/day/'observations.aes';archive=None
    if p.is_file():archive=model['load_broker'](p,day,key)
    cache=root/CACHE_REL;entries=load_cache(cache,key) if cache.is_file() else {}
    reviewed,state,_=reviewed_bundle(root,day)
    snapshot,share,counts=run_stages(scope,metrics,links,holds,market,model,archive,reviewed,state,entries,hashes_)
    folder=root/REL;previous=[]
    for p in sorted(folder.glob('*.aes')):
        require(valid_day(p.stem)<=day,'FUTURE_SNAPSHOT');previous.append(read_snapshot(p,key))
    existing=next((s for s in previous if s['market_date']==day),None)
    complete=archive is not None and archive['state']=='KIS_BROKER_COLLECTION_COMPLETE'
    persist_state='HOLD_SAME_DATE_COMPLETE_KIS_REQUIRED';save=False
    if existing:
        persist_state='EXISTING_SNAPSHOT_REUSED' if existing['snapshot_sha256']==snapshot['snapshot_sha256'] else 'FIRST_SNAPSHOT_PRESERVED_CURRENT_DIFFERS'
    elif complete:
        previous.append(snapshot);persist_state='NEW_SNAPSHOT_READY' if persist else 'NEW_SNAPSHOT_NOT_PERSISTED';save=persist
    sessions,prices,hist=history(root,day,market,previous)
    performance=track(previous,sessions,prices,day)
    report=briefing(scope,snapshot,performance)
    report.update(state='FULL_SCOPE_RESEARCH_ONLY',same_date_complete_kis=complete,share_evidence=share,stage_counts=counts,
                  snapshot_state=persist_state,history=hist,financial_api_calls=0,
                  blockers=['KIS accounting basis, common-share amounts and corporate actions remain independently unreviewed',
                            'Final fair price and final grade contracts not implemented'],
                  source_sha256=hashes_)
    require(all(file_sha(root/rel)==h for rel,h in {**hashes_,**hist['source_sha256']}.items()),'SOURCE_CHANGED')
    if save:write_snapshot(folder/f'{day}.aes',snapshot,key);report['snapshot_state']='NEW_SNAPSHOT_ENCRYPTED'
    out.mkdir(parents=True,exist_ok=True);(out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


def self_test(root):
    from v5_evaluation_scope import build_scope
    day='20261126';codes=[str(i).zfill(6) for i in range(1,11)]
    market=[{'ISU_CD':c,'BAS_DD':day,'MKTCAP':'1' if i==9 else '100000000000','MARKET':'KOSPI','TDD_CLSPRC':'1000'} for i,c in enumerate(codes)]
    cl={'market_date':day,'row_count':len(codes),'rows':[{'ISU_SRT_CD':c,'market':'KOSPI','KIND_STKCERT_TP_NM':'보통주','SECUGRP_NM':'주권'} for c in codes]}
    scope=build_scope(day,market,cl);metrics=[];inputs={};decisions={};strict={}
    for c in codes:
        base={'corp_code':'12345678','fs_div':'CFS'};rec=['20260319000001','20261113000001','20251113000001']
        for y,p,r,ac in [(2025,'annual',rec[0],{'profit':100,'assets':1500,'liabilities':500,'equity':950,'previous_equity':900}),(2026,'q3',rec[1],{'profit':90}),(2025,'q3',rec[2],{'profit':70})]:
            k=f'{c}:{y}:{p}';inputs[k]={**base,'year':y,'period':p,'receipt':r,'amount_basis':'ANNUAL' if p=='annual' else 'CUMULATIVE_INTERIM_IS_CIS','accounts':ac};decisions[k]={**base,'year':y,'period':p,'receipt':r}
        strict[c]={'fs_div':'CFS','receipts':rec,'ttm_profit':120}
        metrics.append({**base,'code':c,'market_date':day,'year':'2025','annual_receipt':rec[0],'annual_source':'RECEIPT_BOUND_ARCHIVE_RESEARCH_ONLY','ttm_state':'RECEIPT_BOUND_CUMULATIVE_RESEARCH_ONLY','ttm_owner_profit_krw':'120','investment_authorized':'NO','financial_disclosure_asof_verified':'NO','operating_profit_source':'RECEIPT_BOUND_ANNUAL','revenue_yoy_pct':'10','owner_profit_yoy_pct':'10','operating_profit_yoy_pct':'10','annual_owner_roe_pct':'10','operating_margin_pct':'10','liabilities_to_total_equity_pct':'50'})
    links={'inputs':inputs,'decisions':decisions,'strict_ttm':strict}
    q={'observed_price':'1000','per':'10','pbr':'1','eps':'100','bps':'1000','sector_name_kis':'fixture','observed_at_kst':'2026-11-26T16:50:00+09:00'}
    archive={'observation_session':day,'state':'KIS_BROKER_COLLECTION_COMPLETE','observations':{c:q for c in codes}}
    model=reader(root);snap,share,counts=run_stages(scope,metrics,links,[],market,model,archive,[],'MISSING',{})
    assert len(validate_snapshot(snap))==10
    assert share['planned_tasks']==36 and share['pending_tasks']==36
    assert counts['kis']['KIS_PROVISIONAL_LINK_RESEARCH_ONLY']==9
    assert counts['ratio_evidence']['HOLD_SHARE_OR_POSITIVE_FINANCIAL_INPUT_MISSING']==9
    assert counts['sector']['HOLD_SECTOR_OR_RATIO_EVIDENCE']==9
    assert all(r['final_grade'] is None for r in snap['rows'])
    missing,_,ct=run_stages(scope,metrics,links,[],market,model,None,[],'MISSING',{})
    assert ct['kis']['WAIT_FOR_SAME_DATE_KIS_ARCHIVE']==9
    p=track([snap],[day],{},day);assert briefing(scope,snap,p)['final_ab_count']==0
    with TemporaryDirectory() as d:
        path=Path(d)/f'{day}.aes';write_snapshot(path,snap,'01'*32);assert read_snapshot(path,'01'*32)==snap
        try:read_snapshot(path,'02'*32)
        except ValueError:pass
        else:raise AssertionError('WRONG_KEY_ACCEPTED')
    print('FULL_PIPELINE_INTEGRATION_SELF_TEST_PASS 9')
    from v5_full_ratio_evidence import diagnose
    from copy import deepcopy
    model=reader(root); financial=evaluate(scope,metrics,links,[]); kis=link_kis(scope,financial,market,archive,model['sector_name'])
    plan,tasks=plan_scope(scope,metrics,links,[]); entries={}
    for tid,t in tasks.items():
        if t['kind']=='weighted': result={'state':'WEIGHTED_ROWS_UNREVIEWED','receipt':t['receipt'],'xml_parse_errors':0,'rows':[{'receipt':t['receipt'],'numeric_cells':[{'value':1}]}]}
        else: result={'state':'ENDING_COMMON_SHARE_CANDIDATE','receipt':t['receipt'],'equity_date':'2026-09-30','ending_common_shares':1}
        entries[tid]={'task':t,'result':result}
    for c in codes: links['inputs'][f'{c}:2026:q3']['accounts']['equity']=1000
    def run(e=entries,ar=archive):
        k=link_kis(scope,financial,market,ar,model['sector_name'])
        return diagnose(scope,financial,k,metrics,links,[],market,ar,e)
    r=run(); assert r['counts']['NUMERIC_MATCH_BASIS_UNREVIEWED']==9
    assert r['numeric_match_counts']=={'annual_eps_numeric_match':9,'ttm_eps_numeric_match':0,'bps_numeric_match':9}
    assert all(not x['official_ratios_verified'] for x in r['rows'])
    assert r['counts']['EXCLUDED_MARKET_CAP']==1
    e=deepcopy(entries)
    for v in e.values():
        if v['task']['kind']=='weighted':v['result']['rows'][0]['numeric_cells'].append({'value':2})
    assert run(e)['counts']['HOLD_SHARE_OR_POSITIVE_FINANCIAL_INPUT_MISSING']==9
    assert run({})['counts']['HOLD_SHARE_OR_POSITIVE_FINANCIAL_INPUT_MISSING']==9
    e=deepcopy(entries)
    for v in e.values():
        if v['task']['kind']=='ending':v['result']['ending_common_shares']=2
    assert run(e)['counts']['HOLD_NUMERIC_MISMATCH_OR_UNREVIEWED_BASIS']==9
    e=deepcopy(entries)
    for v in e.values():
        if v['task']['kind']=='ending':v['result']['equity_date']='2025-12-31'
    assert run(e)['numeric_match_counts']['bps_numeric_match']==0
    a=deepcopy(archive)
    for q in a['observations'].values():q['eps']='120';q['per']='8.333333333'
    assert run(entries,a)['numeric_match_counts']['ttm_eps_numeric_match']==9
    assert run(entries,a)['numeric_match_counts']['annual_eps_numeric_match']==0
    print('RATIO_EVIDENCE_FIXTURE_ASSERTIONS_PASS 10')


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--root',type=Path,default=Path.cwd());a.add_argument('--out',type=Path,default=Path('/tmp/v5-full-pipeline'));a.add_argument('--self-test',action='store_true');a.add_argument('--persist',action='store_true');v=a.parse_args()
    if v.self_test:self_test(v.root.resolve())
    else:run(v.root,v.out,v.persist)
