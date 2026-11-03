#!/usr/bin/env python3
"""Checkpointed batch history collection; relies on verified v5_history_enrich.calculate."""
import argparse, io, json, os, time, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from v5_history_enrich import get, calculate

def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(path)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',default='v5_state/financial_latest.json')
    p.add_argument('--output',default='v5_history_output')
    p.add_argument('--batch-size',type=int,default=45)
    p.add_argument('--sleep',type=float,default=.5)
    a=p.parse_args()
    if not 1 <= a.batch_size <= 150: raise SystemExit('batch-size must be 1..150')
    snapshots=json.loads(Path(a.input).read_text(encoding='utf-8'))
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    dest=out/'history_metrics.json'
    results=json.loads(dest.read_text(encoding='utf-8')) if dest.exists() else {}
    blob=get('corpCode.xml',binary=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        root=ET.fromstring(z.read(next(n for n in z.namelist() if n.lower().endswith('.xml'))))
    mapping={e.findtext('stock_code','').strip():e.findtext('corp_code','').strip() for e in root.findall('list') if e.findtext('stock_code')}
    attempted=0; errors=0; eligible=0; pending=0
    for code,s in sorted(snapshots.items()):
        if not isinstance(s,dict) or not mapping.get(code):continue
        eligible+=1
        identity=[str(s.get('fiscal_year')),s.get('report_code'),s.get('statement_type'),s.get('verified_at_utc')]
        previous=results.get(code,{})
        if previous.get('identity')==identity and previous.get('status') in ('COMPLETE','PARTIAL'):
            continue
        pending+=1
        if attempted>=a.batch_size:continue
        attempted+=1
        try:
            result=calculate(s,mapping[code])
            result.update({'identity':identity,'ISU_NM':s.get('ISU_NM'),'period':s.get('period')})
            if result.get('status') in ('COMPLETE','PARTIAL'):
                results[code]=result
            else:
                errors+=1
                print('RETRY_NEXT_RUN',code,result.get('status'),flush=True)
        except (OSError,ValueError,RuntimeError,KeyError) as exc:
            errors+=1
            print('RETRY_NEXT_RUN',code,str(exc)[:100],flush=True)
        if attempted%10==0:save(dest,results)
        time.sleep(a.sleep)
    save(dest,results)
    verified={k:v for k,v in results.items() if isinstance(v,dict) and v.get('status') in ('COMPLETE','PARTIAL')}
    remaining=sum(1 for code,s in snapshots.items() if isinstance(s,dict) and mapping.get(code) and not (verified.get(code,{}).get('identity')==[str(s.get('fiscal_year')),s.get('report_code'),s.get('statement_type'),s.get('verified_at_utc')]))
    summary={'asof_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),'snapshot_count':len(snapshots),'eligible':eligible,'verified_records':len(verified),'attempted_this_run':attempted,'errors_this_run':errors,'remaining':remaining,'ttm_net_income_available':sum(isinstance(v.get('ttm_net_income_krw'),int) for v in verified.values()),'roe_diagnostic_available':sum(isinstance(v.get('roe_ttm_pct_diagnostic'),(int,float)) for v in verified.values()),'cfo_ttm_available':sum(isinstance(v.get('cfo_ttm_krw'),int) for v in verified.values()),'note':'Diagnostics only. Failures retry on subsequent runs; no v4/GC or scoring changes.'}
    save(out/'history_summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':main()
