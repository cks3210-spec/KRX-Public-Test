"""Reviewed screening and hypothetical strategies. No API or order routing.
Independent review is an external prerequisite, never manufactured by this module.
All per-code output is private and must be encrypted by the caller.
"""
import json,re
from collections import Counter,defaultdict
from datetime import date
from decimal import Decimal as D, ROUND_FLOOR, ROUND_CEILING
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from v5_evaluation_scope import validate_scope,validate_stage,index,require,digest,valid_day
from v5_full_share_evidence import plan_scope
from v5_full_ratio_evidence import share_result,single_weight,period_days,period_end
from v5_valuation_crosscheck import positive,crosscheck

ELIGIBLE='EVALUATE_COMMON_STOCK_RESEARCH_ONLY'
QUALITY='GROWTH_AND_HEALTH_CRITERIA_MET_RESEARCH_ONLY'
REVIEW_DOMAIN=b'KRX-V5-INDEPENDENT-REVIEW-V1'
REVIEW_MAGIC=b'V5REV1\x00\x00'
REVIEW_FIELDS=('provider_basis','common_attribution','share_periods','corporate_actions','class_asof','financial_asof','sector_classification')
BUY=D('.001');SELL=D('.003') # inherited illustrative Stage8 assumptions, not actual fees/taxes

def load_reviews(root,day,key):
    p=root/'data/v5_full_research/reviews'/f'{day}.aes'
    if not p.is_file(): return {},'NO_INDEPENDENT_REVIEW_BUNDLE'
    raw=p.read_bytes();require(raw.startswith(REVIEW_MAGIC) and len(raw)>36,'INVALID_REVIEW_ARCHIVE')
    require(re.fullmatch(r'[a-fA-F0-9]{64}',key or ''),'INVALID_REVIEW_KEY')
    cipher=AESGCM(HKDF(algorithm=hashes.SHA256(),length=32,salt=None,info=REVIEW_DOMAIN).derive(bytes.fromhex(key)))
    try: data=json.loads(cipher.decrypt(raw[8:20],raw[20:],REVIEW_DOMAIN+b':'+day.encode()))
    except Exception: raise ValueError('REVIEW_AUTHENTICATION_FAILED') from None
    require(data.get('schema')=='INDEPENDENT_REVIEW_V1' and data.get('market_date')==day and isinstance(data.get('rows'),list),'INVALID_REVIEW_SCHEMA')
    return index(data['rows'],'code'),'EXTERNAL_REVIEW_BUNDLE_PRESENT'


def inputs_for(code,fin,links,metrics,tasks,entries,basis):
    """Reconstruct from exact receipts and cached candidate values, not broker values."""
    ar=fin.get('annual_receipt');rr=fin.get('ttm_receipts',[])
    if not ar or basis not in ('ANNUAL','TTM'):return None
    def exact(rc):
        hits=[x for k,x in links['inputs'].items() if k.split(':')[0]==code and x.get('receipt')==rc and x.get('corp_code')==metrics.get('corp_code') and x.get('fs_div')==metrics.get('fs_div')=='CFS' and links['decisions'].get(k,{}).get('receipt')==rc]
        return hits[0] if len(hits)==1 else None
    a=exact(ar)
    if not a:return None
    at,aw=share_result(tasks,entries,code,ar,'weighted'); w=single_weight(aw or {})
    profit=positive(a['accounts'].get('profit'));latest=a;lr=ar
    if not at or not w or not profit:return None
    if len(rr)==3 and rr[0]==ar:
        cur,prior=exact(rr[1]),exact(rr[2])
        if not cur or not prior:return None
        latest=cur;lr=rr[1]
        if basis=='TTM':
            ct,cw=share_result(tasks,entries,code,rr[1],'weighted');pt,pw=share_result(tasks,entries,code,rr[2],'weighted')
            wc,wp=single_weight(cw or {}),single_weight(pw or {})
            if None in (ct,pt,wc,wp) or ct['period']!=pt['period'] or int(ct['year'])!=int(at['year'])+1 or pt['year']!=at['year']:return None
            days=period_days(at)+period_days(ct)-period_days(pt)
            if days<=0:return None
            w=positive((w*period_days(at)+wc*period_days(ct)-wp*period_days(pt))/D(days))
            profit=positive(metrics.get('ttm_owner_profit_krw'))
    elif basis=='TTM':return None
    et,er=share_result(tasks,entries,code,lr,'ending')
    if not et or not er or er.get('equity_date')!=period_end(et).isoformat():return None
    end=positive(er.get('ending_common_shares'));eq=positive(latest['accounts'].get('equity'))
    if None in (w,profit,end,eq):return None
    return {'common_profit':str(profit),'common_equity':str(eq),'weighted_common_shares':str(w),'ending_common_shares':str(end),'equity_date':period_end(et).strftime('%Y%m%d'),'annual_year':str(a['year']),'eps_period':f"{latest['year']}:{latest['period']}" if basis=='TTM' else str(a['year'])+':annual'}


def reviewed_peer(code,day,scope,fr,m,q,mt,rat,record,links,tasks,entries,model):
    """A review assertion is not source authentication; must be made by an authorized independent reviewer.
    Cryptographic bindings prevent reusing it on changed records. Numeric match alone never promotes.
    """
    if not isinstance(record,dict):return None,'HOLD_INDEPENDENT_REVIEW_MISSING'
    refs=record.get('source_references',{})
    if not (record.get('market_date')==day and record.get('code')==code and record.get('scope_sha256')==scope['scope_sha256'] and record.get('observation_sha256')==digest(q) and record.get('financial_row_sha256')==digest(fr) and isinstance(record.get('reviewer'),str) and record['reviewer'].strip() and isinstance(refs,dict) and all(isinstance(refs.get(k),str) and refs[k].strip() for k in REVIEW_FIELDS) and record.get('common_attribution_reviewed') is True and record.get('share_period_units_reviewed') is True and record.get('corporate_actions_reviewed') is True and record.get('asof_reviewed') is True and record.get('class_asof_reviewed') is True and record.get('provider_basis_reviewed') is True):return None,'HOLD_REVIEW_BINDING_OR_ATTESTATION'
    # Bind all actual source records, not only the stage status or receipt numbers.
    relevant={k:v for k,v in links['inputs'].items() if k.split(':')[0]==code}
    decisions={k:v for k,v in links['decisions'].items() if k.split(':')[0]==code}
    shares={k:entries.get(k) for k,t in tasks.items() if t['code']==code}
    proof=digest({'inputs':relevant,'decisions':decisions,'strict_ttm':links['strict_ttm'].get(code),'metrics':mt,'shares':shares})
    if record.get('input_evidence_sha256')!=proof:return None,'HOLD_REVIEW_SOURCE_CHANGED'
    basis=record.get('eps_basis');fs=record.get('fs_div');sector=model['sector_name'](q.get('sector_name_kis'))
    if basis not in ('ANNUAL','TTM') or fs!='CFS' or record.get('sector_id')!=sector or not sector:return None,'HOLD_REVIEW_BASIS_OR_SECTOR'
    if record.get('sector_type')!='GENERAL' or re.search(r'금융|은행|보험|증권|카드|캐피탈|부동산|리츠|financial|bank|insurance|reit|real\s*estate',sector,re.I):return None,'HOLD_SPECIAL_SECTOR_MODEL_REQUIRED'
    if rat.get('bps_numeric_match') is not True or rat.get('annual_eps_numeric_match' if basis=='ANNUAL' else 'ttm_eps_numeric_match') is not True:return None,'HOLD_REVIEW_NUMERIC_MISMATCH'
    vals=inputs_for(code,fr,links,mt,tasks,entries,basis)
    if vals is None or record.get('equity_date')!=vals['equity_date']:return None,'HOLD_REVIEW_FINANCIAL_PERIOD'
    ev={**vals,'code':code,'market_date':day,'eps_basis':basis,'fs_div':fs,'asof_reviewed':True,'basis_reviewed':True,'share_counts_reviewed':True,'corporate_actions_reviewed':True}
    b={**q,'code':code,'market_date':day,'close':q.get('observed_price'),'eps_basis':basis,'fs_div':fs,'equity_date':record['equity_date']}
    result=crosscheck({'code':code,'market_date':day,'share_class':'COMMON','market_cap':m['MKTCAP'],'close':m['TDD_CLSPRC']},b,ev)
    if result['state']!='CROSSCHECK_CONSISTENT_RESEARCH_ONLY':return None,'HOLD_REVIEW_CROSSCHECK'
    return {'code':code,'market_date':day,'sector_id':sector,'sector_type':'GENERAL','source_kind':'KIS_EXTERNALLY_REVIEWED','accounting_basis':basis+':'+fs+':'+vals['eps_period']+':'+vals['equity_date'],'close_krw':m['TDD_CLSPRC'],**{k:q[k] for k in ('per','pbr','eps','bps')}},'REVIEWED_PEER_RESEARCH_ONLY'


def floor(v):return int(v.to_integral_value(rounding=ROUND_FLOOR))
def fee(v,r):return int((v*r).to_integral_value(rounding=ROUND_CEILING))

def ladders(low):
    low=positive(low);require(low is not None,'INVALID_LADDER')
    out=[]
    for budget in (1000000,3000000,5000000):
        orders=[]
        for alloc,discount in ((D('.4'),D('.05')),(D('.3'),D('.10')),(D('.3'),D('.20'))):
            price=floor(low*(1-discount));cap=floor(D(budget)*alloc)
            if price<1:continue
            qty=floor(D(cap)/(D(price)*(1+BUY)))
            while qty>0 and qty*price+fee(D(qty*price),BUY)>cap:qty-=1
            orders.append({'hypothetical_price_krw':price,'shares':qty,'cash_limit_krw':cap,'cost_with_assumed_fee_krw':qty*price+fee(D(qty*price),BUY)})
        out.append({'budget_krw':budget,'orders':orders,'remaining_cash_krw':budget-sum(x['cost_with_assumed_fee_krw'] for x in orders)})
    return out


def simulate(path,fraction):
    """Inherited Stage9: 100 shares, sell at +2, signal 10% below sale,
    next session execution only; no final liquidation. Illustrative fees."""
    require(len(path)>=6 and all(positive(x) is not None for x in path),'BAD_PATH')
    p=list(map(lambda x:D(str(x)),path));qty=100;sold=floor(D(qty)*fraction);sale=p[2]
    cash=D(sold)*sale-fee(D(sold)*sale,SELL);remain=qty-sold
    trigger=next((i for i in range(3,len(p)) if p[i]<=sale*D('.90')),None)
    fill=trigger+1 if trigger is not None and trigger+1<len(p) else None
    if fill is not None:
        cost=p[fill];buy=floor(cash/(cost*(1+BUY)))
        while buy>0 and cost*buy+fee(cost*buy,BUY)>cash:buy-=1
        cash-=cost*buy+fee(cost*buy,BUY);remain+=buy
    initial=p[0]*qty+fee(p[0]*qty,BUY);hold=p[-1]*qty;value=p[-1]*remain+cash
    return {'sale_pct':str(fraction*100),'difference_vs_hold_pp':str(((value-hold)/initial*100).quantize(D('.0001'))),'reentry_state':'FILLED' if fill is not None else 'SIGNAL_AT_HORIZON' if trigger is not None else 'NO_SIGNAL'}


def decide(scope,financial,kis,ratio,grade,sensitivity,market_rows,links,metrics,holds,archive,entries,reviews,model):
    universe=validate_scope(scope);day=scope['market_date']
    for rep in (financial,kis,ratio,grade,sensitivity):validate_stage(scope,rep)
    fi,ki,ra,gr,sv=[index(rep['rows'],'code') for rep in (financial,kis,ratio,grade,sensitivity)]
    market=index(market_rows,'ISU_CD');mt=index(metrics,'code');_,tasks=plan_scope(scope,metrics,links,holds)
    obs=archive.get('observations',{}) if archive and archive.get('state')=='KIS_BROKER_COLLECTION_COMPLETE' else {}
    qualified={};groups=defaultdict(list);rows=[]
    for code,s in sorted(universe.items()):
        r={'code':code,'market_date':day,'state':s['scope_state'],'reviewed_screen_grade':None,'buy_signal':False,'sell_signal':False,'investment_authorized':False};rows.append(r)
        if s['scope_state']!=ELIGIBLE:continue
        r['state']='HOLD_RATIO_OR_REVIEW_EVIDENCE'
        if code not in obs or ki[code]['state']!='KIS_PROVISIONAL_LINK_RESEARCH_ONLY':continue
        target,state=reviewed_peer(code,day,scope,fi[code],market[code],obs[code],mt[code],ra[code],reviews.get(code),links,tasks,entries,model)
        r['state']=state
        if target:
            qualified[code]=target;groups[(target['sector_id'],target['accounting_basis'])].append(target)
        # Conditional numeric ranges are private research, never final-grade inputs.
        if sv[code].get('state')=='SENSITIVITY_RANGE_RESEARCH_ONLY' and gr[code].get('research_grade') in ('A','B') and fi[code]['state']==QUALITY:
            r['conditional_strategy']={'state':'HYPOTHETICAL_ONLY','ladders':ladders(sv[code]['conditional_range_krw']['low'])}
    for r in rows:
        code=r['code'];t=qualified.get(code)
        if not t:continue
        peers=[p for p in groups[(t['sector_id'],t['accounting_basis'])] if p['code']!=code]
        est=model['estimate'](t,peers);r['state']=est['state'];r['reviewed_peer_count']=len(peers)
        if est['state']!='PEER_RANGE_RESEARCH_ONLY':continue
        r['reviewed_model_range_krw']={k:est['research_'+k+'_krw'] for k in ('low','mid','high')}
        if fi[code]['state']!=QUALITY:r['state']='HOLD_QUALITY_REVIEW';continue
        # Preserve existing R14 thresholds, but replace market-cap proxy valuation points with
        # independently reviewed broker ratios. This is a screening grade, not an order signal.
        parts=gr[code].get('score_parts')
        if not parts:r['state']='HOLD_SCORE_EVIDENCE';continue
        pe,pb=positive(t['per']),positive(t['pbr'])
        val=25 if pe<=12 and pb<=D('1.5') else 15 if pe<=20 and pb<=3 else 0
        score=sum(parts[k] for k in ('roe','owner_equity_leverage','ttm_vs_annual'))+val
        r['reviewed_score']=score
        grade_value='A' if score>=85 else 'B' if score>=65 else None
        if not grade_value:r['state']='BELOW_REVIEWED_B';continue
        r['state']='REVIEWED_SCREEN_ONLY';r['reviewed_screen_grade']=grade_value
        r['reviewed_strategy']={'state':'HYPOTHETICAL_ONLY','ladders':ladders(est['research_low_krw'])}
    rep={'market_date':day,'scope_sha256':scope['scope_sha256'],'rows':rows,'reviewed_screen_counts':dict(Counter(r['reviewed_screen_grade'] for r in rows if r['reviewed_screen_grade'])),'investment_decisions_authorized':False,'final_buy_signals':0,'final_sell_signals':0,'financial_api_calls':0}
    rep['counts']=validate_stage(scope,rep);return rep


def self_test():
    assert all(x['remaining_cash_krw']>=0 for x in ladders('10000'))
    assert all(sum(o['cost_with_assumed_fee_krw'] for o in x['orders'])<=x['budget_krw'] for x in ladders('9999'))
    assert simulate([100,100,100,89,80,100],D('.5'))['reentry_state']=='FILLED'
    assert D(simulate([100,100,100,89,80,100],D('.5'))['difference_vs_hold_pp'])>0
    assert D(simulate([100,100,100,89,110,120],D('.5'))['difference_vs_hold_pp'])<0
    assert simulate([100,100,100,100,100,80],D('.3'))['reentry_state']=='SIGNAL_AT_HORIZON'
    assert simulate([100,100,100,100,100,100],D('.4'))['reentry_state']=='NO_SIGNAL'
    print('FULL_DECISION_STRATEGY_FIXTURES_PASS 7')

if __name__=='__main__':self_test()
