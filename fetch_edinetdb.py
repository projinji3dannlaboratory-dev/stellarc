#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STELLARC データ取得（edinetdb.jp 版） v1.0  ★推奨
================================================================
edinetdb.jp（Cabocia Inc. / 金融庁EDINETを構造化して配信）の
/v1/screener から、上場全社のデータを数十リクエストで取得し
`stellarc_data.js` を生成する。

直接EDINETを叩く edinet_pipeline.py（30〜60分／株価=時価総額は取れない）
に対し、こちらは:
  ・時価総額(market-cap) を含む財務指標がそのまま取れる ★最大の利点
  ・営業利益率 / 売上成長率 / 健全性スコア / 女性管理職比率 / 男性育休取得率
  ・全社で 1〜2 分程度（無料枠 100req/日に対し ~30req）

なぜ複数回に分けて取得するか:
  screener は「条件に渡した指標」を列として返すと同時に、その指標を
  持たない社を除外（AND絞り込み）する。男性育休(約1,900社)・女性管理職
  (約2,700社)はカバレッジが低いため、財務系と同じクエリに混ぜると全体が
  削られる。そこで指標グループごとに別々に走査し、edinetCodeでマージする。

実行方法:
  1) edinetdb.jp でAPIキーを無料取得（edb_... 形式）
  2) pip install requests
  3) 環境変数に設定:  set EDINETDB_API_KEY=あなたのキー   （チャット等に貼らない）
     ※同梱の salary-ranking-jp/.env.local がある場合は自動で読みます
  4) python fetch_edinetdb.py
  5) 動作確認のみ:  python fetch_edinetdb.py --limit 300

出力: stellarc_data.js / stellarc_data.json
外部評価(OpenWork/ONE CAREER/転職会議)は規約準拠で入手した ratings.csv が
あれば取り込む（code,openwork,onecareer,jobtalk の各1〜5）。

注意: 数値は edinetdb.jp 経由のEDINET開示情報に基づく推計であり、実際の
      給与・時価総額等を保証するものではない（サイト上にも同旨を表示）。
      market-cap は edinetdb の単位「百万円」を STELLARC 用に「億円」へ換算。
================================================================
"""
import os, sys, io, csv, json, time, argparse
from pathlib import Path

# Windowsコンソール(cp932)対策
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests

BASE = "https://edinetdb.jp/v1"
ROOT = Path(__file__).resolve().parent

# ---- APIキー: 環境変数 → 近傍の .env.local の順で取得 ----
def find_key():
    k = os.environ.get("EDINETDB_API_KEY", "").strip()
    if k:
        return k
    for cand in (ROOT / ".env.local",
                 ROOT.parent.parent / "projects" / "salary-ranking-jp" / ".env.local"):
        try:
            if cand.exists():
                for line in cand.read_text(encoding="utf-8").splitlines():
                    if line.startswith("EDINETDB_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return ""

KEY = find_key()

# ---- 取得する指標グループ（カバレッジで分割） ----
# value はヌル除外を最小化するため十分小さい下限を使う
LOW = -1e15
WALKS = {
    "core": [   # 高カバレッジの基礎・財務
        ("avg-annual-salary", 0), ("avg-age", 0), ("avg-tenure-years", LOW),
        ("num-employees", LOW), ("operating-margin", LOW), ("revenue-growth", LOW),
        ("health-score", LOW), ("net-margin", LOW), ("roe", LOW), ("revenue", LOW),
    ],
    "cap": [    # 時価総額・バリュエーション
        ("market-cap", 0), ("per", LOW), ("pbr", LOW), ("eps", LOW), ("equity-ratio", LOW),
    ],
    "female": [ ("female-manager-ratio", -1), ("female-director-ratio", -1) ],
    "parental": [ ("male-parental-leave-ratio", -1) ],
}

# edinetdb の業種名 → STELLARC(東証33業種)表記 の差異を吸収
IND_ALIAS = {
    "倉庫・運輸関連": "倉庫・運輸関連業",
    "証券・商品先物取引業": "証券、商品先物取引業",
    "証券業": "証券、商品先物取引業",
}
SALARY_FLOOR = 120   # 平均年収(万円)の下限。これ未満は開示異常値とみなし除外

session = requests.Session()
session.headers.update({"X-API-Key": KEY, "User-Agent": "STELLARC-fetch/1.0"})

def screener_walk(metrics, *, page_size=500, sort=None, limit_total=0):
    """1グループぶんを offset ページングで全件取得し edinetCode->row を返す"""
    conditions = [{"metric": m, "operator": "gte", "value": v} for m, v in metrics]
    cj = json.dumps(conditions, ensure_ascii=False)
    out, offset = {}, 0
    while True:
        params = {"conditions": cj, "limit": page_size, "offset": offset, "order": "desc"}
        if sort:
            params["sort"] = sort
        for attempt in range(4):
            try:
                r = session.get(f"{BASE}/screener", params=params, timeout=60)
                if r.status_code == 401:
                    sys.exit("[エラー] APIキーが無効です(401)。EDINETDB_API_KEY を確認してください。")
                if r.status_code == 429:
                    time.sleep(5 * (attempt + 1)); continue
                r.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
        body = r.json()
        if "error" in body:
            sys.exit(f"[エラー] edinetdb: {body['error']}")
        data = body.get("data", {})
        rows = data.get("companies", [])
        total = int(data.get("total", 0))
        if not rows:
            break
        for row in rows:
            ec = row.get("edinetCode")
            if ec:
                out[ec] = row
        offset += len(rows)
        print(f"    {offset}/{total}", end="\r")
        time.sleep(0.2)
        if offset >= total or (limit_total and offset >= limit_total):
            break
    print(f"    {len(out)} 社" + " " * 12)
    return out

def num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def rnd(v, n=1):
    return None if v is None else round(v, n)

def load_ratings():
    f = ROOT / "ratings.csv"
    if not f.exists():
        return {}
    out = {}
    def r5(v):
        try:
            x = float(str(v).strip()); return round(x, 1) if 1 <= x <= 5 else None
        except (ValueError, TypeError):
            return None
    with open(f, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            c = str(row.get("code", "")).strip()[:4]
            if c:
                out[c.zfill(4)] = {"ow": r5(row.get("openwork")),
                                   "oc": r5(row.get("onecareer")),
                                   "jt": r5(row.get("jobtalk"))}
    print(f"  ratings.csv: {len(out)} 社の外部評価を取込")
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="各グループ先頭N社のみ（動作確認用）")
    args = ap.parse_args()
    if not KEY:
        sys.exit("[エラー] EDINETDB_API_KEY が未設定です。\n"
                 "  edinetdb.jp でキーを取得し  set EDINETDB_API_KEY=...  で設定してください。")

    print("[1/4] screener から指標グループごとに取得")
    walks = {}
    for name, metrics in WALKS.items():
        print(f"  - {name}（{len(metrics)}指標）")
        sort = "market-cap" if name == "cap" else ("avg-annual-salary" if name == "core" else None)
        walks[name] = screener_walk(metrics, sort=sort, limit_total=args.limit)

    print("[2/4] 外部評価 ratings.csv を確認（任意）")
    ratings = load_ratings()

    print("[3/4] edinetCode でマージし STELLARC スキーマへ変換")
    core, cap, fem, par = walks["core"], walks["cap"], walks["female"], walks["parental"]
    out = []
    for ec, row in core.items():
        sal = num(row.get("avg-annual-salary"))
        if not sal or sal < SALARY_FLOOR:
            continue
        sec = (row.get("secCode") or "")
        code4 = sec[:4] if sec else None
        c = cap.get(ec, {})
        mc_man = num(c.get("market-cap"))         # 単位: 百万円
        mktcap = round(mc_man / 100, 1) if mc_man and mc_man > 0 else None  # → 億円
        ind = (row.get("industry") or "").strip()
        ind = IND_ALIAS.get(ind, ind)
        rec = {
            "code":   code4,
            "name":   row.get("filerName") or "",
            "ind":    ind,
            "market": None,
            "empl":   int(num(row.get("num-employees"))) if num(row.get("num-employees")) else None,
            "salary": round(sal),
            "age":    rnd(num(row.get("avg-age"))),
            "tenure": rnd(num(row.get("avg-tenure-years"))),
            "margin": rnd(num(row.get("operating-margin"))),
            "growth": rnd(num(row.get("revenue-growth"))),
            "mktcap": mktcap,
            "health": rnd(num(row.get("health-score"))),
            "papa":   rnd(num((par.get(ec) or {}).get("male-parental-leave-ratio"))),
            "fkanri": rnd(num((fem.get(ec) or {}).get("female-manager-ratio"))),
            "wagegap": None,
            "ow": None, "oc": None, "jt": None,
        }
        r = ratings.get(code4 or "")
        if r:
            rec["ow"], rec["oc"], rec["jt"] = r["ow"], r["oc"], r["jt"]
        out.append(rec)

    out.sort(key=lambda c: (c["code"] is None, c["code"] or ""))

    print("[4/4] 出力ファイル生成")
    (ROOT / "stellarc_data.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "stellarc_data.js").write_text(
        "// generated by fetch_edinetdb.py / source: EDINET(金融庁) via edinetdb.jp"
        " + ratings.csv（規約準拠で入手した外部評価のみ）\n"
        "window.STELLARC_DATA=" + json.dumps(out, ensure_ascii=False) + ";",
        encoding="utf-8")
    n_mc = sum(1 for c in out if c.get("mktcap") is not None)
    n_mg = sum(1 for c in out if c.get("margin") is not None)
    n_gr = sum(1 for c in out if c.get("growth") is not None)
    n_pa = sum(1 for c in out if c.get("papa") is not None)
    n_fk = sum(1 for c in out if c.get("fkanri") is not None)
    n_rt = sum(1 for c in out if c.get("ow") or c.get("oc") or c.get("jt"))
    print(f"  完了: {len(out)} 社")
    print(f"        時価総額 {n_mc} / 営業利益率 {n_mg} / 売上成長率 {n_gr}")
    print(f"        男性育休 {n_pa} / 女性管理職 {n_fk} / 外部評価 {n_rt}")
    print("  → stellarc_data.js を index.html と同じ場所に置いて開いてください。")
    print("    画面右上が「LIVE — EDINET」表示になれば本番銀河です。")

if __name__ == "__main__":
    main()
