#!/usr/bin/env python3
"""R14 full-market research pipeline. No edits to upstream caches; no actionable signals."""
import csv, json, math, pathlib, re, datetime as dt, statistics
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'data/v5_investment_r14'; NOW=dt.datetime.now(ZoneInfo('Asia/Seoul'))
CAP=100_000_000_000

def number(v):
    try:
        x=float(str(v).replace(',',''));return x if math.isfinite(x) else None
    except (TypeError,ValueError,OverflowError):return None

def csvread(path):
    if not path.exists():return []
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def jsonread(path):
    if not path.exists():return {}
    x=json.loads(path.read_text(encoding='utf-8'));return x if isinstance(x,dict) else {}

def writecsv(name,rows,fields):
    OUT.mkdir(parents=True,exist_ok=True);p=OUT/name;t=p.with_suffix('.tmp')
    with t.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
    t.replace(p)

def writejson(name,x):
    OUT.mkdir(parents=True,exist_ok=True);p=OUT/name;t=p.with_suffix('.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');t.replace(p)

def div(a,b,scale=1):return a/b*scale if a is not None and b is not None and b>0 else None

def rnd(x):return '' if x is None or not math.isfinite(x) else round(x,3)

def history():
    paths=['data/daily_indicators.csv','data/market_history.csv','data/history.csv','data/latest.csv']
    series={};counts={}
    for name in paths:
        path=ROOT/name;records=csvread(path);counts[name]=len(records)
        for r in records:
            code=str(r.get('ISU_CD') or r.get('stock_code') or r.get('code') or '').strip()
            day=str(r.get('BAS_DD') or r.get('date') or r.get('trade_date') or '').replace('-','')
            price=number(r.get('TDD_CLSPRC') or r.get('close') or r.get('Close'))
            volume=number(r.get('ACC_TRDVOL') or r.get('volume'))
            if re.fullmatch(r'\d{6}',code) and re.fullmatch(r'\d{8}',day) and price and price>0:
                series.setdefault(code,{})[day]=(price,volume)
    return series,counts

def pick_prior(code,year):
    # Only explicitly comparable annual CFS records; never substitute interim YTD for annual.
    for folder in ['v5_financial_r8','v5_financial_r7']:
        rec=jsonread(ROOT/'data'/folder/'annual_financial_cache.json').get(code,{})
        if rec.get('state')=='FINANCIAL_FIELDS_FOUND' and str(rec.get('year'))==str(year) and rec.get('report')=='11011' and rec.get('fs_div')=='CFS':return rec
    return {}

def main():
    market=csvread(ROOT/'data/latest.csv');annual=jsonread(ROOT/'data/v5_financial_r9/annual_financial_cache.json')
    if len(market)<1500:raise RuntimeError('Full market input missing')
    dates={r.get('BAS_DD') for r in market}
    if len(dates)!=1 or not re.fullmatch(r'\d{8}',str(next(iter(dates)))):raise RuntimeError('Market date invalid')
    day=next(iter(dates))
    if len({r.get('ISU_CD') for r in market})!=len(market):raise RuntimeError('Duplicate market codes')
    series,history_sources=history();old_baselines=csvread(OUT/'tracking_history.csv')
    baseline={(r['ISU_CD'],r['signal_date']):r for r in old_baselines if r.get('ISU_CD') and r.get('signal_date')}
    rows=[];issues=[];watch=[];new_baselines=0;verified_growth=0;tech_ready=0
    for m in market:
        code=m.get('ISU_CD','');name=m.get('ISU_NM','');cap=number(m.get('MKTCAP'));close=number(m.get('TDD_CLSPRC'))
        preferred=bool(re.search(r'(?:우$|우B$|우C$|우\d|우\(|우선|전환우)',name))
        eligible=bool(cap is not None and cap>=CAP and re.fullmatch(r'\d{6}',code) and not preferred)
        rec=annual.get(code,{}) if eligible else {}
        valid=rec.get('state')=='FINANCIAL_FIELDS_FOUND' and rec.get('report')=='11011' and rec.get('fs_div')=='CFS'
        profit=number(rec.get('profit')) if valid else None;equity=number(rec.get('equity')) if valid else None
        revenue=number(rec.get('revenue')) if valid else None;liabilities=number(rec.get('liabilities')) if valid else None
        per=div(cap,profit) if eligible else None;pbr=div(cap,equity) if eligible else None;roe=div(profit,equity,100)
        margin=div(profit,revenue,100);owner_debt_proxy=div(liabilities,equity,100)
        # Year-over-year only with a verified previous annual report. No inferred operating profit.
        prior=pick_prior(code,int(rec.get('year'))-1) if valid and str(rec.get('year','')).isdigit() else {}
        prev_rev=number(prior.get('revenue'));prev_profit=number(prior.get('profit'))
        rev_growth=(revenue/prev_rev-1)*100 if revenue is not None and prev_rev is not None and prev_rev>0 else None
        profit_growth=(profit/prev_profit-1)*100 if profit is not None and prev_profit is not None and prev_profit>0 else None
        if rev_growth is not None:verified_growth+=1
        points=sorted(series.get(code,{}).items());past=[(d,p,v) for d,(p,v) in points if d<=day]
        closes=[p for d,p,v in past];vols=[v for d,p,v in past]
        ma5=statistics.mean(closes[-5:]) if len(closes)>=5 else None
        ma10=statistics.mean(closes[-10:]) if len(closes)>=10 else None
        ma20=statistics.mean(closes[-20:]) if len(closes)>=20 else None
        cross=(ma5>ma10 and statistics.mean(closes[-6:-1])<=statistics.mean(closes[-11:-1])) if len(closes)>=11 else None
        volratio=div(vols[-1],statistics.mean(vols[-21:-1])) if len(vols)>=21 and all(v is not None and v>=0 for v in vols[-21:]) and statistics.mean(vols[-21:-1])>0 else None
        if len(closes)>=21:tech_ready+=1
        flags=[]
        if not eligible:flags.append('NOT_ELIGIBLE_OR_PREFERRED')
        if eligible and not valid:flags.append('ANNUAL_MISSING')
        if valid and (profit is None or equity is None):flags.append('FINANCIAL_FIELDS_INCOMPLETE')
        if rev_growth is None:flags.append('YOY_NOT_VERIFIED')
        if len(closes)<21:flags.append('HISTORY_LT_21')
        if day!=NOW.strftime('%Y%m%d'):flags.append('SNAPSHOT_NOT_TODAY')
        flags+=['OFFICIAL_PER_PBR_NOT_VERIFIED','TTM_NOT_VERIFIED','SHARE_CLASS_NOT_OFFICIALLY_VERIFIED','SECTOR_ADJUSTMENT_PENDING']
        # Owner equity is not total equity: do not treat owner debt proxy as verified leverage.
        score=None;grade=''
        if eligible and valid and all(x is not None for x in (per,pbr,roe)):
            score=sum((roe>=12,0<per<=18,0<pbr<=2.5))
            grade='A' if score==3 else 'B+' if score==2 else 'B' if score==1 else ''
        # Illustrative multiples only, NOT fair value or buy price.
        low=close*8/per if close and per and per>0 else None
        high=close*15/per if close and per and per>0 else None
        row=dict(BAS_DD=day,MARKET=m.get('MARKET',''),ISU_CD=code,ISU_NM=name,MKTCAP=rnd(cap),close=rnd(close),eligible=int(eligible),annual_year=rec.get('year','') if valid else '',annual_valid=int(valid),reference_per=rnd(per),reference_pbr=rnd(pbr),reference_roe_pct=rnd(roe),owner_equity_debt_proxy_pct=rnd(owner_debt_proxy),net_margin_pct=rnd(margin),revenue_yoy_pct=rnd(rev_growth),owner_profit_yoy_pct=rnd(profit_growth),operating_profit_yoy_pct='',ttm_net_income='',ma5=rnd(ma5),ma10=rnd(ma10),ma20=rnd(ma20),golden_cross='' if cross is None else int(cross),volume_ratio_20d=rnd(volratio),illustrative_low_price=rnd(low),illustrative_high_price=rnd(high),research_score='' if score is None else score,provisional_grade=grade,final_grade='WITHHELD',buy_signal='NONE',flags=';'.join(flags))
        rows.append(row)
        if eligible and flags:issues.append(dict(ISU_CD=code,ISU_NM=name,issues=';'.join(flags)))
        if grade:watch.append(row)
        if grade and close and (code,day) not in baseline:
            baseline[(code,day)]=dict(ISU_CD=code,ISU_NM=name,signal_date=day,reference_close=close,provisional_grade=grade)
            new_baselines+=1
    track=[];completed={5:0,10:0,20:0}
    for (code,start),base in sorted(baseline.items()):
        observations=sorted((d,p) for d,(p,v) in series.get(code,{}).items() if d>start)
        r=dict(base)
        for n in (5,10,20):
            value=(observations[n-1][1]/number(base.get('reference_close'))-1)*100 if len(observations)>=n and number(base.get('reference_close')) and number(base.get('reference_close'))>0 else None
            r[f'return_{n}d']=rnd(value)
            if value is not None:completed[n]+=1
        r['state']='20D_COMPLETE' if r['return_20d']!='' else 'AWAITING_VERIFIED_FUTURE_SESSIONS'
        track.append(r)
    fields=list(rows[0]);writecsv('full_market_research.csv',rows,fields)
    writecsv('provisional_ab_watchlist.csv',watch,fields)
    writecsv('issues_only.csv',issues,['ISU_CD','ISU_NM','issues'])
    writecsv('tracking_history.csv',track,['ISU_CD','ISU_NM','signal_date','reference_close','provisional_grade','return_5d','return_10d','return_20d','state'])
    status=dict(version='R14',generated_kst=NOW.isoformat(),state='RESEARCH_ONLY_NOT_FINAL',market_date=day,market_rows=len(rows),eligible_rows=sum(x['eligible'] for x in rows),annual_valid=sum(x['annual_valid'] for x in rows if x['eligible']),provisional_ab_count=len(watch),history_source_rows=history_sources,technical_ready_21d=tech_ready,revenue_yoy_verified=verified_growth,operating_profit_yoy_verified=0,ttm_verified=0,official_per_pbr_verified=0,final_grades=0,buy_signals=0,tracking_baselines=len(track),new_tracking_baselines=new_baselines,tracking_completed=completed,limitations=['No operating profit in R9 annual schema','No comparable quarterly report pairs for TTM','No verified official PER/PBR or industry classification','Historical data only if present in repository','Illustrative price bands are not fair values','No trade signal on stale or unverified inputs'])
    writejson('status.json',status);print(json.dumps(status,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
