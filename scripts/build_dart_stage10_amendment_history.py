#!/usr/bin/env python3
"""Stage 10: audit OpenDART periodic filing amendment history, fail closed.
Reads daily_dart_evidence.json and stage9 verification; writes stage10 audit.
This is a receipt/history audit, NOT proof of full financial restatement lineage.
"""
import datetime as dt
import json, os, pathlib, re, time, urllib.parse, urllib.request
DATA=pathlib.Path(__file__).resolve().parents[1]/'data'
API='https://opendart.fss.or.kr/api/list.json'
CODES={'03':'11013','06':'11012','09':'11014','12':'11011'}

def classify(name):
    m=re.search(r'\((20\d{2})\.(03|06|09|12)\)',name or '')
    if not m:return None
    month=m.group(2)
    if month=='06' and '반기보고서' not in name:return None
    if month=='12' and '사업보고서' not in name:return None
    if month in ('03','09') and ('분기보고서' not in name or '반기보고서' in name):return None
    return (int(m.group(1)),CODES[month])

def fetch(key,corp,start,end,page):
    args={'crtfc_key':key,'corp_code':corp,'bgn_de':start,'end_de':end,
          'last_reprt_at':'N','pblntf_ty':'A','sort':'date','sort_mth':'desc',
          'page_no':page,'page_count':100}
    url=API+'?'+urllib.parse.urlencode(args)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'KRX-research/1.0'}),timeout=35) as r:return json.load(r)
        except Exception:
            if attempt==2:raise
            time.sleep(2**attempt)

def main():
    key=os.getenv('DART_API_KEY','').strip()
    if not key:raise SystemExit('DART_API_KEY missing')
    evidence=json.loads((DATA/'daily_dart_evidence.json').read_text(encoding='utf-8'))
    stage9=json.loads((DATA/'daily_dart_stage9_verification.json').read_text(encoding='utf-8'))
    s9={str(x.get('code')).zfill(6):x for x in stage9.get('results',[])}
    now=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    start=(now-dt.timedelta(days=800)).strftime('%Y%m%d');end=now.strftime('%Y%m%d')
    results=[]
    for item in evidence.get('results',[]):
        code=str(item.get('code')).zfill(6);corp=item.get('corp_code')
        result={'code':code,'name':item.get('name'),'corp_code':corp,
                'status':'UNVERIFIED','history_search_complete':False,
                'amendment_detected':None,'amendment_financial_change_verified':False,
                'financial_verified':False,'grade_authorized':False,'buy_signal':None,
                'periods':[],'issues':[]}
        if not corp:
            result['issues'].append('CORP_CODE_MISSING');results.append(result);continue
        found=[];complete=True
        try:
            for page in range(1,21):
                resp=fetch(key,corp,start,end,page)
                if resp.get('status')=='013':break
                if resp.get('status')!='000':
                    result['issues'].append('DART_API_'+str(resp.get('status')));complete=False;break
                found.extend(resp.get('list') or [])
                if page>=int(resp.get('total_page') or 1):break
            else:
                complete=False;result['issues'].append('PAGINATION_LIMIT_REACHED')
        except Exception as exc:
            complete=False;result['issues'].append('DART_REQUEST_FAILED_'+type(exc).__name__)
        result['history_search_complete']=complete
        groups={}
        for filing in found:
            identity=classify(filing.get('report_nm',''))
            if identity:
                groups.setdefault(identity,[]).append({'receipt_no':filing.get('rcept_no'),
                    'receipt_date':filing.get('rcept_dt'),'report_name':filing.get('report_nm'),
                    'remark':filing.get('rm',''),'amended':'정정' in filing.get('report_nm',''),
                    'withdrawn':'W' in str(filing.get('rm',''))})
        amendment=False
        for filing in item.get('filings',[]):
            year=int(filing['year']);report=filing['report_code']
            history=sorted(groups.get((year,report),[]),key=lambda x:(x['receipt_date'] or '',x['receipt_no'] or ''))
            amendments=[x for x in history if x['amended']]
            amendment=amendment or bool(amendments)
            latest=history[-1] if history else None
            receipts=filing.get('receipt_numbers') or []
            matched=bool(latest and latest['receipt_no'] in receipts)
            result['periods'].append({'year':year,'report_code':report,'statement_type':filing.get('fs_div'),
                'collected_receipts':receipts,'latest_disclosed_receipt':latest['receipt_no'] if latest else None,
                'latest_receipt_matches':matched,'amendment_count':len(amendments),
                'history':history,'status':('MATCHED' if matched else 'MISSING_OR_MISMATCHED')})
            if not matched:result['issues'].append('PERIOD_HISTORY_MISSING_OR_RECEIPT_MISMATCH')
            if any(x['withdrawn'] for x in history):result['issues'].append('WITHDRAWN_FILING_PRESENT')
        result['amendment_detected']=amendment if complete else None
        if amendment:result['issues'].append('AMENDMENT_PRESENT_FINANCIAL_DIFF_NOT_VERIFIED')
        if not complete:result['issues'].append('INCOMPLETE_HISTORY_SEARCH')
        if not s9.get(code,{}).get('evidence_consistency_passed'):
            result['issues'].append('STAGE9_CONSISTENCY_NOT_PASSED')
        # Listing history cannot prove original-vs-amended financial row differences.
        result['issues'].append('ORIGINAL_VS_AMENDED_FINANCIAL_VALUES_NOT_COMPARED')
        result['issues'].append('GRADE_MODEL_NOT_VALIDATED')
        result['status']='HISTORY_AUDITED_NOT_FINANCIALLY_VERIFIED' if complete and not any(p['status']!='MATCHED' for p in result['periods']) else 'HISTORY_INCOMPLETE_OR_MISMATCHED'
        results.append(result)
    output={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'trading_date':evidence.get('trading_date'),'search_receipt_dates':[start,end],
        'candidate_count':len(results),
        'history_audited_count':sum(x['status']=='HISTORY_AUDITED_NOT_FINANCIALLY_VERIFIED' for x in results),
        'amendment_detected_count':sum(x['amendment_detected'] is True for x in results),
        'financial_verified_count':0,'final_ab_grade_count':0,
        'note':'Searches all returned periodic filings including corrections; financial value differences and completeness outside date window remain unverified. No buy signals.',
        'results':results}
    path=DATA/'daily_dart_stage10_amendment_history.json'
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'candidates':len(results),'audited':output['history_audited_count'],
        'amendments':output['amendment_detected_count'],'verified':0},ensure_ascii=False))
if __name__=='__main__':main()
