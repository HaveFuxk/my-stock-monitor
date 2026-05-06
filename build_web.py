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


def _export_kline_json(report_df, market_id="tw-share", top_n=300, history_days=500):
    """
    從 data/<market_id>/dayK/*.csv 中挑出 report_df 排名 top_n 的個股，
    每檔 export 成 dist/data/<safe_id>.json（lightweight-charts 格式）。
    同時寫 dist/data/manifest.json 列出所有可用 ticker。

    safe_id = ticker.replace('.', '_').replace('/', '_')，避免 URL 路徑問題。

    回傳 manifest list（即使部分檔案失敗也會繼續）。
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

    # 用 Year_High 排序，取前 top_n
    df_ranked = (
        report_df.dropna(subset=["Year_High"])
        .sort_values("Year_High", ascending=False)
        .head(top_n)
    )

    manifest = []
    skipped = 0
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
            # yfinance 第一欄通常是 Date；若無 'date' 嘗試把第一欄當 date
            if "date" not in df.columns:
                first_col = df.columns[0]
                df = df.rename(columns={first_col: "date"})
            required = {"date", "open", "high", "low", "close"}
            if not required.issubset(df.columns):
                skipped += 1
                continue

            # 截尾保留最近 history_days 天，控制 JSON size
            if len(df) > history_days:
                df = df.tail(history_days)

            records = []
            for _, r in df.iterrows():
                try:
                    records.append({
                        "time": str(r["date"])[:10],
                        "open": float(r["open"]),
                        "high": float(r["high"]),
                        "low": float(r["low"]),
                        "close": float(r["close"]),
                    })
                except (ValueError, TypeError):
                    continue
            if not records:
                skipped += 1
                continue

            safe_id = ticker.replace(".", "_").replace("/", "_")
            (out_dir / f"{safe_id}.json").write_text(
                json.dumps(records, ensure_ascii=False), encoding="utf-8"
            )

            manifest.append({
                "ticker": ticker,
                "name": name,
                "safe_id": safe_id,
                "year_high": float(row["Year_High"]) if pd.notna(row.get("Year_High")) else None,
                "month_high": float(row["Month_High"]) if pd.notna(row.get("Month_High")) else None,
                "week_high": float(row["Week_High"]) if pd.notna(row.get("Week_High")) else None,
                "samples": len(records),
            })
        except Exception as e:
            skipped += 1
            continue

    # 排序後寫 manifest（依年漲幅 desc）
    manifest.sort(key=lambda x: x.get("year_high") or -999, reverse=True)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"   - K 線 JSON：{len(manifest)} 檔 → dist/data/（跳過 {skipped} 檔）")
    return manifest


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
