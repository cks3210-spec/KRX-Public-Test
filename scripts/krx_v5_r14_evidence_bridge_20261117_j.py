#!/usr/bin/env python3
"""R14 J evidence bridge: optional KRX share-class metadata, externally verified valuation,
sector evidence and persistent forward tracking. Never invent official PER/PBR.
"""
import csv, json, os, pathlib, datetime, math, urllib.request, urllib.parse, time
from collections import Counter, defaultdict
ROOT=pathlib.Path(os.environ.get('GITHUB_WORKSPACE','.')).resolve()
I=ROOT/'data/v5_investment_r14_research_i/full_market_research_i.csv'
OUT=ROOT/'data/v5_investment_r14_research_j'
INPUT=ROOT/'data/v5_investment_r14_research_i_inputs'
HISTORY=ROOT/'data/v5_investment_r14_history_link'
I_LEDGER=ROOT/'data/v5_investment_r14_research_i/observation_ledger.csv'

def read(p):
    if not p.exists():return []
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(p,rows,fields):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
def n(x):
    try:
        v=float(str(x).replace(',',''));return v if math.isfinite(v) else None
    except (ValueError,TypeError):return None
def code(x):
    x=str(x or '').strip();return x.zfill(6) if x.isdigit() and len(x)<=6 else ''
def date(x):
    s=str(x or '').replace('-','').strip();return s if len(s)==8 and s.isdigit() else ''
def krx_metadata(day):
    key=os.getenv('KRX_API_KEY','').strip()
    if not key:return {},'NO_KRX_API_KEY'
    records={};failures=[]
    for endpoint in ('stk_isu_base_info','ksq_isu_base_info'):
        url='https://data-dbg.krx.co.kr/svc/apis/sto/'+endpoint+'?'+urllib.parse.urlencode({'basDd':day})
        try:
            req=urllib.request.Request(url,headers={'AUTH_KEY':key,'Accept':'application/json'})
            with urllib.request.urlopen(req,timeout=25) as res:payload=json.load(res)
            block=payload.get('OutBlock_1',[])
            if not isinstance(block,list):raise ValueError('OutBlock_1 missing')
            for r in block:
                c=code(r.get('ISU_SRT_CD'))
                if c:records[c]={'share_class':r.get('KIND_STKCERT_TP_NM',''),
                  'security_group':r.get('SECUGRP_NM',''),'krx_section':r.get('SECT_TP_NM',''),
                  'market_type':r.get('MKT_TP_NM',''),'metadata_date':day}
        except Exception as e:failures.append(endpoint+':'+type(e).__name__)
    return records,('PARTIAL:'+','.join(failures)) if failures else 'OK'
def evidence():
    # This input must be obtained separately from a verifiable official source.
    # KRX Open API stock endpoints do NOT supply stock-level PER/PBR.
    values={};rejections=Counter()
    for r in read(INPUT/'official_valuation.csv'):
        d,c=date(r.get('BAS_DD')),code(r.get('ISU_CD'))
        src=(r.get('source') or '').strip().upper()
        verified=str(r.get('verified','')).strip().lower() in ('yes','true','1')
        ref=(r.get('source_reference') or '').strip()
        if src!='KRX_OFFICIAL' or not verified or not ref or not d or not c:
            rejections['missing_provenance']+=1;continue
        per,pbr=n(r.get('PER')),n(r.get('PBR'))
        per=per if per is not None and per>0 else None
        pbr=pbr if pbr is not None and pbr>0 else None
        if per is None and pbr is None:rejections['no_positive_ratio']+=1;continue
        values[(d,c)]={'per':per,'pbr':pbr,'reference':ref}
    return values,rejections
def sectors():
    values={}
    for r in read(INPUT/'sectors.csv'):
        c=code(r.get('ISU_CD'));s=(r.get('sector') or '').strip().upper()
        ref=(r.get('source_reference') or '').strip()
        if c and s in ('FINANCIAL','NON_FINANCIAL') and ref:values[c]=(s,ref)
    return values
def history_prices():
    # Read only known generated history files; never invent sessions.
    paths=[HISTORY/'daily_close_history.csv',HISTORY/'linked_daily_close_history.csv',
           HISTORY/'full_market_daily_close.csv',
           ROOT/'data/v5_investment_r14_fundamental/daily_close_archive.csv']
    prices={};files=[]
    for p in paths:
        if not p.exists():continue
        rows=read(p);found=0
        for r in rows:
            c=code(r.get('ISU_CD') or r.get('code'))
            d=date(r.get('BAS_DD') or r.get('market_date') or r.get('date'))
            price=n(r.get('TDD_CLSPRC') or r.get('close') or r.get('verified_close'))
            if c and d and price and price>0:prices[(c,d)]=price;found+=1
        files.append({'path':str(p.relative_to(ROOT)),'valid_rows':found})
    return prices,files

def main():
    rows=read(I)
    if not rows:raise SystemExit('MISSING_I_INPUT: '+str(I))
    dates={date(r.get('BAS_DD')) for r in rows}
    if len(dates)!=1 or '' in dates:raise SystemExit('INVALID_MIXED_DATES')
    d=next(iter(dates))
    meta,meta_state=krx_metadata(d)
    official,rejected=evidence();industry=sectors()
    result=[]
    for r in rows:
        x=dict(r);c=code(r.get('ISU_CD'));m=meta.get(c,{})
        kind=m.get('share_class','');share_status='UNVERIFIED'
        if kind:share_status='COMMON' if '보통' in kind else 'NON_COMMON' if ('우선' in kind or '종류' in kind) else 'OTHER_OR_UNKNOWN'
        sector,sector_ref=industry.get(c,('UNKNOWN',''))
        v=official.get((d,c),{});per,pbr=v.get('per'),v.get('pbr')
        close=n(r.get('verified_close')) or n(r.get('close'))
        eps=close/per if close and per else None
        # PE sensitivity is NOT an independent intrinsic value or a buy signal.
        scenario=[round(eps*k,2) if eps and eps>0 and sector=='NON_FINANCIAL' else '' for k in (8,12,16)]
        eligible=str(r.get('i_eligible','')).strip()=='1' and share_status!='NON_COMMON'
        x.update(j_krx_share_class=kind,j_share_status=share_status,j_metadata_date=m.get('metadata_date',''),
            j_krx_section=m.get('krx_section',''),j_sector=sector,j_sector_reference=sector_ref,
            j_official_per=per if per is not None else '',j_official_pbr=pbr if pbr is not None else '',
            j_official_reference=v.get('reference',''),j_eligible=int(eligible),
            j_pe_sensitivity_8x=scenario[0],j_pe_sensitivity_12x=scenario[1],j_pe_sensitivity_16x=scenario[2],
            j_price_status='SENSITIVITY_ONLY_NOT_FAIR_VALUE' if scenario[0]!='' else 'NOT_AVAILABLE',
            j_grade_provisional=r.get('i_h_grade','') if eligible else '',j_final_grade='',j_buy_signal='',
            j_research_status='PROVISIONAL_NOT_RECOMMENDATION')
        result.append(x)
    fields=list(result[0]);write(OUT/'full_market_research_j.csv',result,fields)
    ab=[r for r in result if r['j_grade_provisional'] in ('A','B+','B')]
    write(OUT/'provisional_ab_research_j.csv',ab,fields)
    # Persist prior observations without replacing original observation dates or prices.
    ledger_path=OUT/'observation_ledger.csv'
    ledger={}
    for path in (ledger_path,I_LEDGER):
        for r in read(path):
            c=code(r.get('ISU_CD'));dd=date(r.get('observation_date'))
            if c and dd and (c,dd) not in ledger:ledger[(c,dd)]=r
    for r in ab:
        c=code(r.get('ISU_CD'));p=n(r.get('verified_close')) or n(r.get('close'))
        if c and p and (c,d) not in ledger:
            ledger[(c,d)]={'ISU_CD':c,'ISU_NM':r.get('ISU_NM',''),'observation_date':d,
             'observation_price':p,'provisional_grade_at_observation':r['j_grade_provisional'],
             'forward_5d_pct':'','forward_10d_pct':'','forward_20d_pct':'','tracking_state':'PENDING_FUTURE_SESSIONS'}
    prices,price_files=history_prices()
    for r in result:
        c=code(r.get('ISU_CD'));p=n(r.get('verified_close')) or n(r.get('close'))
        if c and p and p>0:prices[(c,d)]=p
    sessions=defaultdict(list)
    for c,dd in prices:sessions[c].append(dd)
    for c in sessions:sessions[c].sort()
    for (c,dd),item in ledger.items():
        p=n(item.get('observation_price'))
        if not p or p<=0:continue
        future=[t for t in sessions.get(c,[]) if t>dd]
        for period in (5,10,20):
            field=f'forward_{period}d_pct'
            if (item.get(field) is None or str(item.get(field))=='') and len(future)>=period:
                item[field]=round((prices[(c,future[period-1])]/p-1)*100,3)
        item['tracking_state']='COMPLETE_20D' if str(item.get('forward_20d_pct',''))!='' else 'PENDING_FUTURE_SESSIONS'
    ledger_rows=sorted(ledger.values(),key=lambda x:(x.get('observation_date',''),x.get('ISU_CD','')))
    ledger_fields=['ISU_CD','ISU_NM','observation_date','observation_price','provisional_grade_at_observation','forward_5d_pct','forward_10d_pct','forward_20d_pct','tracking_state']
    write(ledger_path,ledger_rows,ledger_fields)
    status={'version':'R14_J_EVIDENCE_BRIDGE','generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'market_date':d,'rows':len(result),'provisional_ab':len(ab),
        'official_per_count':sum(r['j_official_per']!='' for r in result),
        'official_pbr_count':sum(r['j_official_pbr']!='' for r in result),
        'sector_verified_count':sum(r['j_sector']!='UNKNOWN' for r in result),
        'krx_metadata_records':len(meta),'krx_metadata_status':meta_state,
        'share_class_verified_count':sum(r['j_share_status']!='UNVERIFIED' for r in result),
        'non_common_excluded':sum(r['j_share_status']=='NON_COMMON' for r in result),
        'official_input_present':(INPUT/'official_valuation.csv').exists(),
        'sector_input_present':(INPUT/'sectors.csv').exists(),
        'official_rejections':dict(rejected),'historical_sources':price_files,
        'ledger_observations':len(ledger_rows),
        **{f'forward_{k}d_complete':sum(str(r.get(f'forward_{k}d_pct',''))!='' for r in ledger_rows) for k in (5,10,20)},
        'golden_cross_used':False,'final_buy_signals':0,
        'notes':['KRX Open API stock endpoints do not provide official stock PER/PBR',
                 'KRX SECT_TP_NM is not treated as an industry classification',
                 'Official ratios accepted only from dated, externally verified source with reference',
                 'Price sensitivities are not validated fair values',
                 'No historical session is fabricated and no final buy signal is issued']}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(status,ensure_ascii=False))
if __name__=='__main__':main()
