#!/usr/bin/env python3
"""Stage57: reproducible provisional A/B regrading, without releasing final trade grades.
Reuses frozen Stage54 cohort; preserves Stage50-56. No network calls.
"""
import csv, json, datetime as dt
from pathlib import Path
from decimal import Decimal, InvalidOperation
ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'stage56_input/provisional_ab_318_evidence_audit.csv'
OUT=ROOT/'stage57_output'
def dec(x):
    try:
        n=Decimal(str(x).strip().replace(',',''))
        return n if n.is_finite() else None
    except (InvalidOperation,ValueError): return None

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    status={'stage':57,'mode':'PROVISIONAL_REGRADING_REUSE_STAGE54','generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'final_grades_released':0,'buy_signals_released':0,'warnings':['Stage54 financial scores are reused; no independent final grade is asserted.','Official PER/PBR, owner-attributable financials and share class remain unverified.']}
    try:
        with SRC.open(encoding='utf-8-sig',newline='') as f: records=list(csv.DictReader(f))
        if len(records)!=318 or {r.get('BAS_DD') for r in records}!={'20261106'}:raise ValueError('Frozen Stage54 cohort/date mismatch')
        seen=set();out=[];counts={}
        for r in records:
            code=r.get('ISU_CD','').strip();market=r.get('MARKET','').strip();key=(market,code)
            if key in seen:raise ValueError('Duplicate security '+str(key))
            seen.add(key)
            prior=r.get('provisional_grade','').strip();score=dec(r.get('stage53_quality_adjusted_score'))
            blockers=[]
            if r.get('shareclass_official')!='VERIFIED':blockers.append('SHARECLASS_NOT_VERIFIED')
            if r.get('financial_period')!='2025_FY':blockers.append('FINANCIAL_PERIOD_UNEXPECTED')
            if r.get('financial_statement_type') not in ('CFS','OFS'):blockers.append('STATEMENT_TYPE_UNKNOWN')
            if not r.get('dart_corp_code','').strip():blockers.append('DART_MAPPING_MISSING')
            if not r.get('per','').strip() or not r.get('pbr','').strip():blockers.append('OFFICIAL_VALUATION_NOT_VERIFIED')
            if r.get('financial_statement_type')=='OFS':blockers.append('OFS_REQUIRES_COMPARABILITY_REVIEW')
            if score is None:blockers.append('STAGE53_SCORE_MISSING')
            if prior not in ('A','A+','B','B+'):blockers.append('PROVISIONAL_GRADE_OUT_OF_SCOPE')
            status_label='PROVISIONAL_RETAINED_WITH_BLOCKERS' if prior in ('A','A+','B','B+') and score is not None else 'MANUAL_REVIEW_REQUIRED'
            counts[status_label]=counts.get(status_label,0)+1
            out.append({'BAS_DD':r['BAS_DD'],'MARKET':market,'ISU_CD':code,'ISU_NM':r.get('ISU_NM',''),'stage54_provisional_grade':prior,'stage53_quality_adjusted_score':str(score) if score is not None else '', 'stage57_provisional_grade':prior if status_label.startswith('PROVISIONAL') else '', 'stage57_status':status_label,'stage57_blockers':';'.join(blockers),'final_grade':'WITHHELD','buy_signal':'NONE'})
        with (OUT/'provisional_regrade.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(out[0]));writer.writeheader();writer.writerows(out)
        status.update({'candidate_count':len(out),'market_date':'20261106','counts':counts,'source':'stage56_input/provisional_ab_318_evidence_audit.csv'})
    except Exception as exc:status['error']=str(exc)
    (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(status,ensure_ascii=False,indent=2))
    if 'error' in status:raise SystemExit(1)
if __name__=='__main__':main()
