#!/usr/bin/env python3
"""Read-only OpenDART ROE source pilot. Never replaces production history or scores."""
import argparse, csv, json, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

API='https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json'
OWNER_NI={'ifrs-full_ProfitLossAttributableToOwnersOfParent','ifrs_ProfitLossAttributableToOwnersOfParent'}
OWNER_EQ={'ifrs-full_EquityAttributableToOwnersOfParent','ifrs_EquityAttributableToOwnersOfParent'}

def number(x):
    try:return int(str(x).replace(',','').strip())
    except (TypeError,ValueError):return None

def get(corp,year,report,fs):
    params={'crtfc_key':os.environ['DART_API_KEY'],'corp_code':corp,'bsns_year':str(year),'reprt_code':report,'fs_div':fs}
    url=API+'?'+urllib.parse.urlencode(params)
    for i in range(4):
        try:
            with urllib.request.urlopen(url,timeout=45) as f:data=json.load(f)
            if str(data.get('status')) in ('020','800','900'):raise RuntimeError('retryable DART status')
            return data
        except (OSError,ValueError,RuntimeError):
            if i==3:raise
            time.sleep(2**i)

def pick(rows,ids,section,keys):
    candidates=[r for r in rows if r.get('sj_div') in section and r.get('account_id') in ids and r.get('account_detail','-') in ('-','')]
    for key in keys:
        vals={number(r.get(key)) for r in candidates if number(r.get(key)) is not None}
        if len(vals)==1:return vals.pop(),key
        if len(vals)>1:return None,'AMBIGUOUS_'+key
    return None,'MISSING'

def evaluate(code,s,corp):
    out={'code':code,'name':s.get('ISU_NM'),'period':s.get('period'),'statement_type':s.get('statement_type'),'source':'OpenDART fnlttSinglAcntAll','status':'UNVERIFIED'}
    year=int(s['fiscal_year']);report=s['report_code'];fs=s['statement_type']
    if fs!='CFS':out['status']='NOT_CONSOLIDATED';return out
    current=get(corp,year,report,fs)
    prior=get(corp,year-1,'11011',fs)
    if current.get('status')!='000' or prior.get('status')!='000':
        out['status']='DART_UNAVAILABLE';out['dart_status_current']=current.get('status');out['dart_status_prior']=prior.get('status');return out
    now=current['list'];prev=prior['list']
    # IS/CIS cumulative columns, except annual where current-period field is used.
    current_keys=['thstrm_amount'] if report=='11011' else ['thstrm_add_amount']
    prev_ytd_keys=['frmtrm_amount'] if report=='11011' else ['frmtrm_add_amount']
    ni_now,k1=pick(now,OWNER_NI,{'IS','CIS'},current_keys)
    ni_prev_ytd,k2=pick(now,OWNER_NI,{'IS','CIS'},prev_ytd_keys) if report!='11011' else (None,'NOT_NEEDED')
    ni_prior_fy,k3=pick(prev,OWNER_NI,{'IS','CIS'},['thstrm_amount'])
    # Current and comparable 12-month-prior balance sheet from same interim filing.
    # For annual report, prior-year-end equity from comparative BS.
    eq_now,k4=pick(now,OWNER_EQ,{'BS'},['thstrm_amount'])
    eq_prior,k5=pick(now,OWNER_EQ,{'BS'},['frmtrm_amount'])
    out.update({'owner_ni_current_ytd':ni_now,'owner_ni_previous_ytd':ni_prev_ytd,'owner_ni_prior_fy':ni_prior_fy,
                'owner_equity_current':eq_now,'owner_equity_comparative':eq_prior,
                'field_keys':{'current_ni':k1,'previous_ytd_ni':k2,'prior_fy_ni':k3,'current_equity':k4,'comparative_equity':k5}})
    # WARNING: interim BS frmtrm_amount is generally prior FY-end, NOT same quarter last year.
    # Only annual comparison is a 12-month aligned equity pair. For interim, fetch previous-year same report.
    if report!='11011':
        prior_same=get(corp,year-1,report,fs)
        if prior_same.get('status')=='000':
            eq_prior,k5=pick(prior_same['list'],OWNER_EQ,{'BS'},['thstrm_amount'])
            out['owner_equity_12m_prior']=eq_prior
            out['field_keys']['equity_12m_prior']='previous_year_same_report:'+k5
        else:
            out['owner_equity_12m_prior']=None;out['field_keys']['equity_12m_prior']='DART_UNAVAILABLE'
    else:
        out['owner_equity_12m_prior']=eq_prior
        out['field_keys']['equity_12m_prior']='current_annual_comparative:'+k5
    ni=ni_now if report=='11011' else (ni_prior_fy+ni_now-ni_prev_ytd if None not in (ni_prior_fy,ni_now,ni_prev_ytd) else None)
    eq_old=out['owner_equity_12m_prior']
    out['owner_ttm_net_income']=ni
    if None not in (ni,eq_now,eq_old) and eq_now>0 and eq_old>0:
        out['roe_owner_ttm_pct']=round(200*ni/(eq_now+eq_old),4)
        out['status']='ARITHMETIC_READY_SOURCE_REVIEW_REQUIRED'
    else:out['status']='MISSING_OR_NONPOSITIVE_OWNER_EQUITY_OR_PROFIT'
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument('--snapshot',default='v5_state/financial_latest.json');p.add_argument('--history',default='v5_history_output/history_metrics.json');p.add_argument('--limit',type=int,default=5);p.add_argument('--output',default='v5_roe_pilot_output');a=p.parse_args()
    if a.limit<1 or a.limit>10:raise SystemExit('pilot limit must be 1..10')
    snapshots=json.loads(Path(a.snapshot).read_text());history=json.loads(Path(a.history).read_text())
    # DART corp code mapping from official corpCode.xml
    import io,zipfile,xml.etree.ElementTree as ET
    url='https://opendart.fss.or.kr/api/corpCode.xml?'+urllib.parse.urlencode({'crtfc_key':os.environ['DART_API_KEY']})
    with urllib.request.urlopen(url,timeout=60) as f:blob=f.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as z:root=ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith('.xml'))))
    mapping={e.findtext('stock_code','').strip():e.findtext('corp_code','').strip() for e in root.findall('list') if e.findtext('stock_code')}
    output=[]
    for code in sorted(history):
        if len(output)>=a.limit:break
        if code not in snapshots or code not in mapping:continue
        s=snapshots[code]
        if s.get('statement_type')!='CFS':continue
        try:r=evaluate(code,s,mapping[code])
        except Exception as e:r={'code':code,'name':s.get('ISU_NM'),'status':'ERROR','error':str(e)[:150]}
        output.append(r);print(code,r['status'],flush=True)
        time.sleep(.5)
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    (out/'pilot_details.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    summary={'utc':datetime.now(timezone.utc).isoformat(),'pilot_count':len(output),'status_counts':{k:sum(x['status']==k for x in output) for k in sorted({x['status'] for x in output})},'caution':'Source/field diagnostics only. No automatic replacement of existing ROE or investment grades.'}
    (out/'pilot_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
