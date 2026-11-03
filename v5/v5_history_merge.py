#!/usr/bin/env python3
"""Merge v5 diagnostic financial snapshots; preserve last verified values on failures."""
import csv,json,os
from pathlib import Path
from datetime import datetime,timezone
FIELDS=('revenue','operating_profit','net_income','assets','liabilities','equity')
ROOT=Path('v5_output'); ROOT.mkdir(exist_ok=True)
PRIOR=Path('v5_prior')
def read(path):
 if not path.exists():return []
 with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(path,rows,cols):
 with path.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)
def main():
 now=datetime.now(timezone.utc).isoformat(timespec='seconds')
 incoming=read(ROOT/'dart_validate_v2.csv')
 if not incoming:raise SystemExit('No current extraction CSV: stop, do not overwrite prior history')
 old=read(PRIOR/'financial_latest.csv')
 old_by={r['ISU_CD']:r for r in old}
 merged={r['ISU_CD']:dict(r) for r in old}
 changes=read(PRIOR/'financial_changes.csv')
 events=[]
 for row in incoming:
  code=row['ISU_CD']; prior=old_by.get(code)
  valid=row.get('fetch_status')=='OK' and all(row.get(f+'_status')=='OK' and row.get(f+'_krw','')!='' for f in FIELDS)
  if not valid:
   events.append({'ISU_CD':code,'ISU_NM':row.get('ISU_NM',''),'event':'PRESERVED_OLD' if prior else 'NO_VERIFIED_SNAPSHOT','detail':row.get('fetch_status','') or 'INCOMPLETE','timestamp_utc':now})
   continue
  candidate={'ISU_CD':code,'ISU_NM':row.get('ISU_NM',''),'fiscal_year':row.get('fiscal_year',''),'report_code':row.get('report_code',''),'statement_type':row.get('statement_type',''),'verified_at_utc':now}
  candidate.update({f+'_krw':row[f+'_krw'] for f in FIELDS})
  if prior:
   for f in FIELDS:
    k=f+'_krw'
    if prior.get(k)!=candidate[k] and prior.get('fiscal_year')==candidate['fiscal_year'] and prior.get('report_code')==candidate['report_code']:
     changes.append({'ISU_CD':code,'field':f,'old_value':prior.get(k,''),'new_value':candidate[k],'fiscal_year':candidate['fiscal_year'],'report_code':candidate['report_code'],'detected_at_utc':now,'reason':'VALUE_CHANGED_UNVERIFIED_CAUSE'})
  merged[code]=candidate
  events.append({'ISU_CD':code,'ISU_NM':candidate['ISU_NM'],'event':'VERIFIED_UPDATED','detail':candidate['fiscal_year']+' '+candidate['statement_type'],'timestamp_utc':now})
 latest_cols=['ISU_CD','ISU_NM','fiscal_year','report_code','statement_type','verified_at_utc']+[f+'_krw' for f in FIELDS]
 change_cols=['ISU_CD','field','old_value','new_value','fiscal_year','report_code','detected_at_utc','reason']
 write(ROOT/'financial_latest.csv',[merged[k] for k in sorted(merged)],latest_cols)
 write(ROOT/'financial_changes.csv',changes,change_cols)
 write(ROOT/'financial_events.csv',events,['ISU_CD','ISU_NM','event','detail','timestamp_utc'])
 summary={'incoming_count':len(incoming),'prior_verified_count':len(old),'verified_current':sum(e['event']=='VERIFIED_UPDATED' for e in events),'preserved_old':sum(e['event']=='PRESERVED_OLD' for e in events),'verified_snapshot_count':len(merged),'change_events_total':len(changes),'limitations':['2025 annual-only source: not a latest-filing validator','Change detection does not establish a formal correction filing','GitHub artifact retention is limited; archive is not permanent','No investment ratings; v4 and GC untouched']}
 (ROOT/'history_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
