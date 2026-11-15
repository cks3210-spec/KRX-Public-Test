#!/usr/bin/env python3
"""V5 full-market universe: preserve all eligible stocks, independently of technical signals.
This is an integration foundation, not a verified A/B grading or trade recommendation.
"""
import csv, json, datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'
def rows(path):
 with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def number(value):
 try:return float(str(value).replace(',',''))
 except (ValueError,TypeError):return None
def main():
 summary=json.loads((DATA/'summary.json').read_text(encoding='utf-8'))
 day=str(summary['latest_trading_date'])
 datetime.datetime.strptime(day,'%Y%m%d')
 latest=rows(DATA/'latest.csv'); indicators=rows(DATA/'daily_indicators.csv')
 if not latest:raise RuntimeError('EMPTY_LATEST')
 market=[r for r in latest if r.get('BAS_DD')==day]
 if not market:raise RuntimeError('MARKET_DATE_MISMATCH')
 if any(r.get('BAS_DD')!=day for r in indicators):raise RuntimeError('INDICATOR_DATE_MISMATCH')
 technical={r.get('ISU_CD'):r for r in indicators}
 research_path=DATA/'all_candidates_318.csv'
 research={r.get('code','').zfill(6):r for r in rows(research_path)} if research_path.exists() else {}
 out=[]; seen=set(); errors=[]
 for r in market:
  code=str(r.get('ISU_CD','')).zfill(6);name=r.get('ISU_NM','');cap=number(r.get('MKTCAP'))
  if not code or code in seen:errors.append('DUPLICATE_OR_EMPTY_CODE:'+code);continue
  seen.add(code)
  if cap is None:errors.append('MARKET_CAP_MISSING:'+code);continue
  if cap<100_000_000_000:continue
  if '스팩' in name or 'SPAC' in name.upper():continue
  if r.get('MARKET') and r.get('MARKET') not in ('KOSPI','KOSDAQ','유가증권','코스닥'):
   errors.append('MARKET_LABEL_UNRECOGNIZED:'+code+':'+str(r.get('MARKET')))
  t=technical.get(r.get('ISU_CD'));f=research.get(code)
  out.append({'code':code,'name':name,'market':r.get('MARKET'),'market_cap_krw':int(cap),
    'close_krw':number(r.get('TDD_CLSPRC')),'technical_data_present':t is not None,
    'technical_uptrend':(str(t.get('UPTREND','')).lower()=='true') if t else None,
    'research_record_present':f is not None,'financial_verification':'NOT_VERIFIED',
    'grade':None,'fair_price':None,'buy_signal':None})
 out.sort(key=lambda x:x['code'])
 report={'trading_date':day,'generated_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'classification':'FULL_MARKET_UNIVERSE_NOT_VERIFIED_INVESTMENT_GRADES',
  'market_rows':len(market),'eligible_universe_count':len(out),
  'technical_coverage_count':sum(x['technical_data_present'] for x in out),
  'research_coverage_count':sum(x['research_record_present'] for x in out),
  'missing_research_count':sum(not x['research_record_present'] for x in out),
  'errors':errors,'stocks':out,
  'note':'All market-cap-eligible stocks retained, including those without uptrend or financial coverage. A/B grades and buy signals remain withheld.'}
 DATA.mkdir(exist_ok=True)
 (DATA/'v5_full_market_universe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 with (DATA/'v5_full_market_universe.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(out[0]) if out else ['code']);w.writeheader();w.writerows(out)
 print(json.dumps({k:report[k] for k in ('trading_date','market_rows','eligible_universe_count','technical_coverage_count','research_coverage_count','missing_research_count')},ensure_ascii=False))
 if errors:print('WARNINGS:',len(errors),errors[:10])
 if not out:raise RuntimeError('EMPTY_ELIGIBLE_UNIVERSE')
if __name__=='__main__':main()
