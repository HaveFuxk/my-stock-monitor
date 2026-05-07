# -*- coding: utf-8 -*-
"""
downloader_chips.py — 三大法人買賣超 daily downloader（TWSE 上市）

策略：
  1. 走 TWSE rwd JSON API 抓 daily 全市場三大法人買賣超
  2. 存到 SQLite `data/chips.db`，table chips(date, ticker, name, foreign_net, trust_net, dealer_net, total_net, market)
  3. update_chips_db(days_back=60) 會抓最近 60 個交易日（自動跳過假日 / 無資料日）
  4. 每天 GH Actions 在 main.py 之前跑一次，累積歷史資料
  5. build_web 從 SQLite query 個股最近 60 天三大法人時序，寫進個股 JSON 的 chips 欄位

注意：TPEX 上櫃 API 介面不同，本 MVP 暫不實作（log warning 即可）。
"""
import sqlite3
import time
import random
import json
import sys
import urllib.request
import urllib.error
import ssl
from datetime import datetime, timedelta
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB_PATH = Path("data") / "chips.db"
TWSE_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"

IS_GITHUB_ACTIONS = (
    str(globals().get("__file__", "")).find("/runner/") >= 0
    or "GITHUB_ACTIONS" in __import__("os").environ
)


def _ssl_ctx():
    """TWSE 證書老舊可能擋，本機關掉嚴格驗證。risk profile：公開股票資料，MITM 影響有限。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _ensure_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chips (
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            name TEXT,
            foreign_net INTEGER,
            trust_net INTEGER,
            dealer_net INTEGER,
            total_net INTEGER,
            market TEXT,
            PRIMARY KEY (date, ticker)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chips_ticker ON chips(ticker)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chips_date ON chips(date)")
    conn.commit()
    return conn


def _parse_int(s: str):
    """TWSE 數字字串（含千分位逗號 / 可能負號 / 可能為空）→ int 或 None"""
    if s is None:
        return None
    t = str(s).strip().replace(",", "").replace(" ", "")
    if not t or t == "--":
        return None
    try:
        return int(float(t))
    except (ValueError, TypeError):
        return None


def fetch_twse_chips(date_obj):
    """
    抓 TWSE 上市單日三大法人買賣超 JSON。
    date_obj: datetime / date 物件。
    回傳 list of dict（已過濾掉空筆）。
    若該日無資料（假日 / API 回 stat != OK）回 []。
    """
    date_str = date_obj.strftime("%Y%m%d")
    url = f"{TWSE_URL}?date={date_str}&selectType=ALL&response=json"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.twse.com.tw/",
    })
    try:
        with urllib.request.urlopen(req, timeout=20, context=_ssl_ctx()) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        print(f"   ⚠️  [{date_str}] TWSE 抓取失敗: {type(e).__name__}: {e}")
        return []

    if data.get("stat") != "OK":
        # 假日 / 無資料
        return []

    fields = data.get("fields") or []
    rows = data.get("data") or []
    if not rows:
        return []

    # field index 對映（用 in field name 搜尋更穩定）
    def find_idx(keyword):
        for i, f in enumerate(fields):
            if keyword in f:
                return i
        return None

    idx_ticker = find_idx("證券代號")
    idx_name = find_idx("證券名稱")
    # "外陸資買賣超股數(不含外資自營商)" 是外資主力
    idx_foreign = find_idx("外陸資買賣超")
    idx_trust = find_idx("投信買賣超")
    idx_total = find_idx("三大法人買賣超")
    # 自營商可能有兩個欄位（自行買賣 / 避險），用「自營商買賣超股數」純名匹配
    idx_dealer = None
    for i, f in enumerate(fields):
        # 找最一般的自營商買賣超（沒帶括號限定）
        if f.strip() == "自營商買賣超股數":
            idx_dealer = i
            break
    if idx_dealer is None:
        # fallback：找第一個含「自營商」+「買賣超」
        idx_dealer = find_idx("自營商買賣超")

    out = []
    for row in rows:
        try:
            ticker = (row[idx_ticker] or "").strip() if idx_ticker is not None else ""
            if not ticker:
                continue
            out.append({
                "date": date_obj.strftime("%Y-%m-%d"),
                "ticker": ticker,
                "name": (row[idx_name] or "").strip() if idx_name is not None else "",
                "foreign_net": _parse_int(row[idx_foreign]) if idx_foreign is not None else None,
                "trust_net": _parse_int(row[idx_trust]) if idx_trust is not None else None,
                "dealer_net": _parse_int(row[idx_dealer]) if idx_dealer is not None else None,
                "total_net": _parse_int(row[idx_total]) if idx_total is not None else None,
                "market": "tw-share",
            })
        except (IndexError, TypeError):
            continue
    return out


def update_chips_db(days_back=60, max_fetches=70):
    """
    抓最近 days_back 天的三大法人資料寫入 SQLite（INSERT OR REPLACE）。
    max_fetches：最多向 API 探詢幾天（含假日空查），避免無窮迴圈。
    回傳 (fetched_dates, total_rows)
    """
    conn = _ensure_db()

    today = datetime.now()
    fetched_dates = []
    total_rows = 0

    # 從今天往前推
    for offset in range(max_fetches):
        d = today - timedelta(days=offset)
        # 跳過週六週日
        if d.weekday() >= 5:
            continue

        date_str = d.strftime("%Y-%m-%d")
        # 已存在則跳過（節省 API call）
        cur = conn.execute("SELECT COUNT(*) FROM chips WHERE date = ?", (date_str,))
        if cur.fetchone()[0] > 0:
            print(f"   📦 [{date_str}] 已有資料，跳過")
        else:
            print(f"   🌐 [{date_str}] 抓 TWSE 三大法人...")
            rows = fetch_twse_chips(d)
            if rows:
                conn.executemany("""
                    INSERT OR REPLACE INTO chips
                    (date, ticker, name, foreign_net, trust_net, dealer_net, total_net, market)
                    VALUES (:date, :ticker, :name, :foreign_net, :trust_net, :dealer_net, :total_net, :market)
                """, rows)
                conn.commit()
                total_rows += len(rows)
                print(f"      ✅ 寫入 {len(rows)} 筆")
            else:
                print(f"      ⚠️  無資料（假日 / API 異常）")

            # 禮貌等待
            sleep_s = random.uniform(0.4, 0.9) if not IS_GITHUB_ACTIONS else random.uniform(1.0, 1.8)
            time.sleep(sleep_s)

        fetched_dates.append(date_str)

        # 已收集到 days_back 天就結束
        cur = conn.execute(
            "SELECT COUNT(DISTINCT date) FROM chips WHERE date <= ? AND date >= ?",
            (today.strftime("%Y-%m-%d"), (today - timedelta(days=days_back + 30)).strftime("%Y-%m-%d"))
        )
        existing_dates = cur.fetchone()[0]
        if existing_dates >= days_back:
            print(f"   ✅ DB 內已有 {existing_dates} 個交易日（>= {days_back}），結束探詢")
            break

    conn.close()
    return fetched_dates, total_rows


def query_chips(ticker: str, days: int = 60):
    """
    給定 ticker（含或不含 .TW 後綴），回最近 days 個交易日的三大法人時序。
    回 list of dict：[{date, foreign_net, trust_net, dealer_net, total_net}, ...]，依日期升序。
    """
    if not DB_PATH.exists():
        return []
    # 去掉後綴 .TW / .TWO
    clean = ticker.split(".")[0].strip()
    if not clean:
        return []
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("""
        SELECT date, foreign_net, trust_net, dealer_net, total_net
        FROM chips
        WHERE ticker = ?
        ORDER BY date DESC
        LIMIT ?
    """, (clean, days))
    rows = cur.fetchall()
    conn.close()
    out = []
    for date, fnet, tnet, dnet, total in reversed(rows):  # 升序
        out.append({
            "date": date,
            "foreign_net": fnet,
            "trust_net": tnet,
            "dealer_net": dnet,
            "total_net": total,
        })
    return out


def main():
    print("=" * 60)
    print("📊 三大法人買賣超 downloader（TWSE 上市）")
    print("=" * 60)
    fetched, total = update_chips_db(days_back=60, max_fetches=80)
    print(f"\n✅ 完成：探詢 {len(fetched)} 天，新寫入 {total} 筆")

    if DB_PATH.exists():
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("SELECT COUNT(*) FROM chips")
        total_rows = cur.fetchone()[0]
        cur = conn.execute("SELECT COUNT(DISTINCT date) FROM chips")
        total_dates = cur.fetchone()[0]
        cur = conn.execute("SELECT MIN(date), MAX(date) FROM chips")
        min_d, max_d = cur.fetchone()
        cur = conn.execute("SELECT COUNT(DISTINCT ticker) FROM chips")
        total_tickers = cur.fetchone()[0]
        conn.close()
        print(f"   DB 累積：{total_rows} 筆，{total_dates} 個交易日，{total_tickers} 檔個股")
        print(f"   時間範圍：{min_d} ~ {max_d}")


if __name__ == "__main__":
    main()
