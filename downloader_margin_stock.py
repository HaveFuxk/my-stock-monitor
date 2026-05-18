# -*- coding: utf-8 -*-
"""
downloader_margin_stock.py — B3：個股融資融券餘額

Endpoint：TWSE openapi（每日 snapshot，上市股）
  https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN
  欄位（張數）：
    融資買進 / 融資賣出 / 融資現金償還 / 融資前日餘額 / 融資今日餘額 / 融資限額
    融券買進 / 融券賣出 / 融券現券償還 / 融券前日餘額 / 融券今日餘額 / 融券限額
    資券互抵 / 註記

TPEX 上櫃個股 margin 沒有可用 JSON endpoint（openapi 返 HTML），略過。
27 家 tech zone 中約 8 家 OTC 會無此資料，前端會 fallback 顯示 "—"。

寫到 dist/data/margin_stock.json，僅留 tech zone 成員精簡 JSON。
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

OUT_FILE = Path("dist") / "data" / "margin_stock.json"
INDUSTRY_MAPS_FILE = Path("config") / "industry_maps.json"
TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"


def _collect_tech_zone_codes() -> set[str]:
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


def _to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _normalize(row: dict) -> dict:
    """TWSE margin row → 精簡欄位（張數）。"""
    return {
        "code": row.get("股票代號"),
        "name": row.get("股票名稱"),
        "margin_balance": _to_int(row.get("融資今日餘額")),
        "margin_prev": _to_int(row.get("融資前日餘額")),
        "margin_buy": _to_int(row.get("融資買進")),
        "margin_sell": _to_int(row.get("融資賣出")),
        "short_balance": _to_int(row.get("融券今日餘額")),
        "short_prev": _to_int(row.get("融券前日餘額")),
        "short_buy": _to_int(row.get("融券買進")),
        "short_sell": _to_int(row.get("融券賣出")),
    }


def build_margin_stock_json(out_path: Path = OUT_FILE) -> dict:
    print("=" * 60)
    print("📊 [margin_stock] 抓個股融資融券（TWSE openapi）")
    print("=" * 60)

    codes = _collect_tech_zone_codes()
    print(f"  Tech zone 成員：{len(codes)} 家")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(TWSE_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
            data = json.loads(r.read())
        print(f"  ✓ TWSE 上市 {len(data)} 筆原始")
    except Exception as e:
        print(f"  ⚠️ TWSE 抓取失敗（不擋 build）: {e}")
        data = []

    by_code = {}
    for raw in data:
        norm = _normalize(raw)
        if norm["code"]:
            by_code[norm["code"]] = norm

    tz_rows = {c: by_code[c] for c in codes if c in by_code}

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
