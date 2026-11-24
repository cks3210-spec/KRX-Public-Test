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

# Stage 1-1: one authoritative KRX *market evaluation date* for both full
# collection and cache-only rebuilds. This is NOT a filing-effective date.
MARKET_SUMMARY = ROOT / 'data/summary.json'
MARKET_LATEST = ROOT / 'data/latest.csv'


def official_market_snapshot():
    """Fail closed unless the promoted KRX snapshot is internally consistent.

    A stale R14 research-grade status must never select the financial pipeline's
    market evaluation date. Official filing periods/versions remain separate.
    """
    try:
        summary = json.loads(MARKET_SUMMARY.read_text(encoding='utf-8-sig'))
        market_date = str(summary.get('latest_trading_date', '')).strip()
        if not re.fullmatch(r'20\d{6}', market_date):
            raise ValueError('MARKET_SUMMARY_DATE_MISSING_OR_INVALID')
        dt.datetime.strptime(market_date, '%Y%m%d')
        with MARKET_LATEST.open(encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            required = {'BAS_DD', 'ISU_CD', 'MARKET'}
            if not required.issubset(set(reader.fieldnames or [])):
                raise ValueError('MARKET_LATEST_REQUIRED_FIELDS_MISSING')
            count = 0
            kospi = kosdaq = 0
            identities = set()
            for row in reader:
                if str(row.get('BAS_DD', '')).strip() != market_date:
                    raise ValueError('MARKET_LATEST_DATE_MISMATCH')
                market = str(row.get('MARKET', '')).strip()
                code = str(row.get('ISU_CD', '')).strip()
                if market not in ('KOSPI', 'KOSDAQ') or not re.fullmatch(r'[0-9A-Z]{6}', code):
                    raise ValueError('MARKET_LATEST_INVALID_IDENTITY')
                key = market, code
                if key in identities:
                    raise ValueError('MARKET_LATEST_DUPLICATE_IDENTITY')
                identities.add(key)
                count += 1
                kospi += market == 'KOSPI'
                kosdaq += market == 'KOSDAQ'
    except (FileNotFoundError, IsADirectoryError) as exc:
        raise ValueError('OFFICIAL_MARKET_FILES_UNAVAILABLE') from exc
    if count < 2000 or kospi < 500 or kosdaq < 1000:
        raise ValueError('OFFICIAL_MARKET_COVERAGE_INSUFFICIENT')
    if (summary.get('kospi_rows_latest') != kospi or
            summary.get('kosdaq_rows_latest') != kosdaq):
        raise ValueError('OFFICIAL_MARKET_COUNTS_MISMATCH')
    return market_date, count

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
        'financial_snapshot_date_source':metrics.get('date_source','VALIDATED_OFFICIAL_KRX_SNAPSHOT'),
        'official_market_date':market_date,
        'official_market_source_rows':metrics.get('market_rows'),
        'market_evaluation_date_only_not_disclosure_date':True,
        'annual_financial_report_year':annual_year,
        'financial_reporting_period':kind or 'ANNUAL_ONLY',
        'financial_rebuild_only':metrics.get('rebuild_only',False),
        'prior_financial_snapshot_date':metrics.get('prior_date',''),
        'financial_snapshot_date_changed':metrics.get('date_changed',False),
        'financial_disclosure_asof_verified':False,
        'point_in_time_financials_authorized':False,
        'disclosure_evidence_records':len(evidence),
        'disclosure_evidence_added_this_run':metrics.get('evidence_added',0),
        'disclosure_evidence_ambiguous_this_run':metrics.get('evidence_ambiguous',0),
        'disclosure_evidence_failed_this_run':metrics.get('evidence_failed',0),
        'unmapped_corp_codes':metrics.get('unmapped'),
        'pending_annual':metrics.get('pending_annual'),'pending_quarters':metrics.get('pending_quarters'),
        'selected_annual':metrics.get('selected_annual'),'selected_quarters':metrics.get('selected_quarters'),
        'final_buy_signals':0,'golden_cross_used':False,'investment_decisions_authorized':False,
        'notes':['Disclosure receipt date is evidence only, not proof that cached financial values match that filing',
                 'Corrections and point-in-time versions require independent validation before any trading signals',
                 'Original verified financial cache is preserved; official PER/PBR still unverified']}
    m.save_json(OUT/'status.json', status)
    print(json.dumps(status, ensure_ascii=False, indent=2))

def disclosure_evidence(corp, year, report):
    """Read all filing-list pages conservatively; no financial-value PIT claims."""
    start = f'{year}0101'
    end = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d')
    max_pages = max(1, min(20, int(os.getenv('R14_DISCLOSURE_MAX_PAGES', '10'))))
    titles = {'annual':'사업보고서','q1':'분기보고서','half':'반기보고서','q3':'분기보고서'}
    month = {'annual':'12','q1':'03','half':'06','q3':'09'}[report]
    matches = {}
    total_pages = None
    for page in range(1, max_pages + 1):
        data = m.get_json('list.json', {'crtfc_key':m.KEY,'corp_code':corp,
            'bgn_de':start,'end_de':end,'page_count':'100','page_no':str(page)})
        if not isinstance(data,dict) or data.get('status') != '000':
            return {'state':'API_UNVERIFIED','api_status':data.get('status','') if isinstance(data,dict) else '',
                'pages_checked':page-1}
        try: pages = int(data['total_page'])
        except (KeyError,ValueError,TypeError):
            return {'state':'PAGINATION_METADATA_UNVERIFIED','pages_checked':page-1}
        if pages < 1 or (total_pages is not None and pages != total_pages):
            return {'state':'PAGINATION_METADATA_UNVERIFIED','pages_checked':page-1}
        total_pages = pages
        entries = data.get('list')
        if not isinstance(entries,list):
            return {'state':'PAGINATION_METADATA_UNVERIFIED','pages_checked':page-1}
        for item in entries:
            if not isinstance(item,dict): continue
            name = str(item.get('report_nm',''))
            if titles[report] not in name or not re.search(r'\('+str(year)+r'\.'+month+r'\)',name): continue
            receipt = str(item.get('rcept_no',''))
            filing_date = str(item.get('rcept_dt',''))
            if not re.fullmatch(r'\d{14}',receipt) or not re.fullmatch(r'\d{8}',filing_date): continue
            matches[receipt] = {'rcept_no':receipt,'rcept_dt':filing_date,'report_nm':name}
        if page >= total_pages: break
        time.sleep(.13)
    if total_pages is None or total_pages > max_pages:
        return {'state':'PAGINATED_UNVERIFIED','total_page':total_pages,
            'pages_checked':min(max_pages,total_pages or 0)}
    candidates = sorted(matches.values(),key=lambda x:(x['rcept_dt'],x['rcept_no']))
    if not candidates:
        return {'state':'FILING_NOT_FOUND','pages_checked':total_pages,'total_page':total_pages}
    return {'state':'FILING_CANDIDATES_FOUND','candidates':candidates,
        'earliest_filing_date':candidates[0]['rcept_dt'],
        'pages_checked':total_pages,'total_page':total_pages,
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
    # The same verified KRX date is required in both modes. A historical R14
    # research-status date (e.g. 20261116) is never a date authority.
    market_date, market_rows = official_market_snapshot()
    date_source = 'VALIDATED_OFFICIAL_KRX_MARKET_SNAPSHOT'
    if rebuild_only:
        date_source += '_REBUILD_ONLY'
    previous_date = str(prior.get('market_date',''))
    if re.fullmatch(r'\d{8}',previous_date) and market_date < previous_date:
        raise SystemExit('BLOCKED_FINANCIAL_DATE_REGRESSION: prior='+previous_date+' candidate='+market_date)
    asof_year = int(market_date[:4])
    annual_year = asof_year - 1
    kind = qkind(market_date)
    metrics = {'fetched':0,'failed':0,'rejected':0,'date_source':date_source,
        'prior_date':previous_date,'date_changed':market_date!=previous_date,
        'market_rows':market_rows,'rebuild_only':rebuild_only,
        'evidence_added':0,'evidence_ambiguous':0,'evidence_failed':0}
    if rebuild_only:
        # The workflow has just merged its current collection status. Keep
        # the actual batch counts instead of silently reporting zero work.
        copied = {'fetched':'fetched_this_run','failed':'failed_this_run',
                  'rejected':'api_rejected_this_run',
                  'evidence_added':'disclosure_evidence_added_this_run',
                  'evidence_ambiguous':'disclosure_evidence_ambiguous_this_run',
                  'evidence_failed':'disclosure_evidence_failed_this_run',
                  'unmapped':'unmapped_corp_codes',
                  'pending_annual':'pending_annual','pending_quarters':'pending_quarters',
                  'selected_annual':'selected_annual','selected_quarters':'selected_quarters'}
        metrics.update({target:prior.get(source) for target,source in copied.items()})
    print('R14_DATE_AUDIT',json.dumps({'official_market_date':market_date,
        'previous_financial_evaluation_date':previous_date,'date_source':date_source,
        'official_krx_market_snapshot_verified_here':True,
        'market_rows':market_rows,'disclosure_asof_verified':False}))
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
        if not valid(record): continue
        previous = evidence.get(key, {})
        if previous.get('state') == 'FILING_CANDIDATES_FOUND': continue
        # Retry incomplete evidence after a cooldown; avoid repeated API calls.
        last = str(previous.get('checked_utc',''))
        try: last_checked = dt.datetime.fromisoformat(last)
        except ValueError: last_checked = None
        if last_checked is not None and last_checked.tzinfo is not None and now - last_checked < dt.timedelta(days=1): continue
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
