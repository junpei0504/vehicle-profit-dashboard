# 車両別収支ダッシュボード（Streamlit版）

毎月の車両別収支Excelを読み込み、**全社 → 拠点 → 車種 → 車番**の順で収入・支出・収益を確認するWebアプリです。

**アプリ本体は `app.py`。Streamlit Community Cloudで公開できます。**

## Streamlitで公開する設定

[Streamlit Community Cloud](https://share.streamlit.io/)で「Create app」を選び、次の内容を指定します。

| 項目 | 設定値 |
| --- | --- |
| Repository | `junpei0504/vehicle-profit-dashboard` |
| Branch | `main` |
| Main file path | `app.py` |
| Python version | `3.12` |
| Dependencies | ルートの `requirements.txt` を自動使用 |

最初はSecrets未設定でも起動し、そのブラウザーのセッション内でExcelを読み込めます。実際のExcelや収支データはGitHubには含めていません。

## 主な機能

- 全社・拠点・車種・車番別の収支表示
- 車種の表記ゆれ統一（`3t・冷蔵` / `3t冷蔵`、`ﾄﾞﾗｲ` / `ドライ`）
- 通常シートの自動判定と選択、`.xls` / `.xlsx`対応
- 車種小計・拠点計・全社計と明細の照合
- 月次比較、経費内訳、車両検索、赤字の明細抽出
- 修正版の差し替え・重複登録防止・取り込み履歴・復元
- 車両コードによる識別、車番変更の表示
- CSV出力・Excel原本ダウンロード
- データ・履歴・原本をまとめたバックアップ（セッション / SQLiteモード）
- 共有モードの管理者 / 閲覧者ログイン

## 毎月の使い方

1. 「Excelをアップロード」から、毎月のExcelを選択します。複数月の一括選択に対応しています。
2. 通常シート・対象年月・明細数・合計照合を確認して読み込みます。
3. 左メニューや上部の選択欄から、拠点・車種を選択します。
4. 車両一覧の行や車両選択欄から、車両詳細を開きます。
5. 「月次比較」で前の月との差額を確認します。

## 共有保存の設定

Streamlit Community Cloudのローカルファイルは、再起動後も残る保存先としては扱いません。以下の3モードを用意しています。

| モード | 保存範囲 | 用途 |
| --- | --- | --- |
| `session`（初期値） | 現在のブラウザーのセッション | すぐに試す・個別のExcel分析。終了前にバックアップを保存 |
| `remote` | 外部の共有保存先 | 経営者・各拠点責任者が同じ履歴を閲覧する運用 |
| `sqlite` | 実行サーバーのローカルDB | ローカルPCまたは永続ディスク付きサーバー |

**継続的な共有利用には `remote` を使用してください。** セッションモードでは、別のブラウザーや他の利用者とデータを共有しません。

### 既存の共有保存先を利用する

作成済みのアプリの保存APIへ接続できるため、8月・9月を含む既存データを引き継げます。既存の画面にログインする必要はなく、Streamlitサーバーから接続します。

Streamlitの「App settings → Secrets」に、次の項目を設定します。接続キーとパスワードは**Secretsにのみ保存し、GitHubへ書き込まないでください。**

```toml
storage_mode = "remote"
backend_url = "https://sako-vehicle-profit.shbata.chatgpt.site"
backend_token = ""  # 保存先の接続キー
admin_password = ""  # 12文字以上
viewer_password = ""  # 管理者と異なる12文字以上
```

実際の値を設定するための空欄付きテンプレートは `.streamlit/secrets.example.toml` にあります。`backend_token` は、既存保存先で発行されたサービスアクセスキーを使用します。

- 管理者：Excelの取り込み・差し替え・分類変更・履歴の復元ができます。
- 閲覧者：収支・履歴の閲覧、CSV出力、原本確認ができます。
- 設定が不足している場合、共有データを読み込む前に初期設定画面で停止します。
- 接続キーはブラウザーへ返さず、サーバー側のAPI呼び出しにのみ使用します。
- パスワードログインは役割ごとの共通パスワード方式です。個人単位のSSO / 操作履歴ではありません。

既存のChatGPT Sites版は移行元としてそのまま残しています。Streamlit版のアプリ本体・画面・Excel集計は、このGitHubリポジトリのPythonコードで動作します。

## ローカルで起動

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS / Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

必要に応じて `.streamlit/secrets.example.toml` を `.streamlit/secrets.toml` にコピーして編集します。SQLiteモードではDBを自動作成するのでマイグレーション操作は不要です。

環境変数でも同じ設定ができます：`FLEET_STORAGE_MODE`、`FLEET_BACKEND_URL`、`FLEET_BACKEND_TOKEN`、`FLEET_ADMIN_PASSWORD`、`FLEET_VIEWER_PASSWORD`、`FLEET_SQLITE_PATH`。

## 集計ルール

- 収益は元Excelの「収益」を使用します。
- 収益率は `収益合計 ÷ 収入合計`。率の単純平均はしません。
- 元Excelの「構成比率」は `支出 ÷ 収入` で、収益率とは異なります。
- 収入ゼロで経費がある明細やトレーラも集計に含めます。
- 実車の台数と混同しないよう、「車両コード単位の明細数」と表示します。
- 小計・拠点計・全社計を明細に加算しません。
- 空欄をゼロにせず、必要な数値に欠損があれば登録を止めます。
- 分母がゼロの収益率・実車率は算出不可とします。
- 当月に存在しない明細はゼロへ置き換えず、月次比較で欠損として表示します。
- 拠点・車種は各月の所属を保存します。分類指定は同じ車両コードの登録済み各月へ適用します。

## テスト

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
```

Excel解析、表記統一、合計照合、重複拒否、差し替え・復元、バックアップ、SQLite競合防止、Streamlitの画面操作、閲覧者の操作制限をテストします。ユーザーのExcel原本はGitHubに含めず、標準テストには架空データを使用します。

## 主なファイル

| ファイル | 内容 |
| --- | --- |
| `app.py` | Streamlitアプリ本体 |
| `fleet/core.py` | Excel解析・集計・表示用データ |
| `fleet/storage.py` | セッション / SQLite / 外部共有保存 |
| `requirements.txt` | 公開環境のPython依存関係 |
| `.streamlit/config.toml` | 配色・アップロード容量など |
| `.streamlit/secrets.example.toml` | 共有保存・ログイン設定の例 |
| `tests/` | 集計・保存・画面のテスト |
| `app/`、`db/`、`worker/`など | 既存React / Sites版の互換用コード。Streamlitの起動には不要 |

GitHubの `main` をStreamlit Community Cloudへ接続すると、以後はコードの更新がアプリへ反映されます。
