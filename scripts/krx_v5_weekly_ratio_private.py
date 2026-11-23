#!/usr/bin/env python3
"""KRX v5: user-manual KRX CSV -> PRIVATE weekly reference -> daily research-only ratios.

No HTTP, scraping, API, credentials, git commands or automatic downloading.
Do NOT commit PRIVATE outputs to a public GitHub repository.  This is a
private-data research engine, not a provider-authentication or trading engine.

Examples:
  python krx_v5_weekly_ratio_private.py weekly --csv data_4341_20261123.csv \
    --as-of-date 20261120 --user-confirmed-date --private-dir /secure/my-ratios
  python krx_v5_weekly_ratio_private.py daily --snapshot \
    /secure/my-ratios/weekly_20261120.private.json --market-csv latest.csv \
    --private-dir /secure/my-ratios
  python krx_v5_weekly_ratio_private.py --self-test
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile

VERSION = 'KRX_V5_STAGE58_WEEKLY_PRIVATE_RESEARCH_V1'
CODE = re.compile(r'^[0-9A-Z]{6}$')
DATE = re.compile(r'^20[0-9]{6}$')
WEEKLY_REQUIRED = ('종목코드', '종목명', '종가', 'EPS', 'PER', 'BPS', 'PBR')
MARKET_REQUIRED = ('BAS_DD', 'ISU_CD', 'TDD_CLSPRC')
Q = Decimal('0.01')


def require(cond: bool, message: str) -> None:
    if not cond:
        raise ValueError('KRX_PRIVATE_RATIO_' + message)


def day8(value: str) -> dt.date:
    require(isinstance(value, str) and DATE.fullmatch(value) is not None, 'BAD_DATE_FORMAT')
    try:
        return dt.datetime.strptime(value, '%Y%m%d').date()
    except ValueError as e:
        raise ValueError('KRX_PRIVATE_RATIO_INVALID_DATE') from e


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_csv(path: Path) -> tuple[list[dict], str]:
    raw = path.read_bytes()
    for encoding in ('utf-8-sig', 'cp949', 'euc-kr'):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError('KRX_PRIVATE_RATIO_UNSUPPORTED_ENCODING')
    reader = csv.DictReader(io.StringIO(decoded))
    require(reader.fieldnames is not None, 'MISSING_CSV_HEADER')
    result = list(reader)
    require(len(result) > 0, 'EMPTY_CSV')
    return result, sha_bytes(raw)


def dec(raw: object) -> Decimal | None:
    s = str(raw or '').strip().replace(',', '')
    if s in ('', '-', '--', 'N/A', 'nan', 'NaN'):
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError('KRX_PRIVATE_RATIO_INVALID_NUMERIC')
    require(d.is_finite(), 'NONFINITE_NUMERIC')
    return d


def code6(raw: object) -> str:
    s = str(raw or '').strip().upper()
    if re.fullmatch(r'A[0-9]{6}', s):
        s = s[1:]
    return s


def ensure_private_dir(root: Path) -> Path:
    path = root.expanduser().resolve()
    # Check all parents for a Git checkout; prohibit any private data in it.
    for parent in (path, *path.parents):
        if (parent / '.git').exists():
            raise ValueError('KRX_PRIVATE_RATIO_OUTPUT_INSIDE_GIT_REPOSITORY_FORBIDDEN')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def private_write(path: Path, data: object) -> str:
    encoded = (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    if path.exists():
        require(path.read_bytes() == encoded, 'IMMUTABLE_OUTPUT_CONFLICT_' + path.name)
        return 'already_verified_identical'
    with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent, prefix='.ratio_', delete=False) as f:
        temporary = Path(f.name)
        os.chmod(temporary, 0o600)
        f.write(encoded)
    try:
        if path.exists():
            require(path.read_bytes() == encoded, 'IMMUTABLE_OUTPUT_CONFLICT_' + path.name)
            return 'already_verified_identical'
        temporary.replace(path)
        os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
    return 'created'


def validate_research(path: Path, date: str, records: dict[str, dict]) -> dict:
    research = json.loads(path.read_text(encoding='utf-8-sig'))
    require(research.get('research_market_date', research.get('market_date')) == date,
            'RESEARCH_DATE_MISMATCH')
    candidates = research.get('candidates')
    require(isinstance(candidates, list), 'RESEARCH_CANDIDATES_MISSING')
    codes = [code6(c.get('code')) for c in candidates]
    require(len(set(codes)) == len(codes), 'DUPLICATE_RESEARCH_CODES')
    require(set(codes).issubset(records), 'RESEARCH_CODE_MISSING_FROM_KRX_EXPORT')
    mismatches = []
    available = 0
    for c in candidates:
        code = code6(c.get('code'))
        recorded = dec(c.get('close_krw', c.get('close')))
        krx_close = dec(records[code]['close_krw'])
        if recorded is not None and recorded != krx_close:
            mismatches.append(code)
        if records[code]['per'] is not None and records[code]['pbr'] is not None:
            available += 1
    require(not mismatches, 'CANDIDATE_CLOSE_MISMATCH')
    return {'research_candidate_count': len(codes),
            'matched_candidate_closes': len(codes),
            'candidate_per_pbr_both_available': available}


def weekly(csv_path: Path, asof: str, confirmed: bool, private_dir: Path,
           research: Path | None = None) -> tuple[dict, Path]:
    day8(asof)
    require(confirmed, 'MANUAL_KRX_DATE_CONFIRMATION_REQUIRED')
    rows, digest = load_csv(csv_path)
    require(all(col in rows[0] for col in WEEKLY_REQUIRED), 'WEEKLY_COLUMNS_MISSING')
    codes = {}
    counts = {'per_present': 0, 'pbr_present': 0, 'both_present': 0,
              'per_arithmetic_checked': 0, 'pbr_arithmetic_checked': 0,
              'per_arithmetic_discrepancies': 0, 'pbr_arithmetic_discrepancies': 0}
    for row in rows:
        code = code6(row['종목코드'])
        require(CODE.fullmatch(code) is not None, 'INVALID_CODE')
        require(code not in codes, 'DUPLICATE_CODE')
        close = dec(row['종가']); per = dec(row['PER']); pbr = dec(row['PBR'])
        eps = dec(row['EPS']); bps = dec(row['BPS'])
        require(close is not None and close > 0, 'CLOSE_INVALID')
        if per is not None:
            require(per > 0, 'PER_NONPOSITIVE')
            counts['per_present'] += 1
        if pbr is not None:
            require(pbr > 0, 'PBR_NONPOSITIVE')
            counts['pbr_present'] += 1
        if per is not None and pbr is not None:
            counts['both_present'] += 1
        if eps is not None and eps > 0 and per is not None:
            counts['per_arithmetic_checked'] += 1
            if abs((close / eps) - per) > Decimal('0.025'):
                counts['per_arithmetic_discrepancies'] += 1
        if bps is not None and bps > 0 and pbr is not None:
            counts['pbr_arithmetic_checked'] += 1
            if abs((close / bps) - pbr) > Decimal('0.025'):
                counts['pbr_arithmetic_discrepancies'] += 1
        codes[code] = {'code': code, 'name': str(row['종목명']),
                       'close_krw': str(close), 'per': str(per) if per is not None else None,
                       'pbr': str(pbr) if pbr is not None else None,
                       'eps': str(eps) if eps is not None else None,
                       'bps': str(bps) if bps is not None else None}
    root = ensure_private_dir(private_dir)
    check = validate_research(research, asof, codes) if research else {}
    snapshot = {
        'version': VERSION, 'data_date_user_confirmed': asof,
        'provider_date_independently_attested': False,
        'provider_origin_independently_authenticated': False,
        'official_per_pbr_certified_count': 0,
        'source_type': 'USER_DOWNLOADED_KRX_ATTRIBUTED_FILE_FOR_PRIVATE_RESEARCH',
        'original_csv_sha256': digest,
        'row_count': len(codes), 'counts': counts, 'research_check': check,
        'investment_decisions_authorized': False, 'final_buy_signals': 0,
        'records': codes,
    }
    snapshot_path = root / ('weekly_' + asof + '.private.json')
    status = private_write(snapshot_path, snapshot)
    summary = {
        'version': VERSION, 'date_user_confirmed': asof,
        'provider_date_independently_attested': False,
        'provider_origin_independently_authenticated': False,
        'row_count': len(codes), 'original_csv_sha256': digest,
        'counts': counts, 'research_check': check,
        'raw_per_stock_ratios_released': False,
        'official_per_pbr_certified_count': 0,
        'final_buy_signals': 0,
        'manual_collection_only': True,
        'private_snapshot_state': 'PRIVATE_ONLY_IMMUTABLE',
        'publication_warning': 'Do not commit the raw CSV, private snapshot, or stock-level derived values to public GitHub.'
    }
    private_write(root / ('weekly_' + asof + '.summary.json'), summary)
    return summary, snapshot_path


def daily(snapshot_path: Path, market_csv: Path, private_dir: Path,
          max_age_days: int = 10) -> tuple[dict, Path]:
    require(0 <= max_age_days <= 365, 'BAD_MAX_AGE_DAYS')
    snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
    asof = snapshot.get('data_date_user_confirmed')
    baseline = day8(asof)
    require(snapshot.get('version') == VERSION and
            snapshot.get('investment_decisions_authorized') is False and
            snapshot.get('final_buy_signals') == 0, 'UNTRUSTED_WEEKLY_SNAPSHOT')
    rows, digest = load_csv(market_csv)
    require(all(x in rows[0] for x in MARKET_REQUIRED), 'MARKET_COLUMNS_MISSING')
    dates = {str(r['BAS_DD']).strip() for r in rows}
    require(len(dates) == 1, 'MARKET_MIXED_DATES')
    market_day = dates.pop()
    target = day8(market_day)
    require(target >= baseline, 'DAILY_BEFORE_WEEKLY_REFERENCE')
    age = (target - baseline).days
    stale = age > max_age_days
    market_by_code = {}
    for r in rows:
        code = code6(r['ISU_CD'])
        require(CODE.fullmatch(code) is not None and code not in market_by_code,
                'MARKET_INVALID_OR_DUPLICATE_CODE')
        price = dec(r['TDD_CLSPRC'])
        require(price is not None and price > 0, 'MARKET_PRICE_INVALID')
        market_by_code[code] = price
    out = []
    available_per = available_pbr = matched = 0
    for code, record in sorted(snapshot['records'].items()):
        price = market_by_code.get(code)
        if price is None:
            continue
        matched += 1
        reference_close = dec(record['close_krw'])
        per = dec(record['per']); pbr = dec(record['pbr'])
        require(reference_close is not None and reference_close > 0,
                'REFERENCE_CLOSE_INVALID')
        # Price adjustment only, holding the manual reference EPS/BPS basis fixed.
        estimated_per = ((per * price / reference_close).quantize(Q, rounding=ROUND_HALF_UP)
                         if per is not None else None)
        estimated_pbr = ((pbr * price / reference_close).quantize(Q, rounding=ROUND_HALF_UP)
                         if pbr is not None else None)
        available_per += estimated_per is not None
        available_pbr += estimated_pbr is not None
        out.append({'code': code, 'market_date': market_day,
                    'market_close_krw': str(price),
                    'indicative_derived_per': str(estimated_per) if estimated_per is not None else None,
                    'indicative_derived_pbr': str(estimated_pbr) if estimated_pbr is not None else None,
                    'reference_date_user_confirmed': asof,
                    'state': 'STALE_REFERENCE_RECHECK' if stale else
                             'INDICATIVE_DERIVED_RESEARCH_ONLY',
                    'official_ratio': False,
                    'investment_decisions_authorized': False})
    root = ensure_private_dir(private_dir)
    report = {'version': VERSION, 'market_date': market_day,
              'weekly_reference_date_user_confirmed': asof,
              'reference_age_calendar_days': age, 'stale_reference': stale,
              'stock_matches': matched, 'derived_per_available': available_per,
              'derived_pbr_available': available_pbr,
              'daily_market_csv_sha256': digest,
              'weekly_csv_sha256': snapshot['original_csv_sha256'],
              'official_per_pbr_certified_count': 0,
              'final_buy_signals': 0, 'real_time_price_verified': False,
              'research_only': True,
              'warning': 'Derived ratios hold the weekly EPS/BPS basis fixed; stale after company filings or age limit.',
              'per_stock_records': out}
    output = root / ('daily_' + market_day + '_from_' + asof + '.private.json')
    private_write(output, report)
    aggregate = {k: v for k, v in report.items() if k != 'per_stock_records'}
    aggregate['per_stock_ratios_released'] = False
    private_write(root / ('daily_' + market_day + '_from_' + asof + '.summary.json'), aggregate)
    return aggregate, output


def self_test() -> dict:
    with tempfile.TemporaryDirectory(prefix='krx_private_ratio_') as t:
        root = Path(t)
        file = root / 'upload.csv'
        file.write_bytes(('종목코드,종목명,종가,EPS,PER,BPS,PBR\n'
                          '"000270",기아,100000,10000,10,50000,2\n'
                          '"000050",경방,8000,1000,8,4000,2\n').encode('cp949'))
        research = root / 'research.json'
        research.write_text(json.dumps({'research_market_date': '20261120',
                    'candidates': [{'code':'000270','close_krw':'100000'}]}), encoding='utf-8')
        summary,snapshot = weekly(file,'20261120',True,root/'private',research)
        assert summary['row_count'] == 2
        assert summary['research_check']['matched_candidate_closes'] == 1
        assert summary['counts']['both_present'] == 2
        _, same = weekly(file,'20261120',True,root/'private',research)
        assert same == snapshot
        prices = root/'market.csv'
        prices.write_text('BAS_DD,ISU_CD,TDD_CLSPRC\n20261123,000270,110000\n20261123,000050,8000\n')
        day, path = daily(snapshot,prices,root/'private')
        derived = json.loads(path.read_text())
        a = next(x for x in derived['per_stock_records'] if x['code']=='000270')
        assert a['indicative_derived_per'] == '11.00' and a['indicative_derived_pbr']=='2.20'
        assert day['official_per_pbr_certified_count']==0 and day['final_buy_signals']==0
        assert 'per_stock_records' not in day
        assert (root/'private'/'weekly_20261120.summary.json').is_file()
        assert not (root/'private'/'weekly_20261120.summary.json').read_text().find('"per": "10"')>=0
        try:
            daily(snapshot,prices,root/'private',max_age_days=1)
        except ValueError as exc:
            assert 'IMMUTABLE_OUTPUT_CONFLICT' in str(exc)
        else:
            raise AssertionError('Changed-policy conflicting report was overwritten')
        bad=root/'bad.csv'
        bad.write_text('BAS_DD,ISU_CD,TDD_CLSPRC\n20261121,000270,111000\n20261122,000050,8000\n')
        try:daily(snapshot,bad,root/'private')
        except ValueError as exc:assert 'MIXED_DATES' in str(exc)
        else:raise AssertionError('Mixed-day input accepted')
    return {'status': 'PASS',
            'includes': ['cp949', 'asof validation', 'immutable archive', 'code match',
                         'private values', 'published summary without stock ratios',
                         'daily price recalculation', 'stale gate', 'mixed date rejection']}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--self-test', action='store_true')
    subs = p.add_subparsers(dest='command')
    w = subs.add_parser('weekly', help='Analyze manually downloaded KRX CSV locally and privately')
    w.add_argument('--csv', required=True, type=Path)
    w.add_argument('--as-of-date', required=True)
    w.add_argument('--user-confirmed-date', action='store_true', required=True)
    w.add_argument('--private-dir', type=Path, required=True)
    w.add_argument('--research', type=Path, help='Optional research candidate JSON for price agreement')
    d = subs.add_parser('daily', help='Recalculate INDICATIVE non-official ratios using close prices')
    d.add_argument('--snapshot', required=True, type=Path)
    d.add_argument('--market-csv', required=True, type=Path)
    d.add_argument('--private-dir', required=True, type=Path)
    d.add_argument('--max-age-days', type=int, default=10)
    args = p.parse_args()
    if args.self_test:
        print(json.dumps(self_test(),ensure_ascii=False))
    elif args.command=='weekly':
        result, _ = weekly(args.csv,args.as_of_date,args.user_confirmed_date,args.private_dir,args.research)
        print(json.dumps(result, ensure_ascii=False,indent=2))
    elif args.command=='daily':
        result, _ = daily(args.snapshot,args.market_csv,args.private_dir,args.max_age_days)
        print(json.dumps(result, ensure_ascii=False,indent=2))
    else:
        p.print_help()

if __name__ == '__main__':
    main()
