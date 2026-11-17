#!/usr/bin/env python3
"""R13 integrated investment research, research-only. Read-only R9 + market; R13 output only."""
import csv, json, pathlib, datetime as dt, math, re, statistics
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'data/v5_investment_r13'
NOW=dt.datetime.now(ZoneInfo('Asia/Seoul'))
MIN_CAP=100_000_000_000

def num(x):
    try:
        v=float(str(x).replace(',','').strip()); return v if math.isfinite(v) else None
    except (TypeError,ValueError,OverflowError): return None

def readcsv(p):
    if not p.exists(): return []
    with p.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

def loadjson(p):
    if not p.exists(): return {}
    x=json.loads(p.read_text(encoding='utf-8'));return x if isinstance(x,dict) else {}

def savejson(p,x):
    p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');tmp.replace(p)

def savecsv(p,rows,fields):
    p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp')
    with tmp.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
    tmp.replace(p)

def fmt(x,n=3):return '' if x is None or not math.isfinite(x) else round(x,n)
def ratio(a,b,mult=1):return a/b*mult if a is not None and b is not None and b>0 else None

def history():
    """Use only dated, code-identified, observed closes. No synthetic history."""
    paths=[ROOT/'data/daily_indicators.csv',ROOT/'data/market_history.csv',ROOT/'data/history.csv']
    by={}
    for p in paths:
        for r in readcsv(p):
            code=r.get('ISU_CD') or r.get('stock_code') or r.get('code')
            day=r.get('BAS_DD') or r.get('date') or r.get('trade_date')
            price=num(r.get('TDD_CLSPRC') or r.get('close') or r.get('Close'))
            volume=num(r.get('ACC_TRDVOL') or r.get('volume'))
            if code and re.fullmatch(r'\d{8}',str(day or '').replace('-','')) and price and price>0:
                by.setdefault(code,{})[str(day).replace('-','')]=(price,volume)
    return by

def main():
    market=readcsv(ROOT/'data/latest.csv')
    annual=loadjson(ROOT/'data/v5_financial_r9/annual_financial_cache.json')
    r9status=loadjson(ROOT/'data/v5_financial_r9/status.json')
    if len(market)<1500:raise RuntimeError('Full market snapshot missing; no synthetic rows')
    days={r.get('BAS_DD') for r in market}
    if len(days)!=1 or not re.fullmatch(r'\d{8}',str(next(iter(days)))):raise RuntimeError('Market dates invalid')
    day=next(iter(days))
    if len({r.get('ISU_CD') for r in market})!=len(market):raise RuntimeError('Duplicate stock codes')
    market_stale=(dt.datetime.strptime(day,'%Y%m%d').date()!=NOW.date())
    hist=history();rows=[];issues=[];candidates=[];tracking=[]
    for m in market:
        code=m.get('ISU_CD','');name=m.get('ISU_NM','');cap=num(m.get('MKTCAP'));price=num(m.get('TDD_CLSPRC'))
        eligible=bool(cap is not None and cap>=MIN_CAP and re.fullmatch(r'\d{6}',code))
        # Common stock not established merely by a 6-digit code; obvious preferred labels are excluded.
        preferred=bool(re.search(r'(?:우$|우B$|우C$|우\d|우\(|우선|전환우)',name))
        f=annual.get(code,{}) if eligible else {}
        valid=bool(f.get('state')=='FINANCIAL_FIELDS_FOUND' and f.get('report')=='11011' and f.get('fs_div')=='CFS')
        profit=num(f.get('profit')) if valid else None
        equity=num(f.get('equity')) if valid else None
        revenue=num(f.get('revenue')) if valid else None
        assets=num(f.get('assets')) if valid else None
        liabilities=num(f.get('liabilities')) if valid else None
        # Owner-attributable equity and income are provided by R9; assets/liabilities are total CFS.
        per=ratio(cap,profit) if eligible else None
        pbr=ratio(cap,equity) if eligible else None
        roe=ratio(profit,equity,100)
        debt_proxy=ratio(liabilities,equity,100)  # NOT official total-equity debt ratio
        margin=ratio(profit,revenue,100)
        # One annual period alone cannot substantiate year-over-year growth or TTM.
        growth=None;operating_growth=None;ttm=None
        prices=sorted(hist.get(code,{}).items()); closes=[p for _,(p,v) in prices]; vols=[v for _,(p,v) in prices]
        ma5=statistics.mean(closes[-5:]) if len(closes)>=5 else None
        ma10=statistics.mean(closes[-10:]) if len(closes)>=10 else None
        ma20=statistics.mean(closes[-20:]) if len(closes)>=20 else None
        cross=(ma5>ma10 and statistics.mean(closes[-6:-1])<=statistics.mean(closes[-11:-1])) if len(closes)>=11 else None
        volume_ratio=ratio(vols[-1],statistics.mean([v for v in vols[-21:-1] if v is not None])) if len(vols)>=21 and vols[-1] is not None and len([v for v in vols[-21:-1] if v is not None])==20 else None
        # Research valuation bands: transparent scenario multiples, not intrinsic fair value or verified target.
        low=price*(8/per) if price and per and per>0 else None
        high=price*(15/per) if price and per and per>0 else None
        score=None;grade='';flags=[]
        if not eligible:flags.append('BELOW_CAP_OR_CODE_FILTER')
        if preferred:flags.append('PREFERRED_SHARE_EXCLUDED')
        if not valid:flags.append('ANNUAL_FINANCIAL_MISSING')
        if valid and all(x is not None for x in (per,pbr,roe,debt_proxy)):
            score=sum([roe>=12,0<per<=18,0<pbr<=2.5,debt_proxy<=150]);grade='A' if score==4 else 'B+' if score==3 else 'B' if score==2 else ''
        if not f.get('revenue'):flags.append('REVENUE_UNAVAILABLE')
        if not prices:flags.append('PRICE_HISTORY_UNAVAILABLE')
        elif len(prices)<21:flags.append('INSUFFICIENT_PRICE_HISTORY')
        if market_stale:flags.append('MARKET_SNAPSHOT_NOT_TODAY')
        flags.extend(['OFFICIAL_PER_PBR_NOT_VERIFIED','TOTAL_EQUITY_DEBT_RATIO_NOT_VERIFIED','YOY_GROWTH_NOT_AVAILABLE','TTM_NOT_AVAILABLE','SECTOR_NOT_NORMALIZED','SHARE_CLASS_NOT_OFFICIALLY_VERIFIED'])
        if eligible and not preferred and grade:candidates.append(code)
        if eligible and (not valid or (valid and (assets is None or liabilities is None))):issues.append(dict(ISU_CD=code,ISU_NM=name,issue='ANNUAL_MISSING_OR_PARTIAL'))
        row=dict(BAS_DD=day,MARKET=m.get('MARKET',''),ISU_CD=code,ISU_NM=name,MKTCAP=fmt(cap,0),close=fmt(price,0),eligible=int(eligible),preferred_name_flag=int(preferred),annual_year=f.get('year','') if valid else '',annual_valid=int(valid),reference_per=fmt(per),reference_pbr=fmt(pbr),reference_roe_pct=fmt(roe),owner_equity_debt_proxy_pct=fmt(debt_proxy),reference_net_margin_pct=fmt(margin),revenue_yoy_pct='',operating_profit_yoy_pct='',ttm_net_income='',ma5=fmt(ma5),ma10=fmt(ma10),ma20=fmt(ma20),golden_cross='' if cross is None else int(cross),volume_ratio_20d=fmt(volume_ratio),scenario_low_price=fmt(low,0),scenario_high_price=fmt(high,0),research_score='' if score is None else score,provisional_grade=grade if eligible and not preferred else '',final_grade='WITHHELD',buy_signal='NONE',flags=';'.join(flags))
        rows.append(row)
        if eligible and not preferred and grade:
            tracking.append(dict(ISU_CD=code,ISU_NM=name,signal_date=day,reference_close=fmt(price,0),provisional_grade=grade,return_5d='',return_10d='',return_20d='',state='AWAITING_VERIFIED_FUTURE_SESSIONS'))
    fields=list(rows[0]);savecsv(OUT/'full_market_research.csv',rows,fields)
    savecsv(OUT/'provisional_ab_watchlist.csv',[r for r in rows if r['provisional_grade']],fields)
    savecsv(OUT/'issues_only.csv',issues,['ISU_CD','ISU_NM','issue'])
    savecsv(OUT/'forward_tracking_baseline.csv',tracking,['ISU_CD','ISU_NM','signal_date','reference_close','provisional_grade','return_5d','return_10d','return_20d','state'])
    status=dict(version='R13',generated_kst=NOW.isoformat(),state='RESEARCH_ONLY_NOT_FINAL',market_date=day,market_snapshot_stale=market_stale,market_rows=len(rows),eligible_rows=sum(r['eligible'] for r in rows),annual_valid_in_eligible=sum(r['annual_valid'] for r in rows if r['eligible']),provisional_ab_count=len(candidates),history_codes=len(hist),official_per_pbr_verified=0,final_grades=0,buy_signals=0,source_r9_generated_kst=r9status.get('generated_kst'),warnings=['No verified official PER/PBR or sector adjustment','Valuation bands are illustrative multiple scenarios, not fair value','Owner-equity debt proxy is not standard debt ratio','Historical returns need future verified sessions','Annual YoY growth and TTM require comparable reports','R9 and other existing files remain untouched'])
    savejson(OUT/'status.json',status)
    print(json.dumps(status,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
