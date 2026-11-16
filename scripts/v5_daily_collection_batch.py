#!/usr/bin/env python3
"""KRX v5: independent daily official-market + incremental DART disclosure collector.
Never overwrites existing Stage caches; never claims financial regrading is complete.
"""
import csv, datetime as dt, json, os, pathlib, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'data'/'v5_daily_collection'
KST=ZoneInfo('Asia/Seoul')
TODAY=dt.datetime.now(KST).date()
DATE=TODAY.strftime('%Y%m%d')
STATUS={'target_date':DATE,'generated_at_kst':dt.datetime.now(KST).isoformat(),'market':'NOT_STARTED','dart':'NOT_STARTED','full_market_regrade':'NOT_IMPLEMENTED','buy_signals':0}

def get_json(url,params,headers=None):
    req=urllib.request.Request(url+'?'+urllib.parse.urlencode(params),headers=headers or {'User-Agent':'KRX-v5-research/1.0'})
    with urllib.request.urlopen(req,timeout=35) as response:
        return json.load(response)

def save_csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not rows:return
    tmp=path.with_suffix('.tmp')
    with tmp.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),extrasaction='ignore')
        writer.writeheader();writer.writerows(rows)
    tmp.replace(path)

def collect_market(day_dir):
    key=os.environ.get('KRX_API_KEY','').strip()
    if not key:raise RuntimeError('KRX_API_KEY missing')
    endpoints={'KOSPI':'https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd','KOSDAQ':'https://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd'}
    rows=[];counts={}
    for market,url in endpoints.items():
        payload=get_json(url,{'basDd':DATE},{'AUTH_KEY':key,'Accept':'application/json','User-Agent':'KRX-v5-research/1.0'})
        block=payload.get('OutBlock_1')
        if not isinstance(block,list) or len(block)<100:raise RuntimeError(f'{market}: insufficient official rows')
        counts[market]=len(block)
        for r in block:
            if str(r.get('BAS_DD',''))!=DATE:raise RuntimeError(f'{market}: wrong data date')
            code=str(r.get('ISU_CD','')).strip()
            close=str(r.get('TDD_CLSPRC','')).replace(',','').strip()
            cap=str(r.get('MKTCAP','')).replace(',','').strip()
            if not code or not close.isdigit() or not cap.isdigit() or int(close)<=0 or int(cap)<=0:raise RuntimeError(f'{market}: invalid row')
            rows.append({'BAS_DD':DATE,'MARKET':market,'ISU_CD':code,'ISU_NM':r.get('ISU_NM',''),'TDD_CLSPRC':close,'MKTCAP':cap,'ACC_TRDVOL':r.get('ACC_TRDVOL',''),'source':'KRX_OPEN_API'})
    if len({(r['MARKET'],r['ISU_CD']) for r in rows})!=len(rows):raise RuntimeError('Duplicate securities')
    save_csv(day_dir/'official_market.csv',rows)
    STATUS.update(market='SUCCESS',market_rows=len(rows),market_counts=counts,market_date=DATE)

def collect_dart(day_dir):
    key=os.environ.get('DART_API_KEY','').strip()
    if not key:raise RuntimeError('DART_API_KEY missing')
    # The public OpenDART list endpoint returns new disclosure metadata, not parsed financial statements.
    items=[]
    for page in range(1,51):
        result=get_json('https://opendart.fss.or.kr/api/list.json',{'crtfc_key':key,'bgn_de':DATE,'end_de':DATE,'page_no':page,'page_count':100})
        status=result.get('status')
        if status=='013':break
        if status!='000':raise RuntimeError('OpenDART response '+str(status)+' '+str(result.get('message','')))
        items.extend(result.get('list') or [])
        total=int(result.get('total_page',page))
        if page>=total:break
    else:raise RuntimeError('DART disclosure pagination exceeded safety limit')
    # Keep every filing for later financial-statement extraction; never mislabel it as extracted financials.
    if items:save_csv(day_dir/'dart_disclosures.csv',items)
    STATUS.update(dart='SUCCESS',dart_disclosure_rows=len(items),dart_financial_statements_refreshed=False)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    day_dir=OUT/'daily'/DATE
    day_dir.mkdir(parents=True,exist_ok=True)
    try:
        import exchange_calendars as xcals
        import pandas as pd
        if not xcals.get_calendar('XKRX').is_session(pd.Timestamp(TODAY.isoformat())):
            STATUS.update(market='SKIPPED_KRX_CLOSED',dart='SKIPPED_KRX_CLOSED')
            return
    except Exception as exc:
        STATUS.update(market='BLOCKED_CALENDAR',dart='BLOCKED_CALENDAR',error=str(exc))
        raise
    if dt.datetime.now(KST).hour<18:raise RuntimeError('Run after 18:00 KST')
    for name,fn in [('market',collect_market),('dart',collect_dart)]:
        try:fn(day_dir)
        except Exception as exc:STATUS[name]='FAILED';STATUS[name+'_error']=str(exc)[:500]
    if STATUS['market']!='SUCCESS' or STATUS['dart']!='SUCCESS':raise RuntimeError('One or more sources failed; see status.json')
    STATUS['state']='DAILY_COLLECTION_SUCCESS_NOT_FINANCIAL_REGRADING'
    return

if __name__=='__main__':
    try:main()
    except Exception as exc:
        STATUS.setdefault('state','FAILED')
        STATUS.setdefault('error',str(exc)[:500])
        raise
    finally:
        OUT.mkdir(parents=True,exist_ok=True)
        (OUT/'status.json').write_text(json.dumps(STATUS,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(STATUS,ensure_ascii=False))
