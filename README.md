# 車両別収支ダッシュボード

毎月の車両別収支Excelを取り込み、**全社 → 拠点 → 車種 → 車番**の順に収支を確認するWebアプリです。

## 利用中のアプリ

https://sako-vehicle-profit.shbata.chatgpt.site

上記は限定公開の運用環境です。ChatGPTでログインし、サイトの閲覧権限がある方が利用できます。GitHubはソースコードの管理に使用し、収支データ・Excel原本はアプリの共有データベースとファイル保管先で管理します。

## 主な機能

- 拠点・車種・車番ごとの収入、支出、収益、収益率の可視化
- 車種の表記統一（例：`3t・冷蔵` / `3t冷蔵`、`ﾄﾞﾗｲ` / `ドライ`）
- 月次比較、経費内訳、車両検索、赤字の明細抽出
- `.xls` / `.xlsx`の取り込みプレビューと合計照合
- 通常シートのみの取り込み、重複登録防止、修正版への差し替え
- 取り込み履歴と過去データの復元
- CSV出力と元Excelのダウンロード
- 管理者による更新と、共有メンバーによる閲覧

## データの取り扱い

このリポジトリには、実際の車両別収支・Excel原本・ログイン情報を含めていません。`app/seed-data.json`は空配列、`app/server/seed-files.json`は空オブジェクトです。データは運用アプリの画面からアップロードします。

運用中のアプリには2026年8月・9月分が登録されています。このリポジトリを新しい環境へ配置した場合は空の状態で起動します。既存データは自動でコピーされません。

## 開発環境

- Node.js 22.13以上（24推奨）
- pnpm 11.25
- React / TypeScript / Vinext / Vite
- Cloudflare Workers / D1 / R2
- Recharts / SheetJS

```bash
corepack enable
corepack pnpm install --frozen-lockfile
corepack pnpm run check
corepack pnpm test
corepack pnpm build
```

ローカルで共有保存を確認するには、初回ビルド後にD1のスキーマを適用します。

```bash
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0000_thankful_captain_america.sql
corepack pnpm dev
```

通常の開発環境では `http://localhost:5173` を開きます。ローカルデータは `.wrangler/` に保存され、運用中のデータとは別です。開発モードでは、認証ヘッダーのないローカルアクセスに限り管理者操作を許可します。

## 本番運用・更新

この構成は**ChatGPT Sitesの限定公開環境**で運用する設計です。サーバー処理とデータベースがあるため、GitHub Pagesのみでは動作しません。

1. GitHubでコードを更新し、チェックを通します。
2. ChatGPT Workでこのリポジトリを指定して、Sitesへの更新を依頼します。
3. 既存サイトを更新する場合は、既存のサイトIDとD1/R2の接続を維持します。
4. 新しい環境では、管理者のChatGPTログイン用メールアドレスをランタイム設定 `ADMIN_EMAIL` に登録します。
5. サイトの共有設定から経営者・拠点責任者へ閲覧権限を追加します。

**GitHubへpushするだけでは、現在のアプリは自動更新されません。** ソースの保存と運用アプリへの反映は別の操作です。

公開用のリポジトリには既存サイトのIDや管理者の個人メールアドレスを固定していません。既存サイトのランタイム設定を変更する場合は `ADMIN_EMAIL` を設定してから、このコードを反映してください。

## 集計の定義

- 収益は元Excelの「収益」を使用します。
- 収益率は `収益合計 ÷ 収入合計`。各車両の率を単純平均しません。
- 元Excelの「構成比率」は `支出 ÷ 収入` で、収益率とは異なります。
- 収入ゼロで経費がある明細やトレーラも集計に含めます。
- 台数は実車保有台数と混同しないよう「車両コード単位の明細数」と表示します。
- 小計・拠点計・全社計は明細に加算しません。
- 空欄を勝手にゼロにせず、通常シートの必須数値に欠損があれば登録を止めます。
- 車番ではなく車両コードを識別に使用し、車番変更を詳細画面で表示します。

## 主なファイル

| ファイル | 内容 |
| --- | --- |
| `app/dashboard.tsx` | ダッシュボード・車両詳細・取り込み画面 |
| `app/globals.css` | デザイン・レスポンシブ表示 |
| `app/parse-excel.ts` | 帳票形式の解析 |
| `app/model.ts` | 指標・表記統一・合計照合 |
| `app/api/` | 取り込み・参照・復元などのAPI |
| `app/server/store.ts` | D1 / R2による共有保存 |
| `db/schema.ts` / `drizzle/` | データベース定義・マイグレーション |
| `.github/workflows/check.yml` | GitHubでの型チェック・テスト |

## ランタイムの境界

認証はSitesのアクセス制御と、Sitesが付与する認証ヘッダーを前提にしています。他のサービスへ移設する場合は、サーバー側の認証・認可と保存先を実装してから公開してください。管理者以外の更新操作はサーバー側でも拒否します。
