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
    if financial_date!=market_date:
        raise SystemExit(f'FINANCIAL_MARKET_DATE_MISMATCH: bridge={market_date}, financial={financial_date}')
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
        elif f.get('source')!='OpenDART fnlttSinglAcntAll':state='FINANCIAL_SOURCE_UNVERIFIED'
        elif f.get('ttm_status')!='VERIFIED_CUMULATIVE':state='TTM_NOT_VERIFIED'
        elif any(number(f.get(k)) is None for k in ('annual_profit','equity','prior_equity','ttm_profit')):state='FINANCIAL_VALUES_MISSING'
        elif number(f['equity'])<=0 or number(f['prior_equity'])<=0:state='EQUITY_NON_POSITIVE'
        else:state='MARKET_FINANCIAL_EVIDENCE_JOINED'
        counts[state]+=1
        result.append({'market_date':market_date,'code':code,'name':m.get('ISU_NM',''),'market':m['MARKET'],
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
        'market_rows':len(market),'financial_rows':len(fin),'joined_evidence_rows':counts['MARKET_FINANCIAL_EVIDENCE_JOINED'],
        'counts_by_evidence_status':dict(counts),'production_modified':False,'official_per_pbr_verified':False,
        'investment_decisions_authorized':False,'note':'Evidence join only. No official PER/PBR, final grades, or buy signals.'}
    (out/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(status,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
