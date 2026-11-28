"""Full-scope assessment snapshots, research performance and briefing contract.
Offline. No API, trade authorization or publication of raw KIS observations.
Caller must persist snapshots and supply verified official price history/calendar.
"""
import argparse
from collections import Counter, defaultdict
from bisect import bisect_right
from v5_full_decision import simulate
from decimal import Decimal as D, InvalidOperation
from v5_evaluation_scope import validate_scope, validate_stage, index, require, digest, valid_day

ELIGIBLE='EVALUATE_COMMON_STOCK_RESEARCH_ONLY'
HORIZONS=(5,10,20)
SCHEMA='KRX_V5_FULL_ASSESSMENT_SNAPSHOT_V1'
QUALITY='GROWTH_AND_HEALTH_CRITERIA_MET_RESEARCH_ONLY'


def positive(v):
    try:
        x=D(str(v)); return x if x.is_finite() and x>0 else None
    except (InvalidOperation,ValueError): return None


def make_snapshot(scope, financial, kis, sector, grade):
    universe=validate_scope(scope); day=scope['market_date']; reports=(financial,kis,sector,grade)
    for r in reports:
        validate_stage(scope,r)
        require(r.get('investment_decisions_authorized') is False and r.get('final_buy_signals')==0,'UPSTREAM_APPROVAL_INVALID')
    require(grade.get('final_grades')==0 and grade.get('final_sell_signals')==0 and sector.get('verified_fair_prices')==0,'FINAL_CONTRACT_NOT_IMPLEMENTED')
    fi,ki,se,gr=[index(r['rows'],'code') for r in reports]
    rows=[]
    for code,s in sorted(universe.items()):
        g=gr[code]; f=fi[code]; k=ki[code]; v=se[code]
        require(g.get('financial_state')==f['state'] and g.get('sector_state')==v['state'] and v.get('financial_state')==f['state'] and v.get('kis_state')==k['state'],'STAGE_STATE_CONFLICT')
        require(g.get('research_grade') in (None,'A','B') and g.get('final_grade') is None and g.get('buy_signal') is False and g.get('sell_signal') is False and g.get('investment_authorized') is False,'UNSAFE_GRADE')
        require(g.get('entry_prices') is None and g.get('verified_fair_price') is None and g.get('position_actions') is None,'UNVERIFIED_STRATEGY')
        require(s['scope_state']==ELIGIBLE or g['research_grade'] is None,'INELIGIBLE_GRADE')
        rows.append({'code':code,'market_date':day,'scope_state':s['scope_state'],'state':g['state'],'financial_state':f['state'],'kis_state':k['state'],'sector_state':v['state'],'research_grade':g['research_grade'],'score':g.get('score'),'final_grade':None})
    body={'schema':SCHEMA,'market_date':day,'scope_sha256':scope['scope_sha256'],'market_rows':len(rows),'rows':rows,'research_only':True,'investment_decisions_authorized':False,'final_buy_signals':0,'final_sell_signals':0,'upstream_sha256':{n:digest(r) for n,r in zip(('financial','kis','sector','grade'),reports)}}
    return {**body,'snapshot_sha256':digest(body)}


def validate_snapshot(s):
    require(s.get('schema')==SCHEMA and s.get('research_only') is True and s.get('investment_decisions_authorized') is False and s.get('final_buy_signals')==s.get('final_sell_signals')==0,'INVALID_SNAPSHOT')
    require(digest({k:v for k,v in s.items() if k!='snapshot_sha256'})==s.get('snapshot_sha256'),'SNAPSHOT_HASH_MISMATCH')
    day=valid_day(s['market_date']); rows=index(s['rows'],'code')
    require(len(rows)==s['market_rows'] and all(r['market_date']==day and r.get('final_grade') is None and r.get('research_grade') in (None,'A','B') and (r['scope_state']==ELIGIBLE or r['research_grade'] is None) for r in rows.values()),'SNAPSHOT_SCOPE_MISMATCH')
    if 'available_date_kst' in s:require(valid_day(s['available_date_kst'])>=day,'INVALID_AVAILABLE_DATE')
    return rows


def merge_snapshots(previous,current):
    """Immutable first snapshot per session; never overwrite historical assessment."""
    by_day={}
    for s in [*previous,current]:
        validate_snapshot(s); day=s['market_date']
        if day in by_day:
            require(by_day[day]['snapshot_sha256']==s['snapshot_sha256'],'SAME_DATE_SNAPSHOT_CONFLICT')
        else: by_day[day]=s
    return [by_day[d] for d in sorted(by_day)]


def track(snapshots, sessions, prices, asof):
    """Next session close entry; +5/10/20 sessions; missing paths withheld.
    `prices` maps (code, YYYYMMDD) to official unadjusted close. Caller validates provenance.
    """
    valid_day(asof)
    require(sessions==sorted(set(sessions)) and asof in sessions,'INVALID_SESSION_CALENDAR')
    for d in sessions: valid_day(d)
    ix={d:i for i,d in enumerate(sessions)}; states=Counter(); results=[]; values=defaultdict(list); strategy_values=defaultdict(list); seen=set()
    for snap in snapshots:
        rows=validate_snapshot(snap); day=snap['market_date']
        require(day in ix and day<=asof and day not in seen,'INVALID_SNAPSHOT_DATE');seen.add(day)
        for code,r in sorted(rows.items()):
            # Full universe is preserved in snapshots; return cohorts use every scored A/B, not final signals.
            if r['research_grade'] not in ('A','B'): continue
            for h in HORIZONS:
                available=snap.get('available_date_kst'); start=bisect_right(sessions,available or day); end=start+h
                rec={'code':code,'signal_date':day,'research_grade':r['research_grade'],'horizon':h,'entry_date':None,'exit_date':None,'return_pct':None,'state':'PENDING_ENTRY'}
                if not available:rec['state']='HOLD_UNKNOWN_AVAILABILITY'
                elif start<len(sessions) and sessions[start]<=asof:
                    rec['entry_date']=sessions[start];rec['state']='PENDING_HORIZON'
                    if end<len(sessions) and sessions[end]<=asof:
                        rec['exit_date']=sessions[end];path=[positive(prices.get((code,d))) for d in sessions[start:end+1]]
                        if any(v is None for v in path):rec['state']='HOLD_INCOMPLETE_PRICE_PATH'
                        else:
                            rr=(path[-1]/path[0]-1)*100;rec.update(state='MATURED_UNADJUSTED_RESEARCH_ONLY',return_pct=str(rr.quantize(D('.0001'))));values[(r['research_grade'],h)].append(rr)
                            rec['strategies']=[simulate(path,frac) for frac in (D('.30'),D('.40'),D('.50'))]
                            for st in rec['strategies']:strategy_values[(r['research_grade'],h,st['sale_pct'])].append(D(st['difference_vs_hold_pp']))
                results.append(rec);states[rec['state']]+=1
    stats={f'{g}_{h}d':{'observations':len(v),'mean_pct':str((sum(v)/len(v)).quantize(D('.0001'))),'positive_count':sum(x>0 for x in v)} for (g,h),v in sorted(values.items())}
    strategy_stats={f'{g}_{h}d_{f}pct':{'observations':len(v),'mean_difference_vs_hold_pp':str((sum(v)/len(v)).quantize(D('.0001'))),'positive_count':sum(x>0 for x in v)} for (g,h,f),v in sorted(strategy_values.items())}
    return {'market_date':asof,'strategy_stats':strategy_stats,'snapshot_count':len(seen),'horizon_counts':dict(states),'cohort_stats':stats,'rows':results,'research_only':True,'investment_decisions_authorized':False,'final_buy_signals':0,'notes':['New full-scope research cohort; legacy Stage27 ledger stays separate.','Unadjusted close returns exclude dividends, splits, fees and execution effects; not strategy performance.','No missing path or future price is imputed.']}


def briefing(scope,snapshot,performance):
    rows=validate_snapshot(snapshot); universe=validate_scope(scope)
    require(set(rows)==set(universe) and snapshot['scope_sha256']==scope['scope_sha256'] and snapshot['market_date']==scope['market_date']==performance['market_date'],'BRIEFING_SCOPE_MISMATCH')
    require(performance.get('investment_decisions_authorized') is False and performance.get('final_buy_signals')==0,'UNSAFE_PERFORMANCE')
    # Current upstream cannot issue verified final grades. Never present provisional grades as recommendations.
    research=[r for r in rows.values() if r['research_grade'] in ('A','B')]
    return {'market_date':scope['market_date'],'scope_sha256':scope['scope_sha256'],'market_rows':len(rows),'scope_counts':scope['counts'],'evaluation_counts':dict(Counter(r['state'] for r in rows.values())),'research_grade_counts':dict(Counter(r['research_grade'] for r in research)),'final_ab_count':0,'final_ab_candidates':[],'performance_counts':performance['horizon_counts'],'research_performance_stats':performance['cohort_stats'],'strategy_performance_stats':performance.get('strategy_stats',{}),'investment_decisions_authorized':False,'final_buy_signals':0,'state':'HOLD_NO_VERIFIED_FINAL_GRADES','notes':['Only verified final A/B may enter final candidate list; none authorized by current upstream.','Research A/B counts are not buy recommendations.']}


def self_test():
    from v5_evaluation_scope import build_scope
    day='20261102';codes=['000001','000002','000003'];m=[{'ISU_CD':c,'BAS_DD':day,'MARKET':'KOSPI','MKTCAP':'100000000000' if c!=codes[2] else '1'} for c in codes];cl={'market_date':day,'row_count':3,'rows':[{'ISU_SRT_CD':c,'market':'KOSPI','KIND_STKCERT_TP_NM':'보통주','SECUGRP_NM':'주권'} for c in codes]};scope=build_scope(day,m,cl)
    def report(kind):
        rows=[]
        for i,s in enumerate(scope['rows']):
            state=kind if s['scope_state']==ELIGIBLE else s['scope_state'];r={'code':s['code'],'market_date':day,'state':state};rows.append(r)
            if kind=='sector':r.update(financial_state='fin' if i<2 else state,kis_state='kis' if i<2 else state)
            if kind=='grade':r.update(financial_state='fin' if i<2 else state,sector_state='sector' if i<2 else state,research_grade='A' if i==0 else 'B' if i==1 else None,final_grade=None,buy_signal=False,sell_signal=False,investment_authorized=False)
        return {'market_date':day,'scope_sha256':scope['scope_sha256'],'rows':rows,'investment_decisions_authorized':False,'final_buy_signals':0,'final_sell_signals':0,'final_grades':0,'verified_fair_prices':0}
    f,k,s,g=[report(x) for x in ('fin','kis','sector','grade')];snap=make_snapshot(scope,f,k,s,g);snap['available_date_kst']=day;snap['snapshot_sha256']=digest({k:v for k,v in snap.items() if k!='snapshot_sha256'})
    assert len(validate_snapshot(snap))==3
    assert len(merge_snapshots([snap],snap))==1
    from datetime import date,timedelta
    sessions=[(date(2026,11,2)+timedelta(days=i)).strftime('%Y%m%d') for i in range(35) if (date(2026,11,2)+timedelta(days=i)).weekday()<5]
    prices={(c,d):100+j for c in codes[:2] for j,d in enumerate(sessions)}
    p=track([snap],sessions,prices,sessions[1]);assert p['horizon_counts']=={'PENDING_HORIZON':6}
    assert track([snap],sessions,prices,day)['horizon_counts']=={'PENDING_ENTRY':6}
    p=track([snap],sessions,prices,sessions[-1]);assert p['horizon_counts']=={'MATURED_UNADJUSTED_RESEARCH_ONLY':6}
    assert p['rows'][0]['entry_date']==sessions[1] and p['rows'][0]['exit_date']==sessions[6]
    assert p['rows'][0]['return_pct']=='4.9505'
    missing={key:v for key,v in prices.items() if key!=(codes[0],sessions[3])};assert track([snap],sessions,missing,sessions[-1])['horizon_counts']['HOLD_INCOMPLETE_PRICE_PATH']==3
    b=briefing(scope,snap,track([snap],sessions,prices,day));assert b['final_ab_candidates']==[] and b['research_grade_counts']=={'A':1,'B':1}
    def reject(fn):
        try:fn()
        except ValueError:return
        raise AssertionError('EXPECTED_REJECTION')
    reject(lambda:make_snapshot(scope,f,k,s,{**g,'rows':g['rows'][:-1]}))
    reject(lambda:validate_snapshot({**snap,'market_rows':1}))
    reject(lambda:track([snap,snap],sessions,prices,day))
    reject(lambda:make_snapshot(scope,f,k,s,{**g,'rows':[{**g['rows'][0],'final_grade':'A'},*g['rows'][1:]]}))
    print('FULL_PERFORMANCE_BRIEFING_SELF_TEST_PASS 13')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.self_test:self_test()
    else:p.error('Use integration workflow; no standalone live execution.')
