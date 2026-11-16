#!/usr/bin/env python3
"""Stage17 #9 lossless recovery. Standard library only; no DART calls."""
import argparse, collections, copy, datetime, hashlib, json, pathlib, zipfile

def load(path):
    return json.loads(path.read_text(encoding='utf-8'))
def dump(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(path)
def digest(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def comparable(entries):
    codes={k.split(':')[0] for k in entries if k.endswith((':2024',':2025'))}
    count=0; pairs=0
    for code in codes:
        a=(entries.get(code+':2025') or {}).get('filing') or {}
        b=(entries.get(code+':2024') or {}).get('filing') or {}
        if a and b:
            pairs+=1
            if a.get('fs_div')==b.get('fs_div') and not a.get('issues') and not b.get('issues'):
                count+=1
    return pairs,count

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--zip',required=True)
    p.add_argument('--data-dir',default='data')
    p.add_argument('--output-dir',default='stage17_recovery_output')
    p.add_argument('--expected-zip-success',type=int,default=1672)
    a=p.parse_args()
    data=pathlib.Path(a.data_dir);out=pathlib.Path(a.output_dir)
    target=data/'v5_stage15_annual_cache.json'
    if not target.is_file():raise SystemExit('STOP: existing main cache missing')
    before=load(target)
    with zipfile.ZipFile(a.zip) as z:
        if 'v5_stage15_annual_cache.json' not in z.namelist():raise SystemExit('STOP: annual cache absent from ZIP')
        incoming=json.loads(z.read('v5_stage15_annual_cache.json'))
    if before.get('schema')!=1 or incoming.get('schema')!=1:raise SystemExit('STOP: schema mismatch')
    old=before.get('entries');new=incoming.get('entries')
    if not isinstance(old,dict) or not isinstance(new,dict):raise SystemExit('STOP: entries missing')
    zip_success=sum(bool(v.get('filing')) for v in new.values())
    if zip_success!=a.expected_zip_success:raise SystemExit(f'STOP: ZIP success count {zip_success} unexpected')
    merged=copy.deepcopy(before); entries=merged['entries']
    added=[]; retained=[]; conflicting=[]; failure_added=[]
    for k,v in new.items():
        if not isinstance(v,dict):continue
        current=entries.get(k)
        if v.get('filing'):
            if not isinstance(current,dict) or not current.get('filing'):
                entries[k]=copy.deepcopy(v);added.append(k)
            elif digest(current['filing'])!=digest(v['filing']):
                # Keep main evidence and preserve alternate success evidence separately.
                conflicting.append({'key':k,'main':current,'zip':v})
            else:retained.append(k)
        elif k not in entries:
            entries[k]=copy.deepcopy(v);failure_added.append(k)
    lost=[k for k,v in old.items() if isinstance(v,dict) and v.get('filing') and not entries.get(k,{}).get('filing')]
    if lost:raise SystemExit('STOP: successful existing records lost')
    main_success=sum(bool(v.get('filing')) for v in old.values())
    final_success=sum(bool(v.get('filing')) for v in entries.values())
    if final_success<max(main_success,zip_success):raise SystemExit('STOP: success count decreased')
    by_year=collections.Counter(k.rsplit(':',1)[-1] for k,v in entries.items() if v.get('filing'))
    pairs,comps=comparable(entries)
    report={'generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'main_success_before':main_success,'zip_success':zip_success,'merged_success':final_success,
      'new_success_added':len(added),'existing_success_preserved':len(retained),
      'conflicting_success_records':len(conflicting),'failure_only_keys_added':len(failure_added),
      'successful_records_lost':len(lost),'year_success_counts':dict(by_year),
      'annual_pairs':pairs,'comparable_pairs_by_cache_basis':comps,
      'note':'Cache-only pair count; full Stage16 comparable count also applies universe/security filters.',
      'main_cache_sha256':digest(before),'zip_cache_sha256':digest(incoming),'merged_cache_sha256':digest(merged)}
    out.mkdir(parents=True,exist_ok=True)
    dump(out/'recovery_report.json',report)
    dump(out/'success_conflicts.json',conflicting)
    dump(out/'merged_annual_cache.json',merged)
    # Fail closed on conflicting successes: do not silently publish ambiguous records.
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if conflicting:raise SystemExit('STOP: conflicting successful filings require review; no main cache overwritten')
    dump(target,merged)
if __name__=='__main__':main()
