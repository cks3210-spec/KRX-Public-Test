"""Full-scope receipt-bound share evidence collector. Never certifies valuation or emits raw values publicly."""
import argparse, csv, datetime as dt, hashlib, io, json, os, re, sys, time, zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen, HTTPRedirectHandler, build_opener
from defusedxml import ElementTree as ET
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
ROOT=Path.cwd().resolve()
BASE='https://opendart.fss.or.kr/api/'
REPORTS={'annual':'11011','q1':'11013','half':'11012','q3':'11014'}
MAX_CALLS=1000
LIMIT=40*1024*1024
AAD=b'KRX-V5-DART-SHARE-EVIDENCE-FULL-V1'

def require(ok,reason):
    if not ok: raise ValueError(reason)
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def checked(path,digest):
    p=(ROOT/path).resolve(); require(p.is_relative_to(ROOT) and p.is_file() and sha(p)==digest,'SOURCE_HASH_MISMATCH');return p
def receipt(s,day): return isinstance(s,str) and re.fullmatch(r'\d{14}',s) and s[:8]<=day

def number(v):
    s=str(v).strip().replace(',','')
    return int(s) if re.fullmatch(r'[0-9]{1,18}',s) else None

def ending(data,corp,rc,year,period):
    if data.get('status')!='000': return {'state':'API_'+str(data.get('status','UNKNOWN')) if re.fullmatch(r'\d{3}',str(data.get('status',''))) else 'API_UNEXPECTED'}
    rows=data.get('list',[])
    candidates=[r for r in rows if str(r.get('se','')).strip() in ('보통주','보통주식') and r.get('corp_code')==corp and r.get('rcept_no')==rc]
    if len(candidates)!=1:return {'state':'HOLD_RECEIPT_OR_COMMON_CLASS_AMBIGUOUS'}
    r=candidates[0]; issued,treasury,dist=[number(r.get(k)) for k in ('istc_totqy','tesstk_co','distb_stock_co')]
    if None in (issued,treasury,dist) or not (issued>=dist>0 and issued-treasury==dist):return {'state':'HOLD_SHARE_ARITHMETIC'}
    try:d=dt.date.fromisoformat(r['stlm_dt'])
    except (KeyError,TypeError,ValueError):return {'state':'HOLD_PERIOD_DATE'}
    expected={'annual':'12-31','q1':'03-31','half':'06-30','q3':'09-30'}[period]
    if d.isoformat()!=year+'-'+expected:return {'state':'HOLD_PERIOD_DATE'}
    return {'state':'ENDING_COMMON_SHARE_CANDIDATE','issued':issued,'treasury':treasury,'ending_common_shares':dist,'equity_date':d.isoformat(),'receipt':rc,'source':'stockTotqySttus'}

def tag(x):return x.tag.split('}')[-1].upper() if isinstance(x.tag,str) else ''
def norm(s):return re.sub(r'\s+','',s).lower()
def weighted_candidates(blob,rc):
    if not zipfile.is_zipfile(io.BytesIO(blob)):
        try:
            status=ET.fromstring(blob).findtext('status')
            return {'state':'API_'+status if status and re.fullmatch(r'\d{3}',status) else 'DOCUMENT_NOT_ZIP'}
        except Exception:return {'state':'DOCUMENT_NOT_ZIP'}
    candidates=[]; parse_errors=0
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        files=[i for i in z.infolist() if i.filename.lower().endswith('.xml')]
        if not files or len(files)>40 or sum(i.file_size for i in files)>LIMIT:return {'state':'HOLD_DOCUMENT_SIZE'}
        for f in files:
            try:
                raw=z.read(f)
                try:root=ET.fromstring(raw)
                except (LookupError,ET.ParseError):
                    txt=raw.decode('cp949');root=ET.fromstring(re.sub(r'^\s*<\?xml[^?]*\?>','',txt,count=1))
            except Exception:parse_errors+=1;continue
            for idx,row in enumerate(e for e in root.iter() if tag(e)=='TR'):
                cells=[' '.join(''.join(c.itertext()).split()) for c in row if tag(c) in ('TD','TH','TE','TU')]
                for col,label in enumerate(cells):
                    n=norm(label)
                    if ('가중평균' in n and ('보통주' in n or '유통주식' in n) and '주식수' in n and '희석' not in n and '증가' not in n and '감소' not in n) or n in ('weightedaveragenumberofordinarysharesoutstanding','weightedaveragenumberofcommonsharesoutstanding'):
                        vals=[{'column':i,'value':number(v)} for i,v in enumerate(cells) if i!=col and number(v) is not None]
                        if vals:candidates.append({'file':Path(f.filename).name,'row_index':idx,'label':label[:180],'numeric_cells':vals,'receipt':rc})
                        if len(candidates)>=100:return {'state':'HOLD_TOO_MANY_WEIGHTED_ROWS'}
    return {'state':'WEIGHTED_ROWS_UNREVIEWED' if candidates else 'HOLD_NO_WEIGHTED_ROWS','rows':candidates,'xml_parse_errors':parse_errors,'receipt':rc}

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
class Client:
    def __init__(self,key,limit=200):self.key=key;self.calls=0;self.stop=False;self.limit=limit;self.deadline=time.monotonic()+1200
    def get(self,endpoint,params):
        require(endpoint in ('stockTotqySttus.json','document.xml'),'INVALID_ENDPOINT')
        if self.stop or self.calls>=self.limit or time.monotonic()>=self.deadline:return None
        self.calls+=1
        try:
            with build_opener(NoRedirect()).open(Request(BASE+endpoint+'?'+urlencode({'crtfc_key':self.key,**params}),headers={'User-Agent':'KRX-v5-share-evidence-full/1'}),timeout=40) as r:
                blob=r.read(LIMIT+1)
            if len(blob)>LIMIT:return None
            return blob
        except Exception:return None # Never print exception or URL (contains API key).
        finally:time.sleep(.25)
    def observe(self,state):
        if state in {'API_010','API_011','API_012','API_020','API_021','API_101','API_800','API_901'}:self.stop=True

def cipher(key):
    require(re.fullmatch(r'[0-9a-fA-F]{64}',key or '') is not None,'MISSING_ARCHIVE_KEY')
    return AESGCM(HKDF(algorithm=hashes.SHA256(),length=32,salt=None,info=AAD).derive(bytes.fromhex(key)))
def seal(payload,key):
    nonce=os.urandom(12);return b'DARTSH2\x00'+nonce+cipher(key).encrypt(nonce,json.dumps(payload,ensure_ascii=False).encode(),AAD)

from v5_evaluation_scope import validate_scope, validate_stage, index
from v5_full_financial_evaluation import load_sources
ELIGIBLE='EVALUATE_COMMON_STOCK_RESEARCH_ONLY'
CACHE_REL='data/v5_share_evidence/cache.aes'


def plan_scope(scope,metrics,link,holds):
    universe=validate_scope(scope);day=scope['market_date'];met=index(metrics,'code');held=index(holds,'code')
    require(set(met)==set(universe) and all(m['market_date']==day for m in met.values()),'METRICS_SCOPE_MISMATCH')
    by_code={}
    for k,d in link['decisions'].items():
        code=k.split(':')[0]; by_code.setdefault(code,[]).append(d)
    tasks={};rows=[]
    for code,s in sorted(universe.items()):
        state=s['scope_state']; row={'code':code,'market_date':day,'state':state,'task_ids':[]};rows.append(row)
        if state!=ELIGIBLE:continue
        m=met[code];corp=m.get('corp_code');basis=m.get('fs_div')
        if held.get(code,{}).get('reason') in ('EXISTING_CORRECTION_EXCLUSION','IDENTITY_REVIEW') or m.get('annual_state')=='IDENTITY_REVIEW':row['state']='HOLD_DISCLOSURE_OR_IDENTITY';continue
        if not re.fullmatch(r'\d{8}',corp or '') or basis not in ('CFS','OFS'):row['state']='HOLD_CORP_OR_BASIS_MISSING';continue
        # Select the latest recorded receipt per period, including receipts whose financial payload is missing.
        candidates={}
        for d in by_code.get(code,[]):
            y=d.get('year');p=d.get('period');rc=d.get('receipt')
            if d.get('corp_code')!=corp or not isinstance(y,int) or p not in REPORTS or not receipt(rc,day):continue
            if y not in (int(day[:4]),int(day[:4])-1,int(day[:4])-2):continue
            candidates.setdefault((y,p),set()).add(rc)
        if any(len(v)!=1 for v in candidates.values()):row['state']='HOLD_AMBIGUOUS_RECEIPT';continue
        order={'annual':4,'q3':3,'half':2,'q1':1}
        annuals=[k for k in candidates if k[1]=='annual']; annual=max(annuals,default=None)
        interim=[k for k in candidates if k[1]!='annual' and (annual is None or k[0]>annual[0])];current=max(interim,key=lambda k:(k[0],order[k[1]]),default=None)
        prior=(current[0]-1,current[1]) if current else None
        selected=[k for k in (annual,current,prior) if k in candidates]
        if not selected:row['state']='HOLD_FILING_RECEIPT_MISSING';continue
        latest=current or annual
        for k in selected:
            rc=next(iter(candidates[k])); y,p=k
            for kind in (['weighted','ending'] if k==latest else ['weighted']):
                task={'code':code,'corp_code':corp,'fs_div':basis,'receipt':rc,'year':str(y),'period':p,'kind':kind}
                tid=':'.join(task[x] for x in ('code','corp_code','fs_div','receipt','kind'))
                tasks[tid]=task;row['task_ids'].append(tid)
        row['state']='SHARE_EVIDENCE_PLANNED' if annual and current and prior in candidates else 'SHARE_EVIDENCE_PARTIAL_PERIOD_PLAN'
    report={'market_date':day,'scope_sha256':scope['scope_sha256'],'rows':rows}
    report['counts']=validate_stage(scope,report)
    return report,tasks


def load_cache(path,key):
    if not path.exists():return {}
    raw=path.read_bytes();require(raw.startswith(b'DARTSH2\x00') and len(raw)>36,'INVALID_SHARE_CACHE')
    try: payload=json.loads(cipher(key).decrypt(raw[8:20],raw[20:],AAD))
    except Exception:raise ValueError('SHARE_CACHE_AUTHENTICATION_FAILED') from None
    require(payload.get('schema')==1 and isinstance(payload.get('entries'),dict),'SHARE_CACHE_SCHEMA')
    return payload['entries']


def save_cache(path,entries,key):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp')
    tmp.write_bytes(seal({'schema':1,'entries':entries},key));os.replace(tmp,path)


def reusable(entry,task):
    if not isinstance(entry,dict) or entry.get('task')!=task:return False
    result=entry.get('result',{});state=result.get('state')
    # Only successful evidence or completely parsed immutable document without matches is retained.
    return state=='ENDING_COMMON_SHARE_CANDIDATE' if task['kind']=='ending' else (state in ('WEIGHTED_ROWS_UNREVIEWED','HOLD_NO_WEIGHTED_ROWS') and result.get('xml_parse_errors')==0)


def collect_task(client,task):
    if task['kind']=='ending':
        raw=client.get('stockTotqySttus.json',{'corp_code':task['corp_code'],'bsns_year':task['year'],'reprt_code':REPORTS[task['period']]})
        try:return ending(json.loads(raw),task['corp_code'],task['receipt'],task['year'],task['period']) if raw else {'state':'HOLD_REQUEST_FAILED'}
        except (TypeError,ValueError,AttributeError):return {'state':'HOLD_INVALID_RESPONSE'}
    raw=client.get('document.xml',{'rcept_no':task['receipt']})
    if not raw:return {'state':'HOLD_REQUEST_FAILED'}
    try:r=weighted_candidates(raw,task['receipt'])
    except Exception:return {'state':'HOLD_DOCUMENT_PARSE_ERROR'}
    r['document_sha256']=hashlib.sha256(raw).hexdigest();return r


def run_collection(tasks,entries,client,path,key):
    counts=Counter();changed=0
    for tid,task in sorted(tasks.items()):
        if reusable(entries.get(tid),task):counts['CACHE_REUSED']+=1;continue
        if client.stop or client.calls>=client.limit or time.monotonic()>=client.deadline:counts['PENDING_BUDGET_OR_STOP']+=1;continue
        result=collect_task(client,task);client.observe(result['state']);counts[result['state']]+=1
        # Save valid immutable evidence immediately. Failed requests never replace a valid entry.
        entry={'task':task,'result':result}
        if reusable(entry,task):
            entries[tid]=entry;changed+=1;save_cache(path,entries,key)
    return counts,changed


def self_test():
    from tempfile import TemporaryDirectory
    from v5_evaluation_scope import build_scope
    day='20261126'; codes=['%06d'%i for i in range(1,10)]
    market=[{'ISU_CD':c,'BAS_DD':day,'MKTCAP':'100000000000' if i<8 else '1','MARKET':'KOSPI'} for i,c in enumerate(codes)]
    cl={'market_date':day,'row_count':9,'rows':[{'ISU_SRT_CD':c,'market':'KOSPI','KIND_STKCERT_TP_NM':'보통주','SECUGRP_NM':'주권'} for c in codes]}
    scope=build_scope(day,market,cl);metrics=[{'code':c,'market_date':day,'corp_code':'12345678','fs_div':'CFS'} for c in codes];decisions={}
    for c in codes[:7]:
        for y,p,rc in [(2025,'annual','20260319000001'),(2026,'q3','20261113000001'),(2025,'q3','20251113000001')]:decisions[f'{c}:{y}:{p}']={'year':y,'period':p,'receipt':rc,'corp_code':'12345678'}
    report,tasks=plan_scope(scope,metrics,{'decisions':decisions},[])
    assert len(report['rows'])==9 and len(tasks)==28 # seven companies, not six
    assert report['rows'][7]['state']=='HOLD_FILING_RECEIPT_MISSING'
    assert report['rows'][8]['state']=='EXCLUDED_MARKET_CAP'
    assert len(plan_scope(scope,metrics,{'decisions':decisions},[{'code':codes[0],'reason':'EXISTING_CORRECTION_EXCLUSION'}])[1])==24
    task=next(t for t in tasks.values() if t['kind']=='ending');rc=task['receipt']
    data={'status':'000','list':[{'se':'보통주','corp_code':task['corp_code'],'rcept_no':rc,'istc_totqy':'100','tesstk_co':'5','distb_stock_co':'95','stlm_dt':'2026-09-30'}]}
    result=ending(data,task['corp_code'],rc,task['year'],task['period']);assert result['ending_common_shares']==95
    assert ending(data,task['corp_code'],'20261114000001',task['year'],task['period'])['state'].startswith('HOLD')
    entry={'task':task,'result':result};assert reusable(entry,task) and not reusable(entry,{**task,'receipt':'20261114000001'})
    with TemporaryDirectory() as d:
        p=Path(d)/'cache.aes';key='01'*32;save_cache(p,{'x':entry},key);assert load_cache(p,key)=={'x':entry}
        try:load_cache(p,'02'*32)
        except ValueError:pass
        else:raise AssertionError('WRONG_KEY_ACCEPTED')
        class Fake:
            calls=0;limit=0;stop=False;deadline=time.monotonic()+10
        counts,changed=run_collection({'x':task,'y':{**task,'receipt':'20261114000001'}},{'x':entry},Fake(),p,key)
        assert counts=={'CACHE_REUSED':1,'PENDING_BUDGET_OR_STOP':1} and changed==0
    print('FULL_SHARE_SELF_TEST_PASS 10')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');ap.add_argument('--collect',action='store_true');ap.add_argument('--max-calls',type=int,default=200);ap.add_argument('--root',type=Path,default=Path.cwd());ap.add_argument('--out',type=Path,default=Path('/tmp/v5-full-shares'));a=ap.parse_args()
    if a.self_test:self_test();return
    require(1<=a.max_calls<=MAX_CALLS,'INVALID_API_BUDGET')
    scope,metrics,link,holds,hashes=load_sources(a.root);report,tasks=plan_scope(scope,metrics,link,holds)
    path=a.root.resolve()/CACHE_REL;calls=changed=0;counts={};entries={}
    if a.collect:
        key=os.environ.get('KIS_DATA_ARCHIVE_KEY','');dart=os.environ.get('DART_API_KEY','');require(bool(dart),'MISSING_DART_KEY');cipher(key)
        entries=load_cache(path,key);client=Client(dart,a.max_calls);counts,changed=run_collection(tasks,entries,client,path,key);calls=client.calls
    report['planned_tasks']=len(tasks);report['api_calls']=calls;report['cache_updates']=changed;report['collection_counts']=dict(counts);report['collection_requested']=a.collect
    report['share_counts_independently_verified']=False;report['investment_decisions_authorized']=False;report['final_buy_signals']=0
    # Publish aggregate counts only; detailed receipt task IDs and evidence are not emitted.
    summary={k:v for k,v in report.items() if k!='rows'};a.out.mkdir(parents=True,exist_ok=True);(a.out/'share_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':main()
