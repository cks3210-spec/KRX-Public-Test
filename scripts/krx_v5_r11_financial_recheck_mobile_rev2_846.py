#!/usr/bin/env python3
"""R11 DART consolidated equity reconciliation. Read-only R9/R10; research-only output."""
import csv,datetime as dt,json,os,pathlib,re,time,urllib.parse,urllib.request
from collections import Counter
from decimal import Decimal,InvalidOperation
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]
R9=ROOT/'data/v5_financial_r9';R10=ROOT/'data/v5_financial_r10';OUT=ROOT/'data/v5_financial_r11'
NOW=dt.datetime.now(ZoneInfo('Asia/Seoul'))
IDS={'total_equity':('ifrs-full_Equity','ifrs_Equity'), 'owner_equity':('ifrs-full_EquityAttributableToOwnersOfParent','ifrs_EquityAttributableToOwnersOfParent'),'noncontrolling':('ifrs-full_NoncontrollingInterests','ifrs_NoncontrollingInterests'),'assets':('ifrs-full_Assets','ifrs_Assets'),'liabilities':('ifrs-full_Liabilities','ifrs_Liabilities'),'owner_profit':('ifrs-full_ProfitLossAttributableToOwnersOfParent','ifrs_ProfitLossAttributableToOwnersOfParent')}
FIELDS=['stock_code','name','market','year','prior_r10_quality','prior_balance_flag','source','dart_state','balance_state','owner_attribution_state','assets','liabilities','total_equity','owner_equity','noncontrolling','owner_profit','balance_gap','owner_equity_gap','reference_per','reference_pbr','reference_roe_pct','provisional_grade','final_grade','buy_signal','flags']
def load(p):
 if not p.exists():return {}
 v=json.loads(p.read_text(encoding='utf-8'));return v if isinstance(v,dict) else {}
def dec(x):
 try:
  d=Decimal(str(x).replace(',',''));return d if d.is_finite() else None
 except (ValueError,InvalidOperation,TypeError):return None
def fmt(x):return '' if x is None else str(round(x,4))
def csvread(p):
 if not p.exists():return []
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(p,rows):
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction='ignore');w.writeheader();w.writerows(rows)
def fetch(key,corp,year):
 q=urllib.parse.urlencode({'crtfc_key':key,'corp_code':corp,'bsns_year':year,'reprt_code':'11011','fs_div':'CFS'})
 req=urllib.request.Request('https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?'+q,headers={'User-Agent':'KRX-v5-R11-research/1.0'})
 with urllib.request.urlopen(req,timeout=45) as resp:data=json.load(resp)
 if data.get('status')!='000':return {'state':'DART_'+str(data.get('status')),'checked_at':NOW.isoformat()}
 records=data.get('list') or [];found={};evidence={}
 for k,aliases in IDS.items():
  candidates=[r for r in records if r.get('account_id') in aliases and r.get('sj_div') in ('BS','IS','CIS') and r.get('account_detail','-') in ('-','')]
  for r in candidates:
   v=dec(r.get('thstrm_amount'))
   if v is not None:
    found[k]=str(v);evidence[k]={'account_id':r.get('account_id'),'sj_div':r.get('sj_div'),'account_nm':r.get('account_nm')};break
 return {'state':'OK','year':str(year),'report':'11011','fs_div':'CFS','checked_at':NOW.isoformat(),'accounts':found,'evidence':evidence}
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 status={'version':'R11','state':'STARTED','generated_kst':NOW.isoformat(),'r9_cache_modified':False,'r10_cache_modified':False,'official_per_pbr_verified':0,'final_grades':0,'buy_signals':0}
 try:
  annual=load(R9/'annual_financial_cache.json');r9status=load(R9/'status.json')
  quality=csvread(R10/'financial_quality_audit.csv');market=csvread(ROOT/'data/latest.csv')
  if not annual or not quality or not market:raise RuntimeError('Required R9/R10/market inputs missing')
  qmap={r['stock_code']:r for r in quality};mmap={r['ISU_CD']:r for r in market}
  year=str(r9status.get('expected_market_date','')[:4] or market[0]['BAS_DD'][:4]);year=str(int(year)-1)
  target=[c for c in qmap if c in annual and str(annual[c].get('year'))==year]
  target.sort(key=lambda c:(0 if 'BALANCE_SHEET_INCONSISTENT' in qmap[c].get('quality_flags','') else 1,c))
  cachepath=OUT/'dart_account_evidence_cache.json';cache=load(cachepath)
  key=os.getenv('DART_API_KEY','').strip();budget=max(0,min(300,int(os.getenv('R11_DART_MAX_REQUESTS','120'))))
  calls=0;new=0;errors=[]
  for code in target:
   rec=annual[code];corp=rec.get('corp_code','');ck=f'{code}|{year}|11011|CFS'
   if ck in cache and cache[ck].get('state')=='OK':continue
   if calls>=budget:break
   if not key or not re.fullmatch(r'\d{8}',str(corp)):continue
   calls+=1
   try:
    item=fetch(key,corp,year)
    if item['state']=='OK':cache[ck]=item;new+=1
    else:errors.append(f'{code}:{item["state"]}')
   except Exception as e:errors.append(f'{code}:{str(e)[:100]}')
   if calls%10==0:cachepath.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding='utf-8')
  cachepath.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding='utf-8')
  rows=[]
  for code in target:
   rec=annual[code];m=mmap.get(code,{});q=qmap[code];ev=cache.get(f'{code}|{year}|11011|CFS',{});a=ev.get('accounts',{})
   flags=[];old=q.get('quality_flags','');prior='BALANCE_SHEET_INCONSISTENT' in old
   if prior:flags.append('R10_BALANCE_FLAG_REQUIRES_TOTAL_EQUITY_RECHECK')
   assets=dec(a.get('assets'));liab=dec(a.get('liabilities'));total=dec(a.get('total_equity'))
   owner=dec(a.get('owner_equity'));noncont=dec(a.get('noncontrolling'));profit=dec(a.get('owner_profit'))
   old_owner=dec(rec.get('equity'));old_profit=dec(rec.get('profit'))
   if owner is None:owner=old_owner;flags.append('OWNER_EQUITY_FROM_R9_UNRECHECKED')
   if profit is None:profit=old_profit;flags.append('OWNER_PROFIT_FROM_R9_UNRECHECKED')
   gap=abs(assets-liab-total) if None not in (assets,liab,total) else None
   owner_gap=abs(total-owner-noncont) if None not in (total,owner,noncont) else None
   tolerance=max(Decimal('1000000'),abs(assets)*Decimal('0.0001')) if assets is not None else None
   if gap is None:balance='UNVERIFIED_TOTAL_EQUITY_MISSING'
   elif gap<=tolerance:balance='BALANCED_WITH_TOTAL_EQUITY'
   else:balance='UNBALANCED_REQUIRES_REVIEW';flags.append('OFFICIAL_ACCOUNT_BALANCE_MISMATCH')
   if owner_gap is not None and owner_gap>max(Decimal('1000000'),abs(total)*Decimal('0.0001')):flags.append('OWNER_PLUS_NONCONTROLLING_MISMATCH')
   attribution='DART_OWNER_ACCOUNT_CONFIRMED' if a.get('owner_equity') is not None and a.get('owner_profit') is not None else 'OWNER_ACCOUNT_PARTIAL_OR_UNVERIFIED'
   cap=dec(m.get('MKTCAP'));pe=cap/profit if cap is not None and profit is not None and profit>0 else None
   pb=cap/owner if cap is not None and owner is not None and owner>0 else None
   roe=profit/owner*100 if profit is not None and owner is not None and owner>0 else None
   grade='';name=m.get('ISU_NM',q.get('name',''))
   finance=bool(re.search(r'금융|은행|증권|보험|캐피탈|저축은행|지주',name))
   if finance:flags.append('FINANCIAL_SECTOR_MODEL_PENDING')
   if re.search(r'(?:우|우B|우C|우선주|[0-9]우)$',name):flags.append('POSSIBLE_PREFERRED_SHARE')
   flags+=['MARKET_CAP_IS_NOT_OWNER_SHARE_CLASS_VERIFIED','OFFICIAL_PER_PBR_NOT_VERIFIED','TTM_NOT_VERIFIED']
   # Only retain R10 grade when verified balance, owner attribution and no sector/share class issue.
   if balance=='BALANCED_WITH_TOTAL_EQUITY' and attribution=='DART_OWNER_ACCOUNT_CONFIRMED' and not finance and 'POSSIBLE_PREFERRED_SHARE' not in flags:
    grade=q.get('provisional_grade','') if q.get('provisional_grade','') in ('A','B+','B') else ''
   rows.append(dict(stock_code=code,name=name,market=m.get('MARKET',q.get('market','')),year=year,prior_r10_quality=q.get('quality_state',''),prior_balance_flag=str(prior),source='DART_FNLTT_SINGLE_ACNT_ALL' if ev.get('state')=='OK' else 'R9_CACHE_ONLY',dart_state=ev.get('state','NOT_QUERIED'),balance_state=balance,owner_attribution_state=attribution,assets=fmt(assets),liabilities=fmt(liab),total_equity=fmt(total),owner_equity=fmt(owner),noncontrolling=fmt(noncont),owner_profit=fmt(profit),balance_gap=fmt(gap),owner_equity_gap=fmt(owner_gap),reference_per=fmt(pe),reference_pbr=fmt(pb),reference_roe_pct=fmt(roe),provisional_grade=grade,final_grade='WITHHELD',buy_signal='NONE',flags=';'.join(flags)))
  write(OUT/'reconciliation_audit.csv',rows);write(OUT/'provisional_ab_research_only.csv',[r for r in rows if r['provisional_grade']])
  count=Counter(r['balance_state'] for r in rows);prior_rows=[r for r in rows if r['prior_balance_flag']=='True']
  status.update(state='RESEARCH_ONLY_NOT_FINAL',year=year,annual_in_scope=len(rows),r10_balance_flags_in_scope=len(prior_rows),r10_flags_reconciled=sum(r['balance_state']=='BALANCED_WITH_TOTAL_EQUITY' for r in prior_rows),balance_breakdown=dict(count),owner_account_confirmed=sum(r['owner_attribution_state']=='DART_OWNER_ACCOUNT_CONFIRMED' for r in rows),provisional_ab_count=sum(bool(r['provisional_grade']) for r in rows),dart_api_calls=calls,new_dart_evidence=new,evidence_cache_entries=len(cache),error_count=len(errors),errors=errors[:30],limitations=['R9/R10 original caches are read-only','R10 asset-liability-owner-equity mismatch does not prove accounting error','Reference multiples are not official PER/PBR','Market cap may include share classes and stale price','No final grades or buy signals'])
  (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps(status,ensure_ascii=False,indent=2))
 except Exception as e:
  status.update(state='FAILED',error=str(e)[:500]);(OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8');raise
if __name__=='__main__':main()
