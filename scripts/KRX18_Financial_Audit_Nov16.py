#!/usr/bin/env python3
"""Stage18 offline financial audit. Reads Stage12/13/15/16; writes only Stage18 outputs."""
import argparse,csv,datetime as dt,json,pathlib,re,hashlib
from decimal import Decimal,InvalidOperation

FIELDS=('revenue','operating_profit','net_income','assets','liabilities','equity','operating_cashflow')

def read(path,required=True):
    if not path.exists():
        if required: raise FileNotFoundError(str(path))
        return {}
    return json.loads(path.read_text(encoding='utf-8-sig'))

def num(x):
    if x is None or isinstance(x,bool):return None
    try:
        v=Decimal(str(x).replace(',','').strip())
        return v if v.is_finite() else None
    except (InvalidOperation,ValueError):return None

def ratio(a,b,scale=1):
    if a is None or b is None or b==0:return ''
    return str((a/b*Decimal(scale)).quantize(Decimal('.0001')))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--data-dir',default='data')
    ap.add_argument('--output-dir',default=None)
    a=ap.parse_args(); d=pathlib.Path(a.data_dir);o=pathlib.Path(a.output_dir) if a.output_dir else d
    if d.resolve()==o.resolve():
        # Only distinct Stage18 output filenames are ever written.
        pass
    uni=read(d/'v5_full_market_universe.json'); annual=read(d/'v5_stage15_annual_cache.json')
    progress=read(d/'v5_stage16_progress.json',False)
    entries=annual.get('entries',{});years=annual.get('target_years') or progress.get('annual_years') or [2025,2024]
    if len(years)!=2 or not all(isinstance(y,int) for y in years):raise ValueError('Invalid annual target years')
    if not isinstance(entries,dict):raise ValueError('Invalid annual entries')
    stocks=uni.get('stocks')
    if not isinstance(stocks,list) or not stocks:raise ValueError('Missing market universe')
    rows=[];counts={};grade_counts={'A':0,'B+':0,'B':0};comparables=0;ratio_counts={'per_proxy':0,'pbr_proxy':0,'roe_proxy_pct':0}
    for s in stocks:
        code=str(s.get('code','')).zfill(6);name=str(s.get('name',''))
        if any(x in name for x in ('우선주','우B','우C')) or re.search(r'우\d*$',name):continue
        f1=(entries.get(f'{code}:{years[0]}') or {}).get('filing') or {}
        f0=(entries.get(f'{code}:{years[1]}') or {}).get('filing') or {}
        flags=[]
        if not f1:flags.append('CURRENT_ANNUAL_MISSING')
        if not f0:flags.append('PRIOR_ANNUAL_MISSING')
        if f1 and f0 and (not f1.get('fs_div') or f1.get('fs_div')!=f0.get('fs_div')):flags.append('FS_BASIS_MISMATCH')
        if f1.get('issues') or f0.get('issues'):flags.append('ACCOUNT_EXTRACTION_ISSUES')
        if f1 and f1.get('report_code')!='11011':flags.append('CURRENT_REPORT_CODE_UNVERIFIED')
        if f0 and f0.get('report_code')!='11011':flags.append('PRIOR_REPORT_CODE_UNVERIFIED')
        m1=f1.get('metrics') or {};m0=f0.get('metrics') or {}
        missing=[k for k in FIELDS if num(m1.get(k)) is None]
        if f1 and missing:flags.append('CURRENT_METRICS_MISSING')
        if f0 and num(m0.get('revenue')) is None:flags.append('PRIOR_REVENUE_MISSING')
        assets=num(m1.get('assets'));liab=num(m1.get('liabilities'));equity=num(m1.get('equity'))
        profit=num(m1.get('net_income'));cap=num(s.get('market_cap_krw'))
        if equity is not None and equity<=0:flags.append('NONPOSITIVE_EQUITY')
        if assets is not None and liab is not None and equity is not None:
            if abs(assets-liab-equity)>max(Decimal('1000000'),abs(assets)*Decimal('.01')):flags.append('BALANCE_SHEET_MISMATCH')
        if cap is None or cap<=0:flags.append('MARKET_CAP_UNAVAILABLE')
        if not re.fullmatch(r'\d{6}',code):flags.append('SECURITY_CODE_UNVERIFIED')
        comparable=bool(f1 and f0 and f1.get('fs_div')==f0.get('fs_div') and not f1.get('issues') and not f0.get('issues') and f1.get('report_code')=='11011' and f0.get('report_code')=='11011')
        if comparable:comparables+=1
        per=ratio(cap,profit) if comparable and cap is not None and cap>0 and profit is not None and profit>0 else ''
        pbr=ratio(cap,equity) if f1 and cap is not None and cap>0 and equity is not None and equity>0 else ''
        roe=ratio(profit,equity,100) if comparable and profit is not None and equity is not None and equity>0 else ''
        for k,v in [('per_proxy',per),('pbr_proxy',pbr),('roe_proxy_pct',roe)]:ratio_counts[k]+=bool(v)
        # Grade is inherited as provisional only; no automatic official verification.
        provisional='WITHHELD'
        # Stage16 report lookup is loaded separately below.
        status='COMPARABLE' if comparable else 'REVIEW_REQUIRED'
        for flag in flags:counts[flag]=counts.get(flag,0)+1
        rows.append(dict(code=code,name=name,market=s.get('market',''),annual_year_current=years[0],annual_year_prior=years[1],annual_comparable=comparable,fs_div=f1.get('fs_div',''),status=status,missing_metrics=';'.join(missing),issues=';'.join(flags),per_proxy=per,pbr_proxy=pbr,roe_proxy_pct=roe,market_cap_source_date=uni.get('trading_date',''),official_per_verified=False,official_pbr_verified=False,official_roe_verified=False,verified_grade='',provisional_grade=provisional,valuation_classification='UNVERIFIED_PROXY_ONLY'))
    stage16=read(d/'v5_stage16_full_market.json',False)
    grade_by_code={str(r.get('code','')).zfill(6):r.get('provisional_grade','WITHHELD') for r in stage16.get('results',[]) if isinstance(r,dict)}
    for row in rows:
        g=grade_by_code.get(row['code'],'WITHHELD')
        row['provisional_grade']=g
        if g in grade_counts:grade_counts[g]+=1
    o.mkdir(parents=True,exist_ok=True)
    output=o/'v5_stage18_financial_audit.csv'
    with output.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    summary={'schema':1,'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'source_market_date':uni.get('trading_date'),'annual_years':years,'analyzed_count':len(rows),'annual_comparable_count':comparables,'proxy_counts':ratio_counts,'provisional_grade_counts':grade_counts,'verified_grade_count':0,'issue_counts':counts,'source_annual_cache_sha256':hashlib.sha256((d/'v5_stage15_annual_cache.json').read_bytes()).hexdigest(),'classification':'OFFLINE_DIAGNOSTIC_UNVERIFIED_NO_INVESTMENT_SIGNAL','output_csv':output.name}
    (o/'v5_stage18_financial_audit_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
