#!/usr/bin/env python3
"""KRX v5 R9: scheduled, incremental annual financial coverage. Research only.
Reads R7/R8 caches; writes ONLY data/v5_financial_r9. No final buy signals.
"""
import datetime as dt
import importlib.util
import json
import os
import pathlib
import re
from decimal import Decimal
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/v5_financial_r9'
NOW = dt.datetime.now(ZoneInfo('Asia/Seoul'))
R4_FILE = ROOT / 'scripts/krx_v5_fullmarket_research_r4_20261116.py'
spec = importlib.util.spec_from_file_location('r9_r4_helpers', R4_FILE)
r4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r4)


def load(path):
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'Expected JSON object: {path}')
    return value


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def complete(rec, year):
    return (isinstance(rec, dict) and rec.get('state') == 'FINANCIAL_FIELDS_FOUND'
            and str(rec.get('year')) == str(year) and rec.get('report') == '11011'
            and rec.get('fs_div') == 'CFS'
            and r4.num(rec.get('profit')) is not None
            and r4.num(rec.get('equity')) is not None)


def last_attempt_age(record):
    try:
        stamp = dt.datetime.fromisoformat(record['checked_at_kst'])
        return (NOW - stamp).total_seconds() / 86400
    except (KeyError, ValueError, TypeError):
        return 999999


def session_info():
    import exchange_calendars as xcals
    import pandas as pd
    cal = xcals.get_calendar('XKRX')
    today = pd.Timestamp(NOW.date().isoformat())
    if not cal.is_session(today):
        return None
    return cal.previous_session(today).strftime('%Y%m%d')


def roundval(value):
    return str(round(value, 3)) if value is not None else ''


def main():
    status = dict(version='R9', generated_kst=NOW.isoformat(), state='STARTED',
                  official_per_pbr_verified=0, final_grades=0, buy_signals=0)
    try:
        expected = session_info()
        if expected is None:
            status.update(state='SKIPPED_KRX_CLOSED', dart_api_calls=0)
            save(OUT / 'status.json', status)
            print(json.dumps(status, ensure_ascii=False, indent=2))
            return
        market = r4.readcsv(ROOT / 'data/latest.csv')
        dates = {row.get('BAS_DD', '') for row in market}
        if len(market) < 1500 or len(dates) != 1:
            raise RuntimeError(f'Stage60 market snapshot missing or inconsistent: dates={sorted(dates)[:3]}, rows={len(market)}')
        actual_date = next(iter(dates))
        if not re.fullmatch(r'\d{8}', actual_date) or actual_date > expected:
            raise RuntimeError(f'Invalid market snapshot date: expected<={expected}, actual={actual_date}')
        age_days = (dt.datetime.strptime(expected, '%Y%m%d') - dt.datetime.strptime(actual_date, '%Y%m%d')).days
        if age_days > 14:
            raise RuntimeError(f'Market universe too old even for financial collection: {actual_date}, age={age_days} days')
        stale_market = actual_date != expected
        if stale_market:
            print(f'WARNING: market snapshot {actual_date} is stale vs {expected}; financial collection only; no current-market inference')
        year = int(expected[:4]) - 1
        eligible = [m for m in market if (r4.num(m.get('MKTCAP')) or 0) >= Decimal('100000000000')
                    and re.fullmatch(r'\d{6}', m.get('ISU_CD', ''))]
        if len({m['ISU_CD'] for m in eligible}) != len(eligible):
            raise ValueError('Duplicate eligible stock codes')
        if not eligible:
            raise ValueError('No eligible stocks')

        annual_path = OUT / 'annual_financial_cache.json'
        attempts_path = OUT / 'request_attempts.json'
        annual = load(annual_path)
        attempts = load(attempts_path)
        imported = {'R7': 0, 'R8': 0}
        for label, path in (
            ('R7', ROOT / 'data/v5_financial_r7/annual_financial_cache.json'),
            ('R8', ROOT / 'data/v5_financial_r8/annual_financial_cache.json'),
        ):
            for code, rec in load(path).items():
                if complete(rec, year) and not complete(annual.get(code), year):
                    annual[code] = dict(rec)
                    imported[label] += 1

        # Keep imported records even if DART is temporarily down; fail rather than claim success.
        key = os.getenv('DART_API_KEY', '').strip()
        if not key:
            raise RuntimeError('DART_API_KEY secret missing')
        mapping = r4.corp_map(key)
        if not mapping:
            raise RuntimeError('DART corporation map unavailable')

        groups = {'KOSPI': [], 'KOSDAQ': [], 'OTHER': []}
        for m in eligible:
            group = m.get('MARKET', 'OTHER')
            groups[group if group in groups else 'OTHER'].append(m)
        for group in groups.values():
            group.sort(key=lambda m: m['ISU_CD'])
        ordered = []
        for i in range(max(map(len, groups.values()))):
            for group in ('KOSDAQ', 'KOSPI', 'OTHER'):
                if i < len(groups[group]):
                    ordered.append(groups[group][i])

        budget = max(0, min(300, int(os.getenv('DART_MAX_REQUESTS', '120'))))
        retry_days = max(1, int(os.getenv('R9_RETRY_DAYS', '7')))
        calls = updated = cooldown_skipped = unmapped = 0
        errors = []
        for m in ordered:
            if calls >= budget:
                break
            code = m['ISU_CD']
            if complete(annual.get(code), year):
                continue
            if code not in mapping:
                unmapped += 1
                continue
            attempt_key = f'{code}|{year}|11011'
            previous = attempts.get(attempt_key, {})
            wait_days = 1 if previous.get('outcome') == 'EXCEPTION' else retry_days
            if last_attempt_age(previous) < wait_days:
                cooldown_skipped += 1
                continue
            calls += 1
            attempt = {'checked_at_kst': NOW.isoformat(), 'market_date': expected, 'year': str(year)}
            try:
                rec = r4.financial(key, mapping[code], str(year), '11011')
                attempt['outcome'] = rec.get('state', 'UNKNOWN')
                if complete(rec, year):
                    rec.update(corp_code=mapping[code], checked_at_kst=NOW.isoformat(), asof_market_date=expected)
                    annual[code] = rec
                    updated += 1
                elif rec.get('state') not in ('NO_REPORT', 'PARTIAL'):
                    errors.append(f'{code}: {rec.get("state", "UNKNOWN")}')
            except Exception as exc:
                attempt['outcome'] = 'EXCEPTION'
                errors.append(f'{code}: {str(exc)[:160]}')
            attempts[attempt_key] = attempt
            if calls % 10 == 0:
                save(annual_path, annual)
                save(attempts_path, attempts)
        save(annual_path, annual)
        save(attempts_path, attempts)

        rows, watch = [], []
        breakdown = {}
        for m in eligible:
            code = m['ISU_CD']
            rec = annual.get(code, {})
            valid = complete(rec, year)
            cap = r4.num(m.get('MKTCAP'))
            profit = r4.num(rec.get('profit')) if valid else None
            equity = r4.num(rec.get('equity')) if valid else None
            liabilities = r4.num(rec.get('liabilities')) if valid else None
            pe = cap / profit if cap is not None and profit is not None and profit > 0 else None
            pb = cap / equity if cap is not None and equity is not None and equity > 0 else None
            roe = profit / equity * 100 if profit is not None and equity is not None and equity > 0 else None
            debt = liabilities / equity * 100 if liabilities is not None and equity is not None and equity > 0 else None
            grade = ''
            if all(x is not None for x in (pe, pb, roe, debt)):
                score = sum((roe >= 12, 0 < pe <= 18, 0 < pb <= Decimal('2.5'), debt <= 150))
                grade = 'A' if score == 4 else 'B+' if score == 3 else 'B' if score == 2 else ''
            row = dict(BAS_DD=expected, MARKET=m.get('MARKET', ''), ISU_CD=code,
                       ISU_NM=m.get('ISU_NM', ''), MKTCAP=m.get('MKTCAP', ''),
                       TDD_CLSPRC=m.get('TDD_CLSPRC', ''), annual_year=rec.get('year', ''),
                       annual_report=rec.get('report', ''), annual_state=rec.get('state', 'MISSING'),
                       reference_pe=roundval(pe), reference_pb=roundval(pb),
                       reference_roe_pct=roundval(roe), reference_debt_pct=roundval(debt),
                       provisional_grade=grade, official_per='', official_pbr='',
                       final_grade='WITHHELD', buy_signal='NONE',
                       flags='OFFICIAL_PER_PBR_UNVERIFIED;SHARE_CLASS_UNVERIFIED;SECTOR_NORMALIZATION_PENDING')
            rows.append(row)
            if grade:
                watch.append(row)
            b = breakdown.setdefault(m.get('MARKET', 'UNKNOWN'), dict(eligible=0, annual_complete=0, provisional_ab=0))
            b['eligible'] += 1
            b['annual_complete'] += int(valid)
            b['provisional_ab'] += int(bool(grade))
        r4.writecsv(OUT / 'full_market_annual_audit.csv', rows, list(rows[0]))
        r4.writecsv(OUT / 'provisional_ab_watchlist.csv', watch, list(rows[0]))
        covered = sum(b['annual_complete'] for b in breakdown.values())
        status.update(state='RESEARCH_ONLY_NOT_FINAL', market_date=actual_date,
                      expected_market_date=expected, market_snapshot_stale=stale_market,
                      market_rows=len(market), eligible_rows=len(eligible),
                      annual_complete_in_universe=covered, pending_annual=len(eligible)-covered,
                      annual_coverage_pct=round(100 * covered / len(eligible), 2),
                      annual_cache_entries=len(annual), imported_from_prior=imported,
                      new_annual_records=updated, dart_api_calls=calls,
                      cooldown_skipped=cooldown_skipped, unmapped_count=unmapped,
                      provisional_ab_count=len(watch), market_breakdown=breakdown,
                      error_count=len(errors), errors=errors[:40],
                      warnings=([f'STALE MARKET SNAPSHOT {actual_date}; no current price-based conclusions'] if stale_market else []) + ['Annual reference ratios are NOT official PER/PBR',
                                'Share class and sector normalization unverified',
                                'No final grades, fair values or actionable buy signals'])
        save(OUT / 'status.json', status)
        print(json.dumps(status, ensure_ascii=False, indent=2))
        # Partial API errors are visible in status, but no successful collection is falsely asserted.
        if errors and not updated and calls:
            raise RuntimeError('All requested DART reports failed or were unavailable; inspect status.json')
    except Exception as exc:
        status.update(state='FAILED', error=str(exc)[:500])
        save(OUT / 'status.json', status)
        raise


if __name__ == '__main__':
    main()
