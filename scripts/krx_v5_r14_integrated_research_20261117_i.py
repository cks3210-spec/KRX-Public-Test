#!/usr/bin/env python3
"""R14 I: conservative valuation evidence, sector-aware diagnostics, prospective tracking.
Reads H output only; never changes upstream data. No golden-cross criteria.
"""
import csv, json, math, os, pathlib, datetime, statistics
from collections import Counter
ROOT=pathlib.Path(os.environ.get('GITHUB_WORKSPACE','.')).resolve()
SOURCE=ROOT/'data/v5_investment_r14_valuation_h/full_market_valuation_h.csv'
OUT=ROOT/'data/v5_investment_r14_research_i'
OFFICIAL=ROOT/'data/v5_investment_r14_research_i_inputs/official_valuation.csv'
SECTORS=ROOT/'data/v5_investment_r14_research_i_inputs/sectors.csv'
LEDGER=OUT/'observation_ledger.csv'

def num(x):
    try:
        y=float(str(x).replace(',',''));return y if math.isfinite(y) else None
    except (TypeError,ValueError):return None

def load(path):
    if not path.exists():return []
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def write(path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)

def day(x):
    s=str(x or '').replace('-','');return s if len(s)==8 and s.isdigit() else ''

def code(x):return str(x or '').strip().zfill(6)

def load_official():
    # Explicit provenance required. Never promote reference PER/PBR to official.
    found={};rejected=Counter()
    for r in load(OFFICIAL):
        k=(day(r.get('BAS_DD')),code(r.get('ISU_CD')))
        per,pbr=num(r.get('PER')),num(r.get('PBR'))
        origin=(r.get('source') or '').strip().upper()
        verified=(r.get('verified') or '').strip().upper() in ('TRUE','YES','1')
        if origin not in ('KRX_OFFICIAL','KRX_OPEN_API') or not verified or not k[0] or (per is None and pbr is None):
            rejected['unverified_provenance_or_missing_fields']+=1;continue
        if per is not None and per<=0:per=None
        if pbr is not None and pbr<=0:pbr=None
        if per is None and pbr is None:rejected['nonpositive_valuation']+=1;continue
        found[k]=(per,pbr)
    return found,rejected

def load_sectors():
    found={}
    for r in load(SECTORS):
        s=(r.get('sector') or '').strip().upper()
        if s in ('FINANCIAL','NON_FINANCIAL') and code(r.get('ISU_CD')):found[code(r['ISU_CD'])]=s
    return found

def score_row(r,official,sectors):
    out=dict(r);k=(day(r.get('BAS_DD')),code(r.get('ISU_CD')))
    close=num(r.get('verified_close')) or num(r.get('close'))
    ref_per,ref_pbr=num(r.get('reference_per')),num(r.get('reference_pbr'))
    official_per,official_pbr=official.get(k,(None,None))
    sector=sectors.get(k[1],'UNKNOWN')
    # No guessed sector from a company name. Financials require distinct debt/earnings treatment.
    coverage=sum(num(r.get(x)) is not None for x in ('revenue_yoy_pct','operating_profit_yoy_pct','owner_profit_yoy_pct'))
    roe=num(r.get('reference_roe_pct'))
    score=num(r.get('valuation_h_score'))
    hgrade=r.get('valuation_h_grade_provisional','')
    cap=num(r.get('MKTCAP'))
    is_eligible=str(r.get('eligible','')).strip().lower() in ('1','true','yes') and cap is not None and cap>=100_000_000_000
    financial=str(r.get('annual_valid','')).strip().lower() in ('1','true','yes')
    per_gap=(ref_per/official_per-1)*100 if ref_per and official_per else None
    pbr_gap=(ref_pbr/official_pbr-1)*100 if ref_pbr and official_pbr else None
    # Reference price from H is *not* promoted to fair value; it is often far from market price.
    # Independent transparent sensitivity using EPS implied by same-date official PER.
    eps=close/official_per if close and official_per else None
    scenarios={}
    if eps and eps>0 and sector=='NON_FINANCIAL' and financial:
        for label,mult in (('conservative',8),('base',12),('optimistic',16)):
            scenarios[label]=round(eps*mult,2)
    # For financial companies, no manufacturing-sector PE price model is used.
    price_basis='OFFICIAL_PE_SCENARIO_NOT_TARGET' if scenarios else 'UNAVAILABLE'
    reasons=[]
    if not is_eligible:reasons.append('NOT_ELIGIBLE')
    if not financial:reasons.append('FINANCIAL_DATA_MISSING')
    if sector=='UNKNOWN':reasons.append('SECTOR_UNVERIFIED')
    if official_per is None:reasons.append('OFFICIAL_PER_UNVERIFIED')
    if official_pbr is None:reasons.append('OFFICIAL_PBR_UNVERIFIED')
    if coverage<3:reasons.append('PARTIAL_GROWTH')
    if day(r.get('BAS_DD'))!=day(r.get('BAS_DD')):reasons.append('DATE_ERROR')
    out.update(i_sector=sector,i_official_per=official_per or '',i_official_pbr=official_pbr or '',
        i_reference_per_gap_pct=round(per_gap,2) if per_gap is not None else '',
        i_reference_pbr_gap_pct=round(pbr_gap,2) if pbr_gap is not None else '',
        i_growth_metric_count=coverage,i_financial_valid=int(financial),i_eligible=int(is_eligible),
        i_h_grade=hgrade if is_eligible else '',i_h_score=score if score is not None else '',
        i_reference_price_warning='H_ILLUSTRATIVE_RANGE_NOT_VERIFIED',
        i_scenario_low=scenarios.get('conservative',''),i_scenario_mid=scenarios.get('base',''),
        i_scenario_high=scenarios.get('optimistic',''),i_price_basis=price_basis,
        i_final_grade='',i_buy_signal='',i_decision='RESEARCH_ONLY',i_flags=';'.join(reasons))
    return out

def update_ledger(rows,existing):
    # Records historical *observations* without mistaking trailing returns for forward returns.
    bydate={}
    for r in rows:
        d=day(r.get('BAS_DD'));c=code(r.get('ISU_CD'));p=num(r.get('verified_close')) or num(r.get('close'))
        if d and p and p>0:bydate[(c,d)]=p
    snapshots=sorted({d for _,d in bydate})
    ledger={}
    for r in existing:
        c=code(r.get('ISU_CD'));d=day(r.get('observation_date'))
        if c and d:ledger[(c,d)]=dict(r)
    for r in rows:
        if r.get('i_h_grade') not in ('A','B+','B'):continue
        c=code(r.get('ISU_CD'));d=day(r.get('BAS_DD'));p=bydate.get((c,d))
        if not p:continue
        key=(c,d)
        if key not in ledger:
            ledger[key]={'ISU_CD':c,'ISU_NM':r.get('ISU_NM',''),'observation_date':d,'observation_price':p,
              'provisional_grade_at_observation':r['i_h_grade'],'forward_5d_pct':'','forward_10d_pct':'','forward_20d_pct':'',
              'tracking_state':'PENDING_FUTURE_SESSIONS'}
    # Only use future sessions from subsequent runs, never past returns.
    for (c,d),item in ledger.items():
        p=num(item.get('observation_price'))
        if not p or p<=0:continue
        future=sorted(x for (cc,x) in bydate if cc==c and x>d)
        for n in (5,10,20):
            key='forward_%dd_pct'%n
            if not item.get(key) and len(future)>=n:
                item[key]=round((bydate[(c,future[n-1])]/p-1)*100,3)
        item['tracking_state']='COMPLETE_20D' if item.get('forward_20d_pct')!='' else 'PENDING_FUTURE_SESSIONS'
    return list(ledger.values())

def main():
    rows=load(SOURCE)
    if not rows:raise SystemExit('MISSING_OR_EMPTY_INPUT: '+str(SOURCE))
    official,rejected=load_official();sectors=load_sectors()
    evaluated=[score_row(r,official,sectors) for r in rows]
    dates=sorted({day(r.get('BAS_DD')) for r in evaluated if day(r.get('BAS_DD'))})
    if len(dates)!=1:raise SystemExit('INPUT_MIXED_MARKET_DATES: '+str(dates))
    fields=list(evaluated[0]);write(OUT/'full_market_research_i.csv',evaluated,fields)
    ab=[r for r in evaluated if r['i_h_grade'] in ('A','B+','B')]
    write(OUT/'provisional_ab_research_i.csv',ab,fields)
    ledger=update_ledger(evaluated,load(LEDGER))
    ledgerfields=['ISU_CD','ISU_NM','observation_date','observation_price','provisional_grade_at_observation','forward_5d_pct','forward_10d_pct','forward_20d_pct','tracking_state']
    write(LEDGER,ledger,ledgerfields)
    status={'version':'R14_INTEGRATED_RESEARCH_I','generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'input':'data/v5_investment_r14_valuation_h/full_market_valuation_h.csv','market_date':dates[0],
      'rows':len(evaluated),'provisional_ab':len(ab),'grades':dict(Counter(r['i_h_grade'] for r in ab)),
      'official_per_count':sum(r['i_official_per']!='' for r in evaluated),
      'official_pbr_count':sum(r['i_official_pbr']!='' for r in evaluated),
      'sector_verified_count':sum(r['i_sector']!='UNKNOWN' for r in evaluated),
      'scenario_price_count':sum(r['i_price_basis']!='UNAVAILABLE' for r in evaluated),
      'official_input_present':OFFICIAL.exists(),'sector_input_present':SECTORS.exists(),
      'official_records_rejected':dict(rejected),'tracking_observations':len(ledger),
      'forward_5d_complete':sum(str(r.get('forward_5d_pct',''))!='' for r in ledger),
      'forward_10d_complete':sum(str(r.get('forward_10d_pct',''))!='' for r in ledger),
      'forward_20d_complete':sum(str(r.get('forward_20d_pct',''))!='' for r in ledger),
      'golden_cross_used':False,'final_buy_signals':0,
      'notes':['No official PER/PBR asserted without explicit same-date source provenance',
        'Unknown sector is not guessed; financials excluded from generic PE scenarios',
        'Illustrative H ranges not treated as validated fair prices',
        'Forward outcomes use future sessions only, not trailing historical returns',
        'Only provisional A/B shown; no final recommendation without official evidence']}
    (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(status,ensure_ascii=False))
if __name__=='__main__':main()
