#!/usr/bin/env python3
"""Stage19 R6: KRX Information Data System PER/PBR source acquisition probe.
Read-only; fetched numbers are NOT independently certified official valuations.
"""
import argparse,csv,datetime,hashlib,json,pathlib,re,time,urllib.parse,urllib.request
URL='https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd'
BLD='dbms/MDC/STAT/standard/MDCSTAT03501'
FIELDS=['ISU_SRT_CD','ISU_CD','ISU_ABBRV','PER','PBR','DVD_YLD','EPS','BPS','TDD_CLSPRC']
def fetch(date,market,timeout):
 payload={'bld':BLD,'locale':'ko_KR','mktId':market,'trdDd':date,'share':'1','money':'1','csvxls_isNo':'false'}
 data=urllib.parse.urlencode(payload).encode()
 req=urllib.request.Request(URL,data=data,headers={'User-Agent':'Mozilla/5.0 (compatible; KRX19-R6/1.0)','Referer':'https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd','Origin':'https://data.krx.co.kr','Content-Type':'application/x-www-form-urlencoded','Accept':'application/json, text/plain, */*'},method='POST')
 with urllib.request.urlopen(req,timeout=timeout) as resp:
  body=resp.read(12_000_000);status=resp.status;ctype=resp.headers.get('Content-Type','')
 digest=hashlib.sha256(body).hexdigest()
 obj=json.loads(body.decode('utf-8-sig'))
 return obj,{'http_status':status,'content_type':ctype,'body_sha256':digest,'body_bytes':len(body),'json_keys':list(obj)[:20] if isinstance(obj,dict) else [],'endpoint':URL,'bld':BLD}
def rows_of(obj):
 if not isinstance(obj,dict):return [],'unexpected_json_type'
 for key in ('OutBlock_1','output','result','items','data'):
  value=obj.get(key)
  if isinstance(value,list):return value,key
 return [],'no_known_result_array'
def num(v):
 s=str(v if v is not None else '').strip().replace(',','')
 if s in ('','-','N/A','null'):return None
 try:return float(s)
 except ValueError:return None
def main():
 p=argparse.ArgumentParser();p.add_argument('--date',required=True);p.add_argument('--universe',required=True);p.add_argument('--output-dir',default='stage19_r6_output');p.add_argument('--timeout',type=int,default=18);a=p.parse_args()
 out=pathlib.Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
 universe=json.loads(pathlib.Path(a.universe).read_text(encoding='utf-8'))
 expected={str(x['code']).strip().upper() for x in universe['stocks'] if x.get('code')}
 report={'stage':'19_R6','requested_date':a.date,'universe_date':str(universe.get('trading_date')),'source':'KRX_INFORMATION_DATA_SYSTEM','endpoint':URL,'bld_probe':BLD,'attempts':[],'official_per_pbr_independently_verified_count':0,'status':'SOURCE_PROBE_NOT_VERIFIED','caution':'KRX website JSON responses are preliminary evidence; independent provenance/date validation remains required.'}
 if not re.fullmatch(r'20\d{6}',a.date) or report['universe_date']!=a.date:
  report['status']='BLOCKED_DATE_MISMATCH'
 else:
  found={}
  for market in ('STK','KSQ'):
   item={'market':market,'requested_date':a.date}
   try:
    obj,meta=fetch(a.date,market,a.timeout);item.update(meta)
    rr,key=rows_of(obj);item['result_key']=key;item['raw_rows']=len(rr)
    item['sample_field_names']=list(rr[0])[:30] if rr and isinstance(rr[0],dict) else []
    for row in rr:
     if not isinstance(row,dict):continue
     code=str(row.get('ISU_SRT_CD') or row.get('ISU_CD') or row.get('isuSrtCd') or '').strip().upper()
     if code.startswith('A') and len(code)==7:code=code[1:]
     if code not in expected:continue
     per=num(row.get('PER'));pbr=num(row.get('PBR'))
     if per is None and pbr is None:continue
     found[code]={'code':code,'name':str(row.get('ISU_ABBRV','')),'requested_date':a.date,'market_query':market,'per_raw':row.get('PER',''),'pbr_raw':row.get('PBR',''),'dividend_yield_raw':row.get('DVD_YLD',''),'source':'KRX_INFORMATION_DATA_SYSTEM_UNVERIFIED_RESPONSE','source_bld':BLD,'status':'RAW_SOURCE_REVIEW_REQUIRED'}
    item['matched_numeric_candidates']=sum(x['market_query']==market for x in found.values())
   except Exception as e:item['error']=f'{type(e).__name__}: {str(e)[:250]}'
   report['attempts'].append(item)
   time.sleep(.5)
  report['raw_matched_candidate_count']=len(found)
  if found:report['status']='RAW_SOURCE_CANDIDATES_REQUIRE_REVIEW'
  else:report['status']='NO_VALID_SOURCE_ROWS_DIAGNOSTIC'
  path=out/'v5_stage19_r6_raw_candidates.csv'
  with path.open('w',encoding='utf-8-sig',newline='') as f:
   fields=['code','name','requested_date','market_query','per_raw','pbr_raw','dividend_yield_raw','source','source_bld','status'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(sorted(found.values(),key=lambda x:x['code']))
 (out/'v5_stage19_r6_source_diagnostic.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
