#!/usr/bin/env python3
"""Standalone v5 full-universe OpenDART collector. Writes only to v5_state/.

Designed for a dedicated GitHub Actions state branch; no v4/GC modification.
"""
import csv, io, json, os, random, subprocess, time, urllib.parse, urllib.request, zipfile
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

API='https://opendart.fss.or.kr/api/'
CAP=100_000_000_000
FIELDS=('revenue','operating_profit','net_income','assets','liabilities','equity')
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
def report_candidates(now):
    """Newest first; use calendar only to bound queries, not to claim a filing exists."""
    today=now.date()
    out=[]
    # Business report is generally filed in the following year; query prior FY too.
    for year in range(today.year, max(2015,today.year-4), -1):
        for code,label,earliest in (
            ('11014','Q3',(year,11,1)),
            ('11012','H1',(year,8,1)),
            ('11013','Q1',(year,5,1)),
            ('11011','FY',(year+1,3,1)),
        ):
            if today >= datetime(*earliest).date():
                out.append((str(year),code,f'{year}_{label}'))
    return sorted(out,key=lambda r:int(r[0])*10+{'11011':4,'11014':3,'11012':2,'11013':1}[r[1]],reverse=True)

REPORTS=report_candidates(datetime.now(timezone(timedelta(hours=9))))
PERIOD_RANK={label: int(year)*10+{'11011':4,'11014':3,'11012':2,'11013':1}[code] for year,code,label in REPORTS}

STATE=Path(os.getenv('V5_STATE_DIR','v5_state'))
KEY=os.getenv('DART_API_KEY','').strip()
MAX_STOCKS=int(os.getenv('V5_MAX_STOCKS','0')) # 0 means all
FLUSH_EVERY=int(os.getenv('V5_FLUSH_EVERY','20'))
MIN_INTERVAL=float(os.getenv('V5_API_INTERVAL','0.45'))
FULL_REFRESH_DAYS=int(os.getenv('V5_FULL_REFRESH_DAYS','90'))

class ApiFailure(Exception): pass

def api(endpoint,params,binary=False):
    params={'crtfc_key':KEY,**params}
    url=API+endpoint+'?'+urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'KRX-v5-full-collector/1.0'}),timeout=45) as response:
                payload=response.read()
            if binary: return payload
            result=json.loads(payload)
            status=str(result.get('status','UNKNOWN'))
            if status in ('020','800','900'):
                raise ApiFailure('RETRYABLE_DART_'+status)
            return result
        except (OSError,ValueError,ApiFailure) as exc:
            if attempt==4: raise ApiFailure(type(exc).__name__+':'+str(exc)[:100])
            time.sleep(min(30,2**attempt+random.random()))
    raise ApiFailure('UNKNOWN')

def amount(v):
    try: return int(str(v).strip().replace(',',''))
    except (ValueError,TypeError): return None

def extract(rows):
    out={}
    for field in FIELDS:
        sj={'BS'} if field in ('assets','liabilities','equity') else {'IS','CIS'}
        valid=[r for r in rows if r.get('sj_div') in sj and r.get('account_detail','-') in ('','-') and amount(r.get('thstrm_amount')) is not None]
        by_id=[r for r in valid if r.get('account_id') in IDS[field]]
        matches=by_id or [r for r in valid if r.get('account_nm','').strip() in LABELS[field]]
        values={amount(r.get('thstrm_amount')) for r in matches}
        out[field+'_krw']=next(iter(values)) if len(values)==1 else None
        out[field+'_status']='OK' if len(values)==1 else ('CONFLICT' if values else 'MISSING')
        out[field+'_source']='ID' if by_id else ('LABEL' if matches else '')
    return out

def load(path,default):
    if not path.exists():return default
    return json.loads(path.read_text(encoding='utf-8'))

def save_atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(tmp,path)

def recent_financial_receipt(corp_code, now):
    """Return latest financial filing receipt, or None for no filings.

    Returns (receipt, safe_to_skip). API failure or a truncated page
    MUST force a full refresh, not silently skip the company.
    """
    start=(now-timedelta(days=120)).strftime('%Y%m%d')
    end=now.strftime('%Y%m%d')
    response=api('list.json',{'corp_code':corp_code,'bgn_de':start,'end_de':end,'page_count':'100'})
    status=str(response.get('status','UNKNOWN'))
    if status=='013':return None,True
    if status!='000':return None,False
    rows=response.get('list') or []
    if int(response.get('total_count',len(rows)))>len(rows):return None,False
    reports=[r for r in rows if any(x in str(r.get('report_nm','')) for x in ('사업보고서','분기보고서','반기보고서'))]
    return max((str(r.get('rcept_no','')) for r in reports),default=None),True

def should_skip_unchanged(old, receipt, safe, now):
    if not old or not safe or not old.get('filing_checked_at_utc'):
        return False
    try:
        checked=datetime.fromisoformat(old['filing_checked_at_utc'])
        age=(now-checked).total_seconds()/86400
    except (ValueError,TypeError):return False
    if age<0 or age>=FULL_REFRESH_DAYS:return False
    return old.get('latest_filing_receipt')==receipt

def main():
    if not KEY: raise SystemExit('DART_API_KEY is missing')
    if not REPORTS: raise SystemExit('No eligible fiscal report periods')
    STATE.mkdir(exist_ok=True)
    with open('data/latest.csv',encoding='utf-8-sig',newline='') as f: raw=list(csv.DictReader(f))
    stocks=sorted((r for r in raw if r.get('ISU_CD','').isdigit() and len(r['ISU_CD'])==6 and amount(r.get('MKTCAP')) is not None and amount(r['MKTCAP'])>=CAP),key=lambda r:r['ISU_CD'])
    if MAX_STOCKS>0: stocks=stocks[:MAX_STOCKS]
    if not stocks: raise SystemExit('No eligible KRX stocks; refusing empty checkpoint')
    stamp=datetime.now(timezone.utc).isoformat(timespec='seconds')
    checkpoint=load(STATE/'checkpoint.json',{'completed':{},'last_updated_utc':None})
    completed=checkpoint.get('completed',{})
    snapshots=load(STATE/'financial_latest.json',{})
    changes=load(STATE/'financial_changes.json',[])
    # Fetch mapping once per run. Missing stock code may mean preferred/share class.
    blob=api('corpCode.xml',{},binary=True)
    if not zipfile.is_zipfile(io.BytesIO(blob)):raise SystemExit('OpenDART corpCode response is not ZIP; no state updated')
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        root=ET.fromstring(z.read(next(n for n in z.namelist() if n.lower().endswith('.xml'))))
    corp={e.findtext('stock_code','').strip():e.findtext('corp_code','').strip() for e in root.findall('list') if e.findtext('stock_code')}
    # A weekly refresh cycle rechecks new filings; reruns within a cycle resume.
    # Keep verified snapshots across all cycles, including years and universe changes.
    universe_date=max((r.get('BAS_DD','') for r in stocks),default='')
    cycle=os.getenv('V5_CYCLE','').strip() or datetime.now(timezone(timedelta(hours=9))).strftime('%G-W%V')
    if checkpoint.get('cycle')!=cycle:
        completed={}
    checkpoint['cycle']=cycle
    new_count=0
    def flush():
        checkpoint.update({'completed':completed,'universe_date':universe_date,'cycle':cycle,'last_updated_utc':datetime.now(timezone.utc).isoformat(timespec='seconds')})
        save_atomic(STATE/'checkpoint.json',checkpoint)
        save_atomic(STATE/'financial_latest.json',snapshots)
        save_atomic(STATE/'financial_changes.json',changes)
        status=Counter(str(v.get('status')) for v in completed.values())
        save_atomic(STATE/'summary.json',{'asof_utc':stamp,'universe_date':universe_date,'cycle':cycle,'latest_report_candidates':REPORTS[:4],'universe_count':len(stocks),'processed_this_universe':len(completed),'remaining':sum(s['ISU_CD'] not in completed for s in stocks),'verified_snapshot_count':len(snapshots),'statuses':dict(status),'note':'Dynamic fiscal years; recent financial filing checks reduce redundant full statements; 90-day forced refresh; quarterly amounts may be cumulative; no investment ratings; no filing-date certification'})
        # Durable checkpoint: commit/push only to dedicated v5-state branch.
        subprocess.run(['git','-C',str(STATE),'add','-A'],check=True)
        changed=subprocess.run(['git','-C',str(STATE),'diff','--cached','--quiet']).returncode
        if changed:
            subprocess.run(['git','-C',str(STATE),'commit','-m','v5: save verified collection checkpoint'],check=True,stdout=subprocess.DEVNULL)
            subprocess.run(['git','-C',str(STATE),'push','origin','HEAD:v5-state'],check=True,stdout=subprocess.DEVNULL)

    try:
        for s in stocks:
            code=s['ISU_CD']
            if code in completed: continue
            cc=corp.get(code)
            record={'name':s.get('ISU_NM',''),'status':'','checked_at_utc':datetime.now(timezone.utc).isoformat(timespec='seconds')}
            if not cc:
                record['status']='CORP_CODE_MISSING_OR_SHARE_CLASS'
            else:
                old=snapshots.get(code)
                now=datetime.now(timezone.utc)
                receipt=None
                safe=False
                try:
                    receipt,safe=recent_financial_receipt(cc,now)
                except ApiFailure as exc:
                    print('Filing lookup unavailable; full refresh:',code,str(exc)[:70],flush=True)
                if should_skip_unchanged(old,receipt,safe,now):
                    record['status']='UNCHANGED_FILING'
                    record['period']=old.get('period','')
                    completed[code]=record
                    new_count+=1
                    if new_count%FLUSH_EVERY==0:flush()
                    continue
                selected=None; failure=None
                for year,report,label in REPORTS:
                    for fs in ('CFS','OFS'):
                        try:
                            j=api('fnlttSinglAcntAll.json',{'corp_code':cc,'bsns_year':year,'reprt_code':report,'fs_div':fs})
                            status=str(j.get('status','UNKNOWN'))
                            if status=='013': continue
                            if status!='000':
                                failure='DART_'+status
                                break
                            fields=extract(j.get('list') or [])
                            if all(fields[k+'_status']=='OK' for k in FIELDS):
                                selected={'ISU_CD':code,'ISU_NM':s.get('ISU_NM',''),'fiscal_year':year,'report_code':report,'period':label,'statement_type':fs,'verified_at_utc':record['checked_at_utc'],'latest_filing_receipt':receipt,'filing_checked_at_utc':now.isoformat(timespec='seconds') if safe else None,**fields}
                                break
                            failure='FINANCIAL_INCOMPLETE'
                        except ApiFailure as exc:
                            failure='API_ERROR_'+str(exc)[:70]
                            break
                        time.sleep(MIN_INTERVAL)
                    if selected or (failure and failure.startswith(('DART_','API_ERROR'))):break
                if selected:
                    old=snapshots.get(code)
                    if old and old.get('fiscal_year')==selected['fiscal_year'] and old.get('report_code')==selected['report_code'] and old.get('statement_type')==selected['statement_type']:
                        for f in FIELDS:
                            k=f+'_krw'
                            if old.get(k)!=selected.get(k):
                                changes.append({'ISU_CD':code,'field':f,'old':old.get(k),'new':selected[k],'detected_at_utc':record['checked_at_utc'],'reason':'VALUE_CHANGED_UNVERIFIED_CAUSE'})
                    # Never replace a more recent period with an older period.
                    if not old or PERIOD_RANK.get(selected['period'],0)>=int(str(old.get('fiscal_year','0')) or '0')*10+{'11011':4,'11014':3,'11012':2,'11013':1}.get(old.get('report_code'),0):
                        snapshots[code]=selected
                    record['status']='VERIFIED'
                    record['period']=selected['period']
                else:record['status']=failure or 'NO_AVAILABLE_COMPLETE_STATEMENT'
            # Retry transient failures on the next run, rather than falsely marking complete.
            if record['status'].startswith(('API_ERROR_','DART_020','DART_800','DART_900')):
                print('Retry next run:',code,record['status'],flush=True)
            else:
                completed[code]=record
            new_count+=1
            if new_count%FLUSH_EVERY==0:
                flush()
                print('checkpoint',len(completed),'/',len(stocks),flush=True)
    finally:
        flush()
    print(json.dumps(load(STATE/'summary.json',{}),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
