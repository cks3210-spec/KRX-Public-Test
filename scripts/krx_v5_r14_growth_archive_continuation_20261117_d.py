#!/usr/bin/env python3
"""R14 continuation: persistent incremental growth cache and dated price archive; no golden-cross decisions."""
import csv, datetime as dt, json, os, pathlib, re, subprocess, sys
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'data/v5_investment_r14_fundamental'
UPSTREAM=ROOT/'scripts/krx_v5_r14_fundamental_growth_no_cross_20261117_c.py'
NOW=dt.datetime.now(ZoneInfo('Asia/Seoul'))

def readcsv(p):
 if not p.exists():return []
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def writecsv(p,rows,fields):
 p.parent.mkdir(parents=True,exist_ok=True)
 tmp=p.with_suffix('.tmp')
 with tmp.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
 tmp.replace(p)
def readjson(p):
 try:return json.loads(p.read_text(encoding='utf-8'))
 except (OSError,ValueError):return {}
def valid_day(s):
 try:return dt.datetime.strptime(s,'%Y%m%d').date()<=NOW.date()
 except (ValueError,TypeError):return False

def main():
 # Existing R14 engine reuses its own cached DART comparative records, querying only missing keys.
 if not UPSTREAM.is_file():raise RuntimeError('Existing R14 fundamental script missing')
 subprocess.run([sys.executable,str(UPSTREAM)],check=True)
 status=readjson(OUT/'status.json');cache=readjson(OUT/'dart_annual_comparatives.json')
 market=readcsv(ROOT/'data/latest.csv')
 archive=OUT/'daily_close_archive.csv';hist=readcsv(archive)
 index={(r.get('BAS_DD'),r.get('ISU_CD')):r for r in hist if valid_day(r.get('BAS_DD')) and re.fullmatch(r'\d{6}',r.get('ISU_CD',''))}
 # Archive all valid current market rows, not only currently eligible ones: avoids losing future candidates.
 indicators={(r.get('BAS_DD'),r.get('ISU_CD')):r for r in readcsv(ROOT/'data/daily_indicators.csv')}
 added=0
 for r in market:
  day,code=r.get('BAS_DD',''),r.get('ISU_CD','')
  if not valid_day(day) or not re.fullmatch(r'\d{6}',code):continue
  try:
   price=float(str(r.get('TDD_CLSPRC','')).replace(',',''))
   if not (0<price<1e10):continue
  except (TypeError,ValueError):continue
  k=(day,code);t=indicators.get(k,{})
  record={'BAS_DD':day,'ISU_CD':code,'close':r['TDD_CLSPRC'],'volume':r.get('ACC_TRDVOL',''),
          'ma5':t.get('MA5',''),'ma10':t.get('MA10',''),'ma20':t.get('MA20',''),
          'volume_ratio_20d':t.get('VOLUME_RATIO','')}
  if k not in index:added+=1
  index[k]=record
 fields=['BAS_DD','ISU_CD','close','volume','ma5','ma10','ma20','volume_ratio_20d']
 writecsv(archive,[index[k] for k in sorted(index)],fields)
 # Independently report growth coverage and cache progress. Never invent a growth rate or a signal.
 enriched=readcsv(OUT/'full_market_research_enriched.csv')
 eligible=[r for r in enriched if r.get('eligible')=='1']
 def count(field):return sum(r.get(field,'') not in ('',None) for r in eligible)
 dates=sorted({d for d,c in index})
 status.update(version='R14_FUNDAMENTAL_GROWTH_CONTINUATION_D',continuation_run_kst=NOW.isoformat(),
               market_dates_archived=len(dates),earliest_archive_date=dates[0] if dates else None,
               latest_archive_date=dates[-1] if dates else None,archive_rows=len(index),archive_rows_added=added,
               growth_cache_entries=len(cache),eligible_rows=len(eligible),eligible_revenue_yoy=count('revenue_yoy_pct'),
               eligible_operating_profit_yoy=count('operating_profit_yoy_pct'),
               eligible_owner_profit_yoy=count('owner_profit_yoy_pct'),golden_cross_used=False,
               official_per_pbr_verified=0,final_buy_signals=0,
               continuation_notes=['Prior DART comparative cache is reused; missing records only are queried by upstream R14',
                'Archive grows by verified market date; same-day reruns replace rows rather than duplicating',
                'Archive includes all six-digit codes, not only current eligible set',
                'Growth coverage is informational; provisional grades are not final recommendations',
                'Golden cross excluded; no confirmed buy signal'])
 (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:status[k] for k in ('version','market_dates_archived','archive_rows','archive_rows_added','growth_cache_entries','eligible_rows','eligible_revenue_yoy','eligible_operating_profit_yoy','dart_calls','dart_errors')},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
