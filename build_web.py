# -*- coding: utf-8 -*-
"""
build_web.py — 把 analyzer 跑出來的 PNG 與文字報表打包成靜態網站

兩種使用方式：
  1) 從 main.py 呼叫：build(images, report_df, text_reports, market_id)
     - 主要路徑，由 main.py 在 analyzer 跑完後呼叫
     - 會產出 dist/index.html + dist/images/*.png
     - 同時把 text_reports + meta dump 到 output/web_meta.json，方便 standalone 重建

  2) 本地 standalone 測試：python build_web.py
     - 從 output/images/tw-share/ 撈 PNG
     - 從 output/web_meta.json 讀 text_reports（若無，圖區仍可看）
     - 不會重新跑 analyzer
"""
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Windows console (cp950) 不支援 emoji，本機跑時轉 utf-8 才不會 print 失敗
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

DIST_DIR = Path("dist")
OUTPUT_DIR = Path("output")
META_FILE = OUTPUT_DIR / "web_meta.json"

LABEL_MAP = {
    "week_high": "週 K 最高-進攻",
    "week_close": "週 K 收盤-實質",
    "week_low": "週 K 最低-防禦",
    "month_high": "月 K 最高-進攻",
    "month_close": "月 K 收盤-實質",
    "month_low": "月 K 最低-防禦",
    "year_high": "年 K 最高-進攻",
    "year_close": "年 K 收盤-實質",
    "year_low": "年 K 最低-防禦",
}

PERIOD_ZH = {"Week": "週 K", "Month": "月 K", "Year": "年 K"}

# 排版用：圖卡顯示順序（時間 × 類型）
PERIOD_ORDER = {"week": 0, "month": 1, "year": 2}
TYPE_ORDER = {"high": 0, "close": 1, "low": 2}


def _img_sort_key(item):
    """以 'week_high' / 'month_close' 等 id 排序：時間（週→月→年）× 類型（最高→收盤→最低）"""
    img_id = item.get("id", "")
    parts = img_id.split("_")
    if len(parts) != 2:
        return (99, 99, img_id)
    period, typ = parts
    return (PERIOD_ORDER.get(period, 99), TYPE_ORDER.get(typ, 99), img_id)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>my-stock-monitor — 台股動能監控</title>
<meta name="description" content="台股全市場動能分布監控 - 週/月/年 × 最高/收盤/最低 報酬分布">
<style>
:root {{
  --bg: #fafafa;
  --card: #ffffff;
  --text: #1f2328;
  --muted: #656d76;
  --border: #d0d7de;
  --accent: #0969da;
  --danger: #cf222e;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #0d1117;
    --card: #161b22;
    --text: #e6edf3;
    --muted: #8b949e;
    --border: #30363d;
    --accent: #58a6ff;
    --danger: #ff7b72;
  }}
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft JhengHei", "PingFang TC", sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
  padding: 1rem;
}}
.container {{ max-width: 1200px; margin: 0 auto; }}
h1 {{ margin: 0 0 0.25rem 0; font-size: 1.75rem; }}
h2 {{ margin: 1.5rem 0 0.75rem 0; font-size: 1.25rem; }}
.meta {{
  color: var(--muted);
  font-size: 0.9rem;
  margin-bottom: 1.5rem;
  border-bottom: 1px solid var(--border);
  padding-bottom: 1rem;
}}
.meta a {{ color: var(--accent); text-decoration: none; }}
.meta a:hover {{ text-decoration: underline; }}
.grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 1rem;
  margin-bottom: 2rem;
}}
.card {{
  background: var(--card);
  padding: 0.75rem;
  border-radius: 8px;
  border: 1px solid var(--border);
}}
.card img {{
  width: 100%;
  height: auto;
  display: block;
  border-radius: 4px;
}}
.card .label {{
  font-size: 0.85rem;
  color: var(--muted);
  margin-top: 0.5rem;
  text-align: center;
}}
.report {{
  background: var(--card);
  padding: 1rem;
  border-radius: 8px;
  border: 1px solid var(--border);
  margin-bottom: 1rem;
  overflow-x: auto;
}}
.report h2 {{ margin-top: 0; }}
.report pre {{
  font-family: ui-monospace, "SF Mono", "Cascadia Mono", Menlo, monospace;
  font-size: 0.82rem;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}}
.report a {{ color: var(--accent); text-decoration: none; }}
.report a:hover {{ text-decoration: underline; }}
.footer {{
  text-align: center;
  color: var(--muted);
  font-size: 0.85rem;
  margin-top: 2rem;
  padding: 1rem 0;
  border-top: 1px solid var(--border);
}}
</style>
</head>
<body>
<div class="container">
  <h1>🇹🇼 my-stock-monitor</h1>
  <p class="meta">
    最後更新：<strong>{updated_at}</strong>（台北時間）
    · 樣本數：<strong>{sample_count}</strong>
    · 市場：<strong>{market_id}</strong>
    · <a href="https://github.com/HaveFuxk/my-stock-monitor" rel="noopener">GitHub</a>
  </p>
  <p class="meta" style="margin-top: -0.75rem;">
    💡 下方飆股清單中，點任一代號即可查看該檔個股 K 線（站內 TradingView 互動圖）。
  </p>

  <h2>動能分布圖（週 / 月 / 年 × 最高 / 收盤 / 最低）</h2>
  <div class="grid">
    {image_cards}
  </div>

  {text_sections}

  <div class="footer">
    Built by GitHub Actions · Hosted on Cloudflare Pages
  </div>
</div>
</body>
</html>
"""


def now_taipei_str() -> str:
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")


def _label_for(img_id: str, fallback: str = "") -> str:
    return LABEL_MAP.get(img_id, fallback or img_id)


def _render_image_cards(image_items):
    """image_items: list of {'id', 'filename', 'label'}，會依時間×類型排序"""
    sorted_items = sorted(image_items, key=_img_sort_key)
    cards = []
    for item in sorted_items:
        cards.append(
            f'<div class="card">'
            f'<img src="images/{item["filename"]}" alt="{item["label"]}" loading="lazy">'
            f'<div class="label">{item["label"]}</div>'
            f'</div>'
        )
    return "\n    ".join(cards)


def _render_text_sections(text_reports):
    if not text_reports:
        return ""
    sections = []
    for period in ["Week", "Month", "Year"]:
        if period in text_reports and text_reports[period]:
            sections.append(
                f'<div class="report">'
                f'<h2>{PERIOD_ZH[period]} 最高-進攻 報酬分布</h2>'
                f'<pre>{text_reports[period]}</pre>'
                f'</div>'
            )
    return "\n  ".join(sections)


def _calc_ma(closes, window):
    """簡單移動平均；前 window-1 天 None；用純 Python 算（不依賴 numpy 也能跑）"""
    out = [None] * len(closes)
    if len(closes) < window:
        return out
    s = sum(closes[:window])
    out[window - 1] = s / window
    for i in range(window, len(closes)):
        s += closes[i] - closes[i - window]
        out[i] = s / window
    return out


def _calc_rsi(closes, period=14):
    """
    Wilder's RSI(period)，跟 TradingView / 大多技術分析平台一致。
    前 period 天為 None（需 period+1 個 close 才能算第一個 RSI）。
    """
    n = len(closes)
    out = [None] * n
    if n <= period:
        return out

    # 計算每日漲跌
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        if d > 0:
            gains[i] = d
        elif d < 0:
            losses[i] = -d

    # SMA seed (index = period)
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    if avg_loss == 0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100.0 - 100.0 / (1.0 + rs)

    # Wilder smoothing
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def _calc_ema(values, period):
    """EMA(period)，種子用前 period 個的 SMA。回傳跟 values 等長 list（前 period-1 是 None）。"""
    n = len(values)
    out = [None] * n
    if n < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    alpha = 2.0 / (period + 1)
    for i in range(period, n):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def _calc_macd(closes, fast=12, slow=26, signal=9):
    """
    MACD(fast, slow, signal)：
        macd_line = EMA(close, fast) - EMA(close, slow)
        signal_line = EMA(macd_line, signal)
        hist = macd_line - signal_line
    回傳三條 list，皆與 closes 等長，無資料的位置為 None。
    """
    n = len(closes)
    macd_line = [None] * n
    signal_line = [None] * n
    hist = [None] * n
    if n < slow:
        return macd_line, signal_line, hist

    ema_fast = _calc_ema(closes, fast)
    ema_slow = _calc_ema(closes, slow)
    for i in range(n):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]

    # 從 macd_line 第一個非 None 開始算 signal EMA
    first_idx = next((i for i, v in enumerate(macd_line) if v is not None), None)
    if first_idx is None:
        return macd_line, signal_line, hist

    macd_segment = macd_line[first_idx:]
    if len(macd_segment) < signal:
        return macd_line, signal_line, hist
    sig_segment = _calc_ema(macd_segment, signal)
    for j, v in enumerate(sig_segment):
        if v is not None:
            signal_line[first_idx + j] = v
            if macd_line[first_idx + j] is not None:
                hist[first_idx + j] = macd_line[first_idx + j] - v
    return macd_line, signal_line, hist


def _fetch_yf_info(ticker):
    """
    撈 yfinance.info 抓基本面（市值/PE/EPS/殖利率/行業/簡介等）。
    yfinance 對台股 .info 支援可能不完整，部分欄位會是 None。
    遇 rate limit / network error 直接回 None，不重試（不阻塞 build）。
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception:
        return None

    # 只挑 chart.html 顯示用得到的欄位（控制 JSON size）
    fields = {
        "longName": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "marketCap": info.get("marketCap"),
        "trailingPE": info.get("trailingPE"),
        "forwardPE": info.get("forwardPE"),
        "trailingEps": info.get("trailingEps"),
        "dividendYield": info.get("dividendYield"),
        "beta": info.get("beta"),
        "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh"),
        "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow"),
        "averageVolume": info.get("averageVolume"),
        "fullTimeEmployees": info.get("fullTimeEmployees"),
        "country": info.get("country"),
        "website": info.get("website"),
        "longBusinessSummary": info.get("longBusinessSummary"),
    }
    # 全部 None 則視為無資料
    if all(v is None for v in fields.values()):
        return None
    return fields


# Phase 3：大型股白名單。Top 100 飆股大多是妖股，使用者搜尋的反而是這些大型股。
# 用市值排名的代理：直接寫死台股權重前 ~30 大的代號，強制納入 yfinance.info 抓取範圍。
INFO_WHITELIST_TW = {
    # 半導體龍頭
    "2330.TW", "2454.TW", "2308.TW", "2382.TW", "3008.TW",
    # 電子組裝 / 系統
    "2317.TW", "2301.TW", "2353.TW", "2376.TW",
    # 金融
    "2881.TW", "2882.TW", "2883.TW", "2884.TW", "2885.TW",
    "2886.TW", "2887.TW", "2890.TW", "2891.TW", "2892.TW", "5880.TW",
    # 傳統產業
    "1101.TW", "1216.TW", "1301.TW", "1303.TW", "1326.TW", "2002.TW",
    # 電信 / 公用
    "2412.TW", "3045.TW", "4904.TW", "9904.TW",
    # 熱門 ETF（用戶搜尋率高）
    "0050.TW", "0056.TW", "00878.TW", "00919.TW", "00929.TW", "00940.TW",
    # 觀光 / 食品
    "2912.TW", "2207.TW", "9921.TW",
}


def _export_kline_json(report_df, market_id="tw-share", top_n=None,
                      history_days=500, info_top_n=100, chips_days=60):
    """
    從 data/<market_id>/dayK/*.csv 中挑出 report_df 中的個股，
    每檔 export 成 dist/data/<safe_id>.json。

    JSON schema (Phase 2):
        {
          "candles":     [{time, open, high, low, close, volume}, ...],
          "ma20":        [None, ..., 612.5, 614.0, ...],   // 對齊 candles 同長度
          "ma60":        [...],
          "ma200":       [...],
          "rsi14":       [...],
          "macd_line":   [...],
          "macd_signal": [...],
          "macd_hist":   [...],
          "info":        {longName, sector, industry, marketCap, trailingPE, ...} | null,
          "chips":       [{date, foreign_net, trust_net, dealer_net, total_net}, ...] | null
        }

    top_n=None 表示 export 全部 K 線（飆股清單每個代號都該點得到）。
    info_top_n=100 表示只對 Year_High Top 100 撈 yfinance.info（避免拖慢 build）。
    chips_days=60 表示每檔 query 最近 60 個交易日的三大法人時序（從 SQLite）。

    safe_id = ticker.replace('.', '_').replace('/', '_')
    回傳 manifest list。
    """
    if report_df is None or len(report_df) == 0:
        print("⚠️ [build_web] report_df 為空，跳過 K 線 export")
        return []

    try:
        import pandas as pd
    except ImportError:
        print("⚠️ [build_web] 沒裝 pandas，跳過 K 線 export")
        return []

    if "Year_High" not in report_df.columns:
        print("⚠️ [build_web] report_df 沒有 Year_High 欄位，跳過 K 線 export")
        return []

    data_dir = Path("data") / market_id / "dayK"
    if not data_dir.exists():
        print(f"⚠️ [build_web] {data_dir} 不存在，跳過 K 線 export")
        return []

    out_dir = DIST_DIR / "data"
    out_dir.mkdir(exist_ok=True)

    # 用 Year_High 排序；top_n=None → 全部，否則取前 top_n
    df_ranked = report_df.dropna(subset=["Year_High"]).sort_values(
        "Year_High", ascending=False
    )
    if top_n is not None and top_n > 0:
        df_ranked = df_ranked.head(top_n)

    # 紀錄前 info_top_n 名要撈 yfinance.info 的 ticker set
    # Phase 3：聯集大型股白名單，避免「搜 2330 但無 info」的 UX 痛點
    info_tickers = set()
    if info_top_n and info_top_n > 0:
        info_tickers = set(df_ranked.head(info_top_n)["Ticker"].astype(str).tolist())
        # 白名單必抓
        wl_in_report = set(df_ranked["Ticker"].astype(str).tolist()) & INFO_WHITELIST_TW
        info_tickers |= wl_in_report
        print(f"   - 將對 Top {info_top_n} 飆股 + 白名單 {len(wl_in_report)} 大型股 = {len(info_tickers)} 檔 撈 yfinance.info")

    # 預載 chips downloader（若 SQLite 不存在就跳過）
    chips_query_fn = None
    if chips_days and chips_days > 0:
        try:
            import downloader_chips
            from pathlib import Path as _P
            if _P("data/chips.db").exists():
                chips_query_fn = downloader_chips.query_chips
                print(f"   - chips DB 偵測到，每檔將寫入最近 {chips_days} 天三大法人時序")
            else:
                print(f"   - chips DB 不存在，跳過三大法人整合（需先跑 downloader_chips.main()）")
        except ImportError:
            print(f"   - 找不到 downloader_chips 模組，跳過")

    manifest = []
    skipped = 0
    info_fetched = 0
    info_failed = 0
    chips_filled = 0
    for _, row in df_ranked.iterrows():
        ticker = str(row["Ticker"])
        name = str(row.get("Full_Name", ticker))

        # 檔名格式跟 analyzer 一致：<ticker>_<name>.csv
        csv_candidates = list(data_dir.glob(f"{ticker}_*.csv"))
        if not csv_candidates:
            csv_candidates = [data_dir / f"{ticker}.csv"]
        csv_path = csv_candidates[0]
        if not csv_path.exists():
            skipped += 1
            continue

        try:
            df = pd.read_csv(csv_path)
            df.columns = [c.lower() for c in df.columns]
            if "date" not in df.columns:
                first_col = df.columns[0]
                df = df.rename(columns={first_col: "date"})
            required = {"date", "open", "high", "low", "close"}
            if not required.issubset(df.columns):
                skipped += 1
                continue

            if len(df) > history_days:
                df = df.tail(history_days)

            records = []
            closes = []
            for _, r in df.iterrows():
                try:
                    rec = {
                        "time": str(r["date"])[:10],
                        "open": float(r["open"]),
                        "high": float(r["high"]),
                        "low": float(r["low"]),
                        "close": float(r["close"]),
                    }
                    if "volume" in df.columns:
                        try:
                            rec["volume"] = float(r["volume"])
                        except (ValueError, TypeError):
                            pass
                    records.append(rec)
                    closes.append(rec["close"])
                except (ValueError, TypeError):
                    continue
            if not records:
                skipped += 1
                continue

            # 算移動平均
            ma20 = _calc_ma(closes, 20)
            ma60 = _calc_ma(closes, 60)
            ma200 = _calc_ma(closes, 200)

            # 算技術指標（Phase 2）
            rsi14 = _calc_rsi(closes, 14)
            macd_line, macd_signal, macd_hist = _calc_macd(closes, 12, 26, 9)

            # 撈基本面（只對 info_tickers 內的個股）
            info = None
            if ticker in info_tickers:
                info = _fetch_yf_info(ticker)
                if info is not None:
                    info_fetched += 1
                else:
                    info_failed += 1

            # 撈三大法人時序（從 SQLite，已先載過的話）
            chips = None
            if chips_query_fn is not None:
                chips_rows = chips_query_fn(ticker, days=chips_days) or []
                if chips_rows:
                    chips = chips_rows
                    chips_filled += 1

            payload = {
                "candles": records,
                "ma20": ma20,
                "ma60": ma60,
                "ma200": ma200,
                "rsi14": rsi14,
                "macd_line": macd_line,
                "macd_signal": macd_signal,
                "macd_hist": macd_hist,
                "info": info,
                "chips": chips,
            }

            safe_id = ticker.replace(".", "_").replace("/", "_")
            (out_dir / f"{safe_id}.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )

            manifest.append({
                "ticker": ticker,
                "name": name,
                "safe_id": safe_id,
                "year_high": float(row["Year_High"]) if pd.notna(row.get("Year_High")) else None,
                "month_high": float(row["Month_High"]) if pd.notna(row.get("Month_High")) else None,
                "week_high": float(row["Week_High"]) if pd.notna(row.get("Week_High")) else None,
                "samples": len(records),
                "has_info": info is not None,
                "has_chips": chips is not None,
                "sector": info.get("sector") if info else None,
                "industry": info.get("industry") if info else None,
            })
        except Exception:
            skipped += 1
            continue

    manifest.sort(key=lambda x: x.get("year_high") or -999, reverse=True)

    # Phase 4：算同 industry peers（v2，候選池限 .TW），回填到每個個股 JSON 的 peers 欄位
    _inject_peers(manifest, out_dir, top_n=5)

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"   - K 線 JSON：{len(manifest)} 檔 → dist/data/（跳過 {skipped} 檔）")
    if info_tickers:
        print(f"   - yfinance.info：成功 {info_fetched} 檔 / 失敗 {info_failed} 檔")
    if chips_query_fn is not None:
        print(f"   - 三大法人 chips：填入 {chips_filled} 檔")
    return manifest


def _inject_peers(manifest, out_dir, top_n=5, min_industry_pool=2):
    """
    peers v2 — 修 v1「台積電 peers 全是上櫃妖股」痛點。

    v1 用 yfinance.sector（粗，Technology 涵蓋 IC 通路 / 軟體 / 妖股），
    且候選池包含 .TWO 上櫃妖股 → 2330 的 peers 全是 +6000% 以上的妖股。

    v2 兩個改動：
      1. 候選池只收 TWSE 上市 .TW，排除 .TWO 上櫃/興櫃妖股
         （endswith('.TW') 不會吃到 .TWO，因為 .TWO 結尾是 'O' 不是 'W'）
      2. 主分組用 industry（細項，Semiconductors / Banks—Regional / ...）
         industry 候選池 < min_industry_pool（自己+至少 1 對手）時 fallback 到 sector

    本身是 .TWO 的飆股仍能拿到 peers — 它的 industry 命中 .TW 候選池，
    撈到「同細項行業的上市對手」，比「sector 內年漲冠軍妖股」實用得多。
    """
    # 候選池：只收 TWSE 上市 .TW + has_info（要有 industry/sector 才能分組）
    pool = [
        m for m in manifest
        if m.get("has_info")
        and m.get("ticker", "").endswith(".TW")
        and (m.get("industry") or m.get("sector"))
    ]

    by_industry = {}
    by_sector = {}
    for m in pool:
        ind = m.get("industry")
        sec = m.get("sector")
        if ind:
            by_industry.setdefault(ind, []).append(m)
        if sec:
            by_sector.setdefault(sec, []).append(m)

    def take_top(items, exclude_ticker, n=top_n):
        ranked = sorted(items, key=lambda x: x.get("year_high") or -999, reverse=True)
        out = []
        for x in ranked:
            if x["ticker"] == exclude_ticker:
                continue
            out.append({
                "ticker": x["ticker"],
                "name": x["name"],
                "safe_id": x["safe_id"],
                "year_high": x.get("year_high"),
            })
            if len(out) >= n:
                break
        return out

    updated = 0
    ind_hits = 0
    sec_fallbacks = 0
    for m in manifest:
        if not m.get("has_info"):
            continue
        ticker = m["ticker"]
        ind = m.get("industry")
        sec = m.get("sector")

        peers = None
        # 先試 industry（細項）
        if ind and ind in by_industry and len(by_industry[ind]) >= min_industry_pool:
            cand = take_top(by_industry[ind], ticker)
            if cand:
                peers = cand
                ind_hits += 1
        # industry 候選池太小 → fallback sector（粗）
        if not peers and sec and sec in by_sector:
            cand = take_top(by_sector[sec], ticker)
            if cand:
                peers = cand
                sec_fallbacks += 1
        if not peers:
            continue

        json_path = out_dir / f"{m['safe_id']}.json"
        if not json_path.exists():
            continue
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload["peers"] = peers
                json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                updated += 1
        except Exception:
            continue
    print(
        f"   - peers v2 回寫：{updated} 檔"
        f"（industry {ind_hits} / sector fallback {sec_fallbacks}），"
        f"候選池 {len(pool)} 檔 .TW"
    )


def build(images, report_df=None, text_reports=None, market_id="tw-share", sample_count=None):
    """
    從 main.py 呼叫的主介面。

    images: list of {'id', 'path', 'label'}（analyzer 的回傳格式）
    report_df: pandas DataFrame，可為 None
    text_reports: dict {'Week': str, 'Month': str, 'Year': str}
    market_id: 'tw-share' 等
    sample_count: 顯示在頁面上的樣本數，None 則用 len(report_df)
    """
    DIST_DIR.mkdir(exist_ok=True)
    images_out = DIST_DIR / "images"
    images_out.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    # 1) 複製 PNG 到 dist/images/，並收集 metadata
    image_items = []
    for img in images or []:
        src = Path(img["path"])
        if not src.exists():
            print(f"⚠️ [build_web] 來源圖檔不存在，跳過：{src}")
            continue
        dst = images_out / src.name
        shutil.copy2(src, dst)
        image_items.append({
            "id": img.get("id", src.stem),
            "filename": src.name,
            "label": img.get("label") or _label_for(img.get("id", src.stem)),
        })

    # 2) 計算樣本數
    if sample_count is None:
        if report_df is not None and hasattr(report_df, "__len__"):
            sample_count = len(report_df)
        else:
            sample_count = "—"

    # 3) 把 meta 寫到 output/web_meta.json，給 standalone 模式重建用
    meta = {
        "updated_at": now_taipei_str(),
        "market_id": market_id,
        "sample_count": sample_count,
        "images": image_items,
        "text_reports": text_reports or {},
    }
    META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # 4) 渲染 HTML
    html = HTML_TEMPLATE.format(
        updated_at=meta["updated_at"],
        sample_count=sample_count,
        market_id=market_id,
        image_cards=_render_image_cards(image_items) or "<p>（無圖檔）</p>",
        text_sections=_render_text_sections(text_reports),
    )
    out = DIST_DIR / "index.html"
    out.write_text(html, encoding="utf-8")

    # 5) 複製 chart.html 模板到 dist/（供站內 K 線頁使用）
    chart_src = Path("chart.html")
    if chart_src.exists():
        shutil.copy2(chart_src, DIST_DIR / "chart.html")
    else:
        print("⚠️ [build_web] 找不到 chart.html 模板，跳過複製（站內 K 線頁不會 work）")

    # 6) Export K 線 JSON 給 chart.html 用
    kline_manifest = _export_kline_json(report_df, market_id=market_id)

    print("\n" + "=" * 60)
    print(f"🌐 [build_web] 靜態站已產出於 {DIST_DIR.resolve()}")
    print(f"   - index.html ({len(html)} chars)")
    print(f"   - {len(image_items)} 張 PNG → dist/images/")
    print(f"   - text_reports 段數：{len(text_reports or {})}")
    print(f"   - chart.html: {'✅ 已複製' if chart_src.exists() else '❌ 未複製'}")
    print(f"   - K 線 JSON：{len(kline_manifest)} 檔 → dist/data/")
    print(f"   - meta 已寫入 {META_FILE}")
    print("=" * 60 + "\n")


def standalone(market_id="tw-share"):
    """
    本地 standalone 模式：不依賴 analyzer 即時輸出，從 output/ 撈現有資料重建 dist/。
    用途：本地煙霧測試版型、或 analyzer 未跑時快速重建頁面。
    """
    print(f"🔧 [build_web] standalone 模式 — 從 output/ 重建 dist/（market_id={market_id}）")

    image_dir = OUTPUT_DIR / "images" / market_id
    if not image_dir.exists():
        print(f"❌ 找不到 PNG 目錄：{image_dir}")
        print(f"   先跑 python main.py --market {market_id} 產生 PNG，再回來跑此模式。")
        sys.exit(1)

    pngs = sorted(image_dir.glob("*.png"))
    if not pngs:
        print(f"❌ {image_dir} 目錄為空。")
        sys.exit(1)

    images = [
        {"id": p.stem, "path": str(p), "label": _label_for(p.stem)}
        for p in pngs
    ]

    # 嘗試讀 web_meta.json 拿到上次的 text_reports
    text_reports = None
    sample_count = None
    if META_FILE.exists():
        try:
            meta = json.loads(META_FILE.read_text(encoding="utf-8"))
            text_reports = meta.get("text_reports")
            sample_count = meta.get("sample_count")
            print(f"✅ 從 {META_FILE} 載入 text_reports（{len(text_reports or {})} 段）")
        except Exception as e:
            print(f"⚠️ 讀 {META_FILE} 失敗：{e}")

    build(images, report_df=None, text_reports=text_reports,
          market_id=market_id, sample_count=sample_count)


if __name__ == "__main__":
    market = sys.argv[1] if len(sys.argv) > 1 else "tw-share"
    standalone(market_id=market)
