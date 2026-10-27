from __future__ import annotations

import base64
import copy
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from fleet.core import normalize_type, validate_month

class StorageError(ValueError):
    pass

def now():
    return datetime.now(timezone.utc).isoformat()

class SessionStore:
    """Per-Streamlit-session storage. Never shared through a module/global cache."""
    mode = 'session'
    def __init__(self, state):
        self.state = state
        self.state.setdefault('fleet_store', {'months': {}, 'history': [], 'overrides': {}, 'originals': {}})

    @property
    def data(self):
        return self.state['fleet_store']

    def load(self):
        return {'months': [copy.deepcopy(m) for _, m in sorted(self.data['months'].items())], 'overrides': dict(self.data['overrides'])}

    def save(self, payload, original, expected_hash=None, action=None):
        validate_month(payload)
        if hashlib.sha256(original).hexdigest() != payload['hash']:
            raise StorageError('元ファイルのハッシュが一致しません。')
        month = payload['month']
        current = self.data['months'].get(month)
        if current and current['hash'] == payload['hash']:
            return '登録済み'
        if (current or {}).get('hash') != expected_hash:
            raise StorageError('別の更新が先に保存されました。再読み込みしてください。')
        document = copy.deepcopy(payload)
        document['updatedAt'] = now()
        record = {'id': str(uuid.uuid4()), 'month': month, 'fileName': payload['fileName'], 'sheetName': payload['sheetName'], 'hash': payload['hash'], 'importedAt': document['updatedAt'], 'count': len(payload['records']), 'action': action or ('差し替え' if current else '追加'), 'payload': document}
        self.data['originals'][payload['hash']] = original
        self.data['history'].insert(0, record)
        self.data['months'][month] = document
        self.persist()
        return record['action']

    def history(self):
        return [{k: v for k, v in h.items() if k != 'payload'} for h in self.data['history']]

    def restore(self, history_id, expected_hash):
        found = next((h for h in self.data['history'] if h['id'] == history_id), None)
        if found is None:
            raise StorageError('履歴が見つかりません。')
        # Even if the content is identical, no destructive change is made.
        return self.save(found['payload'], self.data['originals'].get(found['hash'], b''), expected_hash, '履歴から復元')

    def classify(self, code, vehicle_type):
        if not str(code).isdigit() or len(vehicle_type) > 40:
            raise StorageError('車両コードと車種名を確認してください。')
        if vehicle_type.strip():
            self.data['overrides'][code] = normalize_type(vehicle_type)
        else:
            self.data['overrides'].pop(code, None)
        self.persist()

    def original(self, month):
        document = self.data['months'].get(month)
        if not document:
            raise StorageError('元データが見つかりません。')
        return self.data['originals'].get(document['hash'], b'')

    def backup(self):
        snapshot = copy.deepcopy(self.data)
        snapshot['originals'] = {k: base64.b64encode(v).decode() for k, v in snapshot['originals'].items()}
        return json.dumps({'format': 'vehicle-profit-backup-v1', 'data': snapshot}, ensure_ascii=False, allow_nan=False).encode()

    def restore_backup(self, content):
        if len(content) > 60 * 1024 * 1024:
            raise StorageError('バックアップは60MB以下にしてください。')
        try:
            snapshot = json.loads(content)
            if snapshot.get('format') != 'vehicle-profit-backup-v1':
                raise StorageError('対応するバックアップ形式ではありません。')
            document = snapshot['data']
            for month, payload in document['months'].items():
                validate_month(payload)
                if payload['month'] != month:
                    raise StorageError('対象月が一致しません。')
            for item in document.get('history', []):
                validate_month(item['payload'])
            originals = {key: base64.b64decode(value, validate=True) for key, value in document['originals'].items()}
            for key, content in originals.items():
                if hashlib.sha256(content).hexdigest() != key:
                    raise StorageError('元ファイルのハッシュが一致しません。')
            document['originals'] = originals
            overrides = document.get('overrides', {})
            if not isinstance(overrides, dict) or any(not str(k).isdigit() or not isinstance(v, str) or len(v) > 40 for k, v in overrides.items()):
                raise StorageError('車種分類の形式が不正です。')
        except StorageError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError('バックアップを読み取れません。') from exc
        self.state['fleet_store'] = document
        self.persist()

    def persist(self):
        pass

class SQLiteStore(SessionStore):
    """For local/self-hosted installations with a durable mounted volume."""
    mode = 'sqlite'
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = {}
        with sqlite3.connect(self.path) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS fleet_state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL, revision INTEGER NOT NULL)')
            record = connection.execute('SELECT payload, revision FROM fleet_state WHERE id=1').fetchone()
        self.revision = record[1] if record else 0
        super().__init__(self.state)
        if record:
            snapshot = json.loads(record[0])
            snapshot['originals'] = {key: base64.b64decode(value) for key, value in snapshot['originals'].items()}
            self.state['fleet_store'] = snapshot

    def persist(self):
        document = json.loads(self.backup())['data']
        with sqlite3.connect(self.path, timeout=15) as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT revision FROM fleet_state WHERE id=1').fetchone()
            if (row[0] if row else 0) != self.revision:
                raise StorageError('別の更新が先に保存されました。再読み込みしてください。')
            self.revision += 1
            connection.execute('INSERT INTO fleet_state(id,payload,revision) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,revision=excluded.revision', (json.dumps(document, ensure_ascii=False), self.revision))

class RemoteStore:
    """Adapter for the existing authenticated shared storage API."""
    mode = 'remote'
    def __init__(self, base_url, token):
        parsed = urlparse(base_url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise StorageError('保存先URLは認証情報やクエリのないHTTPS URLを指定してください。')
        if not token:
            raise StorageError('共有保存先の接続キーが未設定です。')
        self.base = base_url.rstrip('/')
        self.headers = {'OAI-Sites-Authorization': 'Bearer ' + token}

    def request(self, method, path, **kwargs):
        try:
            response = requests.request(method, self.base + path, headers=self.headers, timeout=(10, 60), allow_redirects=False, **kwargs)
        except requests.RequestException as exc:
            raise StorageError('共有保存先に接続できません。設定と接続状態を確認してください。') from exc
        if response.status_code not in range(200, 300):
            raise StorageError(f'共有保存先で処理できませんでした（HTTP {response.status_code}）。再読み込みして確認してください。')
        return response

    def load(self):
        try:
            result = self.request('GET', '/api/data').json()
            if not isinstance(result.get('months'), list):
                raise ValueError()
            for month in result['months']:
                validate_month(month)
            return {'months': result['months'], 'overrides': result.get('overrides', {})}
        except (ValueError, KeyError) as exc:
            raise StorageError('共有保存先のデータ形式を確認してください。') from exc

    def save(self, payload, original, expected_hash=None, action=None):
        validate_month(payload)
        response = self.request('POST', '/api/import', files={'file': (payload['fileName'], original, 'application/octet-stream')}, data={'sheet': payload['sheetName'], 'expectedHash': expected_hash or ''}).json()
        return '登録済み' if response.get('skipped') else '保存しました'

    def history(self):
        return self.request('GET', '/api/history').json()

    def restore(self, history_id, expected_hash):
        self.request('POST', '/api/restore', json={'id': history_id, 'expectedHash': expected_hash})

    def classify(self, code, vehicle_type):
        self.request('POST', '/api/classification', json={'code': code, 'type': vehicle_type})

    def original(self, month):
        return self.request('GET', '/api/file', params={'month': month}).content
