# ホワイト企業発見マップ STELLARC — 隠れた優良企業が見つかる

全上場企業（約3,500社）を宇宙の銀河に見立てて探索するWebアプリ。サービス名は「ホワイト企業発見マップ」、
英字ロゴ/コードネームは `STELLARC`。転職・就活の企業研究で、知名度は低いが優良な“隠れ優良企業”を発見する。

- **星の大きさ = 時価総額**（最大企業=最小企業で約10000:1。トップ企業は太陽のように巨大。データ無しは最小表示）
- **星の輝き = 優良企業度**（売上成長率20pt・営業利益率25pt・働きやすさ30pt・平均年収25pt の独自スコア、最低1〜最高100に正規化）
- **星雲 = 東証33業種**。業種ごとに星が塊になっており、俯瞰時は業種名ラベルが浮かぶ。ラベルをタップするとその星雲へ移動

## ファイル構成

| ファイル | 役割 |
|---|---|
| `index.html` | 本体（単一ファイル・静的ホスティングだけで公開可能） |
| `fetch_edinetdb.py` | ★**推奨**。edinetdb.jp から時価総額・財務を含む全社データを取得し `stellarc_data.js` を生成 |
| `edinet_pipeline.py` | 金融庁EDINET API を直接叩く版（株価＝時価総額は取得不可・低速）。`fetch_edinetdb.py` が使えない場合の予備 |
| `ratings_template.csv` | 外部評価の取込テンプレート（`ratings.csv` にリネームして使用） |

`stellarc_data.js` が `index.html` と同じ場所に無い場合は、自動で架空データのデモ銀河（DEMO DATA表示）になります。

## 実データの取得（推奨: edinetdb.jp）

時価総額を含む全指標が取れるため、こちらを推奨します（全社1〜2分／無料枠100req/日に対し約30req）。

1. https://edinetdb.jp/developers でAPIキーを無料取得（`edb_...` 形式）
2. `pip install requests`
3. `set EDINETDB_API_KEY=あなたのキー`（キーはコードやチャットに貼らない）
4. `python fetch_edinetdb.py`（動作確認は `--limit 300`）
5. 生成された `stellarc_data.js` を `index.html` の隣に置く → 右上が「LIVE — EDINET」になる

取得元: 金融庁EDINETの開示情報を [edinetdb.jp（Cabocia Inc.）](https://edinetdb.jp/) が構造化・配信。
`/v1/screener` から `market-cap`（時価総額）・`operating-margin`（営業利益率）・`revenue-growth`
（売上成長率）・`avg-annual-salary`（平均年収）・`health-score`（財務健全性）・`female-manager-ratio`
（女性管理職比率）・`male-parental-leave-ratio`（男性育休取得率）等を取得します。カバレッジの低い
人的資本系は別クエリで取得し、`edinetCode` でマージしています。

### 取得できる指標と STELLARC での使い道
| edinetdb 指標 | STELLARC |
|---|---|
| `market-cap`（百万円→億円換算） | **惑星の大きさ** |
| `operating-margin` / `revenue-growth` / `avg-annual-salary` / 働きやすさ | **惑星の輝き（優良企業度100点満点）** |
| `female-manager-ratio` / `male-parental-leave-ratio` | 大気観測（人的資本） |
| 時価総額＋従業員規模 | 知名度（アルベド）→ 高優良度×低知名度 = ◆暗黒巨星 |

> 時価総額が取れない一部企業（新規上場直後など約400社）は、従業員数を代理に星サイズを決定します。

### 予備手段（金融庁EDINET直叩き）
`edinet_pipeline.py` は金融庁EDINET API v2 を直接使う版です（`pip install requests pandas xlrd`、
`set EDINET_API_KEY=...`、`python edinet_pipeline.py`）。全社30〜60分かかり、**株価＝時価総額は
有報CSVに含まれないため取得できません**（発行済株式数のみ）。`fetch_edinetdb.py` が使えない場合の予備です。

## 外部評価（OpenWork / ONE CAREER / 転職会議）の扱い — 重要

この3サイトの利用規約は**スクレイピング（自動収集）を禁止**しています。無断収集したデータを
公開サイトに掲載すると、利用規約違反・著作権/不正競争上のリスクがあります。そのため本プロジェクトは:

1. **リンク方式（標準）**: 各社の詳細パネル「EXTERNAL OBSERVATORIES」から3サイトの該当ページへ
   リンクします。リンク自体は収集ではないため安全です。
2. **取込方式（任意）**: 規約に沿って入手した評価（手動転記、または各社との正規提携・ライセンスデータ）
   を `ratings.csv` として置くと、パイプラインが取り込み、★表示と優良企業度スコア
   （働きやすさ30ptの部分）に反映されます。
   - 列: `code,openwork,onecareer,jobtalk`（証券コード4桁、評価は1〜5、空欄可）
   - 取込が無い企業は、勤続年数＋男性育休取得率から働きやすさを推定します

本格的に評価データを載せたい場合は、各社（オープンワーク社など）のデータ提供・API提携の
問い合わせ窓口に正式に相談するのが確実です。

## 公開方法

静的ファイルのみなので、Netlify / Cloudflare Pages / GitHub Pages 等にフォルダごとアップロードするだけです。
`stellarc_data.js` は約1MBになるため、gzip/brotli配信が有効なホスティングを推奨します。

## 月次自動更新（GitHub Actions + Pages）

`.github/workflows/refresh-data.yml` が **毎月1日 09:00 JST** に edinetdb.jp から最新データを取得し、
`stellarc_data.js` を再生成してコミットします。GitHub Pages は main/root から配信され、push を検知して
自動再デプロイされるため、ビルド設定は不要です。手動実行は Actions タブの「Run workflow」から。

### 初回セットアップ手順
1. GitHub で空のリポジトリを作成（例: `stellarc`）し、このフォルダを push
   ```bash
   git remote add origin https://github.com/<user>/stellarc.git
   git push -u origin main
   ```
2. **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `EDINETDB_API_KEY` / Value: edinetdb.jp のキー（`edb_...`）
3. **Settings → Pages → Build and deployment**
   - Source: *Deploy from a branch* / Branch: `main` / フォルダ: `/ (root)`
4. **Settings → Actions → General → Workflow permissions**
   - *Read and write permissions* を有効化（bot がデータをコミットできるように）
5. Actions タブ →「Refresh STELLARC Data」→ Run workflow で初回手動実行 → 公開URLで確認

> `.env.local` / `stellarc_data.json` / `cache/` は `.gitignore` 済みなので、APIキーや中間ファイルは
> コミットされません。サイトが使うのは `stellarc_data.js` のみです。

### 公開前チェックリスト
- [ ] `stellarc_data.js` を生成して同梱（無いとDEMO表示のまま）
- [ ] フッター等に出典表記:「出典: EDINET（金融庁）・JPX。数値は開示情報に基づく推計であり正確性を保証しない」
- [ ] `ratings.csv` を使う場合、データの入手経路が各サイトの規約に適合していることを確認
- [ ] 推計値である旨の免責表示（降下シミュレーション内に組込済み）

## クレジット
- データ: EDINET（金融庁）/ JPX 東証上場銘柄一覧
- 描画: Three.js r128
