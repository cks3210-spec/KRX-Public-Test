#!/usr/bin/env python3
"""Independent growth enrichment: only verified same-report, same-statement comparatives."""
import argparse, csv, io, json, os, time, urllib.parse, urllib.request, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

API='https://opendart.fss.or.kr/api/'
IDS={'revenue':{'ifrs-full_Revenue','ifrs_Revenue','ifrs-full_RevenueFromContractsWithCustomers'},'operating_profit':{'dart_OperatingIncomeLoss'},'net_income':{'ifrs-full_ProfitLoss','ifrs_ProfitLoss'}}
LABELS={'revenue':{'매출액','수익(매출액)','영업수익','매출','수익'},'operating_profit':{'영업이익','영업이익(손실)'},'net_income':{'당기순이익','당기순이익(손실)','연결당기순이익'}}
def amount(v):
    try:return int(str(v).replace(',','').strip())
    except (ValueError,TypeError):return None
def get(endpoint,params={},binary=False):
    key=os.environ['DART_API_KEY']
    url=API+endpoint+'?'+urllib.parse.urlencode({'crtfc_key':key,**params})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url,timeout=40) as f:raw=f.read()
            if binary:return raw
            obj=json.loads(raw)
            if str(obj.get('status')) in ('020','800','900'):raise RuntimeError('retryable API status '+str(obj['status']))
            return obj
        except (OSError,ValueError,RuntimeError):
            if attempt==3:raise
            time.sleep(2**attempt)
def extract_comparatives(rows,report):
    # OpenDART: quarter/H1/Q3 income statement current thstrm_amount is 3-month,
    # while thstrm_add_amount/frmtrm_add_amount are year-to-date comparable sums.
    # FY compares thstrm_amount against frmtrm_amount.
    cumulative=report!='11011'
    current_key='thstrm_add_amount' if cumulative else 'thstrm_amount'
    prior_key='frmtrm_add_amount' if cumulative else 'frmtrm_amount'
    result={}
    for field in IDS:
        candidates=[r for r in rows if r.get('sj_div') in ('IS','CIS') and r.get('account_detail','-') in ('','-')]
        by_id=[r for r in candidates if r.get('account_id') in IDS[field]]
        matches=by_id or [r for r in candidates if r.get('account_nm','').strip() in LABELS[field]]
        pairs={(amount(r.get(current_key)),amount(r.get(prior_key))) for r in matches if amount(r.get(current_key)) is not None and amount(r.get(prior_key)) is not None}
        result[field]=next(iter(pairs)) if len(pairs)==1 else None
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',default='v5_state/financial_latest.json');p.add_argument('--output',default='v5_growth_output');p.add_argument('--limit',type=int,default=0);a=p.parse_args()
    snapshots=json.loads(Path(a.input).read_text(encoding='utf-8'))
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    blob=get('corpCode.xml',binary=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:root=ET.fromstring(z.read(next(x for x in z.namelist() if x.lower().endswith('.xml'))))
    mapping={e.findtext('stock_code','').strip():e.findtext('corp_code','').strip() for e in root.findall('list') if e.findtext('stock_code')}
    prior={}
    dest=out/'growth_comparatives.json'
    if dest.exists():
        try:prior=json.loads(dest.read_text(encoding='utf-8'))
        except (ValueError,OSError):pass
    results=dict(prior);count=0;fail=0
    for code,s in sorted(snapshots.items()):
        if a.limit and count>=a.limit:break
        if not isinstance(s,dict):continue
        report=s.get('report_code');year=s.get('fiscal_year');fs=s.get('statement_type')
        if report not in ('11011','11012','11013','11014') or not year or fs not in ('CFS','OFS') or not mapping.get(code):continue
        identity=[str(year),report,fs,s.get('verified_at_utc')]
        if results.get(code,{}).get('identity')==identity:continue
        count+=1
        try:
            data=get('fnlttSinglAcntAll.json',{'corp_code':mapping[code],'bsns_year':str(year),'reprt_code':report,'fs_div':fs})
            if str(data.get('status'))!='000':raise ValueError('DART_'+str(data.get('status')))
            fields=extract_comparatives(data.get('list') or [],report)
            metrics={};details={}
            for k,pair in fields.items():
                if pair is None:continue
                current,previous=pair
                details[k]={'current_krw':current,'previous_year_same_period_krw':previous}
                if k=='revenue' and previous>0:
                    metrics['revenue_growth_pct']=round((current/previous-1)*100,2)
                elif k=='operating_profit':
                    if previous>0:metrics['operating_profit_growth_pct']=round((current/previous-1)*100,2)
                    elif previous<=0 and current>0:metrics['operating_profit_turnaround']=True
                elif k=='net_income':
                    if previous>0:metrics['net_income_growth_pct']=round((current/previous-1)*100,2)
                    elif previous<=0 and current>0:metrics['net_income_turnaround']=True
            results[code]={'identity':identity,'ISU_NM':s.get('ISU_NM'),'period':s.get('period'),'statement_type':fs,'comparison_basis':'YTD_SAME_PERIOD' if report!='11011' else 'FY_SAME_PERIOD','metrics':metrics,'raw_comparatives':details,'status':'PARTIAL' if len(details)<3 else 'VERIFIED'}
        except (OSError,ValueError,RuntimeError) as exc:
            fail+=1
            # Never overwrite previously verified data on failure.
            print('RETRY_LATER',code,str(exc)[:80],flush=True)
        if count%20==0:
            dest.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        time.sleep(0.5)
    dest.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    summary={'snapshot_count':len(snapshots),'growth_records':len(results),'requests_this_run':count,'failures_this_run':fail,'note':'Growth only from same report and CFS/OFS; negative prior profit uses turnaround instead of invalid growth percentage'}
    (out/'growth_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
