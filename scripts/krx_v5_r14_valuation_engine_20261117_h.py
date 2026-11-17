#!/usr/bin/env python3
"""R14 H: evidence-aware valuation, independent of golden crosses and upstream caches."""
import csv, json, math, os, pathlib, datetime
ROOT=pathlib.Path(os.environ.get('GITHUB_WORKSPACE','.'))
SOURCE=ROOT/'data/v5_investment_r14_integrated_g/full_market_integrated.csv'
OUT=ROOT/'data/v5_investment_r14_valuation_h'

def number(v):
    try:
        n=float(v)
        return n if math.isfinite(n) else None
    except (TypeError,ValueError): return None

def clamp(x,a,b): return max(a,min(b,x))
def fmt(v): return '' if v is None else str(round(v,3))

def analyze(row):
    close=number(row.get('verified_close')) or number(row.get('close'))
    per=number(row.get('reference_per'));pbr=number(row.get('reference_pbr'))
    roe=number(row.get('reference_roe_pct'))
    rev=number(row.get('revenue_yoy_pct'));op=number(row.get('operating_profit_yoy_pct'))
    profit=number(row.get('owner_profit_yoy_pct'))
    low=number(row.get('illustrative_low_price'));high=number(row.get('illustrative_high_price'))
    cap=number(row.get('MKTCAP'))
    eligible=str(row.get('eligible','')).strip().lower() in ('1','true','yes')
    financial=str(row.get('annual_valid','')).strip().lower() in ('1','true','yes')
    official=str(row.get('official_valuation_verified','')).strip().lower() in ('yes','true','1')
    # Reference PER/PBR are not official confirmation; valuation estimates are illustrative.
    metrics=[x for x in (rev,op,profit) if x is not None]
    growth_score=(sum(clamp(x,-40,40) for x in metrics)/len(metrics)) if metrics else None
    quality_score=roe if roe is not None else None
    valuation_score=None
    if per is not None and per>0 and pbr is not None and pbr>0:
        valuation_score=clamp(20-per,-20,20)*0.55+clamp(2-pbr,-3,2)*4.5
    elif per is not None and per>0: valuation_score=clamp(20-per,-20,20)*0.55
    elif pbr is not None and pbr>0: valuation_score=clamp(2-pbr,-3,2)*4.5
    weights=[(growth_score,.4),(quality_score,.3),(valuation_score,.3)]
    active=[(v,w) for v,w in weights if v is not None]
    score=round(sum(v*w for v,w in active)/sum(w for _,w in active),2) if active else None
    coverage=sum(v is not None for v in (rev,op,profit,roe,per,pbr))
    confidence='HIGH' if coverage>=5 and financial and official else ('MEDIUM' if coverage>=4 and financial else 'LOW')
    # Conservative illustrative value range: upstream reference range only if positive and ordered.
    fair_low=low if low and low>0 and high and high>=low else None
    fair_high=high if fair_low is not None else None
    margin=(fair_low/close-1)*100 if fair_low is not None and close and close>0 else None
    # No final grades or buy recommendations without official valuation verification.
    provisional='A' if score is not None and score>=14 and coverage>=4 else ('B+' if score is not None and score>=7 and coverage>=3 else ('B' if score is not None and score>=2 and coverage>=3 else ''))
    if not eligible or cap is None or cap<100_000_000_000: provisional=''
    flags=[]
    if not official:flags.append('OFFICIAL_PER_PBR_UNVERIFIED')
    if not financial:flags.append('FINANCIALS_INCOMPLETE')
    if len(metrics)<3:flags.append('GROWTH_PARTIAL')
    if number(row.get('actual_return_20d_pct')) is None:flags.append('20D_HISTORY_UNAVAILABLE')
    if fair_low is None:flags.append('FAIR_RANGE_UNAVAILABLE')
    return dict(row,valuation_h_score=fmt(score),valuation_h_grade_provisional=provisional,
        valuation_h_confidence=confidence,valuation_h_metrics_available=str(coverage),
        valuation_h_growth_score=fmt(growth_score),valuation_h_quality_score=fmt(quality_score),
        valuation_h_reference_score=fmt(valuation_score),valuation_h_fair_low_reference=fmt(fair_low),
        valuation_h_fair_high_reference=fmt(fair_high),valuation_h_reference_margin_pct=fmt(margin),
        valuation_h_official_verified='YES' if official else 'NO',valuation_h_final_grade='',
        valuation_h_final_buy_signal='',valuation_h_flags=';'.join(flags),
        valuation_h_decision='RESEARCH_ONLY_NOT_BUY_ADVICE')

def main():
    if not SOURCE.exists():raise SystemExit('MISSING_INPUT: '+str(SOURCE))
    with SOURCE.open(encoding='utf-8-sig',newline='') as f:reader=csv.DictReader(f); rows=[analyze(r) for r in reader]
    if not rows:raise SystemExit('EMPTY_INPUT')
    OUT.mkdir(parents=True,exist_ok=True)
    def save(name,items):
        with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0].keys()),extrasaction='ignore');w.writeheader();w.writerows(items)
    save('full_market_valuation_h.csv',rows)
    ab=[r for r in rows if r['valuation_h_grade_provisional'] in ('A','B+','B')]
    save('provisional_ab_valuation_h.csv',ab)
    dates=sorted({r.get('BAS_DD','') for r in rows if r.get('BAS_DD')})
    status={'version':'R14_VALUATION_H','generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'input':str(SOURCE.relative_to(ROOT)),'latest_market_date':dates[-1] if dates else None,
      'rows':len(rows),'provisional_ab':len(ab),'confidence':{k:sum(r['valuation_h_confidence']==k for r in rows) for k in ('HIGH','MEDIUM','LOW')},
      'official_verified':sum(r['valuation_h_official_verified']=='YES' for r in rows),
      'final_buy_signals':0,'golden_cross_used':False,
      'caution':'Reference valuations are illustrative; official PER/PBR not established by this engine. Provisional grades are not final recommendations.'}
    (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(status,ensure_ascii=False))
if __name__=='__main__':main()
