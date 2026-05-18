# -*- coding: utf-8 -*-
"""
downloader_tech_history.py — Tier 3 C4 + C1：產業歷史走勢 + 輪動分析

依賴：dist/data/*.json 內每家成員的 candles[] (約 484 天 OHLC)。

對每個 industry：
  1. 取所有成員的 close 時序，對齊日期
  2. 每位成員 normalize 到 day 0 = 1.0（除以該成員 day 0 close）
  3. 同日跨成員取平均 → 產業 daily index
  4. 整段 × 100 → 起點 = 100 的指數，類似 NDX/SOX 走勢

只保留最後 ~250 個交易日（約 1 年）。5 產業 × 250 點 × 1 float ≈ 25 KB。

也算 rotation：4 週 return (20 day) vs 12 週 return (60 day)，給輪動圖用。
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from downloader_utils import init_stdout

init_stdout()

OUT_FILE = Path("dist") / "data" / "tech_zone_history.json"
DIST_DATA = Path("dist") / "data"
INDUSTRY_MAPS_FILE = Path(__file__).resolve().parent / "config" / "industry_maps.json"

HISTORY_DAYS = 250  # 保留最後 ~1 年交易日

# 顏色 token（跟前端 line chart 對應）
INDUSTRY_COLOR = {
    "ai-server-odm":   "#06b6d4",
    "semi-foundry":    "#f59e0b",
    "ic-design":       "#a78bfa",
    "semi-package":    "#22c55e",
    "optical-thermal": "#ef4444",
}


def _collect_industries() -> list[dict]:
    if not INDUSTRY_MAPS_FILE.exists():
        return []
    imap = json.loads(INDUSTRY_MAPS_FILE.read_text(encoding="utf-8"))
    return imap.get("industries") or []


def _industry_member_codes(ind: dict) -> list[str]:
    """Industry obj → list of 4-碼 code（layers + flat 都支援）。"""
    codes = []
    for layer in (ind.get("layers") or []):
        for role in (layer.get("roles") or []):
            for c in (role.get("companies") or []):
                if c.get("ticker"):
                    codes.append(c["ticker"])
    for c in (ind.get("companies") or []):
        if c.get("ticker"):
            codes.append(c["ticker"])
    return codes


def _load_candles(code: str) -> list[dict] | None:
    """Code → per-stock JSON 的 candles list。.TW 跟 .TWO 都試。"""
    for suffix in ["_TW", "_TWO"]:
        path = DIST_DATA / f"{code}{suffix}.json"
        if path.exists():
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                return d.get("candles") or None
            except (OSError, json.JSONDecodeError):
                continue
    return None


def _build_industry_series(member_candles: list[list[dict]]) -> tuple[list[str], list[float]]:
    """
    Input: list of per-member candles (already only valid members).
    Output: (shared dates list, normalized index series 100=start).

    每成員 normalize 到自己 day-0 = 1.0，再跨成員平均，最後 × 100。
    """
    if not member_candles:
        return [], []

    # 取「所有成員都有」的日期交集，排序
    date_sets = [set(c["time"] for c in mc) for mc in member_candles]
    common = sorted(set.intersection(*date_sets))
    if len(common) < 5:
        return [], []

    # 每成員：日期 → close
    member_maps = [{c["time"]: c["close"] for c in mc} for mc in member_candles]

    # 取最後 HISTORY_DAYS 天
    dates = common[-HISTORY_DAYS:]
    base_date = dates[0]

    series = []
    for d in dates:
        ratios = []
        for m in member_maps:
            cur = m.get(d)
            base = m.get(base_date)
            if cur and base and base > 0:
                ratios.append(cur / base)
        if ratios:
            series.append(sum(ratios) / len(ratios) * 100)
        else:
            series.append(None)
    return dates, series


def _compute_returns(series: list[float], dates: list[str]) -> dict:
    """從產業 index 算近 4 週（20 day）/ 12 週（60 day）return。"""
    if not series or len(series) < 60:
        return {"ret_4w": None, "ret_12w": None}
    last = series[-1]
    return {
        "ret_4w": (last / series[-21] - 1) * 100 if series[-21] else None,
        "ret_12w": (last / series[-61] - 1) * 100 if series[-61] else None,
    }


def build_tech_history_json(out_path: Path = OUT_FILE) -> dict:
    print("=" * 60)
    print("📊 [tech_history] 從成員 K 線算產業歷史走勢 + 輪動")
    print("=" * 60)

    industries = _collect_industries()
    industries_out = {}
    shared_dates = None

    for ind in industries:
        ind_id = ind["id"]
        codes = _industry_member_codes(ind)
        loaded = [_load_candles(c) for c in codes]
        valid = [mc for mc in loaded if mc and len(mc) >= 60]
        dates, series = _build_industry_series(valid)
        if not dates:
            print(f"  ⚠️ {ind_id} 資料不足 skip")
            continue

        if shared_dates is None:
            shared_dates = dates
        else:
            # 用各產業日期交集（極少數情況某產業缺日，本來就會自動對齊 close range）
            if len(dates) != len(shared_dates):
                # 取最短的當基準
                shared_dates = dates if len(dates) < len(shared_dates) else shared_dates

        rets = _compute_returns(series, dates)
        industries_out[ind_id] = {
            "name": ind["name"],
            "icon": ind.get("icon", "🔬"),
            "color": INDUSTRY_COLOR.get(ind_id, "#6b7280"),
            "members_used": len(valid),
            "members_listed": len(codes),
            "series": series,
            **rets,
        }
        ret4 = rets.get("ret_4w")
        ret12 = rets.get("ret_12w")
        ret4_s = f"{ret4:+.1f}%" if ret4 is not None else "—"
        ret12_s = f"{ret12:+.1f}%" if ret12 is not None else "—"
        print(f"  ✓ {ind_id:18s} {len(valid)}/{len(codes)} 成員 / {len(series)} 點 / 4W {ret4_s} / 12W {ret12_s}")

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dates": shared_dates or [],
        "history_days": len(shared_dates) if shared_dates else 0,
        "industries": industries_out,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ [tech_history] 寫入 {out_path}：{len(industries_out)} 產業 × {len(shared_dates or [])} 點")
    return out


if __name__ == "__main__":
    build_tech_history_json()
