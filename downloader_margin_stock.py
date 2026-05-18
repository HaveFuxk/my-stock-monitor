# -*- coding: utf-8 -*-
"""
downloader_margin_stock.py — B3：個股融資融券餘額

Endpoint：TWSE openapi MI_MARGN（每日 snapshot，上市股）
  https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN

TPEX 上櫃個股 margin 沒有可用 JSON endpoint（openapi 返 HTML），略過。
27 家 tech zone 中約 8 家 OTC 會無此資料，前端 fallback 顯示 "—"。

只 keep 前端真正使用的欄位：margin_balance / margin_prev / short_balance。
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from downloader_utils import init_stdout, http_get_json, to_int, collect_tech_zone_codes

init_stdout()

OUT_FILE = Path("dist") / "data" / "margin_stock.json"
TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"


def _normalize(row: dict) -> dict:
    """TWSE margin row → 精簡欄位（張數）。
    只保留前端用得到的：餘額 + 昨日餘額（算變化）+ 融券餘額。
    融資/融券買賣明細省略（前端不顯示）。"""
    return {
        "code": row.get("股票代號"),
        "name": row.get("股票名稱"),
        "margin_balance": to_int(row.get("融資今日餘額")),
        "margin_prev": to_int(row.get("融資前日餘額")),
        "short_balance": to_int(row.get("融券今日餘額")),
    }


def build_margin_stock_json(out_path: Path = OUT_FILE) -> dict:
    print("=" * 60)
    print("📊 [margin_stock] 抓個股融資融券（TWSE openapi）")
    print("=" * 60)

    codes = collect_tech_zone_codes()
    print(f"  Tech zone 成員：{len(codes)} 家")

    data = http_get_json(TWSE_URL, timeout=30) or []
    print(f"  ✓ TWSE 上市 {len(data)} 筆原始")

    # Filter-before-normalize：先濾再 normalize
    tz_rows = {}
    for row in data:
        code = row.get("股票代號")
        if code in codes:
            tz_rows[code] = _normalize(row)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "TWSE openapi MI_MARGN（上市；上櫃無 JSON endpoint 已 skip）",
        "tech_zone_count": len(tz_rows),
        "tech_zone": tz_rows,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ [margin_stock] 寫入 {out_path}：{len(tz_rows)}/{len(codes)} 家有融資融券資料")
    return out


if __name__ == "__main__":
    build_margin_stock_json()
