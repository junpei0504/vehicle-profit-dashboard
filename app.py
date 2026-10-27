from __future__ import annotations

import hashlib
import hmac
import html
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from fleet.core import BRANCH_ORDER, COSTS, LABELS, NUMERIC_KEYS, aggregate, dataframe, export_csv, month_label, normalize_type, parse_workbook, previous_month, summary, workbook_sheets
from fleet.storage import RemoteStore, SessionStore, SQLiteStore, StorageError

st.set_page_config(page_title='車両収支管理 | 迫トラック', page_icon='🚚', layout='wide', initial_sidebar_state='expanded')
st.markdown('''<style>
.stApp{font-family:Inter,"Noto Sans JP","Meiryo",sans-serif}.block-container{max-width:1550px;padding-top:2rem;padding-bottom:2rem}h1{font-size:1.85rem!important;font-weight:750!important;letter-spacing:.025em}h2{font-size:1.18rem!important}h3{font-size:1.0rem!important}[data-testid="stSidebar"]{background:linear-gradient(155deg,#192f48,#14263c);color:#d6e1ef}[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] p,[data-testid="stSidebar"] label,[data-testid="stSidebar"] summary,[data-testid="stSidebar"] [data-testid="stMarkdownContainer"]{color:#d6e1ef}[data-testid="stSidebar"] [data-testid="stRadio"] label{padding:8px 0}[data-testid="stSidebar"] button{border-color:#3a5572}[data-testid="stMetric"]{background:white;border:1px solid #e4eaf3;border-radius:12px;padding:18px 20px}[data-testid="stMetricValue"]{font-size:1.9rem;color:#1d304b}[data-testid="stVerticalBlockBorderWrapper"]{border-radius:12px}.eyebrow{font-size:10px;letter-spacing:1.8px;color:#91a0b4;font-weight:650}.lead{color:#8794a8;font-size:12px;margin:2px 0 18px}.brand{font-size:22px;font-weight:750;margin-bottom:0}.brand-sub{font-size:9px;letter-spacing:2px;color:#8da8c9;margin-bottom:27px}.status-pill{display:inline-block;padding:5px 11px;border-radius:20px;font-size:11px;background:#e6f7f3;color:#069c8f}.status-pill.loss{background:#fff0f2;color:#df6c7e}.breadcrumb{font-size:12px;color:#8294ae;background:white;border:1px solid #e8edf4;border-radius:7px;padding:12px 16px;margin:8px 0 18px}.fine{font-size:10px;color:#97a6ba}.positive{color:#079e99}.negative{color:#e7687b}.welcome{background:linear-gradient(110deg,#e9f2ff,#f5f9ff);border:1px solid #dce9fc;border-radius:14px;padding:30px;margin:8px 0 20px}.welcome h2{font-size:23px!important}.welcome p{color:#7c91ac;font-size:13px;line-height:1.8}.stButton button,.stDownloadButton button{border-radius:7px}.stSelectbox label,.stTextInput label{font-size:12px}.stCaption p{font-size:11px}footer{visibility:hidden}@media(max-width:700px){.block-container{padding-top:1.2rem;padding-left:1rem;padding-right:1rem}h1{font-size:1.45rem!important}[data-testid="stMetricValue"]{font-size:1.4rem}[data-testid="stMetric"]{padding:12px}}
</style>''', unsafe_allow_html=True)


def configuration():
    try:
        secrets = dict(st.secrets)
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        secrets = {}
    def value(key, default=''):
        return str(os.environ.get('FLEET_' + key.upper(), secrets.get(key, default)))
    return {'mode': value('storage_mode', 'remote' if value('backend_url') else 'session'), 'backend_url': value('backend_url'), 'backend_token': value('backend_token'), 'admin_password': value('admin_password'), 'viewer_password': value('viewer_password'), 'sqlite_path': value('sqlite_path', 'private-data/fleet.db')}


config = configuration()
mode = config['mode']
if mode not in {'session', 'remote', 'sqlite'}:
    st.error('storage_mode は session / remote / sqlite のいずれかを指定してください。')
    st.stop()


def authenticate():
    if mode == 'session':
        return 'admin'
    passwords = {role: config[role + '_password'] for role in ('admin', 'viewer') if config[role + '_password']}
    if not passwords or any(len(p) < 12 for p in passwords.values()):
        st.title('車両収支管理')
        st.info('共有利用の初期設定が必要です。StreamlitのSecretsに、12文字以上の管理者・閲覧者パスワードを設定してください。設定例はリポジトリの .streamlit/secrets.example.toml にあります。')
        st.stop()
    if len(passwords) == 2 and passwords['admin'] == passwords['viewer']:
        st.error('管理者と閲覧者には異なるパスワードを設定してください。')
        st.stop()
    fingerprint = hashlib.sha256('|'.join(passwords.values()).encode()).hexdigest()
    if st.session_state.get('auth_config') != fingerprint or time.time() - st.session_state.get('auth_time', 0) > 6 * 3600:
        st.session_state.pop('auth_role', None)
    if st.session_state.get('auth_role') in passwords:
        return st.session_state['auth_role']
    def login():
        if time.time() < st.session_state.get('login_wait_until', 0):
            return
        role = 'admin' if st.session_state['login_role'] == '管理者' else 'viewer'
        supplied = st.session_state.pop('login_password', '')
        if hmac.compare_digest(supplied.encode(), passwords.get(role, '').encode()) and role in passwords:
            st.session_state.update(auth_role=role, auth_config=fingerprint, auth_time=time.time(), login_attempts=0)
        else:
            attempts = st.session_state.get('login_attempts', 0) + 1
            st.session_state['login_attempts'] = attempts
            st.session_state['login_error'] = 'パスワードを確認してください。'
            if attempts % 5 == 0:
                st.session_state['login_wait_until'] = time.time() + 30
    left, center, right = st.columns([1, 1.1, 1])
    with center:
        st.markdown('<div class="eyebrow">SAKO TRANSPORT</div>', unsafe_allow_html=True)
        st.title('車両収支管理')
        st.caption('共有データを確認するにはログインしてください。')
        with st.form('login'):
            roles = [('管理者' if role == 'admin' else '閲覧者') for role in passwords]
            st.selectbox('利用区分', roles, key='login_role')
            st.text_input('パスワード', type='password', key='login_password')
            st.form_submit_button('ログイン', type='primary', on_click=login, width='stretch')
        if st.session_state.get('login_error'):
            st.warning(st.session_state.pop('login_error'))
        if time.time() < st.session_state.get('login_wait_until', 0):
            st.warning('30秒ほど待ってから再度お試しください。')
    st.stop()


role = authenticate()
admin = role == 'admin'
try:
    store = RemoteStore(config['backend_url'], config['backend_token']) if mode == 'remote' else SQLiteStore(config['sqlite_path']) if mode == 'sqlite' else SessionStore(st.session_state)
except StorageError as exc:
    st.error(str(exc))
    st.stop()


def reload_data():
    st.session_state.pop('remote_payload', None)
    st.session_state.pop('remote_loaded', None)


def load_data():
    if mode == 'remote' and st.session_state.get('remote_payload') and time.time() - st.session_state.get('remote_loaded', 0) < 30:
        return st.session_state['remote_payload']
    result = store.load()
    if mode == 'remote':
        st.session_state.update(remote_payload=result, remote_loaded=time.time())
    return result


try:
    payload = load_data()
except StorageError as exc:
    st.error(str(exc))
    if st.button('再読み込み'):
        reload_data()
        st.rerun()
    st.stop()
months = sorted(payload['months'], key=lambda d: d['month'])
overrides = payload.get('overrides', {})
periods = [d['month'] for d in months]
frames = {d['month']: dataframe(d, overrides) for d in months}
st.session_state.setdefault('scope_branch', '全拠点')
st.session_state.setdefault('scope_type', '全車種')
st.session_state.setdefault('nav', 'ダッシュボード')


def scope_to(branch='全拠点', vehicle_type='全車種'):
    st.session_state.update(scope_branch=branch, scope_type=vehicle_type, nav='ダッシュボード')
    st.session_state.pop('detail_code', None)


def reset_type():
    st.session_state['scope_type'] = '全車種'
    st.session_state.pop('detail_code', None)


def go_upload():
    st.session_state['nav'] = 'データ管理'


def money(value, sign=False):
    if value is None or pd.isna(value):
        return '—'
    return f'{value / 10000:+,.1f}' if sign else f'{value / 10000:,.1f}'


def ratio(value):
    return '算出不可' if value is None or pd.isna(value) else f'{value:.1f}%'


def date_label(value):
    if not value:
        return '—'
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(ZoneInfo('Asia/Tokyo')).strftime('%Y/%m/%d %H:%M')
    except ValueError:
        return value


with st.sidebar:
    st.markdown('<div class="brand">🚚 車両収支管理</div><div class="brand-sub">SAKO TRANSPORT</div>', unsafe_allow_html=True)
    st.radio('ワークスペース', ['ダッシュボード', '月次比較', '車両一覧', 'データ管理'], key='nav')
    st.divider()
    st.caption('拠点 → 車種 → 車番')
    st.button('全社', on_click=scope_to, width='stretch')
    latest = frames.get(st.session_state.get('period', periods[-1] if periods else ''), pd.DataFrame())
    if not latest.empty:
        branches = sorted(latest['branch'].unique(), key=lambda b: (BRANCH_ORDER.index(b) if b in BRANCH_ORDER else 99, b))
        for b in branches:
            with st.expander(f'{b}  ·  {int((latest.branch == b).sum())}明細', expanded=st.session_state['scope_branch'] == b):
                st.button(f'{b}の収支', key=f'branch_{b}', on_click=scope_to, args=(b,), width='stretch')
                for kind in sorted(latest.loc[latest.branch == b, 'type'].unique()):
                    st.button(kind, key=f'type_{b}_{kind}', on_click=scope_to, args=(b, kind), width='stretch')
    st.divider()
    st.caption('共有保存に接続' if mode == 'remote' else 'ローカル保存' if mode == 'sqlite' else 'このブラウザーのセッション内のみ')
    st.caption('管理者' if admin else '閲覧者')
    st.button('最新のデータを再読み込み', on_click=reload_data, width='stretch')
    if mode != 'session' and st.button('ログアウト', width='stretch'):
        for key in ('auth_role', 'auth_config', 'auth_time', 'remote_payload', 'remote_loaded'):
            st.session_state.pop(key, None)
        st.rerun()

nav = st.session_state['nav']
header, actions = st.columns([4, 1.4], vertical_alignment='center')
with header:
    st.markdown('<div class="eyebrow">MONTHLY PERFORMANCE</div>', unsafe_allow_html=True)
    st.title({'ダッシュボード': '収支を、車番まで見える化。', '月次比較': '月次の収支を比較', '車両一覧': '車両ごとの収支', 'データ管理': 'データ管理'}[nav])
    st.markdown('<p class="lead">拠点・車種・車番の順に、毎月の変化と経費の内訳を確認。</p>', unsafe_allow_html=True)
with actions:
    if admin:
        st.button('Excelをアップロード', type='primary', on_click=go_upload, width='stretch')
if mode == 'session':
    st.info('お試しモード：データはこのセッション内のみです。継続利用はバックアップを保存するか、Secretsで共有保存先を設定してください。', icon='ℹ️')
elif mode == 'sqlite':
    st.warning('SQLiteはローカル・永続ディスク付きサーバー用です。Streamlit Community Cloudの再起動後の保存は保証されません。共有運用は外部保存先を設定してください。')


def import_screen():
    st.subheader('毎月のExcelを、そのままアップロード。')
    st.caption('通常シートを判定し、車種の表記ゆれを統一。小計・合計行は二重計上しません。')
    files = st.file_uploader('車両別収支実績表', type=['xls', 'xlsx'], accept_multiple_files=True, key='excel_uploads')
    parsed, errors = [], False
    for i, file in enumerate(files or []):
        try:
            content = file.getvalue()
            names = workbook_sheets(content, file.name)
            sheet_name = st.selectbox(f'{file.name} の通常シート', names, key=f'sheet_{i}_{file.name}', disabled=len(names) == 1)
            document = parse_workbook(content, file.name, sheet_name)
            old = next((d for d in months if d['month'] == document['month']), None)
            duplicate = old and old['hash'] == document['hash']
            with st.container(border=True):
                st.markdown(f'**{month_label(document["month"])} · {html.escape(file.name)}**')
                metrics = aggregate(document['records'])
                a, b, c = st.columns(3)
                a.metric('明細数', metrics['count'])
                b.metric('収入計', money(metrics['income']) + '万円')
                c.metric('収益', money(metrics['profit'], True) + '万円')
                st.success('全社・拠点・車種小計と一致しています。')
                if duplicate:
                    st.caption('同じファイルが登録済みです。二重登録しません。')
                elif old:
                    old_by_code = {r['code']: r for r in old['records']}
                    new_by_code = {r['code']: r for r in document['records']}
                    st.warning(f'登録済み月の差し替え：収益差額 {money(metrics["profit"] - aggregate(old["records"])["profit"], True)}万円 / 追加 {len(new_by_code.keys()-old_by_code.keys())}件 / 未掲載 {len(old_by_code.keys()-new_by_code.keys())}件')
                for warning in document.get('warnings', []):
                    st.caption(warning)
            parsed.append((document, content, old, duplicate))
        except (ValueError, TypeError, KeyError) as exc:
            st.error(f'{file.name}：{exc}')
            errors = True
    if len({d['month'] for d, *_ in parsed}) != len(parsed):
        st.error('同じ対象月のファイルが複数あります。1つに絞ってください。')
        errors = True
    replacement = any(old and not duplicate for _, _, old, duplicate in parsed)
    approved = st.checkbox('登録済みの月を差し替えます。現在の内容は履歴に残ります。', key='replace_approved') if replacement else True
    if st.button('共有データに保存' if mode != 'session' else 'このセッションに読み込む', type='primary', disabled=not parsed or errors or not approved, key='save_imports'):
        successes = []
        try:
            for document, content, old, duplicate in parsed:
                result = store.save(document, content, old['hash'] if old else None)
                successes.append(f'{month_label(document["month"])}：{result}')
        except StorageError as exc:
            st.error(str(exc))
            for result in successes:
                st.caption(result)
            reload_data()
        else:
            reload_data()
            st.session_state['import_notice'] = ' / '.join(successes)
            st.session_state['period'] = parsed[-1][0]['month']
            st.rerun()


def display_frame(frame, columns, key, selectable=False):
    shown = frame.reindex(columns=columns).copy()
    for col in ('income', 'expense', 'profit'):
        if col in shown:
            shown[col] /= 10000
    mapping = {**LABELS, 'income': '収入（万円）', 'expense': '支出（万円）', 'profit': '収益（万円）', 'count': '明細数', 'month': '対象年月'}
    shown.rename(columns=mapping, inplace=True)
    column_config = {mapping[col]: st.column_config.NumberColumn(mapping[col], format='%.1f') for col in ('income', 'expense', 'profit', 'rate') if col in columns}
    if 'code' in columns:
        column_config[mapping['code']] = st.column_config.TextColumn(mapping['code'])
    kwargs = {'hide_index': True, 'width': 'stretch', 'height': min(540, 45 + 37 * len(shown)), 'column_config': column_config, 'key': key}
    if selectable:
        kwargs.update(on_select='rerun', selection_mode='single-row')
    return st.dataframe(shown, **kwargs)


def figure_layout(fig, height=310):
    fig.update_layout(height=height, margin=dict(l=5, r=10, t=10, b=5), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(family='Arial, Meiryo, sans-serif', color='#708099', size=11), legend=dict(orientation='h', y=-.15), hoverlabel=dict(bgcolor='white'), dragmode=False)
    fig.update_xaxes(showline=False, zerolinecolor='#c6d1e0', gridcolor='#edf1f7')
    fig.update_yaxes(showline=False, zerolinecolor='#c6d1e0', gridcolor='#edf1f7')
    return fig


if st.session_state.get('import_notice'):
    st.success(st.session_state.pop('import_notice'))
if not months:
    st.markdown('<div class="welcome"><h2>毎月のExcelが、見やすいダッシュボードに。</h2><p>通常シートを読み込むと、拠点 → 車種 → 車番で確認できます。<br>8月・9月のExcelも、まとめて選択できます。</p></div>', unsafe_allow_html=True)
    if admin:
        import_screen()
        if mode != 'remote':
            with st.expander('保存済みのバックアップを読み込む'):
                backup = st.file_uploader('バックアップJSON', type=['json'], key='initial_backup')
                if st.button('バックアップを復元', disabled=backup is None, key='initial_restore'):
                    try:
                        store.restore_backup(backup.getvalue())
                        st.rerun()
                    except StorageError as exc:
                        st.error(str(exc))
    else:
        st.info('管理者がExcelを登録すると表示されます。')
    st.stop()

if nav == 'データ管理':
    if admin:
        import_screen()
    st.divider()
    st.subheader('登録済みの月次データ')
    metadata = []
    for document in reversed(months):
        totals = aggregate(document['records'])
        metadata.append({'対象月': month_label(document['month']), 'ファイル': document['fileName'], 'シート': document['sheetName'], '明細数': len(document['records']), '収入（万円）': totals['income']/10000, '収益（万円）': totals['profit']/10000, '照合': '一致', '更新（日本時間）': date_label(document.get('updatedAt'))})
    st.dataframe(pd.DataFrame(metadata), hide_index=True, width='stretch')
    st.subheader('車種分類の確認')
    st.caption('「3t・冷蔵」と「3t冷蔵」などは自動で統一します。元の車種名がない明細は以下で指定できます。')
    unresolved = {}
    for document in months:
        for row in document['records']:
            if row['type'] == '未分類' or row['code'] in overrides:
                unresolved[row['code']] = row
    for code, row in unresolved.items():
        with st.form('classify_' + code):
            a, b, c = st.columns([2, 2, 1], vertical_alignment='bottom')
            a.caption(f'{row["plate"] or code} / {row["branch"]} / コード {code}')
            value = b.text_input('車種名（空欄で指定解除）', value=overrides.get(code, ''), disabled=not admin, key='type_input_' + code)
            if c.form_submit_button('分類を保存', disabled=not admin, width='stretch'):
                try:
                    store.classify(code, value)
                    reload_data()
                    st.rerun()
                except StorageError as exc:
                    st.error(str(exc))
    st.subheader('取り込み履歴')
    try:
        history = store.history()
        if history:
            shown = pd.DataFrame([{'日時（日本時間）': date_label(h['importedAt']), '対象月': month_label(h['month']), 'ファイル': h['fileName'], '処理': h['action'], '明細数': h['count']} for h in history])
            st.dataframe(shown, hide_index=True, width='stretch')
            if admin:
                selected_history = st.selectbox('復元する履歴', range(len(history)), format_func=lambda i: f'{date_label(history[i]["importedAt"])} / {month_label(history[i]["month"])} / {history[i]["fileName"]}', key='restore_history')
                confirmation = st.checkbox('選択した月をこの履歴に戻します。現在のデータは履歴に残ります。')
                if st.button('選択した履歴から復元', disabled=not confirmation):
                    h = history[selected_history]
                    current = next((m for m in months if m['month'] == h['month']), None)
                    store.restore(h['id'], current['hash'] if current else None)
                    reload_data()
                    st.rerun()
    except StorageError as exc:
        st.error(str(exc))
    if mode != 'remote':
        st.divider()
        st.subheader('データのバックアップ')
        st.caption('月次データ・履歴・車種分類・Excel原本をまとめて保存できます。このファイルには収支データが含まれます。')
        if admin:
            st.download_button('バックアップを保存', store.backup(), file_name='vehicle_profit_backup.json', mime='application/json')
            backup = st.file_uploader('バックアップを復元', type=['json'], key='backup_manage')
            agreed = st.checkbox('現在の全データをバックアップの内容に置き換えます。先に現在のバックアップを保存してください。')
            if st.button('バックアップで置き換え', disabled=backup is None or not agreed):
                try:
                    store.restore_backup(backup.getvalue())
                    st.rerun()
                except StorageError as exc:
                    st.error(str(exc))
    st.stop()

if st.session_state.get('period') not in periods:
    st.session_state['period'] = periods[-1]
a, b, c, d = st.columns([1.15, 1, 1.1, 1.65])
period = a.selectbox('対象年月', periods, format_func=month_label, key='period')
frame = frames[period]
branch_choices = ['全拠点'] + sorted(frame.branch.unique(), key=lambda v: (BRANCH_ORDER.index(v) if v in BRANCH_ORDER else 99, v))
if st.session_state['scope_branch'] not in branch_choices:
    st.session_state['scope_branch'] = '全拠点'
branch = b.selectbox('拠点', branch_choices, key='scope_branch', on_change=reset_type)
type_choices = ['全車種'] + sorted(frame.loc[(frame.branch == branch) if branch != '全拠点' else pd.Series(True, index=frame.index), 'type'].unique())
if st.session_state['scope_type'] not in type_choices:
    st.session_state['scope_type'] = '全車種'
vehicle_type = c.selectbox('車種', type_choices, key='scope_type')
search = d.text_input('車番・車両コードを検索', placeholder='例：6577 / 00693', key='vehicle_search')


def scoped(input_frame):
    result = input_frame.copy()
    if branch != '全拠点':
        result = result[result.branch == branch]
    if vehicle_type != '全車種':
        result = result[result.type == vehicle_type]
    if search:
        query = unicase(search)
        result = result[(result.plate.map(unicase).str.contains(query, regex=False)) | result.code.str.contains(query, regex=False)]
    return result


def unicase(value):
    import unicodedata
    return unicodedata.normalize('NFKC', str(value)).strip()


filtered = scoped(frame)
prior_period = previous_month(period)
prior = scoped(frames[prior_period]) if prior_period in frames else pd.DataFrame(columns=frame.columns)
crumb = '全社' + (f'　›　{html.escape(branch)}' if branch != '全拠点' else '') + (f'　›　{html.escape(vehicle_type)}' if vehicle_type != '全車種' else '')
st.markdown(f'<div class="breadcrumb">{crumb}<span style="float:right">{len(filtered)} 明細 ／ 車両コード単位</span></div>', unsafe_allow_html=True)
if search:
    st.caption(f'検索条件「{search}」を集計にも反映しています。')


def vehicles_table(input_frame, key):
    a, b = st.columns([1.7, 1])
    status = a.radio('表示対象', ['すべて', '赤字の明細', '収入ゼロ・経費あり'], horizontal=True, key=key+'_status')
    ordering = b.selectbox('並び順', ['収益が低い順', '収益が高い順', '収入が高い順', '収益率が低い順', '車両コード順'], key=key+'_sort')
    rows = input_frame.copy()
    if status == '赤字の明細':
        rows = rows[rows.profit < 0]
    elif status == '収入ゼロ・経費あり':
        rows = rows[(rows.income == 0) & (rows.expense != 0)]
    sort_key, ascending = {'収益が低い順': ('profit', True), '収益が高い順': ('profit', False), '収入が高い順': ('income', False), '収益率が低い順': ('rate', True), '車両コード順': ('code', True)}[ordering]
    rows = rows.sort_values([sort_key], ascending=ascending, na_position='last').reset_index(drop=True)
    event = display_frame(rows, ['plate', 'code', 'branch', 'type', 'income', 'expense', 'profit', 'rate', 'runs'], key=f'{key}_{period}_{branch}_{vehicle_type}_{search}_{status}_{ordering}', selectable=True)
    st.caption('行を選択すると、画面下に車両の詳細が表示されます。')
    st.download_button('表示条件の明細をCSV出力', export_csv(rows), file_name=f'vehicle_profit_{period}.csv', mime='text/csv', key=key+'_csv')
    return rows.iloc[event.selection.rows[0]]['code'] if event.selection.rows and len(rows) else None


selected_code = None
if nav == 'ダッシュボード':
    totals = aggregate(filtered.to_dict('records'))
    previous = aggregate(prior.to_dict('records'))
    cards = st.columns(4)
    for card, key, label in zip(cards[:3], ['income', 'expense', 'profit'], ['収入計', '支出計', '収益']):
        delta = money(totals[key]-previous[key], True)+'万円' if len(prior) else None
        card.metric(label, money(totals[key], key == 'profit')+'万円', delta=delta, delta_color='inverse' if key == 'expense' else 'normal')
    delta = f'{totals["rate"]-previous["rate"]:+.1f}pt' if totals['rate'] is not None and previous['rate'] is not None else None
    cards[3].metric('収益率', ratio(totals['rate']), delta=delta)
    st.caption('前月比は前の暦月との比較です。収益率＝収益合計÷収入合計。元Excelの構成比率とは異なります。')
    left, right = st.columns([1.05, 1])
    group = 'branch' if branch == '全拠点' else 'type'
    grouped = summary(filtered, group).sort_values('profit')
    with left, st.container(border=True):
        st.subheader('拠点別の収益' if group == 'branch' else '車種別の収益')
        st.caption('単位：万円 ｜ 詳細は左メニューまたは下の一覧から選択')
        fig = go.Figure(go.Bar(x=grouped.profit/10000, y=grouped[group], orientation='h', marker_color=['#f07886' if n < 0 else '#08a5a0' for n in grouped.profit], text=[money(n, True) for n in grouped.profit], textposition='auto', hovertemplate='%{y}<br>収益 %{x:,.1f}万円<extra></extra>'))
        st.plotly_chart(figure_layout(fig, max(290, min(540, len(grouped)*34))), width='stretch', key='group_profit')
    with right, st.container(border=True):
        st.subheader('月別の収支推移')
        st.caption('単位：万円 ｜ 収入・支出は左軸、収益は右軸')
        trend = []
        for month in months:
            values = scoped(frames[month['month']])
            total = aggregate(values.to_dict('records'))
            trend.append({'label': month_label(month['month']), **{key: total[key]/10000 if len(values) else None for key in ('income', 'expense', 'profit')}})
        fig = make_subplots(specs=[[{'secondary_y': True}]])
        for key, label, color in [('income', '収入', '#3478ef'), ('expense', '支出', '#b7d7ff')]:
            fig.add_trace(go.Bar(x=[v['label'] for v in trend], y=[v[key] for v in trend], name=label, marker_color=color), secondary_y=False)
        fig.add_trace(go.Scatter(x=[v['label'] for v in trend], y=[v['profit'] for v in trend], name='収益（右軸）', mode='lines+markers', line=dict(color='#08a5a0', width=3), connectgaps=False), secondary_y=True)
        fig.update_layout(barmode='group')
        st.plotly_chart(figure_layout(fig), width='stretch', key='monthly_trend')
    with st.container(border=True):
        st.subheader('収支サマリー')
        group_label = st.radio('集計の粒度', ['車種別', '拠点別', '車両別'], horizontal=True, key='summary_level')
        if group_label == '車両別':
            selected_code = vehicles_table(filtered, 'overview_vehicles')
        else:
            dimension = 'type' if group_label == '車種別' else 'branch'
            table = summary(filtered, dimension).reset_index(drop=True)
            event = display_frame(table, [dimension, 'count', 'income', 'expense', 'profit', 'rate'], key=f'summary_{period}_{branch}_{vehicle_type}_{dimension}_{search}', selectable=True)
            if event.selection.rows and len(table):
                name = table.iloc[event.selection.rows[0]][dimension]
                st.caption(f'選択中：{name}')
                st.button('選択した項目の詳細へ', on_click=scope_to, args=(name, '全車種') if dimension == 'branch' else (branch, name), key='drilldown')
    left, right = st.columns([1.05, 1])
    with left, st.container(border=True):
        st.subheader('確認したい車両')
        st.caption('収益の低い5件。車両コードで識別しています。')
        attention = filtered.sort_values('profit').head(5)
        choices = ['選択してください'] + list(attention.code)
        selected_attention = st.selectbox('詳細を見る車両', choices, format_func=lambda value: value if value == choices[0] else f'{attention.loc[attention.code==value,"plate"].iloc[0] or value} / {value} / {money(attention.loc[attention.code==value,"profit"].iloc[0],True)}万円', key=f'attention_{period}_{branch}_{vehicle_type}_{search}')
        display_frame(attention, ['plate', 'code', 'branch', 'type', 'profit'], key='attention_table')
        if selected_attention != choices[0]:
            selected_code = selected_attention
    with right, st.container(border=True):
        st.subheader('経費の内訳')
        costs = sorted([(label, float(filtered[key].sum())) for key, label in COSTS.items()], key=lambda v: v[1], reverse=True)
        fig = go.Figure(go.Bar(y=[v[0] for v in reversed(costs[:6])], x=[v[1]/10000 for v in reversed(costs[:6])], orientation='h', marker_color='#62a5fa', hovertemplate='%{y}<br>%{x:,.1f}万円<extra></extra>'))
        st.plotly_chart(figure_layout(fig, 260), width='stretch', key='cost_summary')
        st.caption('内訳の端数差は保持し、支出計は元Excelの値を使用しています。')
elif nav == '車両一覧':
    st.subheader('車両別収支一覧')
    selected_code = vehicles_table(filtered, 'all_vehicles')
elif nav == '月次比較':
    candidates = [m for m in periods if m != period]
    if not candidates:
        st.info('2か月以上のデータを読み込むと比較できます。')
    else:
        compare = st.selectbox('比較元の月', candidates, index=candidates.index(prior_period) if prior_period in candidates else len(candidates)-1, format_func=month_label)
        other = scoped(frames[compare])
        dimension = 'branch' if branch == '全拠点' and vehicle_type == '全車種' else 'type' if vehicle_type == '全車種' else 'code'
        earlier = summary(other, dimension).rename(columns={c: 'previous_'+c for c in ['income','expense','profit','rate','count']})
        later = summary(filtered, dimension).rename(columns={c: 'current_'+c for c in ['income','expense','profit','rate','count']})
        comparison = earlier.merge(later, on=dimension, how='outer')
        for key in ('income','expense','profit'):
            comparison['delta_'+key] = comparison['current_'+key]-comparison['previous_'+key]
        comparison.sort_values('delta_profit', inplace=True, na_position='last')
        st.caption('差額は比較先−比較元。片方の月にない明細は「データなし」として扱います。')
        show = comparison[[dimension,'previous_profit','current_profit','delta_profit','delta_income','delta_expense']].copy()
        show.columns = [LABELS.get(dimension,dimension),month_label(compare)+' 収益',month_label(period)+' 収益','収益差額','収入差額','支出差額']
        for col in show.columns[1:]:
            show[col] /= 10000
        st.dataframe(show, hide_index=True, width='stretch', column_config={col:st.column_config.NumberColumn(col+'（万円）',format='%.1f') for col in show.columns[1:]})
        fig = go.Figure(go.Bar(x=comparison['delta_profit']/10000, y=comparison[dimension], orientation='h', marker_color=['#e7687b' if pd.notna(v) and v<0 else '#08a5a0' for v in comparison.delta_profit], hovertemplate='%{y}<br>差額 %{x:,.1f}万円<extra></extra>'))
        st.plotly_chart(figure_layout(fig,max(320,len(comparison)*32)),width='stretch',key='comparison_chart')

# The vehicle selector is always available at vehicle-type scope, including months with missing records.
if vehicle_type != '全車種' or selected_code:
    choices = ['選択してください'] + list(filtered.code)
    if selected_code in choices:
        default = choices.index(selected_code)
    else:
        default = 0
    code = st.selectbox('車両詳細', choices, index=default, format_func=lambda v: v if v==choices[0] else f'{filtered.loc[filtered.code==v,"plate"].iloc[0] or "車番未登録"} / コード {v}', key=f'detail_choice_{period}_{branch}_{vehicle_type}_{search}_{selected_code}')
    if code != choices[0]:
        selected_code = code
if selected_code:
    row = frame[frame.code == selected_code]
    if row.empty:
        st.info('この車両コードの当月データはありません。ゼロには置き換えていません。')
    else:
        vehicle = row.iloc[0]
        st.divider()
        with st.container(border=True):
            title, status = st.columns([4, 1])
            title.subheader(f'車両詳細：{vehicle.plate or selected_code}')
            title.caption(f'{vehicle.branch} › {vehicle.type} / コード {selected_code} / {month_label(period)}')
            loss = vehicle.profit < 0
            status.markdown(f'<span class="status-pill {"loss" if loss else ""}">{"赤字" if loss else "黒字" if vehicle.profit > 0 else "収支ゼロ"}</span>', unsafe_allow_html=True)
            a,b,c=st.columns(3)
            a.metric('収入計',money(vehicle.income)+'万円')
            b.metric('収益',money(vehicle.profit,True)+'万円')
            c.metric('収益率',ratio(vehicle.rate))
            previous_vehicle = frames[prior_period].query('code == @selected_code') if prior_period in frames else pd.DataFrame()
            if not previous_vehicle.empty and previous_vehicle.iloc[0].plate != vehicle.plate:
                st.warning(f'前月から車番が変わっています（前月：{previous_vehicle.iloc[0].plate or "空欄"}）。車両コードが同じ明細として表示しています。')
            left,right=st.columns(2)
            with left:
                st.markdown('**経費の内訳**')
                costs=sorted([(label,vehicle[key]) for key,label in COSTS.items() if vehicle[key]!=0],key=lambda v:v[1])
                fig=go.Figure(go.Bar(y=[v[0] for v in costs],x=[v[1]/10000 for v in costs],orientation='h',marker_color='#62a5fa',hovertemplate='%{y}<br>%{x:,.1f}万円<extra></extra>'))
                st.plotly_chart(figure_layout(fig,max(250,len(costs)*28)),width='stretch',key='detail_cost')
                st.caption(f'支出計：{money(vehicle.expense)}万円（元Excel：{vehicle.expense:,.2f}円）')
            with right:
                st.markdown('**収益の月次比較**')
                history=[]
                for m in periods:
                    match=frames[m][frames[m].code==selected_code]
                    history.append({'対象月':month_label(m),'収益':float(match.iloc[0].profit)/10000 if not match.empty else None})
                fig=go.Figure(go.Bar(x=[h['対象月'] for h in history],y=[h['収益'] for h in history],marker_color=['#e7687b' if h['収益'] is not None and h['収益']<0 else '#08a5a0' for h in history],hovertemplate='%{x}<br>%{y:,.1f}万円<extra></extra>'))
                st.plotly_chart(figure_layout(fig,280),width='stretch',key='detail_trend')
                stats=st.columns(2)
                stats[0].metric('稼働回数',f'{vehicle.runs:g}回')
                stats[1].metric('総走行距離',f'{vehicle.totalKm:,.1f}km')
                st.caption(f'実車率：{ratio(vehicle.loadedKm/vehicle.totalKm*100 if vehicle.totalKm else None)} / 給油量：{vehicle.fuelLiters:,.1f}L')
            if not previous_vehicle.empty:
                old=previous_vehicle.iloc[0]
                changes=[('収入',vehicle.income-old.income),('収益',vehicle.profit-old.profit)]+sorted([(label,vehicle[key]-old[key]) for key,label in COSTS.items()],key=lambda v:abs(v[1]),reverse=True)[:3]
                st.markdown('**前月からの変化**')
                st.dataframe(pd.DataFrame({'項目':[c[0] for c in changes],'増減額（万円）':[c[1]/10000 for c in changes]}),hide_index=True,width='stretch')
                st.caption('経費は増減額の大きい3項目。増加は支出増を示します。')
            with st.expander('元データを確認'):
                source=next(m for m in months if m['month']==period)
                st.write(f'ファイル：{source["fileName"]} / シート：{source["sheetName"]} / {int(vehicle.sourceRow)}行目 / 元の車種名：{vehicle.rawType}')
                if st.button('Excel原本を準備',key='prepare_original'):
                    try:
                        st.session_state['download_original']=(period,store.original(period))
                    except StorageError as exc:
                        st.error(str(exc))
                original=st.session_state.get('download_original')
                if original and original[0]==period:
                    st.download_button('元Excelをダウンロード',original[1],file_name=source['fileName'],mime='application/octet-stream')

st.caption('SAKO TRANSPORT / VEHICLE PERFORMANCE　｜　金額は万円表示・元データは円単位で保持')
