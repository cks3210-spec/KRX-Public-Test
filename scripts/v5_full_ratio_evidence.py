"""Offline receipt-bound EPS/BPS diagnostic. No API, no raw values in report.
Matching numeric hypotheses are not proof of provider accounting basis or corporate actions.
"""
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal as D
from v5_evaluation_scope import validate_scope, validate_stage, index, require
from v5_full_share_evidence import plan_scope, reusable
from v5_valuation_crosscheck import positive, crosscheck

ELIGIBLE='EVALUATE_COMMON_STOCK_RESEARCH_ONLY'
ENDS={'annual':(12,31),'q1':(3,31),'half':(6,30),'q3':(9,30)}
TOL=D('.05')

def period_end(task):
    return date(int(task['year']),*ENDS[task['period']])

def period_days(task):
    return (period_end(task)-date(int(task['year']),1,1)).days+1

def single_weight(result):
    # No choosing a cell by proximity to KIS EPS (circular). All positive candidates
    # must agree, even then the period/unit/consolidation semantics remain unreviewed.
    if result.get('state')!='WEIGHTED_ROWS_UNREVIEWED' or result.get('xml_parse_errors')!=0:return None
    cells=[positive(c.get('value')) for r in result.get('rows',[]) if r.get('receipt')==result.get('receipt') for c in r.get('numeric_cells',[])]
    if not cells or None in cells or len(set(cells))!=1:return None
    return cells[0]

def share_result(tasks,entries,code,receipt,kind):
    hits=[(k,t) for k,t in tasks.items() if t['code']==code and t['receipt']==receipt and t['kind']==kind]
    if len(hits)!=1:return None,None
    k,t=hits[0]; e=entries.get(k)
    if not reusable(e,t):return t,None
    r=e['result']
    if r.get('receipt')!=receipt:return t,None
    return t,r

def within(value,expected):
    v=positive(value); e=positive(expected)
    return v is not None and e is not None and abs(v/e-1)<=TOL

def diagnose(scope,financial,kis,metrics,links,holds,market_rows,archive,entries):
    universe=validate_scope(scope);validate_stage(scope,financial);validate_stage(scope,kis)
    day=scope['market_date'];fin=index(financial['rows'],'code');broker=index(kis['rows'],'code');met=index(metrics,'code');market=index(market_rows,'ISU_CD')
    require(set(market)==set(universe)==set(met),'RATIO_SCOPE_MISMATCH')
    plan,tasks=plan_scope(scope,metrics,links,holds);validate_stage(scope,plan)
    inputs={}
    for k,x in links['inputs'].items():inputs.setdefault((k.split(':')[0],x.get('receipt')),[]).append((k,x))
    obs=archive.get('observations',{}) if archive else {};rows=[]
    for code,s in sorted(universe.items()):
        row={'code':code,'market_date':day,'state':s['scope_state'],'annual_eps_numeric_match':False,'ttm_eps_numeric_match':False,'bps_numeric_match':False,'official_ratios_verified':False,'buy_signal':False}
        rows.append(row)
        if s['scope_state']!=ELIGIBLE:continue
        row['state']='HOLD_KIS_ARITHMETIC_OR_DATE'
        if broker[code]['state']!='KIS_PROVISIONAL_LINK_RESEARCH_ONLY' or not broker[code]['arithmetic_consistent']:continue
        q=obs.get(code,{}); f=fin[code]; m=met[code]
        row['state']='HOLD_RECEIPT_BOUND_FINANCIALS'
        if f['financial_evidence_state'] not in ('ANNUAL_LINKED_RESEARCH_ONLY','ANNUAL_AND_TTM_LINKED_RESEARCH_ONLY'):continue
        def exact(rc):
            hits=[x for k,x in inputs.get((code,rc),[]) if x.get('corp_code')==m['corp_code'] and x.get('fs_div')==m['fs_div']=='CFS' and links['decisions'].get(k,{}).get('receipt')==rc and rc[:8]<=day]
            return hits[0] if len(hits)==1 else None
        ar=f.get('annual_receipt'); a=exact(ar) if ar else None
        if not a:continue
        at,aw=share_result(tasks,entries,code,ar,'weighted'); w=single_weight(aw or {})
        annual_profit=positive(a['accounts'].get('profit'))
        if w and annual_profit:row['annual_eps_numeric_match']=within(q.get('eps'),annual_profit/w)
        rec=f.get('ttm_receipts',[]); latest=a; latest_rc=ar
        ttm_weight=None;ttm_profit=None
        if len(rec)==3 and rec[0]==ar:
            cur,prior=exact(rec[1]),exact(rec[2])
            if cur and prior:
                latest=cur;latest_rc=rec[1]
                ct,cw=share_result(tasks,entries,code,rec[1],'weighted');pt,pw=share_result(tasks,entries,code,rec[2],'weighted')
                wc,wp=single_weight(cw or {}),single_weight(pw or {})
                if all(x is not None for x in (at,ct,pt,w,wc,wp)) and ct['period']==pt['period'] and int(ct['year'])==int(at['year'])+1 and pt['year']==at['year']:
                    days=period_days(at)+period_days(ct)-period_days(pt)
                    if days>0:
                        ttm_weight=positive((w*period_days(at)+wc*period_days(ct)-wp*period_days(pt))/D(days))
                ttm_profit=positive(m.get('ttm_owner_profit_krw'))
                if ttm_weight and ttm_profit:row['ttm_eps_numeric_match']=within(q.get('eps'),ttm_profit/ttm_weight)
        et,er=share_result(tasks,entries,code,latest_rc,'ending')
        end=None
        if et and er and er.get('equity_date')==period_end(et).isoformat():end=positive(er.get('ending_common_shares'))
        eq=positive(latest['accounts'].get('equity'))
        if end and eq:row['bps_numeric_match']=within(q.get('bps'),eq/end)
        # Use existing crosscheck contract, but deliberately leave review flags false.
        # Receipt links, unreviewed table cells and numeric matches do not establish them.
        evidence={'market_date':day,'code':code,'asof_reviewed':False,'basis_reviewed':False,'share_counts_reviewed':False,'corporate_actions_reviewed':False}
        mr=market[code]
        guard=crosscheck({'market_date':day,'code':code,'share_class':'COMMON','market_cap':mr['MKTCAP'],'close':mr['TDD_CLSPRC']},{**q,'market_date':day,'code':code,'close':q.get('observed_price')},evidence)
        require(guard['official_ratios_verified'] is False and guard['state']=='HOLD','UNEXPECTED_CROSSCHECK_APPROVAL')
        row['state']='HOLD_SHARE_OR_POSITIVE_FINANCIAL_INPUT_MISSING'
        if end and eq and ((w and annual_profit) or (ttm_weight and ttm_profit)):
            row['state']='NUMERIC_MATCH_BASIS_UNREVIEWED' if row['bps_numeric_match'] and (row['annual_eps_numeric_match'] or row['ttm_eps_numeric_match']) else 'HOLD_NUMERIC_MISMATCH_OR_UNREVIEWED_BASIS'
    report={'market_date':day,'scope_sha256':scope['scope_sha256'],'rows':rows,'financial_api_calls':0,'investment_decisions_authorized':False,'final_buy_signals':0,'official_ratios_verified':False}
    report['counts']=validate_stage(scope,report)
    report['numeric_match_counts']={k:sum(r[k] for r in rows) for k in ('annual_eps_numeric_match','ttm_eps_numeric_match','bps_numeric_match')}
    return report
