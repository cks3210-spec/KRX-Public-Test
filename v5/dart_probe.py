#!/usr/bin/env python3
"""Isolated OpenDART smoke test: 10 KRX companies, 2025 annual statements."""
import csv, io, json, os, sys, time, urllib.parse, urllib.request, zipfile, xml.etree.ElementTree as ET
from pathlib import Path

BASE='https://opendart.fss.or.kr/api/'
def get(endpoint, params, timeout=35):
    url=BASE+endpoint+'?'+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={'User-Agent':'KRX-v5-research/1.0'})
    with urllib.request.urlopen(req,timeout=timeout) as response:
        return response.read()

def main():
    key=os.getenv('DART_API_KEY','').strip()
    if not key:
        raise SystemExit('ERROR: DART_API_KEY secret missing; no key printed')
    path=Path('data/latest.csv')
    with path.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    eligible=[r for r in rows if int(r.get('MKTCAP') or 0)>=100_000_000_000 and r.get('ISU_CD','').isdigit() and len(r['ISU_CD'])==6]
    # Deterministic broad sample, without modifying existing v4/GC inputs.
    eligible=sorted(eligible,key=lambda r:r['ISU_CD'])
    sample=eligible[:10]
    blob=get('corpCode.xml',{'crtfc_key':key})
    if not zipfile.is_zipfile(io.BytesIO(blob)):
        # OpenDART error XML may contain an API error status; never print key.
        try:
            root=ET.fromstring(blob)
            msg=root.findtext('message') or 'Unknown API error'
            status=root.findtext('status') or 'unknown'
            raise SystemExit(f'OpenDART corpCode error status={status}, message={msg}')
        except ET.ParseError:
            raise SystemExit('OpenDART corpCode response was not a ZIP archive')
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name=next((n for n in z.namelist() if n.lower().endswith('.xml')),None)
        if not name: raise SystemExit('corpCode ZIP contains no XML')
        root=ET.fromstring(z.read(name))
    corp={x.findtext('stock_code','').strip():x.findtext('corp_code','').strip() for x in root.findall('list') if x.findtext('stock_code')}
    results=[]
    for r in sample:
        stock=r['ISU_CD']; corp_code=corp.get(stock,'')
        out={'ISU_CD':stock,'ISU_NM':r['ISU_NM'],'corp_code_found':bool(corp_code),'fiscal_year':'2025','report_code':'11011','status':'','statement_rows':0,'statement_type':''}
        if not corp_code: out['status']='CORP_CODE_MISSING'
        else:
            try:
                raw=get('fnlttSinglAcntAll.json',{'crtfc_key':key,'corp_code':corp_code,'bsns_year':'2025','reprt_code':'11011','fs_div':'CFS'})
                j=json.loads(raw)
                if j.get('status')=='000' and j.get('list'):
                    out['status']='OK_CFS';out['statement_rows']=len(j['list']);out['statement_type']='CFS'
                elif j.get('status')=='013':
                    raw=get('fnlttSinglAcntAll.json',{'crtfc_key':key,'corp_code':corp_code,'bsns_year':'2025','reprt_code':'11011','fs_div':'OFS'})
                    j=json.loads(raw)
                    out['status']='OK_OFS' if j.get('status')=='000' and j.get('list') else 'DART_'+str(j.get('status','UNKNOWN'))
                    out['statement_rows']=len(j.get('list') or []);out['statement_type']='OFS' if out['status']=='OK_OFS' else ''
                else: out['status']='DART_'+str(j.get('status','UNKNOWN'))
            except Exception as e:
                out['status']='REQUEST_ERROR_'+type(e).__name__
        results.append(out)
        time.sleep(.25)
    dest=Path('v5_output');dest.mkdir(exist_ok=True)
    with (dest/'dart_probe_10.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
    summary={'asof':rows[0].get('BAS_DD') if rows else None,'sample_size':len(results),'corp_codes_matched':sum(x['corp_code_found'] for x in results),'financial_success':sum(x['status'].startswith('OK_') for x in results),'statuses':{s:sum(x['status']==s for x in results) for s in sorted(set(x['status'] for x in results))},'note':'Annual 2025 smoke test only; not a complete investment-grade dataset. No secrets logged.'}
    (dest/'dart_probe_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if summary['financial_success']==0: sys.exit('No statements collected; inspect statuses')
if __name__=='__main__':main()
