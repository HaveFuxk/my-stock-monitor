# -*- coding: utf-8 -*-
"""
downloader_etf.py — 台灣主動式 ETF 持股 daily downloader

來源：yfinance funds_data.top_holdings（涵蓋 14 檔主動式 ETF Top 10 持股）

流程：
  1. 抓 14 檔主動式 ETF 的 Top 10 持股 + 權重
  2. 存 SQLite `data/etf_holdings.db`，key = (date, etf_ticker, stock_ticker)
  3. 跨日 diff：把今日 vs 上次 snapshot 分類成
       added     (新增持股)
       increased (加碼，weight 上升 ≥ 0.2%)
       decreased (減碼，weight 下降 ≥ 0.2%)
       removed   (移出，今日 Top 10 已不在)
  4. 跨 ETF 聚合：個股被幾家 ETF 持有、平均權重、權重變化
  5. 寫 dist/data/etf.json 給前端 dashboard

跟 downloader_chips.py / downloader_macro.py 同個風格 — 容錯為主，
任一 ETF 抓不到不影響其他 14 檔，pipeline 不會 fail。
"""
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB_PATH = Path("data") / "etf_holdings.db"
OUT_FILE = Path("dist") / "data" / "etf.json"

# 11 檔純台股主動式 ETF —— yfinance funds_data.top_holdings 經 recon 可成功取得（2026-05）
# 中文名稱 hardcoded（yfinance.longName 對台股回英文，自己 mapping 比較準）
#
# 已從 14 檔候選中排除 3 檔持股實為美股的（yfinance 對較新台股 ETF 偶爾回到不相關全球持股）：
#   00983A, 00986A, 00990A
# 篩選邏輯：在 runtime 還會再次過濾 — 若該 ETF Top10 含 < 50% 台股就跳過。
ACTIVE_ETFS = {
    "00981A.TW": "主動統一台股增長",
    "00982A.TW": "主動野村臺灣優選",
    "00984A.TW": "主動安聯台灣高息成長",
    "00985A.TW": "主動國泰台灣科技龍頭",
    "00991A.TW": "主動復華台灣科技優選",
    "00992A.TW": "主動統一台ESG優選",
    "00993A.TW": "主動安聯台灣",
    "00994A.TW": "主動野村臺灣科技",
    "00995A.TW": "主動野村台灣高息",
    "00996A.TW": "主動國泰科技優息",
    "00400A.TW": "主動富邦台股入息",
}

# diff 門檻：權重變化 < 0.2% 視為「不變」，避免每日些微浮動全進入 increased/decreased
WEIGHT_DIFF_THRESHOLD = 0.002

# Runtime filter：Top10 含 ≥ MIN_TW_RATIO 比例的台股才視為純台股 ETF
MIN_TW_RATIO = 0.5


def _ensure_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            date TEXT NOT NULL,
            etf_ticker TEXT NOT NULL,
            etf_name TEXT,
            stock_ticker TEXT NOT NULL,
            stock_name TEXT,
            weight REAL,
            PRIMARY KEY (date, etf_ticker, stock_ticker)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_holdings_date ON holdings(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_holdings_etf ON holdings(etf_ticker)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_holdings_stock ON holdings(stock_ticker)")
    conn.commit()
    return conn


def fetch_etf_holdings(yf_ticker: str):
    """
    抓單檔 ETF 的 Top 10 持股，回傳 list of dict：
        [{"stock_ticker": "2330.TW", "stock_name": "...", "weight": 0.0957}, ...]
    失敗回 None（log warning），不 raise。
    """
    try:
        import yfinance as yf
    except ImportError:
        print("⚠️ [etf] yfinance 未安裝，無法抓持股")
        return None
    try:
        t = yf.Ticker(yf_ticker)
        fd = getattr(t, "funds_data", None)
        if fd is None:
            return None
        h = fd.top_holdings
        if not hasattr(h, "__len__") or len(h) == 0:
            return None
        rows = []
        for symbol, row in h.iterrows():
            name = row.get("Name") if hasattr(row, "get") else None
            weight = row.get("Holding Percent") if hasattr(row, "get") else None
            if name is None and "Name" in h.columns:
                name = h.loc[symbol, "Name"]
            if weight is None and "Holding Percent" in h.columns:
                weight = h.loc[symbol, "Holding Percent"]
            rows.append({
                "stock_ticker": str(symbol),
                "stock_name": str(name) if name else "",
                "weight": float(weight) if weight is not None else None,
            })
        return rows
    except Exception as e:
        print(f"⚠️ [etf] {yf_ticker} 抓取失敗：{e}")
        return None


def save_holdings(conn, date_str: str, etf_ticker: str, etf_name: str, holdings: list):
    """寫入 holdings，已存在的 (date, etf_ticker, stock_ticker) 會被取代。"""
    rows = [
        (date_str, etf_ticker, etf_name, h["stock_ticker"], h["stock_name"], h["weight"])
        for h in holdings
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO holdings "
        "(date, etf_ticker, etf_name, stock_ticker, stock_name, weight) "
        "VALUES (?,?,?,?,?,?)",
        rows,
    )
    conn.commit()


def get_prev_holdings(conn, etf_ticker: str, before_date: str):
    """
    取得該 ETF 在 before_date 之前最近一次的持股。
    回傳：(prev_date, dict{stock_ticker: weight}) 或 (None, {}).
    """
    cur = conn.execute(
        "SELECT MAX(date) FROM holdings WHERE etf_ticker = ? AND date < ?",
        (etf_ticker, before_date),
    )
    row = cur.fetchone()
    prev_date = row[0] if row else None
    if not prev_date:
        return None, {}
    cur = conn.execute(
        "SELECT stock_ticker, weight FROM holdings WHERE etf_ticker = ? AND date = ?",
        (etf_ticker, prev_date),
    )
    return prev_date, {r[0]: r[1] for r in cur.fetchall()}


def classify_diff(today: dict, prev: dict, threshold: float = WEIGHT_DIFF_THRESHOLD):
    """
    把 today vs prev 兩個 dict（stock_ticker → weight）分類成 4 組：
        added     昨日無、今日有
        removed   昨日有、今日無
        increased today >= prev + threshold
        decreased today <= prev - threshold

    每筆都帶 stock_ticker（如 "2330.TW"）+ weight_change（小數）。
    """
    added, removed, increased, decreased = [], [], [], []
    for stk, w_today in today.items():
        if stk not in prev:
            added.append({"stock_ticker": stk, "weight": w_today, "weight_change": w_today})
        else:
            delta = (w_today or 0) - (prev[stk] or 0)
            if delta >= threshold:
                increased.append({"stock_ticker": stk, "weight": w_today, "weight_change": delta})
            elif delta <= -threshold:
                decreased.append({"stock_ticker": stk, "weight": w_today, "weight_change": delta})
    for stk, w_prev in prev.items():
        if stk not in today:
            removed.append({"stock_ticker": stk, "weight": None, "weight_change": -w_prev})
    return {
        "added": added,
        "removed": removed,
        "increased": increased,
        "decreased": decreased,
    }


def aggregate_cross_etf(today_snapshot: list):
    """
    跨 ETF 聚合：個股被幾家 ETF 持有 + 平均權重 + ETF 清單。

    today_snapshot: list of dict from build_etf_data()，每筆含 etf_ticker, holdings, diff

    回傳兩個 list：
      by_buy_count: 「被持有最多家 ETF」的個股 (買進排行)
      by_sell_count: 「被減碼/移出最多家 ETF」的個股 (賣出排行)
    每筆：{stock_ticker, stock_name, count, etf_tickers, weight_avg, weight_change_sum}
    """
    by_stock = {}
    sell_by_stock = {}  # 統計 decreased + removed 的次數
    for etf in today_snapshot:
        etf_tk = etf["ticker"]
        for h in etf.get("holdings", []):
            stk = h["stock_ticker"]
            name = h.get("stock_name", "")
            d = by_stock.setdefault(stk, {
                "stock_ticker": stk, "stock_name": name,
                "etf_tickers": [], "weights": [], "change_sum": 0.0,
            })
            d["etf_tickers"].append(etf_tk)
            if h.get("weight") is not None:
                d["weights"].append(h["weight"])
        # 賣出統計：把該 ETF 的 decreased + removed 計入
        diff = etf.get("diff", {})
        for kind in ("decreased", "removed"):
            for it in diff.get(kind, []):
                stk = it["stock_ticker"]
                s = sell_by_stock.setdefault(stk, {
                    "stock_ticker": stk, "stock_name": "",
                    "etf_tickers": [], "change_sum": 0.0,
                })
                s["etf_tickers"].append(etf_tk)
                if it.get("weight_change") is not None:
                    s["change_sum"] += it["weight_change"]
        # 同步把 added + increased 的 change 進 by_stock（用於買進排行的「變化權重」）
        for kind in ("added", "increased"):
            for it in diff.get(kind, []):
                stk = it["stock_ticker"]
                if stk in by_stock and it.get("weight_change") is not None:
                    by_stock[stk]["change_sum"] += it["weight_change"]

    # 整理買進排行：按 count desc，同 count 看 weight_avg
    buy_rank = []
    for stk, d in by_stock.items():
        weights = d["weights"]
        avg = sum(weights) / len(weights) if weights else 0
        buy_rank.append({
            "stock_ticker": stk,
            "stock_name": d["stock_name"],
            "count": len(d["etf_tickers"]),
            "etf_tickers": d["etf_tickers"],
            "weight_avg": avg,
            "weight_change_sum": d["change_sum"],
        })
    buy_rank.sort(key=lambda x: (-x["count"], -x["weight_avg"]))

    sell_rank = []
    for stk, d in sell_by_stock.items():
        sell_rank.append({
            "stock_ticker": stk,
            "stock_name": d["stock_name"],
            "count": len(d["etf_tickers"]),
            "etf_tickers": d["etf_tickers"],
            "weight_change_sum": d["change_sum"],
        })
    sell_rank.sort(key=lambda x: (-x["count"], x["weight_change_sum"]))

    return buy_rank, sell_rank


def build_etf_data(out_path: Path = OUT_FILE):
    """
    主流程：抓所有 ETF Top10 → 存 SQLite → 算 diff → 跨 ETF 聚合 → 寫 dist/data/etf.json
    """
    conn = _ensure_db()
    today_str = datetime.now().strftime("%Y-%m-%d")

    etfs_payload = []
    success, failed = 0, 0
    for yf_tk, etf_name in ACTIVE_ETFS.items():
        etf_code = yf_tk.split(".")[0]
        holdings = fetch_etf_holdings(yf_tk)
        if not holdings:
            failed += 1
            print(f"  ✗ {etf_code} {etf_name} — 抓取失敗")
            continue
        # Runtime filter：剔除 Top 10 不是「以台股為主」的 ETF（避免污染聚合排行）
        tw_count = sum(
            1 for h in holdings
            if h["stock_ticker"].endswith(".TW") or h["stock_ticker"].endswith(".TWO")
        )
        if tw_count < len(holdings) * MIN_TW_RATIO:
            failed += 1
            print(f"  ✗ {etf_code} {etf_name} — 台股比例 {tw_count}/{len(holdings)} < {MIN_TW_RATIO:.0%}，跳過")
            continue
        success += 1

        # diff：今日 vs 上次 snapshot（DB 中該 ETF 的最新非今日記錄）
        today_dict = {h["stock_ticker"]: h["weight"] for h in holdings}
        prev_date, prev_dict = get_prev_holdings(conn, yf_tk, today_str)
        diff = classify_diff(today_dict, prev_dict)

        # 存入 SQLite
        save_holdings(conn, today_str, yf_tk, etf_name, holdings)

        etfs_payload.append({
            "ticker": etf_code,
            "yf_ticker": yf_tk,
            "name": etf_name,
            "holdings": holdings,
            "diff": diff,
            "prev_date": prev_date,
        })
        time.sleep(0.3)  # 避免 yfinance rate limit

    print(f"  共 {success} 檔成功 / {failed} 檔失敗")
    conn.close()

    # 跨 ETF 聚合
    buy_rank, sell_rank = aggregate_cross_etf(etfs_payload)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "date": today_str,
        "etf_count": len(etfs_payload),
        "etfs": etfs_payload,
        "aggregated": {
            "buy_rank": buy_rank,
            "sell_rank": sell_rank,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✅ [etf] 寫入 {out_path} — {len(etfs_payload)} 檔 ETF, "
          f"買進排行 {len(buy_rank)} 檔個股, 賣出排行 {len(sell_rank)} 檔個股")
    return payload


if __name__ == "__main__":
    build_etf_data()
