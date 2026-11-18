#!/usr/bin/env python3
"""Read-only KRX official market / R14 OpenDART financial evidence join.
No final grades or investment decisions. Does not mutate inputs or repository data.
"""
import argparse,csv,json,pathlib,datetime as dt,collections,re

def read(path):
    with open(path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def number(s):
    try:return float(str(s).replace(',',''))
    except (ValueError,TypeError):return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--bridge',required=True)
    ap.add_argument('--bridge-status',required=True)
    ap.add_argument('--financial',required=True)
    ap.add_argument('--financial-status',required=True)
    ap.add_argument('--out',required=True)
    a=ap.parse_args()
    out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=True)
    bs=json.loads(pathlib.Path(a.bridge_status).read_text(encoding='utf-8-sig'))
    fs=json.loads(pathlib.Path(a.financial_status).read_text(encoding='utf-8-sig'))
    market_date=bs.get('market_date')
    if bs.get('state')!='RESEARCH_BRIDGE_READY' or not re.fullmatch(r'20\d{6}',str(market_date or '')):
        raise SystemExit('BRIDGE_NOT_VERIFIED')
    financial_date=fs.get('market_date')
    def parsed_date(value, label):
        if not re.fullmatch(r'20\d{6}',str(value or '')):
            raise SystemExit(f'INVALID_{label}_DATE: {value}')
        try:return dt.datetime.strptime(value,'%Y%m%d').date()
        except ValueError:raise SystemExit(f'INVALID_{label}_DATE: {value}')
    official_day=parsed_date(market_date,'OFFICIAL')
    financial_day=parsed_date(financial_date,'FINANCIAL')
    lag=(official_day-financial_day).days
    # Market close must be contemporaneous. A financial-cache snapshot can be
    # older, but never from the future. Limit age and report it explicitly.
    if lag<0:raise SystemExit(f'FUTURE_FINANCIAL_SNAPSHOT_BLOCKED: {financial_date}>{market_date}')
    # R14 evaluation date follows official KRX date; the source cache date is
    # retained separately. Cache age alone is not evidence of disclosure freshness.
    if fs.get('version')!='R14_N_ANNUAL_QUARTER_TTM':
        raise SystemExit('FINANCIAL_CACHE_VERSION_UNVERIFIED')
    market=read(a.bridge);fin=read(a.financial)
    required_market={'BAS_DD','ISU_CD','MARKET','TDD_CLSPRC','MKTCAP','price_cap_source'}
    required_fin={'code','annual_profit','equity','prior_equity','ttm_profit','ttm_status','source'}
    if not market or not required_market.issubset(market[0]):raise SystemExit('BRIDGE_COLUMNS_MISSING')
    if not fin or not required_fin.issubset(fin[0]):raise SystemExit('FINANCIAL_COLUMNS_MISSING')
    fidx={}
    for f in fin:
        code=f.get('code','').strip().zfill(6)
        if code in fidx:raise SystemExit('DUPLICATE_FINANCIAL_CODE:'+code)
        fidx[code]=f
    result=[];counts=collections.Counter();seen=set()
    for m in market:
        code=m['ISU_CD'].strip();key=(m['MARKET'],code)
        if key in seen:raise SystemExit('DUPLICATE_MARKET_KEY:'+str(key))
        seen.add(key)
        if m['BAS_DD']!=market_date or m['price_cap_source']!='KRX_OPEN_API':raise SystemExit('UNVERIFIED_MARKET_ROW:'+code)
        f=fidx.get(code)
        if f is None:state='FINANCIAL_NOT_FOUND'
        elif not str(f.get('year','')).isdigit() or int(f['year'])>official_day.year:state='FINANCIAL_YEAR_INVALID'
        elif f.get('source')!='OpenDART fnlttSinglAcntAll':state='FINANCIAL_SOURCE_UNVERIFIED'
        elif f.get('ttm_status')!='VERIFIED_CUMULATIVE':state='TTM_NOT_VERIFIED'
        elif any(number(f.get(k)) is None for k in ('annual_profit','equity','prior_equity','ttm_profit')):state='FINANCIAL_VALUES_MISSING'
        elif number(f['equity'])<=0 or number(f['prior_equity'])<=0:state='EQUITY_NON_POSITIVE'
        else:state='MARKET_FINANCIAL_EVIDENCE_JOINED'
        counts[state]+=1
        result.append({'market_date':market_date,'evaluation_market_date':market_date,'financial_cache_market_date':financial_date,'code':code,'name':m.get('ISU_NM',''),'market':m['MARKET'],
          'official_close_krw':m['TDD_CLSPRC'],'official_market_cap_krw':m['MKTCAP'],
          'financial_year':f.get('year','') if f else '', 'fs_div':f.get('fs_div','') if f else '',
          'annual_profit_krw':f.get('annual_profit','') if f else '',
          'ttm_profit_krw':f.get('ttm_profit','') if f else '',
          'equity_krw':f.get('equity','') if f else '',
          'prior_equity_krw':f.get('prior_equity','') if f else '',
          'financial_source':f.get('source','') if f else '',
          'ttm_status':f.get('ttm_status','') if f else '',
          'evidence_status':state,'official_per_pbr_verified':'false','buy_signal_authorized':'false'})
    with (out/'official_financial_join.csv').open('w',encoding='utf-8-sig',newline='') as fp:
        w=csv.DictWriter(fp,fieldnames=list(result[0]));w.writeheader();w.writerows(result)
    status={'state':'READ_ONLY_EVIDENCE_JOIN_COMPLETE','market_date':market_date,'financial_market_date':financial_date,
        'evaluation_market_date':market_date,'financial_snapshot_lag_days':lag,
        'financial_snapshot_policy':'CACHE_DATE_NOT_FUTURE; ORIGINAL_SOURCE_DATE_PRESERVED',
        'financial_disclosure_asof_verified':False,'point_in_time_financials_authorized':False,
        'market_rows':len(market),'financial_rows':len(fin),'joined_evidence_rows':counts['MARKET_FINANCIAL_EVIDENCE_JOINED'],
        'counts_by_evidence_status':dict(counts),'production_modified':False,'official_per_pbr_verified':False,
        'investment_decisions_authorized':False,'note':'Official KRX date governs evaluation; original financial cache date retained. Disclosure dates are not present in R14 index, so point-in-time financial validity is UNVERIFIED. No official PER/PBR, final grades, or buy signals.'}
    (out/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(status,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
