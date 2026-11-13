#!/usr/bin/env python3
"""Stage56: verify DART owner-attributable fields for the frozen 318 candidates.
Never promotes estimated PER/PBR to official or issues final buy grades.
Environment: DART_API_KEY (or OPENDART_API_KEY).
"""
import csv, json, os, pathlib, time, urllib.parse, urllib.request
from datetime import datetime, timezone
ROOT=pathlib.Path(__file__).resolve().parents[1]
SRC=ROOT/'stage56_input/provisional_ab_318_evidence_audit.csv'
OUT=ROOT/'stage56_official_output'
API='https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json'
# OpenDART standard account IDs (CFS owner-attributable profit/equity)
IDS={'owner_profit':'ifrs-full_ProfitLossAttributableToOwnersOfParent',
     'owner_equity':'ifrs-full_EquityAttributableToOwnersOfParent'}
def fetch(key,corp,year,report):
    query=urllib.parse.urlencode({'crtfc_key':key,'corp_code':corp,'bsns_year':year,'reprt_code':report,'fs_div':'CFS'})
    with urllib.request.urlopen(API+'?'+query,timeout=25) as response:
        return json.load(response)
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    status={'stage':56,'mode':'DART_OWNER_ATTRIBUTABLE_VERIFICATION','generated_utc':datetime.now(timezone.utc).isoformat(),
            'official_per_pbr_verified':0,'final_grades_released':0,'verified_owner_fields':0,'unverified':0}
    try:
        with SRC.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
        if len(rows)!=318: raise ValueError(f'Expected 318 frozen candidates, got {len(rows)}')
        key=os.getenv('DART_API_KEY') or os.getenv('OPENDART_API_KEY')
        if not key: raise ValueError('Missing DART_API_KEY/OPENDART_API_KEY secret; no network queries made')
        results=[]
        for row in rows:
            code=row['ISU_CD']; corp=row.get('dart_corp_code','').strip()
            item={'ISU_CD':code,'ISU_NM':row['ISU_NM'],'dart_corp_code':corp,
                  'source':'OpenDART fnlttSinglAcntAll','fs_div':'CFS','bsns_year':'2026',
                  'reprt_code':'11014','owner_profit':'','owner_equity':'',
                  'status':'UNVERIFIED','detail':''}
            if not (corp.isdigit() and len(corp)==8):
                item['detail']='DART_CORP_CODE_INVALID';results.append(item);continue
            try:
                # 2026 Q3 (11014): owner profit may be cumulative; owner equity period-end.
                data=fetch(key,corp,'2026','11014')
                if data.get('status')!='000':
                    item['detail']='DART_'+str(data.get('status'))+':'+str(data.get('message',''))[:100]
                else:
                    accounts={a.get('account_id'):a for a in data.get('list',[]) if a.get('fs_div')=='CFS' and a.get('sj_div') in ('IS','CIS','BS')}
                    for field,aid in IDS.items():
                        account=accounts.get(aid)
                        if account:
                            item[field]=str(account.get('thstrm_amount','')).replace(',','').strip()
                    if all(item[x] and item[x].lstrip('-').isdigit() for x in IDS):
                        item['status']='OWNER_FIELDS_VERIFIED'
                    else: item['detail']='OWNER_ATTRIBUTABLE_ACCOUNT_IDS_MISSING_OR_NONNUMERIC'
            except Exception as exc: item['detail']=type(exc).__name__+':'+str(exc)[:120]
            results.append(item)
            time.sleep(0.15)
        with (OUT/'owner_fields.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
        status['verified_owner_fields']=sum(r['status']=='OWNER_FIELDS_VERIFIED' for r in results)
        status['unverified']=len(results)-status['verified_owner_fields']
        status['candidate_count']=len(results)
        status['note']='Q3 owner fields only; no official PER/PBR, annualized earnings, or final grades released.'
    except Exception as exc: status['error']=str(exc)
    (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(status,ensure_ascii=False))
    if 'error' in status:raise SystemExit(1)
if __name__=='__main__':main()
