# -*- coding: utf-8 -*-
"""
downloader_intl.py — B4 + B5：國際指數 + 全球競爭者

B4 國際科技股指數
  - ^SOX 費城半導體
  - ^NDX 那斯達克 100
  - ^IXIC 那斯達克綜合
  - ^GSPC S&P 500
  - 0050.TW 元大台灣 50
  - 0056.TW 元大高股息

B5 全球競爭者（per industry）
  - AI Server ODM: NVDA, AMD, AVGO, DELL, HPE, SMCI
  - 晶圓代工: INTC, GFS, ASML, TSM (ADR)
  - IC 設計: NVDA, AMD, AVGO, QCOM, MRVL
  - 封測 / 載板: AMKR
  - 散熱光通訊: VRT

寫到 dist/data/intl.json，供 tech-zone section 拿來跟台股產業 avg 對比。

容錯：個股拉不到（rate limit / delisted）skip，不擋 build。
"""
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

OUT_FILE = Path("dist") / "data" / "intl.json"

INDICES = [
    ("^SOX",   "費城半導體"),
    ("^NDX",   "那斯達克 100"),
    ("^IXIC",  "那斯達克綜合"),
    ("^GSPC",  "S&P 500"),
    ("^DJI",   "道瓊工業"),
    ("0050.TW", "元大台灣 50"),
    ("0056.TW", "元大高股息"),
]

# Per industry_maps 子產業 id → 全球競爭者
GLOBAL_COMPETITORS = {
    "ai-server-odm": [
        ("NVDA", "NVIDIA"),
        ("AMD",  "AMD"),
        ("AVGO", "Broadcom"),
        ("DELL", "Dell"),
        ("HPE",  "HPE"),
        ("SMCI", "Super Micro"),
    ],
    "semi-foundry": [
        ("INTC", "Intel"),
        ("GFS",  "GlobalFoundries"),
        ("ASML", "ASML"),
        ("TSM",  "TSMC ADR"),
    ],
    "ic-design": [
        ("NVDA", "NVIDIA"),
        ("AMD",  "AMD"),
        ("AVGO", "Broadcom"),
        ("QCOM", "Qualcomm"),
        ("MRVL", "Marvell"),
        ("MU",   "Micron"),
    ],
    "semi-package": [
        ("AMKR", "Amkor"),
        ("ASE",  "ASE Group ADR"),
    ],
    "optical-thermal": [
        ("VRT",       "Vertiv"),
        ("005930.KS", "Samsung Electronics"),
        ("000660.KS", "SK Hynix"),
    ],
}


def _fetch_one(ticker: str, label: str) -> dict | None:
    """單一檔抓 2 年歷史，算年/月/週/日漲幅 + 抓 info 取市值。"""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="2y", auto_adjust=False)
        if hist.empty or len(hist) < 30:
            return None
        closes = hist["Close"].tolist()
        last = closes[-1]

        def chg(n):
            if len(closes) <= n:
                return None
            return (last / closes[-n - 1] - 1) * 100

        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass

        return {
            "ticker": ticker,
            "label": label or info.get("shortName") or info.get("longName") or ticker,
            "last_close": round(last, 2),
            "year_change": chg(250) if len(closes) > 250 else chg(len(closes) - 1),
            "month_change": chg(20),
            "week_change": chg(5),
            "day_change": chg(1),
            "market_cap_usd": _market_cap_usd(info),
            "currency": info.get("currency"),
        }
    except Exception as e:
        print(f"  ⚠️ {ticker}: {e}")
        return None


def _market_cap_usd(info: dict) -> float | None:
    """yfinance.info 的 marketCap 是 listed 幣別計價，轉成 USD 粗估（KRW/TWD 等用近似匯率）。"""
    mc = info.get("marketCap")
    if not mc:
        return None
    cur = (info.get("currency") or "").upper()
    # 粗估匯率 — 不要求精準，視覺對比夠用
    rate = {
        "USD": 1.0,
        "TWD": 0.031,    # 1 TWD ≈ 0.031 USD
        "KRW": 0.00070,  # 1 KRW ≈ 0.00070 USD
        "JPY": 0.0064,   # 1 JPY ≈ 0.0064 USD
        "HKD": 0.13,
        "CNY": 0.14,
        "EUR": 1.08,
    }.get(cur, 1.0)
    return round(mc * rate)


def build_intl_json(out_path: Path = OUT_FILE) -> dict:
    print("=" * 60)
    print("📊 [intl] 抓國際指數 + 全球競爭者")
    print("=" * 60)

    indices_out = []
    for tk, label in INDICES:
        r = _fetch_one(tk, label)
        if r:
            indices_out.append(r)
            print(f"  ✓ {tk:10s} {r['label']:20s} 年 {r['year_change']:+.1f}%  月 {r['month_change']:+.1f}%")
        time.sleep(0.4)  # 避免 yfinance rate limit

    competitors_out = {}
    for industry_id, stocks in GLOBAL_COMPETITORS.items():
        members = []
        print(f"\n  抓 {industry_id} 全球競爭者：")
        for tk, label in stocks:
            r = _fetch_one(tk, label)
            if r:
                members.append(r)
                print(f"    ✓ {tk:12s} {r['label']:25s} 年 {r['year_change']:+.1f}%")
            time.sleep(0.4)
        if members:
            competitors_out[industry_id] = members

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "indices": indices_out,
        "competitors_by_industry": competitors_out,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    n_idx = len(indices_out)
    n_comp = sum(len(v) for v in competitors_out.values())
    print(f"\n✅ [intl] 寫入 {out_path}：{n_idx} 個指數 + {n_comp} 個全球競爭者")
    return out


if __name__ == "__main__":
    build_intl_json()
