# -*- coding: utf-8 -*-
"""
news_tagger.py — 對 dist/data/news.json 的每篇文章標記提及的台股 ticker

工作原理：對每篇文章的 title + summary 做兩種匹配：
  1. 中文公司名匹配（從 manifest.json 取 name → ticker 對照，最長優先）
     - 左側 guard：名稱前一個字若是中文 CJK 字元就拒絕（避免 鼎泰豐 → 泰豐、東南亞 → 南亞）
     - 模糊名稱 AMBIGUOUS_NAMES：本身就是常見中文片語的名稱（泰豐、三星、全台、大成、南亞），
       要求 ticker 4 碼數字「共現」才認定，否則 skip
  2. 4 碼 ticker 匹配（過濾年份 1900-2099 後比對 manifest 內的 code）

輸出：每篇 article 新增 mentioned_tickers: ["2330.TW", "2412.TW", ...]

被 build_web._build_news_data() 在 downloader_news.build_news_json() 之後呼叫。
"""
import json
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


# 4 碼數字 + 可選大寫字母（00981A、2330、2412），不允許前後是更多數字或斜線
# 避免比中 1234567 / 2026/01 等
_NUMERIC_TICKER = re.compile(r'(?<![\d/])(\d{4}[A-Z]?)(?![\d])')

# 中文 CJK 統一表意文字（用來判斷左側 guard）
_CJK = re.compile(r'[一-鿿]')

# 名稱本身就是常見中文片語，substring 容易誤匹（鼎泰豐 → 泰豐、三星電子 → 三星）
# 這些名稱必須與其 4 碼 ticker code「共現」於文章才認定為提及。
# 動態擴充規則：發現新的誤匹案例補進來即可。
AMBIGUOUS_NAMES = {
    # 常見飲食 / 連鎖店名片段
    "泰豐", "鼎豐", "全台", "全國", "永豐", "東森",
    # 常見地理 / 名詞片段
    "南亞", "南港", "中央", "中信", "中華", "北銘", "東陽",
    # 通用片語
    "大成", "達新", "正豐", "華新", "華星", "明星", "光明",
    # Samsung 韓國的中文（會跟 5007 三星科技 撞）
    "三星",
    # 其他經常出現於通用文章的 2 字名
    "彰銀", "金山",
}


def _is_likely_ticker(code: str) -> bool:
    """過濾年份。00981A 之類含字母的不過濾。"""
    if not code.isdigit():
        return True
    n = int(code)
    return not (1900 <= n <= 2099)


def _find_with_left_guard(text: str, name: str) -> list[int]:
    """回傳 name 在 text 中所有「左側不是中文 CJK 字元」的起始 index。"""
    out = []
    pos = 0
    while True:
        idx = text.find(name, pos)
        if idx < 0:
            break
        if idx > 0 and _CJK.match(text[idx - 1]):
            # 鼎(CJK) + 泰豐 → 拒絕；位移 1 字繼續找
            pos = idx + 1
            continue
        out.append(idx)
        pos = idx + len(name)
    return out


def tag_mentions(items: list[dict], ticker_index: list[tuple[str, str]]) -> dict:
    """對 items 就地加 mentioned_tickers 欄位。

    ticker_index: [(ticker, name), ...] 例如 [("2330.TW", "台積電"), ...]
    回傳: stats dict
    """
    # 名稱長度 >= 2，最長優先（先匹中華電再匹中華，避免被短的搶先）
    name_pairs = sorted(
        [(name, ticker) for ticker, name in ticker_index if name and len(name) >= 2],
        key=lambda x: -len(x[0])
    )
    # 拆兩組：一般 vs 模糊
    name_pairs_normal = [(n, t) for n, t in name_pairs if n not in AMBIGUOUS_NAMES]
    name_pairs_ambiguous = [(n, t) for n, t in name_pairs if n in AMBIGUOUS_NAMES]

    # code (4 位 + 可選字母) → 完整 ticker（同 code 多 ticker 時 .TW 優先）
    code_to_full: dict[str, str] = {}
    for ticker, _ in ticker_index:
        code = ticker.split(".")[0]
        if code not in code_to_full or ticker.endswith(".TW"):
            code_to_full[code] = ticker

    by_ticker_count: dict[str, int] = {}
    tagged = 0

    for item in items:
        text = (item.get("title") or "") + " " + (item.get("summary") or "")
        mentioned: set[str] = set()
        scratch = text  # 命中後會把該段落替成空白避免重複命中

        # 先掃 text 中所有合法 ticker code（供模糊名稱做共現確認）
        codes_present = set()
        for m in _NUMERIC_TICKER.findall(text):
            if _is_likely_ticker(m) and m in code_to_full:
                codes_present.add(m)

        # Pass 1a: 一般名稱（左側 guard）
        for name, ticker in name_pairs_normal:
            hits = _find_with_left_guard(scratch, name)
            if hits:
                mentioned.add(ticker)
                # 把所有命中位置替成空白
                buf = list(scratch)
                for idx in hits:
                    for k in range(idx, idx + len(name)):
                        if k < len(buf):
                            buf[k] = " "
                scratch = "".join(buf)

        # Pass 1b: 模糊名稱（左側 guard + ticker code 共現）
        for name, ticker in name_pairs_ambiguous:
            code = ticker.split(".")[0]
            if code not in codes_present:
                continue
            hits = _find_with_left_guard(scratch, name)
            if hits:
                mentioned.add(ticker)
                buf = list(scratch)
                for idx in hits:
                    for k in range(idx, idx + len(name)):
                        if k < len(buf):
                            buf[k] = " "
                scratch = "".join(buf)

        # Pass 2: 純 4 碼 ticker（在 scratch 上，已扣除被名稱命中的部分）
        for m in _NUMERIC_TICKER.findall(scratch):
            if not _is_likely_ticker(m):
                continue
            if m in code_to_full:
                mentioned.add(code_to_full[m])

        item["mentioned_tickers"] = sorted(mentioned)
        if mentioned:
            tagged += 1
            for t in mentioned:
                by_ticker_count[t] = by_ticker_count.get(t, 0) + 1

    return {
        "tagged_count": tagged,
        "total": len(items),
        "by_ticker": dict(sorted(by_ticker_count.items(), key=lambda x: -x[1])),
    }


def tag_industries(items: list[dict], industries: list[dict]) -> dict:
    """對 items 就地加 industry_tags 欄位（id 陣列）。

    industries: industry_maps.json 的 industries 陣列；每個 industry 需含 id + keywords。
    Keyword 比對：大小寫不敏感、不要求 word boundary（中英都直接 substring 即可）。
    回傳 stats dict。
    """
    # 預編譯每個 industry 的關鍵字（lower-case 版）
    industry_keys: list[tuple[str, list[str]]] = []
    for ind in industries:
        kws = ind.get("keywords") or []
        kws_lower = [k.lower() for k in kws if k]
        if kws_lower:
            industry_keys.append((ind["id"], kws_lower))

    by_industry_count: dict[str, int] = {}
    tagged = 0

    for item in items:
        text = ((item.get("title") or "") + " " + (item.get("summary") or "")).lower()
        hit: set[str] = set()
        for ind_id, kws in industry_keys:
            for kw in kws:
                if kw in text:
                    hit.add(ind_id)
                    break  # 同產業內任一關鍵字命中即可
        # 不覆寫，保留 mentioned_tickers
        item["industry_tags"] = sorted(hit)
        if hit:
            tagged += 1
            for i in hit:
                by_industry_count[i] = by_industry_count.get(i, 0) + 1

    return {
        "tagged_count": tagged,
        "total": len(items),
        "by_industry": dict(sorted(by_industry_count.items(), key=lambda x: -x[1])),
    }


def tag_news_file(
    news_path: Path,
    manifest_path: Path,
    industry_maps_path: Path | None = None,
) -> dict | None:
    """讀 news.json + manifest.json (+ industry_maps.json)，做 tagging 後寫回 news.json。
    回傳 stats；news/manifest 任一不存在則回 None。industry_maps 可選。"""
    if not news_path.exists():
        print(f"⚠️ [news_tagger] {news_path} 不存在，跳過 tagging")
        return None
    if not manifest_path.exists():
        print(f"⚠️ [news_tagger] {manifest_path} 不存在，跳過 tagging")
        return None

    news = json.loads(news_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    ticker_index = [(x["ticker"], x.get("name", "")) for x in manifest if x.get("ticker")]
    items = news.get("items", [])
    stats_t = tag_mentions(items, ticker_index)

    stats_i = None
    if industry_maps_path and industry_maps_path.exists():
        try:
            imap = json.loads(industry_maps_path.read_text(encoding="utf-8"))
            stats_i = tag_industries(items, imap.get("industries") or [])
        except Exception as e:
            print(f"⚠️ [news_tagger] industry tagging fail: {e}")

    news["tagged"] = {
        "tagged_count": stats_t["tagged_count"],
        "total": stats_t["total"],
        "top_tickers": list(stats_t["by_ticker"].items())[:10],
        **({
            "industry_tagged_count": stats_i["tagged_count"],
            "by_industry": stats_i["by_industry"],
        } if stats_i else {}),
    }
    news_path.write_text(json.dumps(news, ensure_ascii=False, indent=2), encoding="utf-8")
    msg = (
        f"✅ [news_tagger] {stats_t['tagged_count']}/{stats_t['total']} 篇有 ticker；"
        f"top: {list(stats_t['by_ticker'].items())[:5]}"
    )
    if stats_i:
        msg += f" | industry {stats_i['tagged_count']}/{stats_i['total']}: {stats_i['by_industry']}"
    print(msg)
    return {"mention": stats_t, "industry": stats_i}


if __name__ == "__main__":
    # 獨立執行：對 dist/data/news.json 重打 tag
    tag_news_file(
        Path("dist") / "data" / "news.json",
        Path("dist") / "data" / "manifest.json",
        Path("dist") / "data" / "industry_maps.json",
    )
