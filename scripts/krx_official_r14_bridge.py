#!/usr/bin/env python3
"""Read-only official KRX snapshot bridge. Never overwrites production files."""
import argparse,csv,json,pathlib,re,sys
from collections import Counter

def readcsv(path):
    with open(path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def integer(x):
    s=str(x or '').replace(',','').strip()
    return int(s) if s.isdigit() else None

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--official',required=True);p.add_argument('--status',required=True)
    p.add_argument('--existing',required=True);p.add_argument('--out',default='bridge_output')
    a=p.parse_args();out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=True)
    status=json.loads(pathlib.Path(a.status).read_text(encoding='utf-8-sig'))
    rows=readcsv(a.official);old=readcsv(a.existing)
    issues=[];date=status.get('market_date')
    if status.get('state')!='VERIFIED_OFFICIAL_MARKET_SNAPSHOT':issues.append('OFFICIAL_STATUS_NOT_VERIFIED')
    if not re.fullmatch(r'20\d{6}',str(date or '')):issues.append('INVALID_MARKET_DATE')
    if not rows:issues.append('EMPTY_OFFICIAL_FILE')
    required={'BAS_DD','MARKET','ISU_CD','ISU_NM','TDD_CLSPRC','MKTCAP'}
    if rows and not required.issubset(rows[0]):issues.append('MISSING_OFFICIAL_COLUMNS')
    keys=[];valid=[]
    for r in rows:
        code=r.get('ISU_CD','');market=r.get('MARKET','');close=integer(r.get('TDD_CLSPRC'));cap=integer(r.get('MKTCAP'))
        if r.get('BAS_DD')!=date or market not in ('KOSPI','KOSDAQ') or not re.fullmatch(r'\d{6}',code) or not close or not cap:
            issues.append('INVALID_OFFICIAL_ROW');continue
        keys.append((market,code));valid.append(r)
    if len(keys)!=len(set(keys)):issues.append('DUPLICATE_OFFICIAL_KEY')
    counts=Counter(r['MARKET'] for r in valid)
    if counts['KOSPI']<100 or counts['KOSDAQ']<100:issues.append('INCOMPLETE_MARKET_COVERAGE')
    existing={(r.get('MARKET'),r.get('ISU_CD')):r for r in old}
    same_date={k:r for k,r in existing.items() if r.get('BAS_DD')==date}
    fresh=bool(same_date)
    # Existing price/volume are not transferable across dates; never fabricate volume.
    output=[]
    for r in valid:
        key=(r['MARKET'],r['ISU_CD']);prev=same_date.get(key,{})
        output.append({'BAS_DD':date,'ISU_CD':r['ISU_CD'],'ISU_NM':r['ISU_NM'],
          'TDD_CLSPRC':r['TDD_CLSPRC'],'ACC_TRDVOL':prev.get('ACC_TRDVOL',''),
          'MKTCAP':r['MKTCAP'],'MARKET':r['MARKET'],
          'price_cap_source':'KRX_OPEN_API','volume_source':'SAME_DATE_EXISTING' if integer(prev.get('ACC_TRDVOL')) is not None else 'UNVERIFIED',
          'official_per_verified':'false','official_pbr_verified':'false'})
    report={'state':'BLOCKED' if issues else 'RESEARCH_BRIDGE_READY','market_date':date,
       'official_rows':len(rows),'validated_rows':len(valid),'market_counts':dict(counts),
       'existing_rows':len(old),'existing_same_date_rows':len(same_date),
       'official_only_keys':len(set(keys)-set(existing)),
       'existing_only_keys':len(set(existing)-set(keys)),
       'volume_verified_same_date':sum(r['volume_source']=='SAME_DATE_EXISTING' for r in output),
       'volume_unverified':sum(r['volume_source']=='UNVERIFIED' for r in output),
       'issues':sorted(set(issues)),'production_modified':False,
       'official_per_pbr_verified':False,'investment_decisions_authorized':False,
       'note':'Separate research bridge only. Do not replace data/latest.csv. Market cap and close from official snapshot; volume only from same-date existing source.'}
    (out/'status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if not issues:
        with (out/'r14_market_bridge.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(output[0]));w.writeheader();w.writerows(output)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if not issues else 2
if __name__=='__main__':sys.exit(main())
