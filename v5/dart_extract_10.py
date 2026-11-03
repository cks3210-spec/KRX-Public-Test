#!/usr/bin/env python3
"""Independent v5: validate extraction of 2025 annual CFS/OFS figures for 10 stocks."""
import csv, io, json, os, time, urllib.parse, urllib.request, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = 'https://opendart.fss.or.kr/api/'
FIELDS = {
 'revenue': [('ifrs-full_Revenue',), ('ifrs_Revenue',)],
 'operating_profit': [('dart_OperatingIncomeLoss',)],
 'net_income': [('ifrs-full_ProfitLoss',), ('ifrs_ProfitLoss',)],
 'assets': [('ifrs-full_Assets',), ('ifrs_Assets',)],
 'liabilities': [('ifrs-full_Liabilities',), ('ifrs_Liabilities',)],
 'equity': [('ifrs-full_Equity',), ('ifrs_Equity',)],
}
LABELS = {
 'revenue': {'매출액', '수익(매출액)', '영업수익'},
 'operating_profit': {'영업이익', '영업이익(손실)'},
 'net_income': {'당기순이익', '당기순이익(손실)'},
 'assets': {'자산총계'}, 'liabilities': {'부채총계'}, 'equity': {'자본총계'}
}
STATEMENT = {'revenue': 'IS', 'operating_profit': 'IS', 'net_income': 'IS', 'assets': 'BS', 'liabilities': 'BS', 'equity': 'BS'}

def request(endpoint, params):
    url = BASE + endpoint + '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'KRX-v5/1.0'}), timeout=45) as r:
        return r.read()

def amount(value):
    try: return int(str(value).replace(',', '').strip())
    except (ValueError, TypeError): return None

def extract(items):
    output = {}
    for field, ids in FIELDS.items():
        typ = STATEMENT[field]
        matches = [r for r in items if r.get('sj_div') == typ and r.get('account_id') in {i for group in ids for i in group} and r.get('account_detail', '-') in ('-', '')]
        if not matches:
            matches = [r for r in items if r.get('sj_div') == typ and r.get('account_nm', '').strip() in LABELS[field] and r.get('account_detail', '-') in ('-', '')]
        values = {amount(r.get('thstrm_amount')) for r in matches if amount(r.get('thstrm_amount')) is not None}
        output[field + '_krw'] = next(iter(values)) if len(values) == 1 else None
        output[field + '_status'] = 'OK' if len(values) == 1 else ('CONFLICT' if len(values) > 1 else 'MISSING')
    return output

def main():
    key = os.environ.get('DART_API_KEY', '').strip()
    if not key: raise SystemExit('DART_API_KEY secret missing')
    with open('data/latest.csv', encoding='utf-8-sig', newline='') as f: latest = list(csv.DictReader(f))
    eligible = sorted((r for r in latest if int(r.get('MKTCAP') or 0) >= 100_000_000_000 and r.get('ISU_CD','').isdigit() and len(r['ISU_CD']) == 6), key=lambda r: r['ISU_CD'])[:10]
    blob = request('corpCode.xml', {'crtfc_key': key})
    if not zipfile.is_zipfile(io.BytesIO(blob)):
        try:
            root = ET.fromstring(blob)
            raise SystemExit('OpenDART corpCode status=' + str(root.findtext('status')))
        except ET.ParseError: raise SystemExit('OpenDART corpCode unexpected response')
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith('.xml'))
        root = ET.fromstring(z.read(name))
    corp = {x.findtext('stock_code','').strip(): x.findtext('corp_code','').strip() for x in root.findall('list') if x.findtext('stock_code')}
    out = []
    for stock in eligible:
        code = stock['ISU_CD']
        row = {'ISU_CD':code, 'ISU_NM':stock['ISU_NM'], 'year':2025, 'statement_type':'', 'fetch_status':''}
        if code not in corp:
            row['fetch_status'] = 'CORP_CODE_MISSING'
        else:
            for fs in ('CFS','OFS'):
                try:
                    response = json.loads(request('fnlttSinglAcntAll.json', {'crtfc_key':key, 'corp_code':corp[code], 'bsns_year':'2025', 'reprt_code':'11011', 'fs_div':fs}))
                    if response.get('status') == '000' and response.get('list'):
                        row['fetch_status'] = 'OK'; row['statement_type'] = fs
                        row.update(extract(response['list']))
                        break
                    row['fetch_status'] = 'DART_' + str(response.get('status','UNKNOWN'))
                    if response.get('status') != '013': break
                except Exception as e:
                    row['fetch_status'] = 'REQUEST_ERROR_' + type(e).__name__
                    break
                time.sleep(.25)
        out.append(row)
        time.sleep(.25)
    dest = Path('v5_output'); dest.mkdir(exist_ok=True)
    fieldnames = ['ISU_CD','ISU_NM','year','statement_type','fetch_status'] + [v for f in FIELDS for v in (f+'_krw',f+'_status')]
    with (dest/'dart_extracted_10.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fieldnames);writer.writeheader();writer.writerows(out)
    summary = {'sample_size':len(out), 'statement_success':sum(r['fetch_status']=='OK' for r in out), 'complete_six_fields':sum(all(r.get(f+'_status')=='OK' for f in FIELDS) for r in out), 'missing_corp_codes':[{'code':r['ISU_CD'],'name':r['ISU_NM']} for r in out if r['fetch_status']=='CORP_CODE_MISSING'], 'field_success':{f:sum(r.get(f+'_status')=='OK' for r in out) for f in FIELDS}, 'note':'2025 annual data only; verify financial statement semantics and 2026 quarterly filings before investment ratings'}
    (dest/'dart_extraction_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if not summary['statement_success']: raise SystemExit('No financial statements retrieved')
if __name__=='__main__':main()
