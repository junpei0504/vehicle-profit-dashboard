import copy
import hashlib
import io
import os
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from fleet.core import aggregate, dataframe, export_csv, normalize_type, parse_workbook, previous_month, summary, validate_month, workbook_sheets, WorkbookError
from fleet.storage import SessionStore, SQLiteStore, StorageError


def example_workbook(month='2026/09'):
    book = Workbook()
    sheet = book.active
    sheet.title = '2026.9'
    sheet.append(['対象年月：', '', f'{month}～{month}'])
    sheet.append(['営業所：', '', 'テスト(営)'])
    header = [''] * 29
    for col, value in {0:'車両\nコード',1:'正式車両番号',11:'収入計',26:'支出計',27:'収益'}.items():
        header[col] = value
    sheet.append(header)
    def row(code, income, expense):
        values = [0] * 29
        values[:3] = [code, 'テスト100あ' + code, '']
        values[3:6] = [10, 800, 1000]
        values[7], values[11], values[26], values[27] = income, income, expense, income-expense
        return values
    def total(name, income, expense):
        values = [''] * 29
        values[0], values[11], values[26], values[27] = name, income, expense, income-expense
        return values
    sheet.append(row('00001',100000,80000))
    sheet.append(total('3t・冷蔵計',100000,80000))
    sheet.append(header)  # Repeated page header
    sheet.append(row('00002',200000,210000))
    sheet.append(total('3t冷蔵計',200000,210000))
    sheet.append(total('テスト(営)計',300000,290000))
    sheet.append(total('全社計',300000,290000))
    book.copy_worksheet(sheet).title = '97・197除く'
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def parsed():
    return parse_workbook(example_workbook(), 'sample.xlsx')


def test_parse_and_grouping():
    content = example_workbook()
    assert workbook_sheets(content, 'sample.xlsx') == ['2026.9']
    data = parsed()
    assert data['month'] == '2026-09'
    assert len(data['records']) == 2
    assert data['records'][0]['code'] == '00001'
    assert {r['type'] for r in data['records']} == {'3t冷蔵'}
    assert aggregate(data['records'])['profit'] == 10000
    assert len(summary(dataframe(data), 'type')) == 1
    assert normalize_type('10tﾄﾞﾗｲ') == '10tドライ'
    assert previous_month('2026-01') == '2025-12'
    assert aggregate([])['rate'] is None
    zero = {**data['records'][0], 'income':0}
    assert aggregate([zero])['rate'] is None
    assert export_csv(dataframe(data)).startswith(b'\xef\xbb\xbf')
    with pytest.raises(WorkbookError, match='通常シート'):
        parse_workbook(content, 'sample.xlsx', '97・197除く')


def test_bad_values_and_duplicates():
    data=parsed()
    bad=copy.deepcopy(data)
    bad['records'][0]['income']=None
    with pytest.raises(WorkbookError, match='数値'):
        validate_month(bad)
    bad=copy.deepcopy(data)
    bad['records'].append(bad['records'][0])
    with pytest.raises(WorkbookError, match='重複'):
        validate_month(bad)
    bad=copy.deepcopy(data)
    bad['checks'][-1]['profit']+=100
    with pytest.raises(WorkbookError, match='一致'):
        validate_month(bad)


def test_session_storage_and_restore():
    content=example_workbook()
    data=parsed()
    first,second=SessionStore({}),SessionStore({})
    assert first.save(data,content)=='追加'
    assert first.save(data,content,data['hash'])=='登録済み'
    assert len(first.history())==1
    assert not second.load()['months']  # sessions never share
    altered=copy.deepcopy(data)
    altered['fileName']='renamed.xlsx'
    altered['hash']=hashlib.sha256(b'x').hexdigest()
    with pytest.raises(StorageError,match='先に保存'):
        first.save(altered,b'x',None)
    first.save(altered,b'x',data['hash'])
    first.restore(first.history()[-1]['id'],altered['hash'])
    assert first.load()['months'][0]['hash']==data['hash']
    first.classify('00001','4t・冷蔵')
    assert first.load()['overrides']['00001']=='4t冷蔵'
    assert first.original('2026-09')==content


def test_backups():
    content=example_workbook()
    data=parse_workbook(content,'sample.xlsx')
    first,second=SessionStore({}),SessionStore({})
    first.save(data,content)
    second.restore_backup(first.backup())
    assert second.load()['months']==first.load()['months']
    assert second.original(data['month'])==first.original(data['month'])
    with pytest.raises(StorageError):
        second.restore_backup(b'{bad json')


def test_sqlite_persistence_and_conflict(tmp_path):
    path=tmp_path/'fleet.db'
    first=SQLiteStore(path)
    stale=SQLiteStore(path)
    content=example_workbook()
    data=parse_workbook(content,'sample.xlsx')
    first.save(data,content)
    current=SQLiteStore(path)
    assert len(current.load()['months'])==1
    with pytest.raises(StorageError,match='先に保存'):
        stale.save(data,content)
    assert len(SQLiteStore(path).load()['months'])==1


def test_uploaded_original_files():
    path=os.environ.get('FLEET_TEST_INPUT_DIR')
    if not path:
        pytest.skip('User uploads are not included in GitHub')
    expected={'2026-08':168,'2026-09':167}
    for filename in Path(path).glob('*.xls'):
        data=parse_workbook(filename.read_bytes(),filename.name)
        count=expected[data['month']]
        control=next(c for c in data['checks'] if c['label']=='全社計')
        totals=aggregate(data['records'])
        assert len(data['records'])==count
        assert totals['income']==pytest.approx(control['income'])
        assert totals['profit']==pytest.approx(control['profit'])
        assert len({r['branch'] for r in data['records']})==5
