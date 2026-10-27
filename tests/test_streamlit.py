from pathlib import Path
from streamlit.testing.v1 import AppTest
from fleet.storage import SessionStore
from test_fleet import example_workbook
from fleet.core import parse_workbook


def test_empty_app():
    app=AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py',default_timeout=30).run()
    assert not app.exception
    assert any('毎月のExcel' in v.value for v in app.subheader)


def test_dashboard_navigation_and_filters():
    state={}
    store=SessionStore(state)
    for month in ('2026/08','2026/09'):
        content=example_workbook(month)
        store.save(parse_workbook(content,'sample.xlsx'),content)
    app=AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py',default_timeout=30)
    app.session_state['fleet_store']=state['fleet_store']
    app.run()
    assert not app.exception
    assert len(app.metric)==4
    assert app.metric[0].value=='30.0万円'
    app.selectbox(key='scope_branch').select('テスト').run()
    assert not app.exception
    app.selectbox(key='scope_type').select('3t冷蔵').run()
    assert not app.exception
    app.selectbox(key='detail_choice_2026-09_テスト_3t冷蔵__None').select('00001').run()
    assert not app.exception
    assert any('車両詳細' in h.value for h in app.subheader)
    app.radio(key='nav').set_value('月次比較').run()
    assert not app.exception
    app.radio(key='nav').set_value('車両一覧').run()
    assert not app.exception
    app.radio(key='nav').set_value('データ管理').run()
    assert not app.exception
    assert any('取り込み履歴' in h.value for h in app.subheader)


def test_shared_mode_requires_auth_before_loading():
    app=AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py',default_timeout=30)
    app.secrets={'storage_mode':'remote','backend_url':'https://example.com','backend_token':'not-a-real-key'}
    app.run()
    assert not app.exception
    assert any('初期設定' in value.value for value in app.info)
    assert not app.metric


def test_viewer_cannot_upload(tmp_path):
    from fleet.storage import SQLiteStore
    store=SQLiteStore(tmp_path/'data.db')
    content=example_workbook()
    store.save(parse_workbook(content,'sample.xlsx'),content)
    app=AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py',default_timeout=30)
    app.secrets={'storage_mode':'sqlite','sqlite_path':str(tmp_path/'data.db'),'admin_password':'admin-test-password-123','viewer_password':'viewer-test-password-123'}
    app.run()
    assert not app.exception
    app.selectbox(key='login_role').select('閲覧者')
    app.text_input(key='login_password').set_value('viewer-test-password-123')
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state['auth_role']=='viewer'
    assert not any(b.label=='Excelをアップロード' for b in app.button)
    app.radio(key='nav').set_value('データ管理').run()
    assert not app.exception
    assert not app.get('file_uploader')
    assert all(button.disabled for button in app.get('form_submit_button'))
