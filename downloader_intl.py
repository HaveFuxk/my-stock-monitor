# -*- coding: utf-8 -*-
"""
downloader_intl.py — B4 + B5：國際指數 + 全球競爭者（yfinance）

並發 4 個 thread 拉所有 ticker（~30 檔），實測從 ~50s 縮到 ~15s。
指數不抓 info（marketCap 對指數無意義），只抓 history。

寫到 dist/data/intl.json，供 tech-zone section 對比台股產業 avg。
"""
import json
import concurrent.futures
from datetime import datetime, timezone
from pathlib import Path

from downloader_utils import init_stdout

init_stdout()

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

GLOBAL_COMPETITORS = {
    "ai-server-odm": [
        ("NVDA", "NVIDIA"), ("AMD", "AMD"), ("AVGO", "Broadcom"),
        ("DELL", "Dell"), ("HPE", "HPE"), ("SMCI", "Super Micro"),
    ],
    "semi-foundry": [
        ("INTC", "Intel"), ("GFS", "GlobalFoundries"),
        ("ASML", "ASML"), ("TSM", "TSMC ADR"),
    ],
    "ic-design": [
        ("NVDA", "NVIDIA"), ("AMD", "AMD"), ("AVGO", "Broadcom"),
        ("QCOM", "Qualcomm"), ("MRVL", "Marvell"), ("MU", "Micron"),
    ],
    "semi-package": [
        ("AMKR", "Amkor"), ("ASE", "ASE Group ADR"),
    ],
    "optical-thermal": [
        ("VRT", "Vertiv"),
        ("005930.KS", "Samsung Electronics"),
        ("000660.KS", "SK Hynix"),
    ],
}

# FX 粗估表（指數市值不抓 → 不用；競爭者市值用 USD 統一比較）
# 不要求精準（漂移 5-10% 可接受），純為視覺對比；要精準請改用 yfinance fast_info.last_price * FX live
FX_TO_USD = {
    "USD": 1.0, "TWD": 0.031, "KRW": 0.00070, "JPY": 0.0064,
    "HKD": 0.13, "CNY": 0.14, "EUR": 1.08,
}


def _chg(closes: list[float], n: int, last: float) -> float | None:
    if len(closes) <= n:
        return None
    return (last / closes[-n - 1] - 1) * 100


def _fetch_one(ticker: str, label: str, want_info: bool) -> dict | None:
    """單檔抓 2 年 history + 算漲幅。指數不抓 info（marketCap 對指數無意義）。"""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="2y", auto_adjust=False)
        if hist.empty or len(hist) < 30:
            return None
        closes = hist["Close"].tolist()
        last = closes[-1]

        info = {}
        if want_info:
            try:
                info = t.info or {}
            except Exception:
                info = {}

        market_cap_usd = None
        if want_info and info.get("marketCap"):
            cur = (info.get("currency") or "USD").upper()
            market_cap_usd = round(info["marketCap"] * FX_TO_USD.get(cur, 1.0))

        return {
            "ticker": ticker,
            "label": label or info.get("shortName") or info.get("longName") or ticker,
            "last_close": round(last, 2),
            "year_change": _chg(closes, 250, last) if len(closes) > 250 else _chg(closes, len(closes) - 1, last),
            "month_change": _chg(closes, 20, last),
            "week_change": _chg(closes, 5, last),
            "day_change": _chg(closes, 1, last),
            "market_cap_usd": market_cap_usd,
            "currency": info.get("currency"),
        }
    except Exception as e:
        print(f"  ⚠️ {ticker}: {e}")
        return None


def build_intl_json(out_path: Path = OUT_FILE) -> dict:
    print("=" * 60)
    print("📊 [intl] 抓國際指數 + 全球競爭者（4-thread 並發）")
    print("=" * 60)

    # 蒐集所有要抓的 (ticker, label, want_info, category, industry_id) 任務
    tasks = []
    for tk, label in INDICES:
        tasks.append((tk, label, False, "index", None))
    for industry_id, stocks in GLOBAL_COMPETITORS.items():
        for tk, label in stocks:
            tasks.append((tk, label, True, "competitor", industry_id))

    results: list[tuple[str, dict | None]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(_fetch_one, tk, label, want_info): (category, industry_id)
            for tk, label, want_info, category, industry_id in tasks
        }
        for fut in concurrent.futures.as_completed(futures):
            category, industry_id = futures[fut]
            r = fut.result()
            if r:
                results.append((category, industry_id, r))

    indices_out = [r for cat, _, r in results if cat == "index"]
    # 保留 INDICES 順序
    indices_map = {r["ticker"]: r for r in indices_out}
    indices_ordered = [indices_map[tk] for tk, _ in INDICES if tk in indices_map]

    competitors_out: dict[str, list[dict]] = {}
    for cat, industry_id, r in results:
        if cat == "competitor" and industry_id:
            competitors_out.setdefault(industry_id, []).append(r)
    # 保留 GLOBAL_COMPETITORS 順序
    for industry_id, stocks in GLOBAL_COMPETITORS.items():
        if industry_id in competitors_out:
            order = {tk: i for i, (tk, _) in enumerate(stocks)}
            competitors_out[industry_id].sort(key=lambda r: order.get(r["ticker"], 99))

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "indices": indices_ordered,
        "competitors_by_industry": competitors_out,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    n_comp = sum(len(v) for v in competitors_out.values())
    print(f"\n✅ [intl] 寫入 {out_path}：{len(indices_ordered)} 個指數 + {n_comp} 個全球競爭者")
    return out


if __name__ == "__main__":
    build_intl_json()
