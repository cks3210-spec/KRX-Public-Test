#!/usr/bin/env python3
"""KRX v5 stage 3: auditable PER/PBR valuation; verified-input gating.
Run: python scripts/build_daily_valuation_v3.py
Inputs: data/daily_grade_gate.json, data/all_candidates_318.csv
Optional: data/financial_verification_status.json with {"verified":true,"financial_asof":"YYYY-MM-DD","method":"...","source":"..."}.
No grade/buy signal without verified source and consistent valuation.
"""
import csv,json,math,pathlib,datetime
DATA=pathlib.Path(__file__).resolve().parents[1]/'data'

def positive(x):
 try:
  v=float(x)
  return v if math.isfinite(v) and v>0 else None
 except (ValueError,TypeError):return None

def main():
 gate=json.loads((DATA/'daily_grade_gate.json').read_text(encoding='utf-8'))
 with (DATA/'all_candidates_318.csv').open(encoding='utf-8-sig',newline='') as f:
  records={r['code'].zfill(6):r for r in csv.DictReader(f)}
 verification_path=DATA/'financial_verification_status.json'
 verification=json.loads(verification_path.read_text(encoding='utf-8')) if verification_path.exists() else {}
 verified=verification.get('verified') is True and bool(verification.get('financial_asof')) and bool(verification.get('source'))
 result=[]
 for item in gate['results']:
  code=item['code']; r=records.get(code,{})
  close=positive(r.get('official_close'));per=positive(r.get('official_per'));pbr=positive(r.get('official_pbr'))
  peer_per=positive(r.get('market_peer_median_per'));peer_pbr=positive(r.get('market_peer_median_pbr'))
  per_value=round(close*peer_per/per) if close and per and peer_per else None
  pbr_value=round(close*peer_pbr/pbr) if close and pbr and peer_pbr else None
  spread=abs(per_value-pbr_value)/max(per_value,pbr_value)*100 if per_value and pbr_value else None
  reasons=[]
  if item['review_status']!='ELIGIBLE_FOR_GRADE_REVIEW':reasons.append('RESEARCH_REVIEW_REQUIRED')
  if not verified:reasons.append('FINANCIAL_SOURCE_NOT_VERIFIED')
  if not all([close,per,pbr,peer_per,peer_pbr]):reasons.append('VALUATION_INPUT_MISSING')
  if spread is not None and spread>40:reasons.append('PER_PBR_ESTIMATES_DISAGREE_GT_40PCT')
  # Do not issue final grades without a dated, audited financial data lineage and risk model.
  reasons.append('FINAL_GRADE_MODEL_NOT_VALIDATED')
  result.append({'code':code,'name':item.get('name'),'review_status':item['review_status'],
   'reference_close_from_research':close,'peer_median_per':peer_per,'peer_median_pbr':peer_pbr,
   'per_implied_value':per_value,'pbr_implied_value':pbr_value,
   'valuation_spread_pct':round(spread,2) if spread is not None else None,
   'indicative_lower_value':min(per_value,pbr_value) if per_value and pbr_value else None,
   'indicative_upper_value':max(per_value,pbr_value) if per_value and pbr_value else None,
   'valuation_is_investment_target':False,'grade':None,'fair_buy_price':None,'buy_signal':None,
   'blockers':reasons})
 output={'trading_date':gate.get('trading_date'),'financial_verification':verification if verified else 'NOT_VERIFIED',
  'classification':'VALUATION_DIAGNOSTIC_ONLY_NOT_BUY_ADVICE','results':result,
  'note':'Peer-multiple estimates use historical research reference close, not live prices. They are diagnostics only. Never issue A/B grades or buy prices until financial lineage and model validated.'}
 dest=DATA/'daily_valuation_v3.json';dest.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'output':str(dest),'evaluated':len(result),'grade_issued':0},ensure_ascii=False))
if __name__=='__main__':main()
