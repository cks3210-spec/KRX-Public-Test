#!/usr/bin/env python3
"""Independent OpenDART history diagnostics: TTM profit, comparable equity, CFO.
No scores, no edits to any existing pipeline. Missing/ambiguous values stay null.
"""
import argparse, csv, io, json, os, time, urllib.parse, urllib.request, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone

API='https://opendart.fss.or.kr/api/'
ACCOUNTS={
 'net_income':({'ifrs-full_ProfitLoss','ifrs_ProfitLoss'}, {'당기순이익','당기순이익(손실)','연결당기순이익'}, {'IS','CIS'}),
 'equity':({'ifrs-full_Equity','ifrs_Equity'}, {'자본총계'}, {'BS'}),
 'cfo':({'ifrs-full_CashFlowsFromUsedInOperatingActivities','ifrs_CashFlowsFromUsedInOperatingActivities'}, {'영업활동현금흐름','영업활동으로 인한 현금흐름','영업활동으로인한현금흐름'}, {'CF'}),
}

def amount(v):
 try:return int(str(v).replace(',','').strip())
 except (ValueError,TypeError):return None

def get(endpoint, params=None, binary=False):
 key=os.environ['DART_API_KEY']
 url=API+endpoint+'?'+urllib.parse.urlencode({'crtfc_key':key,**(params or {})})
 for attempt in range(4):
  try:
   with urllib.request.urlopen(url,timeout=50) as response: raw=response.read()
   if binary:return raw
   data=json.loads(raw)
   if str(data.get('status')) in ('020','800','900'):raise RuntimeError('DART retryable '+str(data.get('status')))
   return data
  except (OSError,ValueError,RuntimeError):
   if attempt==3:raise
   time.sleep(2**attempt)

def select(rows, metric, key):
 ids, labels, sections=ACCOUNTS[metric]
 eligible=[r for r in rows if r.get('sj_div') in sections and r.get('account_detail','-') in ('','-')]
 by_id=[r for r in eligible if r.get('account_id') in ids]
 candidates=by_id or [r for r in eligible if r.get('account_nm','').strip() in labels]
 values={amount(r.get(key)) for r in candidates if amount(r.get(key)) is not None}
 return next(iter(values)) if len(values)==1 else None

def fetch_statement(corp, year, report, fs):
 data=get('fnlttSinglAcntAll.json',{'corp_code':corp,'bsns_year':str(year),'reprt_code':report,'fs_div':fs})
 if str(data.get('status'))!='000':return None, 'DART_'+str(data.get('status'))
 return data.get('list') or [], None

def calculate(snapshot, corp):
 year=int(snapshot['fiscal_year']);report=snapshot['report_code'];fs=snapshot['statement_type']
 if report not in ('11011','11012','11013','11014') or fs not in ('CFS','OFS'):return {'status':'INVALID_SNAPSHOT'}
 current,error=fetch_statement(corp,year,report,fs)
 if error:return {'status':'CURRENT_'+error}
 # The preceding FY has the annual income and beginning-of-year equity.
 prior,error=fetch_statement(corp,year-1,'11011',fs)
 if error:return {'status':'PRIOR_FY_'+error}
 current_key='thstrm_amount' if report=='11011' else 'thstrm_add_amount'
 previous_ytd_key='frmtrm_amount' if report=='11011' else 'frmtrm_add_amount'
 curr_ni=select(current,'net_income',current_key)
 prior_ytd_ni=select(current,'net_income',previous_ytd_key)
 prior_fy_ni=select(prior,'net_income','thstrm_amount')
 ttm=curr_ni if report=='11011' else (prior_fy_ni+curr_ni-prior_ytd_ni if None not in (prior_fy_ni,curr_ni,prior_ytd_ni) else None)
 end_eq=select(current,'equity','thstrm_amount')
 start_eq=select(prior,'equity','thstrm_amount')
 average_eq=(end_eq+start_eq)/2 if end_eq is not None and start_eq is not None and end_eq>0 and start_eq>0 else None
 roe=round(ttm/average_eq*100,3) if ttm is not None and average_eq else None
 curr_cfo=select(current,'cfo',current_key)
 prior_ytd_cfo=select(current,'cfo',previous_ytd_key)
 prior_fy_cfo=select(prior,'cfo','thstrm_amount')
 cfo_ttm=curr_cfo if report=='11011' else (prior_fy_cfo+curr_cfo-prior_ytd_cfo if None not in (prior_fy_cfo,curr_cfo,prior_ytd_cfo) else None)
 return {'status':'PARTIAL' if None in (ttm,roe,cfo_ttm) else 'COMPLETE',
  'ttm_net_income_krw':ttm,'prior_fy_net_income_krw':prior_fy_ni,
  'current_ytd_net_income_krw':curr_ni,'previous_ytd_net_income_krw':prior_ytd_ni,
  'equity_start_krw':start_eq,'equity_end_krw':end_eq,'roe_ttm_pct_diagnostic':roe,
  'cfo_ttm_krw':cfo_ttm,'prior_fy_cfo_krw':prior_fy_cfo,
  'formula':'FY_prior + current_YTD - previous_YTD' if report!='11011' else 'FY_current',
  'caveat':'CFS total profit and total equity; attributable earnings/equity and financial-sector rules not validated.'}

def main():
 p=argparse.ArgumentParser();p.add_argument('--input',default='v5_state/financial_latest.json');p.add_argument('--output',default='v5_history_output');p.add_argument('--limit',type=int,default=0);p.add_argument('--sleep',type=float,default=.5)
 args=p.parse_args();snapshots=json.loads(Path(args.input).read_text(encoding='utf-8'))
 out=Path(args.output);out.mkdir(parents=True,exist_ok=True);dest=out/'history_metrics.json'
 results=json.loads(dest.read_text(encoding='utf-8')) if dest.exists() else {}
 blob=get('corpCode.xml',binary=True)
 with zipfile.ZipFile(io.BytesIO(blob)) as z:root=ET.fromstring(z.read(next(n for n in z.namelist() if n.lower().endswith('.xml'))))
 mapping={e.findtext('stock_code','').strip():e.findtext('corp_code','').strip() for e in root.findall('list') if e.findtext('stock_code')}
 attempts=0;errors=0
 for code,s in sorted(snapshots.items()):
  if args.limit and attempts>=args.limit:break
  if not isinstance(s,dict) or not mapping.get(code):continue
  identity=[str(s.get('fiscal_year')),s.get('report_code'),s.get('statement_type'),s.get('verified_at_utc')]
  if results.get(code,{}).get('identity')==identity:continue
  attempts+=1
  try:
   result=calculate(s,mapping[code]);result.update({'identity':identity,'ISU_NM':s.get('ISU_NM'),'period':s.get('period')})
   results[code]=result
   if result['status'].startswith(('CURRENT_','PRIOR_FY_')):errors+=1
  except (OSError,ValueError,RuntimeError,KeyError) as exc:
   errors+=1;print('RETRY_LATER',code,str(exc)[:90],flush=True)
  if attempts%20==0:
   dest.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
   print('processed',attempts,'records',len(results),flush=True)
  time.sleep(args.sleep)
 dest.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
 summary={'asof_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),'snapshot_count':len(snapshots),'history_records':len(results),'requests_this_run':attempts,'errors_this_run':errors,
  'ttm_net_income_available':sum(isinstance(v.get('ttm_net_income_krw'),int) for v in results.values()),
  'roe_diagnostic_available':sum(isinstance(v.get('roe_ttm_pct_diagnostic'),(int,float)) for v in results.values()),
  'cfo_ttm_available':sum(isinstance(v.get('cfo_ttm_krw'),int) for v in results.values()),
  'caution':'Diagnostics only; equity/earnings ownership and statement restatements not yet reconciled; do not score or trade.'}
 (out/'history_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
