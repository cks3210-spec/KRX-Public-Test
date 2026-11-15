#!/usr/bin/env python3
"""Audit most recent periodic DART filings and amendments against fetched evidence.
Does not assert financial verification or grant investment grades.
Run after build_dart_period_reconciliation.py; needs DART_API_KEY.
"""
import datetime as dt
import json, os, pathlib, re, time, urllib.parse, urllib.request
DATA=pathlib.Path(__file__).resolve().parents[1]/'data'
BASE='https://opendart.fss.or.kr/api/list.json'
PERIODS={'1분기보고서':('11013',1),'반기보고서':('11012',2),'3분기보고서':('11014',3),'사업보고서':('11011',4)}
def api(key,corp,start,end,page):
    params={'crtfc_key':key,'corp_code':corp,'bgn_de':start,'end_de':end,'last_reprt_at':'N','pblntf_ty':'A','sort':'date','sort_mth':'desc','page_no':page,'page_count':100}
    url=BASE+'?'+urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'KRX-research/1.0'}),timeout=30) as r:
                return json.load(r)
        except Exception:
            if attempt==2:raise
            time.sleep(2**attempt)
def classify(name):
    for title,(code,q) in PERIODS.items():
        if title in name:
            m=re.search(r'\((20\d\d)\.(\d\d)\)',name)
            return {'report_code':code,'quarter':q,'fiscal_year':int(m.group(1)) if m else None,'report_name':name}
    return None
def main():
    key=os.getenv('DART_API_KEY','').strip()
    if not key:raise SystemExit('DART_API_KEY missing')
    source=json.loads((DATA/'daily_dart_evidence.json').read_text(encoding='utf-8'))
    today=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    start=(today-dt.timedelta(days=550)).strftime('%Y%m%d');end=today.strftime('%Y%m%d')
    results=[]
    for item in source.get('results',[]):
        out={'code':item.get('code'),'name':item.get('name'),'corp_code':item.get('corp_code'),'status':'NOT_VERIFIED','errors':[],'latest_periodic':None,'collected_period':None,'newer_filing_available':None,'amendment_review_required':True,'financial_verified':False,'grade_authorized':False}
        corp=item.get('corp_code')
        if not corp:
            out['errors'].append('CORP_CODE_MISSING');results.append(out);continue
        filings=[]
        try:
            for page in range(1,6):
                data=api(key,corp,start,end,page)
                if data.get('status')=='013':break
                if data.get('status')!='000':
                    out['errors'].append({'api_status':data.get('status'),'message':data.get('message')});break
                filings.extend(data.get('list') or [])
                if page>=int(data.get('total_page') or 1):break
            else:out['errors'].append('PAGINATION_LIMIT_REACHED')
        except Exception as e:out['errors'].append('DART_LIST_REQUEST_FAILED_'+type(e).__name__)
        parsed=[]
        for f in filings:
            p=classify(f.get('report_nm',''))
            if p:
                p.update({'receipt_no':f.get('rcept_no'),'receipt_date':f.get('rcept_dt'),'remark':f.get('rm',''),'amended':('정정' in f.get('report_nm','')),'withdrawn':('W' in f.get('rm',''))})
                parsed.append(p)
        parsed.sort(key=lambda p:(p['fiscal_year'] or 0,p['quarter'],p['receipt_date'] or '',p['receipt_no'] or ''),reverse=True)
        if parsed:
            latest=parsed[0]
            out['latest_periodic']=latest
            collected=[{'year':int(f['year']),'report_code':f['report_code'],'receipts':f.get('receipt_numbers',[])} for f in item.get('filings',[])]
            out['collected_period']=collected
            same=[f for f in collected if f['year']==latest['fiscal_year'] and f['report_code']==latest['report_code']]
            out['newer_filing_available']=not bool(same)
            out['latest_receipt_matches_collected']=bool(same and latest['receipt_no'] in same[0]['receipts'])
            out['periodic_filing_count']=len(parsed)
            out['status']='LATEST_PERIOD_NOT_COLLECTED' if not same else ('RECEIPT_MISMATCH_OR_AMENDMENT' if not out['latest_receipt_matches_collected'] else 'PERIOD_FOUND_AMENDMENT_REVIEW_PENDING')
            if any(f['amended'] for f in parsed):out['errors'].append('AMENDED_PERIODIC_FILINGS_PRESENT')
        else:
            out['status']='NO_PERIODIC_FILINGS_FOUND'
        results.append(out)
    output={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'searched_receipt_dates':[start,end], 'trading_date':source.get('trading_date'),'candidate_count':len(results),'latest_period_missing_count':sum(r['newer_filing_available'] is True for r in results),'verified_count':0,'classification':'LATEST_FILING_AND_AMENDMENT_AUDIT_NOT_FINANCIAL_VERIFICATION','results':results}
    dest=DATA/'daily_dart_latest_filing_audit.json';dest.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(dest),'candidates':len(results),'missing_latest':output['latest_period_missing_count'],'verified':0}))
if __name__=='__main__':main()
