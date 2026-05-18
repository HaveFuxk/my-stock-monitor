# -*- coding: utf-8 -*-
"""
downloader_mops.py — B1：月營收（MOPS 公開資訊觀測站）

Endpoints（openapi 上的最新月份 snapshot）：
  - TWSE 上市：https://openapi.twse.com.tw/v1/opendata/t187ap05_L
  - TPEX 上櫃：https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O

每筆含欄位：
  - 公司代號 / 公司名稱 / 產業別
  - 資料年月（民國年月，e.g. 11504 = 2026 年 4 月）
  - 營業收入-當月營收 / 上月營收 / 去年當月營收（千元）
  - 營業收入-上月比較增減(%) (MoM)
  - 營業收入-去年同月增減(%) (YoY)
  - 累計營業收入-當月累計營收 / 去年累計營收 (千元)
  - 累計營業收入-前期比較增減(%) (累計 YoY)

寫到 dist/data/mops_revenue.json，僅保留 tech zone 27 家成員（精簡 JSON）。
"""
import json
import sys
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

OUT_FILE = Path("dist") / "data" / "mops_revenue.json"
INDUSTRY_MAPS_FILE = Path("config") / "industry_maps.json"

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _fetch_json(url: str) -> list:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=30) as r:
        return json.loads(r.read())


def _collect_tech_zone_codes() -> set[str]:
    """從 industry_maps.json 抓所有 tech zone 成員 4 碼。"""
    if not INDUSTRY_MAPS_FILE.exists():
        return set()
    imap = json.loads(INDUSTRY_MAPS_FILE.read_text(encoding="utf-8"))
    codes: set[str] = set()
    for ind in imap.get("industries", []):
        for layer in (ind.get("layers") or []):
            for role in (layer.get("roles") or []):
                for c in (role.get("companies") or []):
                    if c.get("ticker"):
                        codes.add(c["ticker"])
        for c in (ind.get("companies") or []):
            if c.get("ticker"):
                codes.add(c["ticker"])
    return codes


def _normalize(row: dict, market: str) -> dict:
    """MOPS row → 簡化欄位（千元 → 億元、% 直接保留）。"""
    code = row.get("公司代號")
    ym = str(row.get("資料年月") or "")
    return {
        "code": code,
        "name": row.get("公司名稱"),
        "industry": row.get("產業別"),
        "market": market,
        "data_year_month": ym,           # 民國 YYYMM (e.g. 11504)
        "current_revenue": _to_int(row.get("營業收入-當月營收")),  # 千元
        "last_month_revenue": _to_int(row.get("營業收入-上月營收")),
        "last_year_revenue": _to_int(row.get("營業收入-去年當月營收")),
        "mom_pct": _to_float(row.get("營業收入-上月比較增減(%)")),
        "yoy_pct": _to_float(row.get("營業收入-去年同月增減(%)")),
        "ytd_current": _to_int(row.get("累計營業收入-當月累計營收")),
        "ytd_last_year": _to_int(row.get("累計營業收入-去年累計營收")),
        "ytd_yoy_pct": _to_float(row.get("累計營業收入-前期比較增減(%)")),
    }


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_mops_json(out_path: Path = OUT_FILE) -> dict:
    print("=" * 60)
    print("📊 [mops] 抓月營收（MOPS openapi）")
    print("=" * 60)

    codes = _collect_tech_zone_codes()
    print(f"  Tech zone 成員：{len(codes)} 家")

    # 上市 + 上櫃 合併
    rows = []
    for url, market in [(TWSE_URL, "sii"), (TPEX_URL, "otc")]:
        try:
            data = _fetch_json(url)
            print(f"  ✓ {market} {len(data)} 筆原始")
            for r in data:
                rows.append(_normalize(r, market))
        except Exception as e:
            print(f"  ⚠️ {market} 抓取失敗: {e}")

    # 全市場 by code（給其他用途，但只 dump tech zone 27 家精簡版）
    full_by_code = {r["code"]: r for r in rows if r["code"]}
    tz_rows = {c: full_by_code[c] for c in codes if c in full_by_code}

    # 也算全市場累計 YoY top 50（給「半導體題材最強 50 名」用）
    semi_keyword = "半導體"
    semi_rows = [r for r in rows if r.get("industry") and semi_keyword in r["industry"] and r.get("yoy_pct") is not None]
    semi_rows.sort(key=lambda r: r["yoy_pct"], reverse=True)
    semi_top = semi_rows[:30]

    # 找最新資料年月
    yms = [r["data_year_month"] for r in rows if r.get("data_year_month")]
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


def _ym_display(ym: str | None) -> str | None:
    """11504 (民國 115 年 04 月) → '2026/04'"""
    if not ym or len(ym) != 5:
        return ym
    try:
        year = 1911 + int(ym[:3])
        month = int(ym[3:])
        return f"{year}/{month:02d}"
    except Exception:
        return ym


if __name__ == "__main__":
    build_mops_json()
