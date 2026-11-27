"""Shared KRX v5 evaluation universe contract. Offline; no API or grades."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

SCHEMA = 'KRX_V5_FULL_SCOPE_V1'
MIN_CAP = Decimal('100000000000')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def valid_day(day):
    require(isinstance(day, str) and re.fullmatch(r'20\d{6}', day), 'INVALID_DATE')
    datetime.strptime(day, '%Y%m%d')
    return day


def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cap_value(value):
    try:
        d = Decimal(str(value))
        return d if d.is_finite() and d >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def index(rows, field):
    result = {}
    for row in rows:
        code = row.get(field)
        require(isinstance(code, str) and code.strip() == code and bool(code), 'INVALID_CODE')
        require(code not in result, 'DUPLICATE_CODE')
        result[code] = row
    return result


def build_scope(day, market_rows, class_archive=None, source_hashes=None):
    valid_day(day)
    market = index(market_rows, 'ISU_CD')
    require(bool(market) and all(r.get('BAS_DD') == day for r in market.values()), 'MARKET_DATE_MISMATCH')
    classes = {}; class_day = None
    if class_archive is not None:
        class_day = valid_day(class_archive['market_date'])
        require(class_day <= day, 'FUTURE_CLASS_ARCHIVE')
        classes = index(class_archive['rows'], 'ISU_SRT_CD')
        require(len(classes) == class_archive['row_count'], 'CLASS_COUNT_MISMATCH')
    items = []
    for code, row in sorted(market.items()):
        cap = cap_value(row.get('MKTCAP'))
        cl = classes.get(code)
        # Archived classifications are research evidence, never independent as-of verification.
        if cap is None:
            state = 'HOLD_MARKET_CAP_MISSING'
        elif cap < MIN_CAP:
            state = 'EXCLUDED_MARKET_CAP'
        elif not cl or cl.get('market') != row.get('MARKET'):
            state = 'HOLD_CLASS_EVIDENCE_MISSING'
        elif cl.get('KIND_STKCERT_TP_NM') == '보통주' and cl.get('SECUGRP_NM') == '주권':
            state = 'EVALUATE_COMMON_STOCK_RESEARCH_ONLY'
        elif not cl.get('KIND_STKCERT_TP_NM') or not cl.get('SECUGRP_NM'):
            state = 'HOLD_CLASS_EVIDENCE_MISSING'
        elif class_day != day:
            state = 'HOLD_OLDER_NONCOMMON_CLASS_EVIDENCE'
        else:
            state = 'EXCLUDED_NONCOMMON_OR_NONSTOCK_RESEARCH_ONLY'
        items.append({'code': code, 'market_date': day, 'market': row.get('MARKET'),
                      'scope_state': state, 'numeric_provider_code': bool(re.fullmatch(r'\d{6}', code)),
                      'class_asof_independently_verified': False})
    body = {'schema': SCHEMA, 'market_date': day, 'class_archive_date': class_day,
            'market_rows': len(items), 'minimum_market_cap_krw': str(MIN_CAP),
            'counts': dict(Counter(r['scope_state'] for r in items)),
            'source_sha256': source_hashes or {}, 'rows': items,
            'investment_decisions_authorized': False, 'final_buy_signals': 0}
    return {**body, 'scope_sha256': digest(body)}


def validate_scope(scope):
    require(scope.get('schema') == SCHEMA, 'SCOPE_SCHEMA_MISMATCH')
    require(digest({k:v for k,v in scope.items() if k != 'scope_sha256'}) == scope.get('scope_sha256'), 'SCOPE_HASH_MISMATCH')
    rows = index(scope['rows'], 'code')
    require(len(rows) == scope['market_rows'] and all(r['market_date'] == scope['market_date'] for r in rows.values()), 'SCOPE_ROWS_MISMATCH')
    require(dict(Counter(r['scope_state'] for r in rows.values())) == scope['counts'], 'SCOPE_COUNTS_MISMATCH')
    return rows


def evaluation_codes(scope):
    return {k for k,r in validate_scope(scope).items() if r['scope_state'] == 'EVALUATE_COMMON_STOCK_RESEARCH_ONLY'}


def validate_stage(scope, report):
    """All market codes must be accounted for. Held or excluded rows are not silently dropped.
    Each stage must emit market_date, scope_sha256, rows[{code, market_date, state}].
    A stage may hold an eligible stock for missing evidence; it may not omit it.
    """
    expected = validate_scope(scope)
    require(report.get('market_date') == scope['market_date'] and report.get('scope_sha256') == scope['scope_sha256'], 'STAGE_SCOPE_MISMATCH')
    rows = index(report['rows'], 'code')
    require(set(rows) == set(expected), 'STAGE_CODE_COVERAGE_MISMATCH')
    for code, r in rows.items():
        require(r.get('market_date') == scope['market_date'] and isinstance(r.get('state'), str) and bool(r['state'].strip()), 'STAGE_ROW_INVALID')
        if expected[code]['scope_state'] != 'EVALUATE_COMMON_STOCK_RESEARCH_ONLY':
            require(r['state'] == expected[code]['scope_state'], 'INELIGIBLE_SCOPE_STATE_CHANGED')
    return dict(Counter(r['state'] for r in rows.values()))


def self_test():
    day = '20261126'
    market = [{'ISU_CD':k,'BAS_DD':day,'MKTCAP':cap,'MARKET':'KOSPI'} for k,cap in [('000001','100000000000'),('000002','99999999999'),('000003','120000000000'),('000004','130000000000'),('000005','bad'),('00A006','150000000000')]]
    cl = {'market_date':'20261120','row_count':3,'rows':[{'ISU_SRT_CD':k,'market':'KOSPI','KIND_STKCERT_TP_NM':kind,'SECUGRP_NM':'주권'} for k,kind in [('000001','보통주'),('000003','구형우선주'),('00A006','보통주')]]}
    scope = build_scope(day,market,cl)
    assert evaluation_codes(scope) == {'000001','00A006'}
    assert scope['market_rows'] == 6
    assert scope['counts']['HOLD_OLDER_NONCOMMON_CLASS_EVIDENCE'] == 1
    assert scope['counts']['HOLD_CLASS_EVIDENCE_MISSING'] == 1
    assert scope['counts']['HOLD_MARKET_CAP_MISSING'] == 1
    assert scope['counts']['EXCLUDED_MARKET_CAP'] == 1
    report = {'market_date':day,'scope_sha256':scope['scope_sha256'],'rows':[{'code':r['code'],'market_date':day,'state':'HOLD_FINANCIAL_EVIDENCE' if r['code'] in evaluation_codes(scope) else r['scope_state']} for r in scope['rows']]}
    assert validate_stage(scope,report)['HOLD_FINANCIAL_EVIDENCE'] == 2
    def rejected(f):
        try: f()
        except ValueError: return
        raise AssertionError('EXPECTED_REJECTION')
    rejected(lambda:validate_stage(scope,{**report,'rows':report['rows'][:-1]}))
    rejected(lambda:validate_stage(scope,{**report,'market_date':'20261127'}))
    rejected(lambda:build_scope(day,market+market[:1],cl))
    rejected(lambda:build_scope(day,market,{**cl,'market_date':'20261127'}))
    rejected(lambda:validate_scope({**scope,'market_rows':1}))
    print('FULL_SCOPE_SELF_TEST_PASS 12')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    if args.self_test:
        self_test(); return
    require(args.out is not None,'OUTPUT_REQUIRED')
    root=args.root.resolve(); summary=root/'data/summary.json'; latest=root/'data/latest.csv'
    day=valid_day(json.loads(summary.read_text(encoding='utf-8-sig'))['latest_trading_date'])
    with latest.open(encoding='utf-8-sig',newline='') as f: market=list(csv.DictReader(f))
    paths=sorted(p for p in (root/'data/v5_official_shareclass_archive').glob('*.json') if re.fullmatch(r'20\d{6}',p.stem) and p.stem<=day)
    source={str(p.relative_to(root)):file_sha(p) for p in (summary,latest)}; cl=None
    if paths:
        p=paths[-1]; cl=json.loads(p.read_text(encoding='utf-8-sig')); require(cl['market_date']==p.stem,'CLASS_PATH_DATE_MISMATCH');source[str(p.relative_to(root))]=file_sha(p)
    scope=build_scope(day,market,cl,source)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(scope,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in scope.items() if k!='rows'},ensure_ascii=False))

if __name__=='__main__': main()
