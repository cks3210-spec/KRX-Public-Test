"""Offline research-only cross-check. No API, storage or publication side effects."""
from decimal import Decimal, InvalidOperation
from datetime import date
D=Decimal

def positive(v):
    try:
        x=D(str(v)); return x if x.is_finite() and x>0 else None
    except (InvalidOperation,ValueError): return None

def crosscheck(market, broker, evidence, tolerance='0.05'):
    out={'state':'HOLD','official_ratios_verified':False,'investment_authorized':False,'buy_signal':False,'reasons':[]}
    reasons=out['reasons']
    def hold(reason):
        reasons.append(reason); return out
    day=market.get('market_date')
    try: date.fromisoformat(day[:4]+'-'+day[4:6]+'-'+day[6:])
    except (TypeError,ValueError): return hold('INVALID_DATE')
    if len(day)!=8 or any(x.get('market_date')!=day for x in (broker,evidence)): return hold('DATE_MISMATCH')
    code=market.get('code')
    if not code or any(x.get('code')!=code for x in (broker,evidence)): return hold('CODE_MISMATCH')
    if market.get('share_class')!='COMMON' or (positive(market.get('market_cap')) or D(0))<D('100000000000'): return hold('UNIVERSE_EXCLUDED')
    close=positive(market.get('close')); quote=positive(broker.get('close'))
    if close is None or close!=quote: return hold('CLOSE_MISMATCH')
    v={k:positive(broker.get(k)) for k in ('per','pbr','eps','bps')}
    if any(x is None for x in v.values()): return hold('NONPOSITIVE_OR_MISSING_RATIO')
    tol=positive(tolerance)
    if tol is None or tol>D('.05'): return hold('INVALID_TOLERANCE')
    if abs(v['per']*v['eps']/close-1)>tol or abs(v['pbr']*v['bps']/close-1)>tol: return hold('BROKER_ARITHMETIC_MISMATCH')
    # Evidence adapter must establish these independently; never infer from matching arithmetic.
    if any(evidence.get(k) is not True for k in ('asof_reviewed','basis_reviewed','share_counts_reviewed','corporate_actions_reviewed')): return hold('UNREVIEWED_FINANCIAL_EVIDENCE')
    if evidence.get('eps_basis') not in ('ANNUAL','TTM') or evidence.get('eps_basis')!=broker.get('eps_basis') or evidence.get('fs_div')!=broker.get('fs_div') or evidence.get('fs_div') not in ('CFS','OFS') or evidence.get('equity_date')!=broker.get('equity_date') or not evidence.get('equity_date'): return hold('ACCOUNTING_BASIS_MISMATCH')
    profit,equity,weighted,end=[positive(evidence.get(k)) for k in ('common_profit','common_equity','weighted_common_shares','ending_common_shares')]
    if any(x is None for x in (profit,equity,weighted,end)): return hold('MISSING_SHARE_OR_FINANCIAL_EVIDENCE')
    if abs(v['eps']/(profit/weighted)-1)>tol: reasons.append('EPS_MISMATCH')
    if abs(v['bps']/(equity/end)-1)>tol: reasons.append('BPS_MISMATCH')
    if not reasons: out['state']='CROSSCHECK_CONSISTENT_RESEARCH_ONLY'
    return out

def self_test():
    m=dict(code='000001',market_date='20261127',share_class='COMMON',market_cap=100000000000,close=1000)
    b=dict(code=m['code'],market_date=m['market_date'],close=1000,per=10,pbr=1,eps=100,bps=1000,eps_basis='TTM',fs_div='CFS',equity_date='20260930')
    e=dict(code=m['code'],market_date=m['market_date'],eps_basis='TTM',fs_div='CFS',equity_date='20260930',common_profit=10000,common_equity=200000,weighted_common_shares=100,ending_common_shares=200,asof_reviewed=True,basis_reviewed=True,share_counts_reviewed=True,corporate_actions_reviewed=True)
    assert crosscheck(m,b,e)['state']=='CROSSCHECK_CONSISTENT_RESEARCH_ONLY'
    for patch,reason in [({'market_date':'20261126'},'DATE_MISMATCH'),({'weighted_common_shares':None},'MISSING_SHARE_OR_FINANCIAL_EVIDENCE'),({'weighted_common_shares':200},'EPS_MISMATCH'),({'ending_common_shares':100},'BPS_MISMATCH'),({'eps_basis':'ANNUAL'},'ACCOUNTING_BASIS_MISMATCH'),({'asof_reviewed':False},'UNREVIEWED_FINANCIAL_EVIDENCE')]:
        assert reason in crosscheck(m,b,{**e,**patch})['reasons']
    assert crosscheck(m,{**b,'per':20},e)['reasons']==['BROKER_ARITHMETIC_MISMATCH']
    print('SELF_TEST_PASS 8')

if __name__=='__main__': self_test()
