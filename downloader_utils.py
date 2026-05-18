# -*- coding: utf-8 -*-
"""
downloader_utils.py — 多個 downloader 共用 helper

集中：SSL context / Windows stdout 重設 / HTTP GET JSON / 數字 parse / tech zone 成員清單
讓 downloader_mops / downloader_margin_stock / downloader_intl 不再各自 copy-paste。
"""
import json
import ssl
import sys
import urllib.request
import urllib.error
from pathlib import Path

# 絕對路徑：相對於本檔（repo root），讓 callers 從任何 cwd import 都能正確找到。
INDUSTRY_MAPS_FILE = Path(__file__).resolve().parent / "config" / "industry_maps.json"


def init_stdout():
    """Windows console (cp950) 不支援 emoji — 轉 utf-8 才不會 print 失敗。"""
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass


def ssl_ctx() -> ssl.SSLContext:
    """寬鬆 SSL context — 跟 TWSE/TPEX 走的時候避免憑證問題擋住。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def http_get_json(url: str, timeout: int = 30, user_agent: str = "Mozilla/5.0") -> dict | list | None:
    """GET URL 解析成 JSON。失敗回傳 None（caller 自決定要 raise 還是 skip）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, context=ssl_ctx(), timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


def to_int(v) -> int | None:
    """寬鬆 int parser — None / 空字串 / 含逗號 都 OK。"""
    if v is None or v == "":
        return None
    try:
        return int(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def to_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def collect_tech_zone_codes(industry_maps_path: Path = INDUSTRY_MAPS_FILE) -> set[str]:
    """從 industry_maps.json 抓所有 tech zone 成員 4-碼 ticker。
    支援 layers > roles > companies 與 flat companies 兩種結構。
    檔不存在或讀取失敗回空 set（caller 自處理）。"""
    try:
        imap = json.loads(industry_maps_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
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
