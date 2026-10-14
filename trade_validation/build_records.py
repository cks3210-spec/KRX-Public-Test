#!/usr/bin/env python3
"""Build a deduplicated V/G/VG daily candidate history.

One row per (snapshot_date, stock_code). Historical rows are preserved and
same-day source evidence is merged. This is NOT trade recommendation logic.
"""
import csv
import io
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
REPO = 'https://raw.githubusercontent.com/cks3210-spec/KRX-Public-Test/main/data/'
OUT = ROOT / 'candidate_history.csv'
FIELDS = ['record_id','snapshot_date','stock_code','stock_name','market',
          'source_group','v4_date','golden_date','golden_status','close',
          'market_cap','source_note']
MIN_CAP = 100_000_000_000

def fetch(name):
    with urllib.request.urlopen(REPO + name, timeout=25) as f:
        return f.read().decode('utf-8-sig')

def rows(txt):
    return list(csv.DictReader(io.StringIO(txt)))

def normdate(s):
    return ''.join(c for c in str(s or '') if c.isdigit())[:8]

def code(r):
    c = str(r.get('ISU_CD') or r.get('stock_code') or r.get('종목코드') or '').strip()
    return c.zfill(6) if c else ''

def num(s):
    try: return float(str(s or '0').replace(',',''))
    except ValueError: return 0.0

def classify(r):
    if r.get('v4_date') and r.get('golden_date'): return 'VG'
    if r.get('v4_date'): return 'V'
    return 'G'

def merge(old, new):
    """Merge source evidence without discarding earlier nonempty fields."""
    z = dict(old)
    for field in FIELDS:
        if field in ('record_id','source_group','source_note'): continue
        if not z.get(field) and new.get(field): z[field] = new[field]
    # More recent source snapshots are preferred for matching day/code.
    for field in ('stock_name','market','close','market_cap','golden_status'):
        if new.get(field): z[field] = new[field]
    z['source_note'] = old.get('source_note') or new.get('source_note') or ''
    z['source_group'] = classify(z)
    z['record_id'] = f"{z['snapshot_date']}-{z['stock_code']}-{z['source_group']}"
    return z

def main():
    golden = rows(fetch('golden_cross_candidates.csv'))
    if not golden: raise SystemExit('Golden candidate source empty: stopped')
    days = {normdate(r.get('BAS_DD')) for r in golden}
    if len(days) != 1 or not next(iter(days)):
        raise SystemExit('Golden candidate dates mixed/invalid: stopped')
    day = next(iter(days))

    # Daily v4 signal source; independent from weekly Colab A/B grades.
    v4 = rows(fetch('v4_indicators.csv'))
    if not v4:
        raise SystemExit('Daily v4 source empty: stopped (not zero candidates)')
    vdays = {normdate(r.get('BAS_DD')) for r in v4}
    if vdays != {day}:
        raise SystemExit(f'Daily v4 source date mismatch: golden={day}, v4={sorted(vdays)}')
    same_day = True
    vi = {code(r): r for r in v4
          if code(r) and str(r.get('V4_SCREEN','')).strip().lower() in ('true','1')}
    gi = {code(r):r for r in golden if code(r) and num(r.get('MKTCAP')) >= MIN_CAP}

    history = {}
    if OUT.exists():
        for r in csv.DictReader(OUT.open(encoding='utf-8-sig',newline='')):
            d, c = normdate(r.get('snapshot_date')), code(r)
            if not d or not c: continue
            r['snapshot_date'], r['stock_code'] = d, c
            # Recover evidence from legacy G and VG duplicate records.
            group = r.get('source_group','')
            if group in ('V','VG') and not r.get('v4_date'): r['v4_date'] = d
            if group in ('G','VG') and not r.get('golden_date'): r['golden_date'] = d
            k = (d,c)
            history[k] = merge(history[k],r) if k in history else r

    for c in sorted(set(gi) | set(vi)):
        a,b = gi.get(c),vi.get(c)
        # v4 file uses MKTCAP in KRW. Reject missing/undersized cap.
        if b and num(b.get('MKTCAP')) < MIN_CAP:
            b = None
        if not a and not b: continue
        src = a or b
        r = dict.fromkeys(FIELDS,'')
        r.update(snapshot_date=day,stock_code=c,
                 stock_name=src.get('ISU_NM',''),market=src.get('MARKET',''),
                 v4_date=day if b else '',golden_date=day if a else '',
                 golden_status=a.get('상태','') if a else '',
                 close=src.get('TDD_CLSPRC',''),market_cap=src.get('MKTCAP',''),
                 source_note='G is a technical candidate status, not an independently verified cross; V is daily V4_SCREEN, not weekly Colab A/B grade; common-share filter unverified')
        r['source_group'] = classify(r)
        r['record_id'] = f'{day}-{c}-{r["source_group"]}'
        k = (day,c)
        history[k] = merge(history[k],r) if k in history else r

    output = []
    for k in sorted(history):
        r = history[k]
        r['source_group'] = classify(r)
        r['record_id'] = f'{k[0]}-{k[1]}-{r["source_group"]}'
        output.append({f:r.get(f,'') for f in FIELDS})
    with OUT.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS)
        w.writeheader();w.writerows(output)
    current=[r for r in output if r['snapshot_date']==day]
    print(json.dumps({'snapshot_date':day,'total_unique_history':len(output),
                      'current_unique':len(current),
                      'V':sum(r['source_group']=='V' for r in current),
                      'G':sum(r['source_group']=='G' for r in current),
                      'VG':sum(r['source_group']=='VG' for r in current),
                      'v4_same_day':same_day},ensure_ascii=False))

if __name__ == '__main__': main()
