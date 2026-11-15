#!/usr/bin/env python3
"""Stage 8: refresh latest official DART financial evidence, fail closed.
Run after latest-filing audit; run period reconciliation again afterwards.
Never authorizes grades or financial verification.
"""
import datetime as dt
import json, os, pathlib, time, urllib.parse, urllib.request

DATA = pathlib.Path(__file__).resolve().parents[1] / 'data'
BASE = 'https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json'
FIELDS = ('rcept_no','sj_div','account_id','account_nm','account_detail',
          'thstrm_dt','thstrm_amount','thstrm_add_amount','frmtrm_dt',
          'frmtrm_amount','frmtrm_add_amount','currency')

def fetch(key, corp, year, report, fs):
    args = {'crtfc_key':key,'corp_code':corp,'bsns_year':year,
            'reprt_code':report,'fs_div':fs}
    url = BASE + '?' + urllib.parse.urlencode(args)
    for attempt in range(3):
        try:
            req = urllib.request.Request(url,headers={'User-Agent':'KRX-research/1.0'})
            with urllib.request.urlopen(req,timeout=35) as resp:
                return json.load(resp)
        except Exception:
            if attempt == 2: raise
            time.sleep(2**attempt)

def main():
    key=os.getenv('DART_API_KEY','').strip()
    if not key: raise SystemExit('DART_API_KEY missing')
    evidence_path=DATA/'daily_dart_evidence.json'
    audit_path=DATA/'daily_dart_latest_filing_audit.json'
    evidence=json.loads(evidence_path.read_text(encoding='utf-8'))
    audit=json.loads(audit_path.read_text(encoding='utf-8'))
    audit_by_code={str(x.get('code')).zfill(6):x for x in audit.get('results',[])}
    log=[]; updated=0
    for item in evidence.get('results',[]):
        code=str(item.get('code')).zfill(6)
        a=audit_by_code.get(code)
        record={'code':code,'name':item.get('name'),'status':'NOT_REFRESHED',
                'financial_verified':False,'grade_authorized':False,'errors':[]}
        if not a or not a.get('latest_periodic'):
            record['status']='NO_LATEST_FILING_AUDIT';log.append(record);continue
        latest=a['latest_periodic']; corp=item.get('corp_code')
        year=latest.get('fiscal_year');report=latest.get('report_code');receipt=latest.get('receipt_no')
        record.update({'year':year,'report_code':report,'expected_receipt':receipt})
        if not (corp and year and report and receipt):
            record['status']='INCOMPLETE_LATEST_FILING_IDENTITY';log.append(record);continue
        if a.get('errors'):
            record['errors'].append('LATEST_AUDIT_HAS_WARNINGS')
        matching=[f for f in item.get('filings',[]) if str(f.get('year'))==str(year) and f.get('report_code')==report]
        if matching and receipt in matching[0].get('receipt_numbers',[]):
            record['status']='ALREADY_MATCHES_LATEST_RECEIPT'
            record['statement_type']=matching[0].get('fs_div')
            log.append(record);continue
        success=False
        for fs in ('CFS','OFS'):
            try:
                response=fetch(key,corp,year,report,fs)
            except Exception as e:
                record['errors'].append({'fs':fs,'error':type(e).__name__});continue
            if response.get('status')=='013':continue
            if response.get('status')!='000':
                record['errors'].append({'fs':fs,'api_status':response.get('status'),
                                         'message':response.get('message')});continue
            rows=response.get('list') or []
            receipts=sorted({r.get('rcept_no') for r in rows if r.get('rcept_no')})
            if not rows or not receipts:continue
            if receipt not in receipts:
                record['errors'].append({'fs':fs,'expected_receipt':receipt,
                                         'actual_receipts':receipts,
                                         'error':'LATEST_DISCLOSURE_RECEIPT_MISMATCH'})
                continue
            new={'year':int(year),'report_code':report,'fs_div':fs,
                 'receipt_numbers':receipts,'source_api':'fnlttSinglAcntAll.json',
                 'fetched_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
                 'row_count':len(rows),'rows':[{k:r.get(k) for k in FIELDS} for r in rows]}
            item['filings']=[f for f in item.get('filings',[])
                             if not (str(f.get('year'))==str(year) and f.get('report_code')==report)]
            item['filings'].append(new)
            item['filings'].sort(key=lambda f:(int(f['year']),{'11013':1,'11012':2,'11014':3,'11011':4}.get(f['report_code'],0)),reverse=True)
            record.update({'status':'REFRESHED_LATEST_PERIOD','statement_type':fs,
                           'actual_receipts':receipts,'row_count':len(rows)})
            updated+=1;success=True;break
        if not success:record['status']='REFRESH_FAILED_OR_RECEIPT_MISMATCH'
        log.append(record)
    evidence['generated_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
    evidence['classification']='OFFICIAL_DART_EVIDENCE_REFRESHED_NOT_FINAL_VERIFIED'
    evidence['verified_count']=0
    evidence['financial_verification_status_created']=False
    evidence['note']='Latest report refreshed where matching DART receipt exists; amendment lineage and financial verification pending. No A/B grades.'
    evidence_path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    result={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
            'trading_date':evidence.get('trading_date'),'candidate_count':len(log),
            'refreshed_count':updated,'failed_count':sum(x['status']=='REFRESH_FAILED_OR_RECEIPT_MISMATCH' for x in log),
            'financial_verified_count':0,'grade_authorized_count':0,'results':log}
    (DATA/'daily_dart_financial_refresh.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'candidates':len(log),'refreshed':updated,'failed':result['failed_count'],'verified':0},ensure_ascii=False))

if __name__=='__main__':main()
