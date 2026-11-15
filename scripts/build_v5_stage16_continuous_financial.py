#!/usr/bin/env python3
"""Stage16 bounded, resumable full-market financial collector.
Preserves Stage13/14/15 caches, invokes prior engines, tracks collection and
annual comparable valuation coverage. All grades remain provisional.
"""
import argparse, csv, datetime as dt, json, os, pathlib, subprocess, sys, time
from decimal import Decimal
ROOT=pathlib.Path(__file__).resolve().parents[1]
DATA=ROOT/'data'; SCRIPTS=ROOT/'scripts'
sys.path.insert(0,str(SCRIPTS))
import build_v5_stage14_full_market_integration as s14
import build_v5_stage15_full_market_engine as s15

def read(name, default):
    try: return json.loads((DATA/name).read_text(encoding='utf-8'))
    except FileNotFoundError: return default

def save(name, value):
    target=DATA/name
    tmp=target.with_suffix(target.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(target)

def call(script,*args,timeout=1500):
    proc=subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],cwd=ROOT,
                        capture_output=True,text=True,timeout=timeout,check=False)
    if proc.returncode: raise RuntimeError(f'{script}: {proc.stderr[-700:] or proc.stdout[-700:]}')
    return proc.stdout[-1000:]

def report(phase,events,started,limits):
    uni=read('v5_full_market_universe.json',{})
    stocks=uni.get('stocks',[])
    eligible=[s for s in stocks if not s14.preferred(s.get('name',''))]
    codes={str(s['code']).zfill(6) for s in eligible}
    base=read('v5_stage13_financial_cache.json',{}).get('entries',{})
    annual=read('v5_stage15_annual_cache.json',{}).get('entries',{})
    mapping=read('dart_corp_map.json',{}).get('mapping',{})
    years=s15.read(DATA/'v5_stage15_annual_cache.json',{}).get('target_years',[2025,2024])
    if len(years)!=2:years=[2025,2024]
    basic=sum(bool(base.get(c,{}).get('filing')) for c in codes)
    year_counts={str(y):sum(bool(annual.get(f'{c}:{y}',{}).get('filing')) for c in codes) for y in years}
    pairs=0; comparable=0; per=0;pbr=0;roe=0;grades={'A':0,'B+':0,'B':0,'WITHHELD':0}
    rows=[]
    for s in eligible:
        code=str(s['code']).zfill(6)
        f1=(annual.get(f'{code}:{years[0]}',{}).get('filing') or {})
        f0=(annual.get(f'{code}:{years[1]}',{}).get('filing') or {})
        same=bool(f1 and f0 and f1.get('fs_div')==f0.get('fs_div'))
        if f1 and f0:pairs+=1
        if same and not f1.get('issues') and not f0.get('issues'):comparable+=1
        m1=f1.get('metrics') or {};m0=f0.get('metrics') or {}
        cap=s14.dec(s.get('market_cap_krw'));net=s14.dec(m1.get('net_income'));equity=s14.dec(m1.get('equity'))
        metrics={}; grade='WITHHELD';flags=[]
        if not f1 or not f0:flags.append('ANNUAL_PAIR_MISSING')
        if f1 and f0 and not same:flags.append('FS_BASIS_MISMATCH')
        if f1.get('issues') or f0.get('issues'):flags.append('ACCOUNT_EXTRACTION_ISSUES')
        if equity is not None and equity>0 and cap is not None:
            metrics['pbr_proxy']=str((cap/equity).quantize(Decimal('.0001')));pbr+=1
        if same and not flags and net is not None and equity is not None and equity>0:
            metrics['roe_proxy_pct']=str((net/equity*100).quantize(Decimal('.0001')));roe+=1
            if cap is not None and net>0:
                metrics['per_proxy']=str((cap/net).quantize(Decimal('.0001')));per+=1
        if same and not flags and s15.code_type(code,s.get('name',''))=='NUMERIC_6_DART_ELIGIBLE':
            rev=s14.dec(m1.get('revenue'));old=s14.dec(m0.get('revenue'))
            op=s14.dec(m1.get('operating_profit'));debt=s14.dec(m1.get('liabilities'))
            cash=s14.dec(m1.get('operating_cashflow'))
            if all(v is not None for v in (rev,old,op,net,debt,equity,cash)) and old>0 and equity>0:
                growth=(rev/old-1)*100;leverage=debt/equity*100
                score=sum((growth>0,growth>10,op>0,net>0,cash>0,leverage<150,leverage<80))
                grade='A' if score==7 else 'B+' if score==6 else 'B' if score==5 else 'WITHHELD'
                metrics['revenue_growth_yoy_pct']=str(growth.quantize(Decimal('.01')))
                metrics['debt_to_equity_pct']=str(leverage.quantize(Decimal('.01')))
            else:flags.append('INCOMPLETE_ANNUAL_METRICS')
        grades[grade]+=1
        rows.append({'code':code,'name':s.get('name'),'security_type':s15.code_type(code,s.get('name','')),
                     'dart_mapped':bool(mapping.get(code)),'basic_fetched':bool(base.get(code,{}).get('filing')),
                     'annual_current':bool(f1),'annual_prior':bool(f0),'comparable':same and not flags,
                     **metrics,'provisional_grade':grade,'verified_grade':'','fair_price':'','buy_signal':'',
                     'issues':';'.join(flags)})
    progress={'trading_date':uni.get('trading_date'),'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
              'phase':phase,'eligible_count':len(codes),'basic_cached':basic,'basic_missing':len(codes)-basic,
              'basic_coverage_pct':round(basic/len(codes)*100,2) if codes else 0,
              'dart_mapped':sum(bool(mapping.get(c)) for c in codes),'annual_years':years,
              'annual_filing_counts':year_counts,'annual_pair_count':pairs,'annual_comparable_count':comparable,
              'valuation_proxy_counts':{'per':per,'pbr':pbr,'roe':roe},'provisional_grade_counts':grades,
              'verified_ab_count':0,'elapsed_seconds':round(time.monotonic()-started,1),
              'limits':limits,'events':events[-30:],'classification':'UNVERIFIED_RESEARCH_ONLY'}
    save('v5_stage16_progress.json',progress)
    save('v5_stage16_full_market.json',{'progress':progress,'results':rows})
    cols=['code','name','security_type','dart_mapped','basic_fetched','annual_current','annual_prior','comparable',
          'per_proxy','pbr_proxy','roe_proxy_pct','revenue_growth_yoy_pct','debt_to_equity_pct',
          'provisional_grade','verified_grade','fair_price','buy_signal','issues']
    with (DATA/'v5_stage16_full_market.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(rows)
    return progress

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--max-seconds',type=int,default=4800)
    ap.add_argument('--basic-batches',type=int,default=3)
    ap.add_argument('--basic-batch-size',type=int,default=70)
    ap.add_argument('--annual-limit',type=int,default=90)
    ap.add_argument('--retry-days',type=int,default=3)
    ap.add_argument('--no-network',action='store_true')
    a=ap.parse_args()
    if not 10<=a.max_seconds<=9000 or not 0<=a.basic_batches<=12 or not 1<=a.basic_batch_size<=150 or not 0<=a.annual_limit<=500 or not 0<=a.retry_days<=60:
        ap.error('Invalid bounded collection settings')
    if not read('v5_full_market_universe.json',{}).get('stocks'):raise SystemExit('Stage12 universe required')
    started=time.monotonic();events=[];key='' if a.no_network else os.getenv('DART_API_KEY','').strip()
    limits={'max_seconds':a.max_seconds,'basic_batches':a.basic_batches,'basic_batch_size':a.basic_batch_size,
            'annual_limit':a.annual_limit,'retry_days':a.retry_days}
    report('START',events,started,limits)
    if not key:events.append('NO_API_KEY_OFFLINE_MODE')
    else:
        for i in range(a.basic_batches):
            if time.monotonic()-started>a.max_seconds-900:events.append('TIME_BUDGET_BASIC_STOP');break
            before=read('v5_stage13_financial_cache.json',{}).get('entries',{})
            old=sum(bool(v.get('filing')) for v in before.values())
            try:
                call('build_v5_stage14_full_market_integration.py','--batch-size',a.basic_batch_size,'--retry-days',a.retry_days,timeout=min(1500,max(60,a.max_seconds-int(time.monotonic()-started))))
                p=read('v5_stage14_progress.json',{})
                new=p.get('new_fetched_this_run',0)
                events.append(f'BASIC_BATCH_{i+1}_NEW_{new}')
                report('BASIC',events,started,limits)
                if p.get('error_counts') and any(k in str(p['error_counts']) for k in ('010','011','012','020','021')):
                    events.append('DART_QUOTA_OR_KEY_STOP');break
                if not new:events.append('BASIC_NO_NEW_STOP');break
            except Exception as e:events.append('BASIC_ERROR_'+str(e)[:150]);break
        # Collect annual years with checkpoint after every attempt and quota stop.
        universe=read('v5_full_market_universe.json',{}).get('stocks',[])
        mapping=read('dart_corp_map.json',{}).get('mapping',{})
        basic=read('v5_stage13_financial_cache.json',{}).get('entries',{})
        annual=read('v5_stage15_annual_cache.json',{'schema':1,'entries':{}})
        if annual.get('schema')!=1 or not isinstance(annual.get('entries'),dict):raise RuntimeError('Invalid Stage15 annual cache')
        entries=annual['entries'];today=dt.date.today();year=today.year-1 if today.month>=4 else today.year-2
        years=[year,year-1];annual['target_years']=years
        todo=[]
        for s in universe:
            code=str(s['code']).zfill(6)
            if s14.preferred(s.get('name','')) or s15.code_type(code,s.get('name',''))!='NUMERIC_6_DART_ELIGIBLE':continue
            if not mapping.get(code) or not basic.get(code,{}).get('filing'):continue
            for y in years:
                old=entries.get(f'{code}:{y}',{})
                if old.get('filing'):continue
                try: recent=bool(old.get('attempted_on')) and (today-dt.date.fromisoformat(old['attempted_on'])).days<a.retry_days
                except ValueError:recent=False
                if not recent:todo.append((code,y,mapping[code]))
        # Prefer completing a second annual year for an existing partial pair.
        todo.sort(key=lambda x:(0 if entries.get(f'{x[0]}:{years[0]}',{}).get('filing') or entries.get(f'{x[0]}:{years[1]}',{}).get('filing') else 1,x[0],-x[1]))
        attempted=0;fetched=0
        for code,y,corp in todo:
            if attempted>=a.annual_limit:break
            if time.monotonic()-started>a.max_seconds-180:events.append('TIME_BUDGET_ANNUAL_STOP');break
            try:filing,errors,halt=s15.annual_fetch(key,corp,y)
            except Exception as e:filing,errors,halt=None,[type(e).__name__],False
            entries[f'{code}:{y}']={'attempted_on':today.isoformat(),'filing':filing,'errors':errors,
                                      'status':'FETCHED' if filing else 'RETRY_REQUIRED'}
            annual['updated_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
            save('v5_stage15_annual_cache.json',annual)
            attempted+=1;fetched+=bool(filing)
            if attempted%10==0:report('ANNUAL',events,started,limits)
            if halt:events.append('DART_QUOTA_OR_KEY_STOP_ANNUAL');break
        events.append(f'ANNUAL_ATTEMPTED_{attempted}_FETCHED_{fetched}')
    # Reuse Stage15 calculation and preserve its original output contract.
    try:
        call('build_v5_stage15_full_market_engine.py','--extra-batches',0,'--annual-limit',0,'--no-network',timeout=180)
        events.append('STAGE15_REPORT_REFRESHED')
    except Exception as e:events.append('STAGE15_REPORT_ERROR_'+str(e)[:180])
    progress=report('COMPLETE',events,started,limits)
    print(json.dumps(progress,ensure_ascii=False))

if __name__=='__main__':main()
