# -*- coding: utf-8 -*-
"""
downloader_mops_quarterly.py — Tier 3 C3：季財報（每股盈餘 + 損益）

Endpoints (最新季簡明損益表 snapshot)：
  - TWSE 上市：https://openapi.twse.com.tw/v1/opendata/t187ap14_L
  - TPEX 上櫃：https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap14_O

每筆含：
  - 出表日期 / 年度（民國）/ 季別 / 公司代號 / 公司名稱 / 產業別
  - 基本每股盈餘(元) ← EPS
  - 普通股每股面額（多數 10 元，少數面額不同的 e.g. KY）
  - 營業收入 / 營業利益 / 營業外收入及支出 / 稅後淨利（千元）

寫到 dist/data/mops_quarterly.json，僅留 tech zone 27 家精簡版。
順便算每家：營業利益率 = 營業利益 / 營業收入、淨利率 = 稅後淨利 / 營業收入。
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from downloader_utils import init_stdout, http_get_json, to_float, collect_tech_zone_codes

init_stdout()

OUT_FILE = Path("dist") / "data" / "mops_quarterly.json"
TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap14_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap14_O"


def _safe_pct(numer, denom):
    """numer / denom × 100；denom <= 0 或 None 回 None。"""
    if numer is None or denom is None or denom <= 0:
        return None
    return numer / denom * 100


def _normalize(row: dict, market: str) -> dict:
    """t187ap14 row → 精簡欄位 + 算 margins。
    營收/利益單位都是千元；EPS 是 元。"""
    revenue = to_float(row.get("營業收入"))
    op_income = to_float(row.get("營業利益"))
    net_income = to_float(row.get("稅後淨利"))
    return {
        "code": row.get("公司代號"),
        "name": row.get("公司名稱"),
        "industry": row.get("產業別"),
        "market": market,
        "year": int(row.get("年度") or 0) or None,           # 民國年
        "quarter": int(row.get("季別") or 0) or None,
        "eps": to_float(row.get("基本每股盈餘(元)")),         # 元
        "revenue": revenue,                                    # 千元
        "op_income": op_income,                                # 千元
        "non_op_income": to_float(row.get("營業外收入及支出")), # 千元
        "net_income": net_income,                              # 千元
        "op_margin": _safe_pct(op_income, revenue),            # %
        "net_margin": _safe_pct(net_income, revenue),          # %
    }


def _quarter_display(year: int | None, quarter: int | None) -> str | None:
    """民國 年 季 → '2026 Q1'"""
    if not year or not quarter:
        return None
    return f"{1911 + year} Q{quarter}"


def build_mops_quarterly_json(out_path: Path = OUT_FILE) -> dict:
    print("=" * 60)
    print("📊 [mops_quarterly] 抓季財報（綜合損益表 + EPS）")
    print("=" * 60)

    codes = collect_tech_zone_codes()
    print(f"  Tech zone 成員：{len(codes)} 家")

    tz_rows = {}
    for url, market in [(TWSE_URL, "sii"), (TPEX_URL, "otc")]:
        data = http_get_json(url, timeout=30)
        if data is None:
            print(f"  ⚠️ {market} 抓取失敗")
            continue
        print(f"  ✓ {market} {len(data)} 筆原始")
        # filter-before-normalize
        for row in data:
            code = row.get("公司代號")
            if code in codes:
                tz_rows[code] = _normalize(row, market)

    # 找最新 year+quarter（同一批 snapshot 通常一致）
    yqs = [(r["year"], r["quarter"]) for r in tz_rows.values()
           if r.get("year") and r.get("quarter")]
    latest_yq = max(yqs) if yqs else (None, None)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_year": latest_yq[0],
        "data_quarter": latest_yq[1],
        "data_quarter_display": _quarter_display(*latest_yq),
        "tech_zone_count": len(tz_rows),
        "tech_zone": tz_rows,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ [mops_quarterly] 寫入 {out_path}：{len(tz_rows)} 家 tech zone，最新季 {_quarter_display(*latest_yq)}")
    return out


if __name__ == "__main__":
    build_mops_quarterly_json()
