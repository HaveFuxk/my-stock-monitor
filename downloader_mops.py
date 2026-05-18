# -*- coding: utf-8 -*-
"""
downloader_mops.py — B1：月營收（MOPS 公開資訊觀測站）

Endpoints（openapi 上的最新月份 snapshot）：
  - TWSE 上市：https://openapi.twse.com.tw/v1/opendata/t187ap05_L
  - TPEX 上櫃：https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O

寫到 dist/data/mops_revenue.json：tech zone 27 家成員精簡版 + 半導體 top YoY 30 家。
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from downloader_utils import init_stdout, http_get_json, to_int, to_float, collect_tech_zone_codes

init_stdout()

OUT_FILE = Path("dist") / "data" / "mops_revenue.json"
TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"


def _normalize(row: dict, market: str) -> dict:
    """MOPS row → 精簡欄位（金額仍是千元；前端再轉億）。"""
    return {
        "code": row.get("公司代號"),
        "name": row.get("公司名稱"),
        "industry": row.get("產業別"),
        "market": market,
        "data_year_month": str(row.get("資料年月") or ""),
        "current_revenue": to_int(row.get("營業收入-當月營收")),
        "last_month_revenue": to_int(row.get("營業收入-上月營收")),
        "last_year_revenue": to_int(row.get("營業收入-去年當月營收")),
        "mom_pct": to_float(row.get("營業收入-上月比較增減(%)")),
        "yoy_pct": to_float(row.get("營業收入-去年同月增減(%)")),
        "ytd_current": to_int(row.get("累計營業收入-當月累計營收")),
        "ytd_last_year": to_int(row.get("累計營業收入-去年累計營收")),
        "ytd_yoy_pct": to_float(row.get("累計營業收入-前期比較增減(%)")),
    }


def _ym_display(ym: str | None) -> str | None:
    """11504 (民國 115 年 04 月) → '2026/04'"""
    if not ym or len(ym) != 5:
        return ym
    try:
        return f"{1911 + int(ym[:3])}/{int(ym[3:]):02d}"
    except (ValueError, TypeError):
        return ym


def build_mops_json(out_path: Path = OUT_FILE) -> dict:
    print("=" * 60)
    print("📊 [mops] 抓月營收（MOPS openapi）")
    print("=" * 60)

    codes = collect_tech_zone_codes()
    print(f"  Tech zone 成員：{len(codes)} 家")

    # 兩個 endpoint 各抓一次 raw
    raw_rows = []
    for url, market in [(TWSE_URL, "sii"), (TPEX_URL, "otc")]:
        data = http_get_json(url, timeout=30)
        if data is None:
            print(f"  ⚠️ {market} 抓取失敗")
            continue
        print(f"  ✓ {market} {len(data)} 筆原始")
        raw_rows.append((data, market))

    # Filter-before-normalize：先以 4 碼 code 過濾，只 normalize 需要的 row
    # （從 1965 → 34，省記憶體 + CPU）
    tz_rows = {}
    all_normalized_for_semi = []
    for data, market in raw_rows:
        for row in data:
            code = row.get("公司代號")
            industry = row.get("產業別") or ""
            in_tz = code in codes
            is_semi = "半導體" in industry
            if in_tz or is_semi:
                norm = _normalize(row, market)
                if in_tz:
                    tz_rows[code] = norm
                if is_semi and norm.get("yoy_pct") is not None:
                    all_normalized_for_semi.append(norm)

    all_normalized_for_semi.sort(key=lambda r: r["yoy_pct"], reverse=True)
    semi_top = all_normalized_for_semi[:30]

    yms = [r["data_year_month"] for r in tz_rows.values() if r.get("data_year_month")]
    latest_ym = max(yms) if yms else None

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_year_month": latest_ym,
        "data_year_month_display": _ym_display(latest_ym),
        "tech_zone_count": len(tz_rows),
        "tech_zone": tz_rows,
        "semi_top_yoy": semi_top,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ [mops] 寫入 {out_path}：{len(tz_rows)} 家 tech zone + {len(semi_top)} 家半導體 top YoY，資料年月 {_ym_display(latest_ym)}")
    return out


if __name__ == "__main__":
    build_mops_json()
