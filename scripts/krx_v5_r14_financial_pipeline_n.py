#!/usr/bin/env python3
"""R14 N: incremental OpenDART financial collection with conservative filing evidence.

The original financial cache is authoritative and is never relabelled as point-in-time
verified. Disclosure evidence is kept in a separate sidecar. No buy signals.
"""
import csv
import datetime as dt
import importlib.util
import json
import os
import pathlib
import re
import time

ROOT = pathlib.Path(os.getenv('GITHUB_WORKSPACE', '.')).resolve()
OUT = ROOT / 'data/v5_financial_m'
spec = importlib.util.spec_from_file_location('r14_m_existing', ROOT / 'scripts/krx_v5_r14_dart_incremental_m.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
LIMIT = max(1, min(250, int(os.getenv('M_BATCH_LIMIT', '80'))))
COOLDOWN_DAYS = max(1, int(os.getenv('R14_RETRY_DAYS', '7')))
EVIDENCE_LIMIT = max(0, min(200, int(os.getenv('R14_DISCLOSURE_BATCH_LIMIT', '30'))))
FIELDS = ['code','year','fs_div','annual_profit','equity','prior_equity','annual_roe_pct','source','ttm_profit','ttm_status']
EVIDENCE_FILE = OUT / 'dart_disclosure_evidence.json'

def valid(record):
    return isinstance(record, dict) and record.get('status') == '000' and bool(record.get('accounts'))

def retryable(record, now):
    return not valid(record) and (not isinstance(record, dict) or str(record.get('retry_after_utc','')) <= now.isoformat())

def qkind(market_date):
    d = dt.datetime.strptime(market_date, '%Y%m%d').date()
    if (d.month, d.day) >= (11, 15): return 'q3'
    if (d.month, d.day) >= (8, 14): return 'half'
    if (d.month, d.day) >= (5, 15): return 'q1'
    return None

def ttm(cache, code, annual_year, asof_year, kind):
    annual = cache.get(f'{code}:{annual_year}:annual', {})
    if not valid(annual): return None, 'NO_ANNUAL'
    if not kind: return None, 'NO_REPORT_DUE'
    current = cache.get(f'{code}:{asof_year}:{kind}', {})
    previous = cache.get(f'{code}:{annual_year}:{kind}', {})
    if not valid(current) or not valid(previous): return None, 'MISSING_QUARTER'
    if len({annual.get('fs_div'), current.get('fs_div'), previous.get('fs_div')}) != 1:
        return None, 'BASIS_MISMATCH'
    values = [annual['accounts'].get('profit'), current['accounts'].get('profit'), previous['accounts'].get('profit')]
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in values):
        return None, 'MISSING_PROFIT'
    return values[0] + values[1] - values[2], 'VERIFIED_CUMULATIVE'

def rebuild(cache, base, annual_year, asof_year, kind, market_date, metrics, evidence):
    rows = []
    complete = ttm_count = 0
    for row in base:
        code = row['code']
        entry = cache.get(f'{code}:{annual_year}:annual', {})
        accounts = entry.get('accounts', {}) if valid(entry) else {}
        profit, equity, previous_equity = (accounts.get(k) for k in ('profit','equity','previous_equity'))
        annual_roe = m.ratio(None, profit, equity, previous_equity)['roe_pct']
        ttm_profit, ttm_status = ttm(cache, code, annual_year, asof_year, kind)
        complete += bool(accounts)
        ttm_count += ttm_status == 'VERIFIED_CUMULATIVE'
        rows.append({'code':code,'year':annual_year,'fs_div':entry.get('fs_div','') if accounts else '',
            'annual_profit':profit if profit is not None else '',
            'equity':equity if equity is not None else '',
            'prior_equity':previous_equity if previous_equity is not None else '',
            'annual_roe_pct':annual_roe if annual_roe is not None else '',
            'source':'OpenDART fnlttSinglAcntAll' if accounts else 'UNVERIFIED',
            'ttm_profit':ttm_profit if ttm_profit is not None else '', 'ttm_status':ttm_status})
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT/'annual_financial_index_m.csv').open('w', encoding='utf-8-sig', newline='') as fp:
        writer = csv.DictWriter(fp, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    status = {'version':'R14_N_ANNUAL_QUARTER_TTM',
        'generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'market_date':market_date,'base_rows':len(base),'cache_records':len(cache),
        'fetched_this_run':metrics.get('fetched',0),'failed_this_run':metrics.get('failed',0),
        'api_rejected_this_run':metrics.get('rejected',0),'annual_verified_rows':complete,
        'batch_limit':LIMIT,'ttm_calculated':ttm_count,'ttm_period':kind or '',
        'financial_snapshot_date_source':metrics.get('date_source','EXISTING_FINANCIAL_STATUS'),
        'prior_financial_snapshot_date':metrics.get('prior_date',''),
        'financial_snapshot_date_changed':metrics.get('date_changed',False),
        'financial_disclosure_asof_verified':False,
        'point_in_time_financials_authorized':False,
        'disclosure_evidence_records':len(evidence),
        'disclosure_evidence_added_this_run':metrics.get('evidence_added',0),
        'disclosure_evidence_ambiguous_this_run':metrics.get('evidence_ambiguous',0),
        'disclosure_evidence_failed_this_run':metrics.get('evidence_failed',0),
        'unmapped_corp_codes':metrics.get('unmapped',0),
        'pending_annual':metrics.get('pending_annual',0),'pending_quarters':metrics.get('pending_quarters',0),
        'selected_annual':metrics.get('selected_annual',0),'selected_quarters':metrics.get('selected_quarters',0),
        'final_buy_signals':0,'golden_cross_used':False,'investment_decisions_authorized':False,
        'notes':['Disclosure receipt date is evidence only, not proof that cached financial values match that filing',
                 'Corrections and point-in-time versions require independent validation before any trading signals',
                 'Original verified financial cache is preserved; official PER/PBR still unverified']}
    m.save_json(OUT/'status.json', status)
    print(json.dumps(status, ensure_ascii=False, indent=2))

def disclosure_evidence(corp, year, report):
    """List official filings. Never assert a unique match if multiple filings exist."""
    start = f'{year}0101'
    end = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d')
    data = m.get_json('list.json', {'crtfc_key':m.KEY,'corp_code':corp,
        'bgn_de':start,'end_de':end,'page_count':'100','page_no':'1'})
    if data.get('status') != '000':
        return {'state':'API_UNVERIFIED','api_status':data.get('status','')}
    # OpenDART filing list may be paginated; do not infer completeness.
    if int(data.get('total_page',1)) != 1:
        return {'state':'PAGINATED_UNVERIFIED','total_page':data.get('total_page')}
    titles = {'annual':'사업보고서','q1':'분기보고서','half':'반기보고서','q3':'분기보고서'}
    expected = titles[report]
    matches = []
    for item in data.get('list', []):
        name = str(item.get('report_nm',''))
        if expected not in name or not re.search(r'\('+str(year)+r'\.',name):
            continue
        # A quarterly title must match the requested quarter, not just the year.
        if report == 'q1' and not re.search(r'\('+str(year)+r'\.03\)',name): continue
        if report == 'half' and not re.search(r'\('+str(year)+r'\.06\)',name): continue
        if report == 'q3' and not re.search(r'\('+str(year)+r'\.09\)',name): continue
        if report == 'annual' and not re.search(r'\('+str(year)+r'\.12\)',name): continue
        if not re.fullmatch(r'\d{8}',str(item.get('rcept_dt',''))): continue
        matches.append({'rcept_no':str(item.get('rcept_no','')),
            'rcept_dt':str(item['rcept_dt']),'report_nm':name})
    if not matches: return {'state':'FILING_NOT_FOUND'}
    # Even a single filing does not prove cached financial numbers came from it.
    return {'state':'FILING_CANDIDATES_FOUND','candidates':matches,
        'earliest_filing_date':min(v['rcept_dt'] for v in matches),
        'cached_values_matched_to_filing':False,'point_in_time_verified':False}

def main():
    rebuild_only = os.getenv('R14_REBUILD_ONLY') == '1'
    if not m.KEY and not rebuild_only: raise SystemExit('MISSING_DART_API_KEY')
    if not m.L.exists(): raise SystemExit('MISSING_L_INDEX')
    with m.L.open(encoding='utf-8-sig', newline='') as fp:
        base = list(csv.DictReader(fp))
    market_file = ROOT/'data/v5_investment_r14_research_k/full_market_ratios_k.csv'
    if market_file.exists():
        with market_file.open(encoding='utf-8-sig', newline='') as fp:
            market = list(csv.DictReader(fp))
        indexed = {r['code']:r for r in base}
        for row in market:
            code = str(row.get('ISU_CD','')).zfill(6)
            if code.isdigit() and code not in indexed:
                indexed[code] = {'code':code,'corp_code':''}
        base = list(indexed.values())
    cache = m.load_json(OUT/'dart_financial_cache.json', {})
    evidence = m.load_json(EVIDENCE_FILE, {})
    prior = m.load_json(OUT/'status.json', {})
    if rebuild_only:
        market_date = str(prior.get('market_date',''))
        date_source = 'EXISTING_FINANCIAL_STATUS'
    else:
        market_date = str(m.load_json(ROOT/'data/v5_investment_r14_research_k/status.json',{}).get('market_date',''))
        date_source = 'R14_RESEARCH_STATUS'
    if not re.fullmatch(r'\d{8}',market_date): raise SystemExit('INVALID_FINANCIAL_MARKET_DATE')
    try: dt.datetime.strptime(market_date,'%Y%m%d')
    except ValueError: raise SystemExit('INVALID_FINANCIAL_MARKET_DATE')
    previous_date = str(prior.get('market_date',''))
    if re.fullmatch(r'\d{8}',previous_date) and market_date < previous_date:
        raise SystemExit('BLOCKED_FINANCIAL_DATE_REGRESSION: prior='+previous_date+' candidate='+market_date)
    asof_year = int(market_date[:4])
    annual_year = asof_year - 1
    kind = qkind(market_date)
    metrics = {'fetched':0,'failed':0,'rejected':0,'date_source':date_source,
        'prior_date':previous_date,'date_changed':market_date!=previous_date,
        'evidence_added':0,'evidence_ambiguous':0,'evidence_failed':0}
    print('R14_DATE_AUDIT',json.dumps({'financial_snapshot_date':market_date,
        'previous_financial_snapshot_date':previous_date,'date_source':date_source,
        'official_krx_evaluation_date_verified_here':False,'disclosure_asof_verified':False}))
    if rebuild_only:
        rebuild(cache,base,annual_year,asof_year,kind,market_date,metrics,evidence)
        return
    mapping = m.corp_map()
    now = dt.datetime.now(dt.timezone.utc)
    annual, quarters = [], []
    unmapped = 0
    for row in base:
        code = row['code']
        corp = row.get('corp_code') or mapping.get(code)
        if not corp:
            unmapped += 1
            continue
        annual_key = f'{code}:{annual_year}:annual'
        annual_ok = valid(cache.get(annual_key))
        if not annual_ok and retryable(cache.get(annual_key),now):
            annual.append((code,corp,annual_year,'annual'))
        if kind and annual_ok:
            for year in (asof_year,annual_year):
                key = f'{code}:{year}:{kind}'
                if retryable(cache.get(key),now): quarters.append((code,corp,year,kind))
    selected = []
    ai = qi = 0
    while len(selected) < LIMIT and (ai < len(annual) or qi < len(quarters)):
        if ai < len(annual): selected.append(annual[ai]);ai += 1
        if len(selected) < LIMIT and qi < len(quarters): selected.append(quarters[qi]);qi += 1
    metrics.update(unmapped=unmapped,pending_annual=len(annual),pending_quarters=len(quarters),
        selected_annual=ai,selected_quarters=qi)
    print('R14_SELECTION',json.dumps({k:metrics[k] for k in ('unmapped','pending_annual','pending_quarters','selected_annual','selected_quarters')}))
    for code,corp,year,report in selected:
        key = f'{code}:{year}:{report}'
        try:
            record = m.request(corp,year,report)
            record.update(corp_code=corp,year=year,fetched_utc=dt.datetime.now(dt.timezone.utc).isoformat())
            if valid(record):
                cache[key] = record
                metrics['fetched'] += 1
            else:
                metrics['rejected'] += 1
                if not valid(cache.get(key)):
                    cache[key] = {'status':'UNVERIFIED','reason':record.get('status','UNKNOWN'),
                        'api_status':record.get('api_status'),'fetched_utc':now.isoformat(),
                        'retry_after_utc':(now+dt.timedelta(days=COOLDOWN_DAYS)).isoformat()}
        except Exception as exc:
            metrics['failed'] += 1
            print('FETCH_FAILED',key,type(exc).__name__,str(exc)[:150])
            if not valid(cache.get(key)):
                cache[key] = {'status':'FETCH_FAILED','fetched_utc':now.isoformat(),
                    'retry_after_utc':(now+dt.timedelta(days=1)).isoformat()}
        if sum(metrics[k] for k in ('fetched','failed','rejected')) % 10 == 0:
            m.save_json(OUT/'dart_financial_cache.json',cache)
        time.sleep(.13)
    m.save_json(OUT/'dart_financial_cache.json',cache)
    # Evidence enrichment is independent of financial fetching and preserves cache.
    checked = 0
    for key,record in cache.items():
        if checked >= EVIDENCE_LIMIT: break
        if not valid(record) or key in evidence: continue
        parts = key.split(':')
        if len(parts) != 3 or parts[2] not in m.REPORTS: continue
        code,year_text,report = parts
        if not year_text.isdigit(): continue
        corp = record.get('corp_code') or mapping.get(code)
        if not corp: continue
        try:
            result = disclosure_evidence(corp,int(year_text),report)
            result.update(corp_code=corp,financial_cache_key=key,
                checked_utc=dt.datetime.now(dt.timezone.utc).isoformat())
            evidence[key] = result
            metrics['evidence_added'] += 1
            metrics['evidence_ambiguous'] += result['state'] != 'FILING_CANDIDATES_FOUND' or len(result.get('candidates',[])) != 1
        except Exception as exc:
            metrics['evidence_failed'] += 1
            print('DISCLOSURE_EVIDENCE_FAILED',key,type(exc).__name__,str(exc)[:120])
        checked += 1
        time.sleep(.13)
    m.save_json(EVIDENCE_FILE,evidence)
    rebuild(cache,base,annual_year,asof_year,kind,market_date,metrics,evidence)

if __name__ == '__main__':
    main()
