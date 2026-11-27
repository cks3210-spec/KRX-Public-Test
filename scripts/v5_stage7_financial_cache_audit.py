"""Read-only cache schema audit. No network, no financial values in output."""
import argparse, csv, hashlib, json, re, tempfile
from pathlib import Path
from collections import Counter

SHARE_KEYS = re.compile(r'weighted.?average.*share|(?:number|count).*share|(?:issued|outstanding|treasury|ending|weighted|common).*share|share.*(?:count|outstanding|issued|weighted)|주식수|주식총수|유통주식|자기주식', re.I)
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def checked(root, path, expected):
    p=(root/path).resolve()
    if not p.is_relative_to(root) or not p.is_file() or digest(p)!=expected: raise ValueError('SOURCE_HASH_MISMATCH')
    return p

def scan(obj):
    hits=Counter(); nodes=0
    stack=[obj]
    while stack:
        x=stack.pop()
        if isinstance(x,dict):
            nodes+=1
            for k,v in x.items():
                if SHARE_KEYS.search(str(k)): hits['matching_field_names']+=1
                if k in ('account_id','account_nm','concept','concept_name') and isinstance(v,str) and SHARE_KEYS.search(v): hits['matching_account_labels']+=1
                if isinstance(v,(dict,list)): stack.append(v)
        elif isinstance(x,list): stack.extend(x)
    return {'object_count':nodes,'share_field_occurrences':hits['matching_field_names'],'share_account_label_occurrences':hits['matching_account_labels']}

def audit(root):
    root=root.resolve(); base=root/'data/v5_financial_m/filing_refresh'
    summary=read(root/'data/summary.json'); day=summary['latest_trading_date']
    q=read(base/'candidate_regrade/latest_status.json'); m=read(base/'metrics/latest_status.json')
    if q['market_date']!=day or m['market_date']!=day: raise ValueError('MARKET_DATE_MISMATCH')
    qp=checked(root,q['queue_path'],q['queue_sha256']); mp=checked(root,m['csv_path'],m['csv_sha256'])
    cache='data/v5_financial_m/dart_financial_cache.json'
    p=checked(root,cache,q['source_sha256'][cache])
    if m['source_sha256'][cache]!=q['source_sha256'][cache]: raise ValueError('CACHE_SOURCE_CONFLICT')
    def table(p):
        with p.open(encoding='utf-8-sig',newline='') as f:
            r=csv.DictReader(f); cols=r.fieldnames or []; n=0
            for row in r:
                if row.get('market_date')!=day: raise ValueError('ROW_DATE_MISMATCH')
                n+=1
            return {'rows':n,'share_columns':[k for k in cols if SHARE_KEYS.search(k)]}
    qt=table(qp); mt=table(mp)
    if qt['rows']!=q['research_ab_rows']: raise ValueError('QUEUE_COUNT_MISMATCH')
    obj=read(p); counts=scan(obj)
    xbrl={}
    for name in ('r14_xbrl_dimension_fact_cache.json','r14_xbrl_receipt_financial_cache.json'):
        xp=root/'v5_reports/stage28'/name
        if xp.is_file(): xbrl[name]={'state':'SCHEMA_SCAN_ONLY_UNBOUND',**scan(read(xp))}
    return {'state':'CACHE_SCHEMA_AUDITED_RESEARCH_ONLY','market_date':day,'queue':qt,'metrics':mt,'main_cache':counts,'optional_xbrl':xbrl,'share_counts_verified':False,'broker_basis_verified':False,'official_ratios_verified':False,'financial_api_calls':0,'investment_decisions_authorized':False,'final_buy_signals':0,'notes':['Field-name hits are not verified share counts. No missing values inferred. No raw values emitted.']}

def self_test():
    assert scan({'accounts':{'owner_profit':1}})['share_field_occurrences']==0
    assert scan({'records':[{'account_id':'WeightedAverageNumberOfOrdinarySharesOutstanding','value':1}]})['share_account_label_occurrences']==1
    assert scan({'accounts':{'ending_common_shares':1}})['share_field_occurrences']==1
    with tempfile.TemporaryDirectory() as d:
        r=Path(d); p=r/'a'; p.write_text('x'); assert checked(r,'a',digest(p))==p
        try: checked(r,'a','bad')
        except ValueError: pass
        else: raise AssertionError('BAD_HASH_ACCEPTED')
        try: checked(r,'../a','bad')
        except ValueError: pass
        else: raise AssertionError('OUTSIDE_ROOT_ACCEPTED')
    print('CACHE_AUDIT_SELF_TEST_PASS 6')
if __name__=='__main__':
    a=argparse.ArgumentParser(); a.add_argument('--root',type=Path,default=Path.cwd()); a.add_argument('--self-test',action='store_true'); args=a.parse_args()
    if args.self_test: self_test()
    else: print(json.dumps(audit(args.root),ensure_ascii=False))
