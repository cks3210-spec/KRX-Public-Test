#!/usr/bin/env python3
"""Independent v5: diagnostic only; never overwrites v4 or makes buy ratings."""
import csv, io, json, os, time, urllib.parse, urllib.request, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
BASE='https://opendart.fss.or.kr/api/'
IDS={
 'revenue':{'ifrs-full_Revenue','ifrs_Revenue','ifrs-full_RevenueFromContractsWithCustomers'},
 'operating_profit':{'dart_OperatingIncomeLoss'},
 'net_income':{'ifrs-full_ProfitLoss','ifrs_ProfitLoss'},
 'assets':{'ifrs-full_Assets','ifrs_Assets'},
 'liabilities':{'ifrs-full_Liabilities','ifrs_Liabilities'},
 'equity':{'ifrs-full_Equity','ifrs_Equity'},
}
LABELS={
 'revenue':{'매출액','수익(매출액)','영업수익','매출','수익'},
 'operating_profit':{'영업이익','영업이익(손실)'},
 'net_income':{'당기순이익','당기순이익(손실)','연결당기순이익'},
 'assets':{'자산총계'},'liabilities':{'부채총계'},'equity':{'자본총계'},
}
FIELDS=list(IDS)
def get(endpoint,params):
 url=BASE+endpoint+'?'+urllib.parse.urlencode(params)
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'KRX-v5-diagnostic/2.0'}),timeout=40) as r:return r.read()
def money(v):
 try:return int(str(v).replace(',','').strip())
 except (TypeError,ValueError):return None
def extract(rows):
 out={}
 for field in FIELDS:
  divisions={'BS'} if field in ('assets','liabilities','equity') else {'IS','CIS'}
  valid=[r for r in rows if r.get('sj_div') in divisions and r.get('account_detail','-') in ('','-') and money(r.get('thstrm_amount')) is not None]
  idmatches=[r for r in valid if r.get('account_id') in IDS[field]]
  matches=idmatches or [r for r in valid if r.get('account_nm','').strip() in LABELS[field]]
  values={money(r['thstrm_amount']) for r in matches}
  out[field+'_krw']=next(iter(values)) if len(values)==1 else ''
  out[field+'_status']='OK' if len(values)==1 else ('CONFLICT' if values else 'MISSING')
  out[field+'_source']='ID' if idmatches else ('LABEL' if matches else '')
 return out
def main():
 key=os.getenv('DART_API_KEY','').strip()
 if not key:raise SystemExit('DART_API_KEY is missing')
 with open('data/latest.csv',encoding='utf-8-sig',newline='') as f:stocks=list(csv.DictReader(f))
 sample=sorted((s for s in stocks if s.get('ISU_CD','').isdigit() and len(s['ISU_CD'])==6 and int(s.get('MKTCAP') or 0)>=100_000_000_000),key=lambda s:s['ISU_CD'])[:10]
 blob=get('corpCode.xml',{'crtfc_key':key})
 if not zipfile.is_zipfile(io.BytesIO(blob)):raise SystemExit('OpenDART corpCode failed; check secret and API status')
 with zipfile.ZipFile(io.BytesIO(blob)) as z:
  xml=next(n for n in z.namelist() if n.lower().endswith('.xml'))
  root=ET.fromstring(z.read(xml))
 corp={e.findtext('stock_code','').strip():e.findtext('corp_code','').strip() for e in root.findall('list') if e.findtext('stock_code')}
 output=[]; diagnostics=[]
 for s in sample:
  code=s['ISU_CD']; cc=corp.get(code)
  result={'ISU_CD':code,'ISU_NM':s['ISU_NM'],'fiscal_year':'2025','report_code':'11011','fetch_status':'','statement_type':''}
  if not cc:result['fetch_status']='CORP_CODE_MISSING_OR_SHARE_CLASS'
  else:
   for fs in ('CFS','OFS'):
    try:
     j=json.loads(get('fnlttSinglAcntAll.json',{'crtfc_key':key,'corp_code':cc,'bsns_year':'2025','reprt_code':'11011','fs_div':fs}))
     status=str(j.get('status','UNKNOWN'))
     if status=='000' and j.get('list'):
      result['fetch_status']='OK';result['statement_type']=fs;result.update(extract(j['list']))
      for r in j['list']:
       if r.get('sj_div') in ('IS','CIS'):
        diagnostics.append({'ISU_CD':code,'ISU_NM':s['ISU_NM'],'sj_div':r.get('sj_div',''),'account_id':r.get('account_id',''),'account_nm':r.get('account_nm',''),'account_detail':r.get('account_detail',''),'has_amount':money(r.get('thstrm_amount')) is not None})
      break
     result['fetch_status']='DART_'+status
     if status!='013':break
    except Exception as exc:
     result['fetch_status']='REQUEST_ERROR_'+type(exc).__name__;break
    time.sleep(.25)
  output.append(result);time.sleep(.25)
 dest=Path('v5_output');dest.mkdir(exist_ok=True)
 columns=['ISU_CD','ISU_NM','fiscal_year','report_code','fetch_status','statement_type']+[f+s for f in FIELDS for s in ('_krw','_status','_source')]
 with (dest/'dart_validate_v2.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(output)
 with (dest/'dart_income_accounts_v2.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['ISU_CD','ISU_NM','sj_div','account_id','account_nm','account_detail','has_amount']);w.writeheader();w.writerows(diagnostics)
 summary={'sample_size':len(output),'statement_success':sum(r['fetch_status']=='OK' for r in output),'complete_six_fields':sum(all(r.get(k+'_status')=='OK' for k in FIELDS) for r in output),'field_success':{k:sum(r.get(k+'_status')=='OK' for r in output) for k in FIELDS},'status_counts':{s:sum(r['fetch_status']==s for r in output) for s in sorted(set(r['fetch_status'] for r in output))},'limitations':['2025 annual only; not a filing freshness verdict','No filing date validation yet; never infer late filing from missing API rows','Financial companies need separate account mapping','Preferred shares may share a corporation code with common shares','No A/B ratings or investment recommendations']}
 (dest/'dart_validate_v2_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
