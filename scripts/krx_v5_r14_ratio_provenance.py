#!/usr/bin/env python3
"""R14 read-only reconciliation of existing K/M/N financial and KRX ratio fields.
Does NOT treat a nonempty 'official' column as authenticated official KRX data.
"""
import argparse,csv,collections,json,re,pathlib,datetime

def read(path):
    with open(path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def code(v):
    s=str(v or '').strip().upper()
    if re.fullmatch(r'\d{6}',s):return s,'SHORT_CODE'
    if re.fullmatch(r'KR7\d{9}',s):return s[3:9],'KR7_ISIN_DERIVED'
    return None,'UNSUPPORTED_CODE_FORMAT'

def val(v):
    try:
        x=float(str(v).replace(',','').strip())
        return x if x==x and abs(x)!=float('inf') else None
    except (TypeError,ValueError):return None

def summarize(fin,market):
    fs={};fi=collections.Counter();fm=collections.Counter()
    for r in fin:
        c,kind=code(r.get('code'));fm[kind]+=1
        if c:
            if c in fs:fi['duplicate_financial_code']+=1
            fs[c]=r
    ms={};methods=collections.Counter();unmatched=[];conflicts=0
    for r in market:
        c,kind=code(r.get('ISU_CD'));methods[kind]+=1
        if c:
            if c in ms:conflicts+=1
            ms[c]=r
        elif len(unmatched)<10:unmatched.append(str(r.get('ISU_CD','')))
    shared=set(fs)&set(ms)
    fields=['i_official_per','j_official_per','i_official_pbr','j_official_pbr']
    populated={f:sum(val(r.get(f)) is not None for r in market) for f in fields}
    references={f:collections.Counter() for f in ['j_official_reference','j_metadata_date','BAS_DD','k_ratio_basis']}
    for r in market:
        for f in references:
            if r.get(f):references[f][str(r[f]).strip()]+=1
    # A matching code and a nonempty 'official' field do not prove source authenticity.
    paired=collections.Counter();comparison=collections.Counter();examples=[]
    for c in sorted(shared):
        f,m=fs[c],ms[c]
        if val(f.get('annual_profit')) is not None:paired['annual_profit']+=1
        if val(f.get('annual_roe_pct')) is not None:paired['annual_roe']+=1
        if f.get('ttm_status')=='VERIFIED_CUMULATIVE':paired['verified_ttm']+=1
        for key in fields:
            if val(m.get(key)) is not None:paired[key]+=1
        for metric in ('per','pbr'):
            derived=val(m.get('k_annual_'+metric))
            official=[val(m.get(k+'_official_'+metric)) for k in ('i','j')]
            if derived is not None and any(v is not None for v in official):comparison[metric+'_derived_and_labeled_official_present']+=1
        if len(examples)<5:examples.append({'code':c,'market_code':m.get('ISU_CD'),'financial_year':f.get('year'),'market_date':m.get('BAS_DD')})
    return {'result':'DIAGNOSTIC_COMPLETE','financial_rows':len(fin),'market_rows':len(market),
        'financial_code_formats':dict(fm),'market_code_formats':dict(methods),
        'duplicate_financial_codes':fi['duplicate_financial_code'],'duplicate_market_codes':conflicts,
        'unique_financial_codes':len(fs),'unique_market_codes':len(ms),'matched_codes':len(shared),
        'unmatched_financial_codes':len(set(fs)-set(ms)),'unmatched_market_codes':len(set(ms)-set(fs)),
        'unrecognized_market_examples':unmatched,'paired_fields':dict(paired),
        'labeled_official_fields_populated':populated,'comparison_ready_counts':dict(comparison),
        'provenance_samples':{k:dict(v.most_common(8)) for k,v in references.items()},
        'matched_examples':examples,'official_per_verified':0,'official_pbr_verified':0,
        'official_verification_status':'NOT_VERIFIED_BY_THIS_AUDIT',
        'reason':'Existing column names and reference strings alone do not authenticate KRX origin, matching date, and accounting basis.',
        'final_buy_signals':0}

def selftest():
    assert code('000020')==('000020','SHORT_CODE')
    assert code('KR7000020008')==('000020','KR7_ISIN_DERIVED')
    assert code('KR7000020008X')[0] is None
    assert code('A000020')[0] is None
    f=[{'code':'000020','annual_profit':'10','annual_roe_pct':'5','ttm_status':'VERIFIED_CUMULATIVE'}]
    m=[{'ISU_CD':'KR7000020008','BAS_DD':'20261116','i_official_per':'12','k_annual_per':'13'}]
    r=summarize(f,m)
    assert r['matched_codes']==1 and r['official_per_verified']==0 and r['paired_fields']['verified_ttm']==1
    return 5

def main():
    p=argparse.ArgumentParser();p.add_argument('--financial');p.add_argument('--market');p.add_argument('--output');a=p.parse_args()
    tests=selftest()
    if not a.financial or not a.market: print(json.dumps({'result':'SELF_TEST_PASS','tests':tests}));return
    report=summarize(read(a.financial),read(a.market));report['self_tests']=tests
    out=json.dumps(report,ensure_ascii=False,indent=2)
    if a.output:pathlib.Path(a.output).write_text(out,encoding='utf-8')
    print(out)
    if report['duplicate_financial_codes'] or report['duplicate_market_codes']:raise SystemExit('DUPLICATE_NORMALIZED_CODES')
if __name__=='__main__':main()
