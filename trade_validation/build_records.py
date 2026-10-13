#!/usr/bin/env python3
"""Conservative V/G/VG candidate snapshot builder; never creates trade recommendations."""
import csv, io, json, os, pathlib, urllib.request
from datetime import datetime, timezone
ROOT=pathlib.Path(__file__).resolve().parent
REPO='https://raw.githubusercontent.com/cks3210-spec/KRX-Public-Test/main/data/'
OUT=ROOT/'candidate_history.csv'
FIELDS=['record_id','snapshot_date','stock_code','stock_name','market','source_group','v4_date','golden_date','golden_status','close','market_cap','source_note']

def fetch(name):
    with urllib.request.urlopen(REPO+name,timeout=25) as f: return f.read().decode('utf-8-sig')
def rows(txt): return list(csv.DictReader(io.StringIO(txt)))
def normdate(s): return ''.join(c for c in str(s) if c.isdigit())[:8]
def code(r): return str(r.get('ISU_CD') or r.get('stock_code') or r.get('종목코드') or '').strip().zfill(6)
def read_local_v4():
    p=ROOT/'v4_candidates.csv'
    if not p.exists(): return [],'v4 file missing (G only; V/VG not assessed)'
    data=list(csv.DictReader(p.open(encoding='utf-8-sig',newline='')))
    return data,'v4 local snapshot supplied'
def main():
    try: g=rows(fetch('golden_cross_candidates.csv'))
    except Exception as e: raise SystemExit('No new records: golden source unavailable: '+str(e))
    if not g: raise SystemExit('No new records: golden source empty')
    dates={normdate(x.get('BAS_DD','')) for x in g}
    if len(dates)!=1 or not next(iter(dates)): raise SystemExit('Mixed/invalid golden snapshot dates; stopped')
    day=next(iter(dates))
    v,vnote=read_local_v4()
    vdates={normdate(x.get('BAS_DD') or x.get('date') or x.get('기준일') or '') for x in v}
    same_day=bool(v) and vdates=={day}
    if v and not same_day: print('V4 date differs from golden snapshot: no VG classification; V4 skipped')
    vi={code(x):x for x in v} if same_day else {}
    gi={code(x):x for x in g if code(x)!='000000' and float(x.get('MKTCAP') or 0)>=100_000_000_000}
    existing=[]
    if OUT.exists(): existing=list(csv.DictReader(OUT.open(encoding='utf-8-sig',newline='')))
    seen={x['record_id'] for x in existing}
    new=[]
    for c in sorted(set(gi)|set(vi)):
        a,b=gi.get(c),vi.get(c)
        if not a and b and float(b.get('MKTCAP') or b.get('시가총액') or 0)<100_000_000_000: continue
        r=a or b
        group='VG' if a and b else ('G' if a else 'V')
        rid=f'{day}-{c}-{group}'
        if rid in seen: continue
        new.append(dict(record_id=rid,snapshot_date=day,stock_code=c,stock_name=r.get('ISU_NM') or r.get('종목명') or '',market=r.get('MARKET') or r.get('시장') or '',source_group=group,v4_date=day if b else '',golden_date=day if a else '',golden_status=a.get('상태','') if a else '',close=r.get('TDD_CLSPRC') or r.get('종가') or '',market_cap=r.get('MKTCAP') or r.get('시가총액') or '',source_note='G is source candidate classification, NOT independently verified cross; common-share filter unverified; '+vnote))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with OUT.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(existing+new)
    print(json.dumps({'snapshot_date':day,'new_records':len(new),'V':sum(x['source_group']=='V' for x in new),'G':sum(x['source_group']=='G' for x in new),'VG':sum(x['source_group']=='VG' for x in new),'v4_same_day':same_day},ensure_ascii=False))
if __name__=='__main__':main()
