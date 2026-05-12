# -*- coding: utf-8 -*-
"""
downloader_news.py — 台股財經新聞 daily downloader

來源：
  1. 鉅亨網 headline API（無需 key，公開 REST）
  2. Yahoo 奇摩新聞 - 財經 RSS
  3. 自由時報 - 財經 RSS

各取最近 N 篇，整合寫到 dist/data/news.json，供前端 spotlight 卡使用。
每筆 record：source / title / summary / link / published_at(ISO) / tags(list)

容錯：任一 source 抓不到就 skip，不擋住 build。
"""
import json
import re
import sys
import ssl
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

OUT_FILE = Path("dist") / "data" / "news.json"

CNYES_API = "https://api.cnyes.com/media/api/v1/newslist/category/headline"
YAHOO_RSS = "https://tw.news.yahoo.com/rss/finance"
LTN_RSS = "https://news.ltn.com.tw/rss/business.xml"

USER_AGENT = "Mozilla/5.0 my-stock-monitor"


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _http_get(url: str, retries: int = 2, timeout: int = 12, accept: str = "*/*"):
    """通用 GET，回傳 raw bytes（給 RSS）或 None。"""
    last_err = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT, "Accept": accept,
            })
            with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError) as e:
            last_err = e
            if i < retries:
                time.sleep(1.0 + i)
    print(f"⚠️ [news] GET failed: {url} — {last_err}")
    return None


def _strip_html(s: str) -> str:
    """RSS description 常含 HTML tags，剝乾淨；保留中文與基本符號。"""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"&nbsp;", " ", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&quot;", '"', s)
    s = re.sub(r"&lt;", "<", s)
    s = re.sub(r"&gt;", ">", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _truncate(s: str, max_chars: int = 110) -> str:
    if not s:
        return ""
    s = s.strip()
    return s if len(s) <= max_chars else s[:max_chars].rstrip() + "…"


def _to_iso(dt: datetime) -> str:
    """datetime → 'YYYY-MM-DDTHH:MM:SS+0800' 字串（前端好顯示）。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# ====================== Source 1: 鉅亨網 ======================
def fetch_cnyes_headline(limit: int = 8):
    """鉅亨網頭條 API。回傳 list of dict。"""
    url = f"{CNYES_API}?limit={limit}&page=1"
    raw = _http_get(url, accept="application/json")
    if not raw:
        return []
    try:
        d = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        print(f"⚠️ [news/cnyes] JSON decode fail: {e}")
        return []
    items = (d.get("items") or {}).get("data") or []
    out = []
    for n in items:
        ts = n.get("publishAt")
        published = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone() if ts else None
        keywords = n.get("keyword") or []
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",") if k.strip()]
        out.append({
            "source": "鉅亨網",
            "source_slug": "cnyes",
            "title": _strip_html(n.get("title") or ""),
            "summary": _truncate(_strip_html(n.get("summary") or ""), 110),
            "link": f"https://news.cnyes.com/news/id/{n.get('newsId')}",
            "published_at": _to_iso(published) if published else None,
            "category": n.get("categoryName") or "",
            "tags": keywords[:3],
        })
    return out


# ====================== Source 2/3: 通用 RSS parser ======================
def _parse_rss(raw: bytes, source_name: str, source_slug: str, limit: int = 8):
    if not raw:
        return []
    try:
        # RSS 偶爾混 BOM；ET 容忍但保險起見 decode 一次
        text = raw.decode("utf-8", errors="replace")
        root = ET.fromstring(text)
    except ET.ParseError as e:
        print(f"⚠️ [news/{source_slug}] RSS parse fail: {e}")
        return []
    # RSS 標準路徑：rss/channel/item
    items = root.findall(".//item")[:limit]
    out = []
    for it in items:
        title = (it.findtext("title") or "").strip()
        desc = _strip_html(it.findtext("description") or "")
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        # pubDate 格式 e.g. "Tue, 12 May 2026 16:45:19 +0800"
        published_iso = None
        if pub:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(pub)
                published_iso = _to_iso(dt)
            except (TypeError, ValueError):
                pass
        out.append({
            "source": source_name,
            "source_slug": source_slug,
            "title": _strip_html(title),
            "summary": _truncate(desc, 110),
            "link": link,
            "published_at": published_iso,
            "category": "財經",
            "tags": [],  # RSS 沒有結構化 tag；前端會 fallback 用 category
        })
    return out


def fetch_yahoo_finance(limit: int = 8):
    """Yahoo 奇摩新聞 - 財經 RSS。"""
    raw = _http_get(YAHOO_RSS, accept="application/rss+xml, application/xml, text/xml")
    return _parse_rss(raw, "Yahoo 股市", "yahoo", limit=limit)


def fetch_ltn_business(limit: int = 8):
    """自由時報 - 財經 RSS。"""
    raw = _http_get(LTN_RSS, accept="application/rss+xml, application/xml, text/xml")
    return _parse_rss(raw, "自由財經", "ltn", limit=limit)


# ====================== 主流程 ======================
def build_news_json(out_path: Path = OUT_FILE, per_source: int = 6):
    sources = [
        ("cnyes", fetch_cnyes_headline),
        ("yahoo", fetch_yahoo_finance),
        ("ltn", fetch_ltn_business),
    ]
    all_items = []
    by_source = {}
    for slug, fn in sources:
        try:
            items = fn(limit=per_source)
        except Exception as e:
            print(f"⚠️ [news/{slug}] fetcher 拋例外：{e}")
            items = []
        by_source[slug] = items
        all_items.extend(items)
        print(f"   - {slug}: {len(items)} 篇")

    # 按 published_at 排序（新到舊），None 排最後
    all_items.sort(key=lambda x: x.get("published_at") or "", reverse=True)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total": len(all_items),
        "by_source": {k: len(v) for k, v in by_source.items()},
        "items": all_items,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ [news] 寫入 {out_path} — {len(all_items)} 篇（{payload['by_source']}）")
    return payload


if __name__ == "__main__":
    build_news_json()
