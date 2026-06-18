#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STELLARC EDINET Pipeline v2.0
================================================================
EDINET API v2 から直近1年分の有価証券報告書を取得し、上場企業の
  平均年収 / 平均年齢 / 平均勤続 / 従業員数 / 営業利益率 / 売上成長率
  人的資本開示（男性育休取得率・女性管理職比率・男女間賃金差異）
  時価総額の概算（発行済株式数 × 年度内最高・最低株価の平均）★v2
を抽出して `stellarc_data.js` を生成する。
生成物を index.html と同じフォルダに置くと、
銀河が自動で LIVE — EDINET モードに切り替わる。

★v2 外部評価（OpenWork / ONE CAREER / 転職会議）の取込:
  これら3サイトの利用規約はスクレイピング（自動収集）を禁止している。
  本パイプラインは収集を行わない。規約に沿って入手した評価
  （手動転記・正規ライセンスデータ等）を ratings.csv に置くと、
  サイト上の「外部観測所」表示と優良企業度スコアに反映される。
    ratings.csv の列: code,openwork,onecareer,jobtalk （いずれも1〜5、空欄可）
    例:               7203,3.8,4.1,3.5

実行方法（あなたのPCで）:
  1) EDINET APIキーを取得（EDINET 操作ガイド参照・無料）
  2) pip install requests pandas xlrd
  3) 環境変数にキーを設定（チャット等には絶対に貼らないこと）
       mac/linux:  export EDINET_API_KEY="あなたのキー"
       windows  :  set EDINET_API_KEY=あなたのキー
  4) python edinet_pipeline.py
     - 全上場企業 約3,800社 / 所要 30〜60分（0.25秒/リクエストで自主的に低速化）
     - 中断しても再実行すれば cache/ から再開（再ダウンロードしない）
     - v1のキャッシュは時価総額欄が無いため自動で取り直す
  5) 動作確認だけしたい場合:  python edinet_pipeline.py --limit 200

出力: stellarc_data.js / stellarc_data.json / cache/（再開用）
注意: 本スクリプトの数値は EDINET 開示情報に基づく推計であり、
      実際の給与・時価総額等を保証するものではない（サイト上にも同旨を表示）。
      特に時価総額は「年度内の最高・最低株価の平均×発行済株式数」による
      粗い概算。正確な時価総額が必要なら J-Quants API（JPX公式・無料プランあり）
      等で株価を取得して差し替えること。
================================================================
"""
import os, sys, io, re, json, time, zipfile, csv, argparse
import datetime as dt
from pathlib import Path

# Windowsコンソール(cp932)で「—」等が出力エラーにならないようUTF-8化
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests

API = "https://api.edinet-fsa.go.jp/api/v2"
KEY = os.environ.get("EDINET_API_KEY", "").strip()
JPX_XLS_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"

ROOT   = Path(__file__).resolve().parent
CACHE  = ROOT / "cache"
CACHE_LIST = CACHE / "list"
CACHE_DOC  = CACHE / "docs"
for p in (CACHE_LIST, CACHE_DOC): p.mkdir(parents=True, exist_ok=True)

SLEEP = 0.25          # リクエスト間隔（行政APIへの礼儀）
LOOKBACK_DAYS = 380   # 有報は決算後3ヶ月以内提出 → 1年強で全社を網羅

session = requests.Session()
session.headers["User-Agent"] = "STELLARC-pipeline/2.0 (research; contact via site)"

# ----------------------------------------------------------------
# 0. JPX 33業種マップ（証券コード4桁 → 業種名・市場区分）
# ----------------------------------------------------------------
def load_jpx_map():
    """JPX「東証上場銘柄一覧」(data_j.xls) から code->(業種, 市場) を作る"""
    local = ROOT / "data_j.xls"
    try:
        import pandas as pd
        if local.exists():
            df = pd.read_excel(local, dtype=str)
        else:
            print("  JPX銘柄一覧をダウンロード中 ...")
            r = session.get(JPX_XLS_URL, timeout=60); r.raise_for_status()
            local.write_bytes(r.content)
            df = pd.read_excel(io.BytesIO(r.content), dtype=str)
        m = {}
        for _, row in df.iterrows():
            code = str(row.get("コード", "")).strip()
            ind  = str(row.get("33業種区分", "")).strip()
            mkt  = str(row.get("市場・商品区分", "")).strip()
            if not code or ind in ("", "-", "nan"): continue
            mseg = "プライム" if "プライム" in mkt else "スタンダード" if "スタンダード" in mkt \
                   else "グロース" if "グロース" in mkt else mkt
            m[code.zfill(4)] = (ind, mseg)
        print(f"  JPX業種マップ: {len(m)}銘柄")
        return m
    except Exception as e:
        print(f"  [警告] JPX銘柄一覧の取得に失敗: {e}")
        print("  → https://www.jpx.co.jp/markets/statistics-equities/misc/01.html から")
        print("    data_j.xls を手動DLし、このスクリプトと同じフォルダに置いて再実行してください。")
        return {}

# ----------------------------------------------------------------
# 0b. 外部評価 ratings.csv（任意・規約準拠で入手した値のみ）
# ----------------------------------------------------------------
def load_ratings():
    """ratings.csv: code,openwork,onecareer,jobtalk（1〜5、空欄可）→ code4 -> dict"""
    f = ROOT / "ratings.csv"
    if not f.exists():
        print("  ratings.csv なし — 外部評価は未取込（サイト側はリンクのみ表示）")
        return {}
    out = {}
    def num(v):
        try:
            x = float(str(v).strip())
            return round(x, 1) if 1.0 <= x <= 5.0 else None
        except (ValueError, TypeError):
            return None
    with open(f, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            code = str(row.get("code", "")).strip()[:4]
            if not code: continue
            out[code.zfill(4)] = {
                "ow": num(row.get("openwork")),
                "oc": num(row.get("onecareer")),
                "jt": num(row.get("jobtalk")),
            }
    print(f"  ratings.csv: {len(out)}社分の外部評価を取込")
    return out

# ----------------------------------------------------------------
# 1. 書類一覧（日次）から有価証券報告書を列挙
# ----------------------------------------------------------------
def list_yuho_docs():
    today = dt.date.today()
    docs = {}
    days = [today - dt.timedelta(days=i) for i in range(LOOKBACK_DAYS)]
    for i, d in enumerate(days):
        cache_f = CACHE_LIST / f"{d.isoformat()}.json"
        if cache_f.exists():
            data = json.loads(cache_f.read_text(encoding="utf-8"))
        else:
            r = session.get(f"{API}/documents.json",
                            params={"date": d.isoformat(), "type": 2,
                                    "Subscription-Key": KEY}, timeout=30)
            if r.status_code == 401:
                sys.exit("[エラー] APIキーが無効です (401)。環境変数 EDINET_API_KEY を確認してください。")
            r.raise_for_status()
            data = r.json()
            cache_f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            time.sleep(SLEEP)
        for doc in (data.get("results") or []):
            # 有価証券報告書: 府令010 / 様式コード120, 訂正は除外, 上場(secCodeあり), CSVあり
            if doc.get("docTypeCode") != "120": continue
            if doc.get("ordinanceCode") != "010": continue
            if not doc.get("secCode"): continue
            if doc.get("csvFlag") != "1": continue
            code4 = str(doc["secCode"])[:4]
            cur = docs.get(code4)
            if cur is None or (doc.get("submitDateTime") or "") > (cur.get("submitDateTime") or ""):
                docs[code4] = doc
        if i % 30 == 0:
            print(f"  書類一覧走査 {i+1}/{len(days)} 日 ... 有報 {len(docs)} 社", end="\r")
    print(f"\n  有価証券報告書: {len(docs)} 社分を検出")
    return docs

# ----------------------------------------------------------------
# 2. 1社分のCSV(XBRL)を取得・パース
# ----------------------------------------------------------------
NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
def parse_num(v):
    if v is None: return None
    s = str(v).replace(",", "").replace("△", "-").replace("−", "-").strip()
    m = NUM_RE.search(s)
    return float(m.group()) if m else None

def read_csv_rows(zbytes):
    rows = []
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        for name in z.namelist():
            if not name.lower().endswith(".csv"): continue
            if "jpcrp" not in name and "jppfs" not in name: continue
            raw = z.read(name)
            try:   text = raw.decode("utf-16")
            except UnicodeError:
                try: text = raw.decode("utf-8-sig")
                except UnicodeError: continue
            rdr = csv.DictReader(io.StringIO(text), delimiter="\t")
            for r in rdr:
                rows.append(r)
    return rows

def pick(rows, must_substrs, ctx_must=None, ctx_prefer=None, ctx_avoid=None):
    """要素IDに must_substrs を全て含む行から、コンテキスト条件で最良値を選ぶ"""
    best, best_score = None, -99
    for r in rows:
        eid = (r.get("要素ID") or "")
        if not all(s.lower() in eid.lower() for s in must_substrs): continue
        ctx = (r.get("コンテキストID") or "")
        if ctx_must and ctx_must not in ctx: continue
        v = parse_num(r.get("値"))
        if v is None: continue
        score = 0
        if ctx_prefer and ctx_prefer in ctx: score += 2
        if ctx_avoid  and ctx_avoid  in ctx: score -= 2
        if "Member" not in ctx: score += 1     # セグメント別より全社値を優先
        if score > best_score: best, best_score = v, score
    return best

def pct_norm(v):
    """0.45 と 45.0 が混在する開示値を % に正規化"""
    if v is None: return None
    return v*100 if 0 < v <= 1.5 else v

def extract_company(doc):
    doc_id = doc["docID"]
    cache_f = CACHE_DOC / f"{doc_id}.json"
    if cache_f.exists():
        cached = json.loads(cache_f.read_text(encoding="utf-8"))
        # v1キャッシュ（mktcap欄なし）は取り直す
        if cached is None or "mktcap" in cached:
            return cached
    r = session.get(f"{API}/documents/{doc_id}",
                    params={"type": 5, "Subscription-Key": KEY}, timeout=60)
    time.sleep(SLEEP)
    if r.status_code != 200 or not r.content[:2] == b"PK":
        cache_f.write_text("null", encoding="utf-8"); return None
    try:
        rows = read_csv_rows(r.content)
    except Exception:
        cache_f.write_text("null", encoding="utf-8"); return None

    salary  = pick(rows, ["AverageAnnualSalary"])
    age     = pick(rows, ["AverageAgeYears"])
    tenure  = pick(rows, ["AverageLengthOfService"])
    empl_c  = pick(rows, ["NumberOfEmployees"], ctx_must="CurrentYear", ctx_avoid="NonConsolidated")
    empl_n  = pick(rows, ["NumberOfEmployees"], ctx_must="CurrentYear", ctx_prefer="NonConsolidated")
    empl    = empl_c or empl_n
    # 売上・営業利益（jppfs / IFRS の主要パターンを順に探索）
    sales_cur = sales_pri = op = None
    for tag in (["NetSales"], ["RevenueIFRS"], ["Revenue"], ["OperatingRevenue"], ["OrdinaryIncomeBNK"]):
        sales_cur = pick(rows, tag, ctx_must="CurrentYearDuration", ctx_avoid="NonConsolidated") \
                 or pick(rows, tag, ctx_must="CurrentYearDuration")
        if sales_cur:
            sales_pri = pick(rows, tag, ctx_must="Prior1YearDuration", ctx_avoid="NonConsolidated") \
                     or pick(rows, tag, ctx_must="Prior1YearDuration")
            break
    for tag in (["OperatingIncome"], ["OperatingProfitLossIFRS"], ["OperatingProfitLoss"]):
        op = pick(rows, tag, ctx_must="CurrentYearDuration", ctx_avoid="NonConsolidated") \
          or pick(rows, tag, ctx_must="CurrentYearDuration")
        if op is not None: break
    margin = (op/sales_cur*100) if (op is not None and sales_cur) else None
    growth = ((sales_cur/sales_pri - 1)*100) if (sales_cur and sales_pri) else None
    # 人的資本開示（2023年〜）
    papa    = pct_norm(pick(rows, ["ChildcareLeave"]))
    fkanri  = pct_norm(pick(rows, ["Female", "Management"]))
    wagegap = pct_norm(pick(rows, ["WageDifference"]) or pick(rows, ["Difference", "Wage"]))

    # ★v2 時価総額の概算（億円）:
    #   発行済株式数 ×（主要な経営指標等の推移に開示される 年度内最高・最低株価の平均）
    shares = pick(rows, ["TotalNumberOfIssuedShares"]) \
          or pick(rows, ["NumberOfIssuedShares"])
    p_hi = pick(rows, ["Highest", "StockPrice"], ctx_prefer="CurrentYear")
    p_lo = pick(rows, ["Lowest",  "StockPrice"], ctx_prefer="CurrentYear")
    price = None
    if p_hi and p_lo and 0 < p_lo <= p_hi: price = (p_hi + p_lo) / 2
    elif p_hi: price = p_hi
    elif p_lo: price = p_lo
    mktcap = None
    if shares and price and shares > 1000:
        mc = shares * price / 1e8            # 円 → 億円
        if 1 <= mc <= 1_000_000:             # 1億〜100兆円の範囲のみ採用
            mktcap = round(mc, 1)

    def to_man(v):  # 円 / 千円 表記ゆれ → 万円
        if v is None: return None
        if v > 100000: return round(v/10000)   # 円
        if v > 3000:   return round(v/10)      # 千円
        return round(v)                        # 既に万円相当
    out = {
        "code":  str(doc.get("secCode"))[:4],
        "name":  (doc.get("filerName") or "").strip(),
        "fy":    (doc.get("periodEnd") or "")[:10],
        "salary": to_man(salary),
        "age":    age, "tenure": tenure,
        "empl":   int(empl) if empl else None,
        "margin": round(margin, 2) if margin is not None and -100 < margin < 100 else None,
        "growth": round(growth, 2) if growth is not None and -95 < growth < 400 else None,
        "papa":   round(papa, 1)   if papa   is not None and 0 <= papa   <= 100 else None,
        "fkanri": round(fkanri, 1) if fkanri is not None and 0 <= fkanri <= 100 else None,
        "wagegap":round(wagegap,1) if wagegap is not None and 0 <  wagegap<= 150 else None,
        "mktcap": mktcap,
    }
    cache_f.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out

# ----------------------------------------------------------------
# 3. メイン
# ----------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="先頭N社のみ処理（動作確認用）")
    args = ap.parse_args()

    if not KEY:
        sys.exit("[エラー] 環境変数 EDINET_API_KEY が未設定です。READMEの手順を参照。\n"
                 "        ※キーをソースコードやチャットに貼らないでください。")

    print("[1/5] JPX業種マップを構築")
    jpx = load_jpx_map()

    print("[2/5] 外部評価 ratings.csv を確認（任意）")
    ratings = load_ratings()

    print("[3/5] EDINET書類一覧から有価証券報告書を列挙（初回は数分）")
    docs = list_yuho_docs()

    items = sorted(docs.items())
    if args.limit: items = items[:args.limit]

    print(f"[4/5] {len(items)} 社の有報CSVを取得・抽出（cache/ から自動再開）")
    out, ok = [], 0
    for i, (code4, doc) in enumerate(items, 1):
        try:
            c = extract_company(doc)
        except KeyboardInterrupt:
            print("\n  中断しました。再実行すると続きから処理します。"); break
        except Exception:
            c = None
        if c and c.get("salary"):
            ind, mkt = jpx.get(code4, (None, None))
            c["ind"], c["market"] = ind, mkt
            r = ratings.get(code4)
            if r:
                c["ow"], c["oc"], c["jt"] = r["ow"], r["oc"], r["jt"]
            out.append(c); ok += 1
        if i % 25 == 0 or i == len(items):
            print(f"  {i}/{len(items)} 社処理 ... 年収抽出成功 {ok} 社", end="\r")
            # 途中保存（クラッシュ耐性）
            (ROOT/"stellarc_data.json").write_text(
                json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print()

    print("[5/5] 出力ファイル生成")
    out.sort(key=lambda c: c["code"])
    (ROOT/"stellarc_data.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT/"stellarc_data.js").write_text(
        "// generated by edinet_pipeline.py v2 / source: EDINET (金融庁) + JPX"
        " / ratings.csv（規約準拠で入手した外部評価のみ）\n"
        "window.STELLARC_DATA=" + json.dumps(out, ensure_ascii=False) + ";",
        encoding="utf-8")
    n_ind = sum(1 for c in out if c.get("ind"))
    n_hc  = sum(1 for c in out if c.get("papa") is not None)
    n_mc  = sum(1 for c in out if c.get("mktcap") is not None)
    n_rt  = sum(1 for c in out if c.get("ow") is not None or c.get("oc") is not None or c.get("jt") is not None)
    print(f"  完了: {len(out)} 社（業種付与 {n_ind} / 人的資本あり {n_hc} / 時価総額あり {n_mc} / 外部評価あり {n_rt}）")
    print("  → stellarc_data.js を index.html と同じ場所に置いて開いてください。")
    print("    画面右上が「LIVE — EDINET」表示になれば本番銀河です。")

if __name__ == "__main__":
    main()
