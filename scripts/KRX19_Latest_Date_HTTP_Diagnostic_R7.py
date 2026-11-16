#!/usr/bin/env python3
"""Stage19 R7: latest verified local market session + non-destructive KRX HTTP diagnostic."""
import argparse,csv,datetime as dt,hashlib,json,pathlib,re,urllib.request,urllib.parse,urllib.error
URL='https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd'
BLD='dbms/MDC/STAT/standard/MDCSTAT03501'
def read_json(p):return json.loads(pathlib.Path(p).read_text(encoding='utf-8-sig'))
def latest_csv(p):
 with open(p,encoding='utf-8-sig',newline='') as f:
  r=csv.DictReader(f);dates=set();rows=0
  for row in r:
   rows+=1; d=(row.get('BAS_DD') or '').strip()
   if re.fullmatch(r'20\d{6}',d):dates.add(d)
 return {'rows':rows,'dates':sorted(dates)}
def probe(method,payload,timeout):
 data=urllib.parse.urlencode(payload).encode() if method=='POST' else None
 url=URL if method=='POST' else URL+'?'+urllib.parse.urlencode(payload)
 req=urllib.request.Request(url,data=data,headers={'User-Agent':'Mozilla/5.0','Referer':'https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd','Origin':'https://data.krx.co.kr','Accept':'application/json, text/plain, */*','Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'},method=method)
 try:
  with urllib.request.urlopen(req,timeout=timeout) as resp:
   body=resp.read(8192);status=resp.status;headers=resp.headers
 except urllib.error.HTTPError as e:
  body=e.read(8192);status=e.code;headers=e.headers
 except Exception as e:return {'transport_error':type(e).__name__+': '+str(e)[:200]}
 s=body.decode('utf-8','replace')
 result={'http_status':status,'content_type':headers.get('Content-Type',''),'body_bytes_sampled':len(body),'sample_sha256':hashlib.sha256(body).hexdigest(),'body_excerpt':s[:500]}
 try:
  obj=json.loads(s);result['json_keys']=list(obj)[:15] if isinstance(obj,dict) else [];result['array_sizes']={k:len(v) for k,v in obj.items() if isinstance(v,list)} if isinstance(obj,dict) else {}
 except Exception:pass
 return result
def main():
 a=argparse.ArgumentParser();a.add_argument('--summary',default='data/summary.json');a.add_argument('--latest',default='data/latest.csv');a.add_argument('--universe',default='data/v5_full_market_universe.json');a.add_argument('--output-dir',default='stage19_r7_output');a.add_argument('--timeout',type=int,default=12);args=a.parse_args()
 out=pathlib.Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
 summary=read_json(args.summary);universe=read_json(args.universe);csvinfo=latest_csv(args.latest)
 date=str(summary.get('latest_trading_date','')); universe_date=str(universe.get('trading_date',''))
 report={'stage':'19_R7','source_of_selected_date':'data/summary.json.latest_trading_date','summary_latest_trading_date':date,'latest_csv':csvinfo,'universe_trading_date':universe_date,'attempts':[],'official_per_pbr_verified_count':0,'classification':'DIAGNOSTIC_ONLY_NOT_INVESTMENT_VERIFIED'}
 today=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime('%Y%m%d')
 if not re.fullmatch(r'20\d{6}',date) or date>today or csvinfo['dates']!=[date] or csvinfo['rows']<100:
  report['status']='BLOCKED_MARKET_DATE_INTEGRITY'
 else:
  report['selected_date']=date;report['status']='HTTP_DIAGNOSTIC_COMPLETED_NO_OFFICIAL_VERIFICATION'
  # Limited diagnostic variants; no scraping bypass, no unverified data promotion.
  for market in ('STK','KSQ'):
   for variant,method,extra in [('r6_baseline','POST',{'share':'1','money':'1','csvxls_isNo':'false'}),('minimal_post','POST',{}),('minimal_get','GET',{})]:
    payload={'bld':BLD,'locale':'ko_KR','mktId':market,'trdDd':date,**extra}
    report['attempts'].append({'market':market,'variant':variant,'method':method,'date':date,'response':probe(method,payload,args.timeout)})
 (out/'v5_stage19_r7_date_http_diagnostic.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'status':report['status'],'selected_date':report.get('selected_date'),'attempts':len(report['attempts'])},ensure_ascii=False))
if __name__=='__main__':main()
