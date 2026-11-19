#!/usr/bin/env python3
"""R14 read-only A/B research grading and illustrative entry-price estimates.

Does not modify caches, certify filing dates, or authorize investment decisions.
"""
import argparse
import csv
import json
import math
import pathlib
import re

MIN_CAP = 100_000_000_000
ROOT = pathlib.Path(__file__).resolve().parents[1]


def num(x):
    try:
        if x is None or str(x).strip() == '':
            return None
        n = float(str(x).replace(',', ''))
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def read_json(path):
    try:
        with open(path, encoding='utf-8-sig') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def normalize_code(code):
    code = str(code or '').strip()
    return code.zfill(6) if re.fullmatch(r'[0-9]{1,6}', code) else ''


def grade(fin, market):
    cap = num(market.get('market_cap_krw'))
    p, t = num(fin.get('annual_profit')), num(fin.get('ttm_profit'))
    eq, prev = num(fin.get('equity')), num(fin.get('prior_equity'))
    assets, liabilities = num(market.get('assets_krw')), num(market.get('liabilities_krw'))
    if cap is None or cap < MIN_CAP:
        return None, 'MARKET_CAP_MISSING_OR_BELOW_100B'
    if fin.get('source') != 'OpenDART fnlttSinglAcntAll':
        return None, 'UNVERIFIED_FINANCIALS'
    if fin.get('ttm_status') != 'VERIFIED_CUMULATIVE':
        return None, 'TTM_UNVERIFIED'
    if None in (p, t, eq, prev) or eq <= 0 or prev <= 0:
        return None, 'INSUFFICIENT_EQUITY_OR_PROFIT'
    if assets is None or liabilities is None or assets <= 0 or liabilities < 0:
        return None, 'BALANCE_SHEET_NOT_VERIFIED'
    if p <= 0 or t <= 0:
        return None, 'NON_POSITIVE_EARNINGS'
    roe = 100 * p / ((eq + prev) / 2)
    debt = 100 * liabilities / eq
    per, pbr = cap / t, cap / eq
    score = (25 if roe >= 12 else 15 if roe >= 8 else 0)
    score += (25 if debt <= 80 else 15 if debt <= 150 else 0)
    score += (25 if t >= p else 15 if t >= p * .85 else 0)
    score += (25 if per <= 12 and pbr <= 1.5 else 15 if per <= 20 and pbr <= 3 else 0)
    result = 'A' if score >= 85 else 'B' if score >= 65 else None
    if not result:
        return None, 'BELOW_B'
    return {'grade': result, 'score': score, 'roe_pct': round(roe, 2),
            'debt_pct': round(debt, 2), 'ttm_per_est': round(per, 2),
            'pbr_est': round(pbr, 2), 'ttm_to_annual': round(t / p, 3),
            'valuation_basis': 'derived, NOT official KRX PER/PBR',
            'buy_signal': False}, 'CANDIDATE'


def market_index(rows):
    result = {}
    dates = set()
    for row in rows:
        code = normalize_code(row.get('ISU_CD'))
        date = str(row.get('BAS_DD', '')).strip()
        if not code or not re.fullmatch(r'\d{8}', date):
            continue
        dates.add(date)
        result[code] = {'code': code, 'name': row.get('ISU_NM', ''),
                        'market_date': date, 'market_cap_krw': row.get('MKTCAP'),
                        'close_krw': row.get('TDD_CLSPRC'), 'market': row.get('MARKET', '')}
    # A single evaluation date is essential for a coherent cross-sectional ranking.
    if len(dates) != 1:
        raise ValueError('MARKET_DATE_MIXED_OR_MISSING')
    return result, next(iter(dates))


def balance_sheet_from_cache(cache, code, year):
    rec = cache.get(f'{code}:{year}:annual', {})
    accounts = rec.get('accounts', {}) if isinstance(rec, dict) and rec.get('status') == '000' else {}
    if not isinstance(accounts, dict):
        return {}
    return {'assets_krw': accounts.get('assets'), 'liabilities_krw': accounts.get('liabilities')}


def illustrative_prices(grade_result, market, financial=None):
    """Transparent multiple-based *research* reference, NOT a verified fair value.

    The reference is the lower of TTM earnings- and equity-multiple values.
    It is NOT artificially capped at the latest close. Three discount zones
    are calculated from the reference, not from a presumed buy signal.
    Optional financial inputs avoid rounding the intermediate PER/PBR ratios.
    """
    close = num(market.get('close_krw'))
    per = num(grade_result.get('ttm_per_est'))
    pbr = num(grade_result.get('pbr_est'))
    if financial:
        cap = num(market.get('market_cap_krw'))
        ttm = num(financial.get('ttm_profit'))
        equity = num(financial.get('equity'))
        if cap is not None and cap > 0 and ttm is not None and ttm > 0:
            per = cap / ttm
        if cap is not None and cap > 0 and equity is not None and equity > 0:
            pbr = cap / equity
    if any(v is None or v <= 0 for v in (close, per, pbr)):
        return {}
    target_per, target_pbr = (12.0, 1.5) if grade_result['grade'] == 'A' else (10.0, 1.2)
    per_reference = close * target_per / per
    pbr_reference = close * target_pbr / pbr
    reference = min(per_reference, pbr_reference)
    if not math.isfinite(reference) or reference <= 0:
        return {}
    return {
        'research_valuation_model': 'R14_MULTIPLE_DISCOUNT_V2',
        'research_target_per_assumption': target_per,
        'research_target_pbr_assumption': target_pbr,
        'research_per_based_value_krw': math.floor(per_reference),
        'research_pbr_based_value_krw': math.floor(pbr_reference),
        'research_reference_value_krw': math.floor(reference),
        'research_implied_reference_vs_close_pct': round(100 * (reference / close - 1), 2),
        'research_scenario_upper_krw': math.floor(reference * 0.90),
        'research_scenario_mid_krw': math.floor(reference * 0.80),
        'research_scenario_lower_krw': math.floor(reference * 0.70),
        'research_scenario_method': 'reference=min(close*assumed_PER/derived_TTM_PER,close*assumed_PBR/derived_PBR); zones=90/80/70pct_reference',
        'research_price_warning': 'MULTIPLE_REFERENCE_GT_2X_CLOSE' if reference > 2 * close else None,
        'fair_value_verified': False,
        'actionable_entry_price': False,
        'buy_signal': False,
    }


def self_test():
    scale = 1_000_000_000
    f = {'source': 'OpenDART fnlttSinglAcntAll', 'ttm_status': 'VERIFIED_CUMULATIVE',
         'annual_profit': 150*scale, 'ttm_profit': 180*scale,
         'equity': 1000*scale, 'prior_equity': 900*scale}
    m = {'market_cap_krw': 1500*scale, 'assets_krw': 2000*scale,
         'liabilities_krw': 500*scale, 'close_krw': 10000}
    assert grade(f, m)[0]['grade'] == 'A'
    assert grade(f, {**m, 'market_cap_krw': 1})[0] is None
    assert grade({**f, 'ttm_status': 'MISSING_QUARTER'}, m)[0] is None
    assert grade({**f, 'equity': -1}, m)[0] is None
    assert grade({**f, 'ttm_profit': -1}, m)[0] is None
    assert grade(f, {**m, 'assets_krw': ''})[0] is None
    v=illustrative_prices(grade(f,m)[0],m,f)
    assert v['actionable_entry_price'] is False and v['buy_signal'] is False
    assert v['research_reference_value_krw'] > 0
    assert v['research_scenario_upper_krw'] >= v['research_scenario_mid_krw'] >= v['research_scenario_lower_krw'] > 0
    assert v['research_scenario_upper_krw'] == math.floor(v['research_reference_value_krw'] * .9) or v['research_scenario_upper_krw'] == math.floor(v['research_reference_value_krw'] * .9)+1
    low_ratio={'grade':'A','ttm_per_est':4,'pbr_est':.4}
    upper=illustrative_prices(low_ratio, {'close_krw':10000})
    assert upper['research_scenario_upper_krw'] > 10000  # no old close-price ceiling
    assert illustrative_prices(low_ratio,{'close_krw':0}) == {}
    assert normalize_code('0001A0') == ''
    assert balance_sheet_from_cache({'000020:2025:annual': {'status':'000', 'accounts':{'assets':10,'liabilities':4}}},'000020','2025')['assets_krw'] == 10
    return 14


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--financial', help='R14 annual_financial_index_m.csv')
    ap.add_argument('--market', help='normalized market CSV (legacy) OR KRX data/latest.csv')
    ap.add_argument('--cache', help='R14 financial cache JSON (required for KRX market input)')
    ap.add_argument('--output', help='optional output path; does not modify input files')
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    tests = self_test()
    if a.self_test or not (a.financial and a.market):
        print(json.dumps({'result': 'SELF_TEST_PASS', 'tests': tests, 'note': 'no investment grades issued'}))
        return
    financials = read_csv(a.financial)
    market_rows = read_csv(a.market)
    krx_format = 'ISU_CD' in (market_rows[0] if market_rows else {})
    if krx_format:
        if not a.cache:
            raise SystemExit('MISSING_CACHE_FOR_KRX_MARKET_INPUT')
        markets, market_date = market_index(market_rows)
        cache = read_json(a.cache)
        if not isinstance(cache, dict) or not cache:
            raise SystemExit('MISSING_OR_EMPTY_FINANCIAL_CACHE')
    else:
        required = {'code', 'market_cap_krw', 'assets_krw', 'liabilities_krw'}
        if not market_rows or not required.issubset(market_rows[0]):
            raise SystemExit('MISSING_EXPLICIT_MARKET_COLUMNS')
        markets = {normalize_code(r.get('code')): r for r in market_rows if normalize_code(r.get('code'))}
        market_date = 'UNVERIFIED_LEGACY_MARKET_DATE'
        cache = {}
    candidates, excluded = [], {}
    for fin in financials:
        code = normalize_code(fin.get('code'))
        if not code:
            continue
        market = dict(markets.get(code, {}))
        if krx_format:
            market.update(balance_sheet_from_cache(cache, code, str(fin.get('year', ''))))
        # The cash-flow/profit cache is NOT point-in-time filing verified.
        result, reason = grade(fin, market)
        if result:
            result.update(illustrative_prices(result, market, fin))
            candidates.append({'code': code, 'name': market.get('name', ''),
                               'market_date': market.get('market_date', market_date),
                               'close_krw': market.get('close_krw'), **result})
        else:
            excluded[reason] = excluded.get(reason, 0) + 1
    report = {'result': 'PRELIMINARY_RESEARCH_ONLY', 'self_tests': tests,
              'financial_rows': len(financials), 'market_rows': len(markets),
              'market_date': market_date, 'candidate_count': len(candidates),
              'valuation_model': 'R14_MULTIPLE_DISCOUNT_V2',
              'candidates': candidates, 'excluded_by_reason': excluded,
              'financial_disclosure_asof_verified': False,
              'investment_decisions_authorized': False, 'final_buy_signals': 0,
              'limitations': ['Candidate grades are research-only; do not issue trading signals',
                              'Preferred-share class not officially verified; cannot claim final ordinary-share-only screening',
                              'Estimated PER/PBR are NOT official KRX figures',
                              'Research reference can exceed latest close; 90/80/70pct zones are scenarios, NOT buy orders',
                              'Assumed PER/PBR thresholds are not sector-calibrated; reference is NOT certified fair value',
                              'Financial statement filing/version not independently point-in-time verified',
                              'Market and financial snapshot dates may differ']}
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if a.output:
        pathlib.Path(a.output).write_text(output, encoding='utf-8')
    else:
        print(output)

if __name__ == '__main__':
    main()
