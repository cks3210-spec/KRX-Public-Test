#!/usr/bin/env python3
"""OpenDART evidence fetcher: read-only, fail closed; never sets verified=true.
Requires DART_API_KEY GitHub secret. Run after daily_grade_gate.py.
Writes data/daily_dart_evidence.json and data/dart_corp_map.json cache.
"""
import csv, datetime as dt, io, json, os, pathlib, re, time, urllib.parse, urllib.request, zipfile, xml.etree.ElementTree as ET
ROOT=pathlib.Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
BASE='https://opendart.fss.or.kr/api/'
def request(endpoint, params):
    url=BASE+endpoint+'?'+urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'KRX-research/1.0'}),timeout=35) as response:return response.read()
        except Exception:
            if attempt==2:raise
            time.sleep(2**attempt)
def corp_map(key):
    cache=DATA/'dart_corp_map.json'
    if cache.exists():
        try:
            saved=json.loads(cache.read_text()); stamp=dt.date.fromisoformat(saved['fetched_date'])
            if (dt.date.today()-stamp).days<=14 and saved.get('mapping'):return saved['mapping']
        except (ValueError,KeyError,TypeError):pass
    raw=request('corpCode.xml',{'crtfc_key':key})
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        root=ET.fromstring(z.read(next(n for n in z.namelist() if n.lower().endswith('.xml'))))
    mapping={}
    for item in root.findall('.//list'):
        code=(item.findtext('stock_code') or '').strip(); corp=(item.findtext('corp_code') or '').strip()
        if re.fullmatch(r'\d{6}',code) and re.fullmatch(r'\d{8}',corp):mapping[code]=corp
    cache.write_text(json.dumps({'fetched_date':dt.date.today().isoformat(),'mapping':mapping},ensure_ascii=False))
    return mapping
def periods(now):
    # Query recent report slots only; availability depends on actual filings.
    return [(year,report) for year,report in [(now.year,'11014'),(now.year,'11012'),(now.year,'11013'),(now.year-1,'11011'),(now.year-1,'11014'),(now.year-1,'11012'),(now.year-1,'11013')] if year>=2015]
def main():
    key=os.getenv('DART_API_KEY','').strip()
    if not key:raise SystemExit('DART_API_KEY missing; set GitHub Actions secret. No verification performed.')
    gate=json.loads((DATA/'daily_grade_gate.json').read_text(encoding='utf-8'))
    mapping=corp_map(key); now=dt.datetime.now(dt.timezone.utc)
    results=[]
    for item in gate.get('results',[]):
        code=str(item['code']).zfill(6); corp=mapping.get(code)
        result={'code':code,'name':item.get('name'),'corp_code':corp,'status':'UNVERIFIED','filings':[],'errors':[]}
        if not corp:result['errors'].append('DART_CORP_CODE_NOT_FOUND');results.append(result);continue
        # Two fiscal periods are needed for reliable YoY; collect raw rows, do not infer growth.
        for year,report in periods(now):
            for fs in ('CFS','OFS'):
                try:
                    raw=json.loads(request('fnlttSinglAcntAll.json',{'crtfc_key':key,'corp_code':corp,'bsns_year':year,'reprt_code':report,'fs_div':fs}))
                    if raw.get('status')=='013':continue
                    if raw.get('status')!='000':
                        result['errors'].append({'year':year,'report':report,'fs':fs,'status':raw.get('status'),'message':raw.get('message')});continue
                    rows=raw.get('list',[])
                    if not rows:continue
                    receipts=sorted({r.get('rcept_no','') for r in rows if r.get('rcept_no')})
                    if not receipts:result['errors'].append('MISSING_RECEIPT_NUMBER');continue
                    result['filings'].append({'year':year,'report_code':report,'fs_div':fs,'receipt_numbers':receipts,
                       'source_api':'fnlttSinglAcntAll.json','fetched_at_utc':now.isoformat(),
                       'row_count':len(rows),'rows':[{k:r.get(k) for k in ('rcept_no','sj_div','account_id','account_nm','account_detail','thstrm_dt','thstrm_amount','thstrm_add_amount','frmtrm_dt','frmtrm_amount','frmtrm_add_amount','currency')} for r in rows]})
                    break # Prefer CFS; fall back to OFS only when unavailable.
                except Exception as exc:result['errors'].append({'year':year,'report':report,'fs':fs,'error':type(exc).__name__})
            if len(result['filings'])>=2:break
        result['status']='FETCHED_NOT_RECONCILED' if result['filings'] else 'NO_USABLE_FINANCIAL_STATEMENT'
        results.append(result)
    output={'generated_at_utc':now.isoformat(),'trading_date':gate.get('trading_date'),'classification':'RAW_OFFICIAL_DART_EVIDENCE_NOT_FINANCIALLY_RECONCILED',
            'candidate_count':len(results),'fetched_count':sum(bool(x['filings']) for x in results),
            'verified_count':0,'financial_verification_status_created':False,
            'note':'Official DART rows/receipt numbers fetched; growth, cumulative-period, accounting and filing revision reconciliation NOT yet performed. No A/B grade authorized.', 'results':results}
    (DATA/'daily_dart_evidence.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'candidates':len(results),'fetched':output['fetched_count'],'verified':0},ensure_ascii=False))
if __name__=='__main__':main()
