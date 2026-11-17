#!/usr/bin/env python3
"""Read-only discovery of actual dated close records; merge into a separate R14 archive.
No golden-cross calculations, no DART calls, no synthetic historical prices.
"""
import csv, datetime as dt, json, pathlib, re
from collections import defaultdict
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
OUT=DATA/'v5_investment_r14_history_link'
BASE=DATA/'v5_investment_r14_fundamental'/'daily_close_archive.csv'
DATE=('BAS_DD','TRD_DD','TRADE_DATE','trade_date','date','Date','날짜')
CODE=('ISU_CD','ISU_SRT_CD','ISU_CODE','stock_code','code','종목코드')
PRICE=('TDD_CLSPRC','CLSPRC','close','CLOSE','Close','종가')
VOL=('ACC_TRDVOL','volume','VOLUME','거래량')
def field(names,options):
 return next((x for x in options if x in names),None)
def clean_day(x):
 s=str(x or '').strip().replace('-','').replace('/','')
 if not re.fullmatch(r'20\d{6}',s):return None
 try:
  d=dt.datetime.strptime(s,'%Y%m%d').date()
  if d>dt.datetime.now(ZoneInfo('Asia/Seoul')).date():return None
  return s
 except ValueError:return None
def clean_code(x):
 s=str(x or '').strip()
 if re.fullmatch(r'\d{6}',s):return s
 if re.fullmatch(r'A\d{6}',s):return s[1:]
 return None
def clean_num(x):
 try:
  v=float(str(x or '').replace(',','').strip())
  if 0<v<1e10:return str(int(v)) if v.is_integer() else str(v)
 except (ValueError,TypeError,OverflowError):pass
 return None
def sources():
 # Restrict to data directory, avoiding reimport of this script's own output.
 for p in DATA.rglob('*.csv'):
  if OUT in p.parents:continue
  try:
   with p.open(encoding='utf-8-sig',newline='') as f:
    r=csv.DictReader(f);cols=r.fieldnames or []
   if field(cols,DATE) and field(cols,CODE) and field(cols,PRICE):yield p
  except (OSError,UnicodeError,csv.Error):continue
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 archive={}; provenance={}; reports=[]
 for p in sources():
  with p.open(encoding='utf-8-sig',newline='') as f:
   reader=csv.DictReader(f);cols=reader.fieldnames or []
   dc,cc,pc,vc=(field(cols,options) for options in (DATE,CODE,PRICE,VOL))
   rows=[];days=set();invalid=0
   for row in reader:
    day=clean_day(row.get(dc));code=clean_code(row.get(cc));price=clean_num(row.get(pc))
    if not (day and code and price):invalid+=1;continue
    vol=(row.get(vc,'') if vc else '')
    rows.append((day,code,price,vol));days.add(day)
  # Snapshot files are allowed; only real dated rows, never MA-derived estimates.
  added=0
  for day,code,price,vol in rows:
   key=(day,code)
   # Prefer raw daily prices over precomputed indicators when duplicate dates exist.
   priority=(2 if 'daily' in p.name.lower() or 'history' in p.name.lower() else 1)
   if key not in archive or priority>provenance[key][0]:
    archive[key]={'BAS_DD':day,'ISU_CD':code,'close':price,'volume':vol,'source_path':str(p.relative_to(ROOT))}
    provenance[key]=(priority,str(p.relative_to(ROOT)));added+=1
  reports.append({'source':str(p.relative_to(ROOT)),'valid_rows':len(rows),'invalid_rows':invalid,'distinct_dates':len(days),'first_date':min(days) if days else None,'last_date':max(days) if days else None,'merged_rows':added})
 target=OUT/'daily_close_archive_linked.csv'
 fields=['BAS_DD','ISU_CD','close','volume','source_path']
 with target.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
  for key in sorted(archive):w.writerow(archive[key])
 dates=sorted({d for d,_ in archive});counts=defaultdict(int)
 for d,c in archive:counts[d]+=1
 status={'version':'R14_HISTORY_LINK_F','generated_kst':dt.datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
         'state':'HISTORY_LINKED' if len(dates)>=20 else 'INSUFFICIENT_HISTORY',
         'source_files':reports,'distinct_trading_dates':len(dates),'rows':len(archive),
         'first_date':dates[0] if dates else None,'last_date':dates[-1] if dates else None,
         'rows_per_date':dict(sorted(counts.items())),'golden_cross_used':False,
         'existing_r14_archive_untouched':True,'market_latest_untouched':True,
         'note':'Real dated closing prices only; no fabricated dates, golden cross, or investment signals.'}
 (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:status[k] for k in ('state','distinct_trading_dates','rows','first_date','last_date')},ensure_ascii=False))
if __name__=='__main__':main()
