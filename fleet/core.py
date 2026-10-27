from __future__ import annotations

import hashlib
import io
import math
import re
import unicodedata
from typing import Any

import pandas as pd

NUMERIC_KEYS = ['runs', 'loadedKm', 'totalKm', 'loadedRate', 'freight', 'revenuePerRun', 'revenuePerKm', 'highwayRevenue', 'income', 'tolls', 'fuelLiters', 'fuelUnitPrice', 'fuel', 'tires', 'supplies', 'inspection', 'repairs', 'accident', 'refrigeration', 'welfare', 'labor', 'fixed', 'indirect', 'expense', 'profit', 'expenseRate']
COSTS = {'labor': '人件費', 'fuel': '燃料費', 'fixed': '固定経費', 'indirect': '間接経費', 'tolls': '通行費', 'welfare': '福利厚生費', 'tires': 'タイヤ代', 'inspection': '車検点検整備費', 'repairs': '一般修理費', 'supplies': '消耗費', 'accident': '事故修理', 'refrigeration': '冷凍機修理費'}
LABELS = {'code': '車両コード', 'plate': '正式車両番号', 'branch': '拠点', 'type': '車種', 'rawType': '元の車種名', 'income': '収入計', 'expense': '支出計', 'profit': '収益', 'rate': '収益率(%)', 'runs': '稼働回数', 'totalKm': '総走行距離(km)', 'loadedKm': '実車距離(km)', 'loadedRate': '実車率(%)', 'fuelLiters': '給油量(L)', 'freight': '売上運賃', 'highwayRevenue': '売上高速代', 'sourceRow': 'Excel行番号', **COSTS}
BRANCH_ORDER = ['本社', '高清水', '仙台', '盛岡', '郡山']
MAX_BYTES = 12 * 1024 * 1024

class WorkbookError(ValueError):
    pass

def clean(value: Any) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or '')))

def normalize_type(value: str) -> str:
    value = re.sub(r'[・･\s]', '', unicodedata.normalize('NFKC', value))
    return 'その他ドライ' if value == 'そのドライ' else value or '未分類'

def is_normal_sheet(name: str) -> bool:
    return not re.search(r'除|除外', name)

def workbook_sheets(content: bytes, filename: str) -> list[str]:
    if not filename.lower().endswith(('.xls', '.xlsx')):
        raise WorkbookError('.xls または .xlsx のExcelを選択してください。')
    if len(content) > MAX_BYTES:
        raise WorkbookError('12MB以下のExcelを選択してください。')
    try:
        engine = 'openpyxl' if filename.lower().endswith('.xlsx') else 'xlrd'
        with pd.ExcelFile(io.BytesIO(content), engine=engine) as book:
            names = [name for name in book.sheet_names if is_normal_sheet(name)]
        if not names:
            raise WorkbookError('通常シートが見つかりません。除外シートは取り込み対象外です。')
        return names
    except WorkbookError:
        raise
    except Exception as exc:
        raise WorkbookError('Excelを読み取れません。ファイル形式とパスワード保護を確認してください。') from exc

def number(value: Any, row: int) -> float:
    if value == '' or value is None or isinstance(value, bool):
        raise WorkbookError(f'{row}行目：必要な数値が空欄です。通常シートを確認してください。')
    try:
        result = float(str(value).replace(',', ''))
    except (TypeError, ValueError) as exc:
        raise WorkbookError(f'{row}行目：数値を読み取れません。') from exc
    if not math.isfinite(result):
        raise WorkbookError(f'{row}行目：有効な数値がありません。')
    return result

def verify_total(records: list[dict], control: dict, label: str):
    for key in ('income', 'expense', 'profit'):
        if abs(sum(row[key] for row in records) - control[key]) > 1:
            raise WorkbookError(f'{label}の{LABELS[key]}と明細合計が一致しません。')

def validate_month(data: dict) -> None:
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', data.get('month', '')):
        raise WorkbookError('対象年月を判定できません。')
    records = data.get('records', [])
    if not 1 <= len(records) <= 3000:
        raise WorkbookError('明細は1〜3,000件である必要があります。')
    ids = set()
    for row in records:
        if not re.fullmatch(r'\d+', str(row.get('code', ''))) or not row.get('branch') or not row.get('type'):
            raise WorkbookError('車両コード・拠点・車種を確認してください。')
        if row['code'] in ids:
            raise WorkbookError(f"車両コード {row['code']} が重複しています。")
        ids.add(row['code'])
        for key in NUMERIC_KEYS:
            if isinstance(row.get(key), bool) or not isinstance(row.get(key), (float, int)) or not math.isfinite(row[key]):
                raise WorkbookError(f"車両 {row['code']}：{LABELS.get(key,key)}の数値が不正です。")
        if abs(row['income'] - row['expense'] - row['profit']) > 1:
            raise WorkbookError(f"車両 {row['code']} の収益が収入−支出と一致しません。")
    controls = data.get('checks', [])
    total = next((c for c in controls if c['label'] == '全社計'), None)
    if not total:
        raise WorkbookError('全社計が見つかりません。')
    verify_total(records, total, '全社計')
    for branch in {r['branch'] for r in records}:
        control = next((c for c in controls if clean(c['label']).replace('(営)', '') == branch + '計'), None)
        if control is None:
            raise WorkbookError(f'{branch}の拠点計がありません。')
        verify_total([r for r in records if r['branch'] == branch], control, branch)

def parse_workbook(content: bytes, filename: str, sheet_name: str | None = None) -> dict:
    names = workbook_sheets(content, filename)
    sheet_name = sheet_name or names[0]
    if sheet_name not in names:
        raise WorkbookError('通常シートを選択してください。')
    engine = 'openpyxl' if filename.lower().endswith('.xlsx') else 'xlrd'
    try:
        frame = pd.read_excel(io.BytesIO(content), sheet_name=sheet_name, header=None, dtype=object, keep_default_na=False, engine=engine)
    except Exception as exc:
        raise WorkbookError('シートを読み取れません。') from exc
    if frame.shape[1] < 29:
        raise WorkbookError('列構成が異なります。車両別収支実績表を確認してください。')
    month, branch, header = '', '', False
    records, pending, controls = [], [], []
    for index, values in enumerate(frame.itertuples(index=False, name=None), start=1):
        a = clean(values[0])
        if a == '対象年月:':
            match = re.fullmatch(r'(\d{4})/(\d{2})[~〜～](\d{4})/(\d{2})', clean(values[2]))
            if not match or match.groups()[:2] != match.groups()[2:]:
                raise WorkbookError('1か月単位の対象年月を読み取れません。')
            found = f'{match[1]}-{match[2]}'
            if month and month != found:
                raise WorkbookError('シート内に複数の対象月があります。')
            month = found
        if a == '営業所:' and clean(values[2]) != '全営業所':
            found = clean(values[2]).replace('(営)', '')
            if pending and branch != found:
                raise WorkbookError('車種小計のない明細があります。')
            branch = found
        if a == '車両コード':
            if (clean(values[1]), clean(values[11]), clean(values[26]), clean(values[27])) != ('正式車両番号', '収入計', '支出計', '収益'):
                raise WorkbookError('帳票の列構成が異なります。')
            header = True
        code = str(int(values[0])) if isinstance(values[0], (int, float)) and math.isfinite(values[0]) and float(values[0]).is_integer() else a
        if header and re.fullmatch(r'\d+', code):
            if not branch:
                raise WorkbookError(f'{index}行目：拠点がありません。')
            plate = str(int(values[1])) if isinstance(values[1], (int, float)) and float(values[1]).is_integer() else str(values[1]).strip()
            row = {'code': code.zfill(5), 'plate': plate, 'branch': branch, 'sourceRow': index}
            row.update({key: number(values[offset + 3], index) for offset, key in enumerate(NUMERIC_KEYS)})
            pending.append(row)
        if a.endswith('計') and a != '収入計':
            if a not in {branch + '計', branch + '(営)計', '全社計'} and pending:
                raw_type = str(values[0]).removesuffix('計').strip() or '未分類'
                control = {key: number(values[col], index) for key, col in [('income', 11), ('expense', 26), ('profit', 27)]}
                verify_total(pending, control, f'{branch} {raw_type}小計')
                records.extend({**row, 'rawType': raw_type, 'type': normalize_type(raw_type)} for row in pending)
                pending = []
            if values[11] != '' and values[26] != '' and values[27] != '':
                controls.append({'label': str(values[0]), 'row': index, 'income': number(values[11], index), 'expense': number(values[26], index), 'profit': number(values[27], index)})
    if pending:
        raise WorkbookError('車種小計のない明細が残っています。')
    warnings = []
    if any(r['type'] == '未分類' for r in records):
        warnings.append('車種名のない明細は「未分類」として保存します。データ管理から指定できます。')
    blank = sum(not r['plate'] for r in records)
    if blank:
        warnings.append(f'車番が空欄の{blank}件は車両コードで表示します。')
    data = {'month': month, 'fileName': filename, 'sheetName': sheet_name, 'hash': hashlib.sha256(content).hexdigest(), 'records': records, 'checks': controls, 'warnings': warnings}
    validate_month(data)
    return data

def previous_month(month: str) -> str:
    year, number = map(int, month.split('-'))
    return f'{year - 1}-12' if number == 1 else f'{year}-{number - 1:02d}'

def month_label(month: str) -> str:
    year, number = month.split('-')
    return f'{year}年{int(number)}月'

def aggregate(records: list[dict]) -> dict:
    out = {key: math.fsum(r[key] for r in records) for key in NUMERIC_KEYS}
    out['rate'] = out['profit'] / out['income'] * 100 if out['income'] else None
    out['loadedRate'] = out['loadedKm'] / out['totalKm'] * 100 if out['totalKm'] else None
    out['count'] = len(records)
    return out

def dataframe(data: dict, overrides: dict | None = None) -> pd.DataFrame:
    overrides = overrides or {}
    rows = [{**r, 'type': overrides.get(r['code']) or normalize_type(r['type']), 'month': data['month']} for r in data['records']]
    frame = pd.DataFrame(rows, columns=['month', 'branch', 'type', 'code', 'plate', 'rawType', 'sourceRow', *NUMERIC_KEYS])
    frame['rate'] = frame.apply(lambda r: r['profit'] / r['income'] * 100 if r['income'] else None, axis=1) if len(frame) else pd.Series(dtype=float)
    return frame

def summary(frame: pd.DataFrame, group: str) -> pd.DataFrame:
    columns = [group, 'count', 'income', 'expense', 'profit', 'rate']
    if frame.empty:
        return pd.DataFrame(columns=columns)
    result = frame.groupby(group, dropna=False).agg(count=('code', 'count'), income=('income', 'sum'), expense=('expense', 'sum'), profit=('profit', 'sum')).reset_index()
    result['rate'] = result.apply(lambda row: row['profit'] / row['income'] * 100 if row['income'] else None, axis=1)
    return result[columns].sort_values('income', ascending=False)

def export_csv(frame: pd.DataFrame) -> bytes:
    out = frame.copy()
    for column in out.select_dtypes(include=['object', 'string']).columns:
        out[column] = out[column].map(lambda v: "'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v)
    out = out.rename(columns={'month': '対象年月', **LABELS})
    return out.to_csv(index=False).encode('utf-8-sig')
