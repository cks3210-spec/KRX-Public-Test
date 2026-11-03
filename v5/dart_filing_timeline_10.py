#!/usr/bin/env python3
"""v5-only OpenDART filing timeline diagnostic. No existing data/workflow changes."""
import csv, io, json, os, re, time, urllib.parse, urllib.request, zipfile
from datetime import date, datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

API='https://opendart.fss.or.kr/api/'
REPORTS={'사업보고서':'ANNUAL','반기보고서':'HALF','분기보고서':'QUARTER'}
def fetch(endpoint, params):
    url=API+endpoint+'?'+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={'User-Agent':'KRX-v5-filing-test/1.0'})
    with urllib.request.urlopen(req,timeout=45) as res:return res.read()
def query_json(endpoint, params):
    try:return json.loads(fetch(endpoint,params))
    except Exception as exc:return {'status':'NETWORK_ERROR','error_type':type(exc).__name__}
def classify(name):
    for k,v in REPORTS.items():
        if re.search(r'(?:^|정정|첨부정정|기재정정)'+k+r'\s*\(',name):return v
    return ''
def main():
    key=os.getenv('DART_API_KEY','').strip()
    if not key:raise SystemExit('DART_API_KEY missing')
    with open('data/latest.csv',encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    sample=sorted((r for r in rows if r.get('ISU_CD','').isdigit() and len(r['ISU_CD'])==6 and int(r.get('MKTCAP') or 0)>=100_000_000_000),key=lambda r:r['ISU_CD'])[:10]
    raw=fetch('corpCode.xml',{'crtfc_key':key})
    if not zipfile.is_zipfile(io.BytesIO(raw)):raise SystemExit('OpenDART corpCode failed: check authentication')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        root=ET.fromstring(z.read(next(n for n in z.namelist() if n.lower().endswith('.xml'))))
    codes={e.findtext('stock_code','').strip():e.findtext('corp_code','').strip() for e in root.findall('list') if e.findtext('stock_code')}
    today=date.today().strftime('%Y%m%d')
    timeline=[]; summary=[]
    for s in sample:
        code=s['ISU_CD']; corp=codes.get(code)
        item={'ISU_CD':code,'ISU_NM':s['ISU_NM'],'corp_code_matched':bool(corp),'filing_status':'','latest_filing_date':'','latest_report':'','filings_found':0,'corrections_found':0}
        if not corp:
            item['filing_status']='CORP_CODE_MISSING_OR_SHARE_CLASS'
        else:
            filings=[]; api_error=None
            for page in range(1,11):
                result=query_json('list.json',{'crtfc_key':key,'corp_code':corp,'bgn_de':'20250101','end_de':today,'page_no':page,'page_count':100})
                status=str(result.get('status','UNKNOWN'))
                if status=='013':break
                if status!='000':
                    api_error='DART_'+status if status!='NETWORK_ERROR' else 'NETWORK_ERROR_'+result.get('error_type','')
                    break
                for r in result.get('list') or []:
                    typ=classify(r.get('report_nm',''))
                    if typ:
                        filings.append({'ISU_CD':code,'ISU_NM':s['ISU_NM'],'receipt_no':r.get('rcept_no',''),
                                        'receipt_date':r.get('rcept_dt',''),'report_name':r.get('report_nm',''),
                                        'report_type':typ,'is_correction':('정정' in r.get('report_nm',''))})
                if page>=int(result.get('total_page',1)):break
                time.sleep(.15)
            filings.sort(key=lambda r:(r['receipt_date'],r['receipt_no']),reverse=True)
            timeline.extend(filings)
            item['filings_found']=len(filings)
            item['corrections_found']=sum(x['is_correction'] for x in filings)
            if api_error:item['filing_status']='API_ERROR_'+api_error
            elif filings:
                item['filing_status']='FILING_FOUND'
                item['latest_filing_date']=filings[0]['receipt_date']
                item['latest_report']=filings[0]['report_name']
            else:item['filing_status']='NO_MATCHING_FILING_IN_WINDOW'
        summary.append(item)
        time.sleep(.2)
    dest=Path('v5_output');dest.mkdir(exist_ok=True)
    with (dest/'filing_status_10.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(summary[0]));w.writeheader();w.writerows(summary)
    with (dest/'filing_history_10.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['ISU_CD','ISU_NM','receipt_no','receipt_date','report_name','report_type','is_correction']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(timeline)
    report={'asof':today,'sample_size':len(sample),'corp_code_matched':sum(x['corp_code_matched'] for x in summary),
            'filing_found':sum(x['filing_status']=='FILING_FOUND' for x in summary),
            'correction_receipts':sum(x['corrections_found'] for x in summary),
            'status_counts':{k:sum(x['filing_status']==k for x in summary) for k in sorted(set(x['filing_status'] for x in summary))},
            'scope':'Filing metadata only; 2025-01-01 to today',
            'limitations':['No legal deadline or lateness determination','No financial value extraction in this test',
                           'No persistent history across runs; download artifact for retention',
                           'No ratings or recommendations; existing v4/GC untouched']}
    (dest/'filing_summary_10.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not any(x['filing_status']=='FILING_FOUND' for x in summary):raise SystemExit('No filings verified; inspect diagnostics')
if __name__=='__main__':main()
