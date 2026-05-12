# -*- coding: utf-8 -*-
"""
downloader_macro.py — 台股總體籌碼 daily downloader

抓兩個 TWSE 公開 endpoint：
  1. BFI82U  — 三大法人合計（外資 / 投信 / 自營）當日買賣超金額
  2. MI_MARGN — 全市場融資融券餘額

寫成單一 dist/data/macro.json，供前端 dashboard 兩張對照表顯示。
若當日休市，自動往前找最近一個有效交易日（最多回溯 7 天）。

跟 downloader_chips.py 不同：chips 是個股 × 日期的時序，這支只取最新一日總體。
"""
import json
import sys
import ssl
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

OUT_FILE = Path("dist") / "data" / "macro.json"
TWSE_BFI82U = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
TWSE_MARGN = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"


def _ssl_ctx():
    """TWSE 證書老舊；本機關掉嚴格驗證（公開資料，MITM 影響有限）。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _http_get_json(url: str, retries: int = 2, timeout: int = 15):
    """GET JSON，失敗 retry。回傳 dict 或 None。"""
    last_err = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 my-stock-monitor",
                "Accept": "application/json, text/plain, */*",
            })
            with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
            last_err = e
            if i < retries:
                time.sleep(1.5 + i)
    print(f"⚠️ [macro] GET failed: {url} — {last_err}")
    return None


def _parse_num(s):
    """TWSE 千分位數字字串 → int 或 None。"""
    if s is None:
        return None
    t = str(s).strip().replace(",", "").replace(" ", "")
    if not t or t in ("--", "-"):
        return None
    try:
        return int(float(t))
    except (ValueError, TypeError):
        return None


def fetch_institutional_total(date_str: str):
    """
    抓 BFI82U（三大法人合計買賣超），回傳：
        {
          "date": "20260511",
          "foreign":      {"buy": ..., "sell": ..., "net": ...},   # 外資及陸資
          "trust":        {"buy": ..., "sell": ..., "net": ...},   # 投信
          "dealer_self":  {...},   # 自營(自行買賣)
          "dealer_hedge": {...},   # 自營(避險)
          "dealer_total": {...},   # 自營合計（自行買賣 + 避險）
          "grand_total":  {...},   # 三大法人合計
        }
    若該日休市 / API 無資料，回 None。

    BFI82U rows 順序（已固定多年）：
        0. 自營商(自行買賣)
        1. 自營商(避險)
        2. 投信
        3. 外資及陸資(不含外資自營商)
        4. 外資自營商
        5. 合計
    """
    url = f"{TWSE_BFI82U}?dayDate={date_str}&type=day&response=json"
    d = _http_get_json(url)
    if not d or d.get("stat") != "OK":
        return None
    rows = d.get("data") or []
    if len(rows) < 5:
        return None

    def parse_row(r):
        if not r or len(r) < 4:
            return {"buy": None, "sell": None, "net": None}
        return {"buy": _parse_num(r[1]), "sell": _parse_num(r[2]), "net": _parse_num(r[3])}

    dealer_self = parse_row(rows[0])
    dealer_hedge = parse_row(rows[1])
    trust = parse_row(rows[2])
    foreign = parse_row(rows[3])

    # 自營合計（自行買賣 + 避險）
    def _sum(a, b):
        return {
            "buy": (a["buy"] or 0) + (b["buy"] or 0) if a["buy"] is not None or b["buy"] is not None else None,
            "sell": (a["sell"] or 0) + (b["sell"] or 0) if a["sell"] is not None or b["sell"] is not None else None,
            "net": (a["net"] or 0) + (b["net"] or 0) if a["net"] is not None or b["net"] is not None else None,
        }
    dealer_total = _sum(dealer_self, dealer_hedge)
    grand_total = parse_row(rows[5]) if len(rows) > 5 else _sum(_sum(foreign, trust), dealer_total)

    return {
        "date": date_str,
        "foreign": foreign,
        "trust": trust,
        "dealer_self": dealer_self,
        "dealer_hedge": dealer_hedge,
        "dealer_total": dealer_total,
        "grand_total": grand_total,
    }


def fetch_margin_balance(date_str: str):
    """
    抓 MI_MARGN（全市場融資融券彙總），回傳：
        {
          "date": "20260511",
          "financing": {"buy": ..., "sell": ..., "repay": ..., "prev_balance": ..., "today_balance": ..., "change": ...},
          "shorting":  {...},
          "financing_amount": {...},   # 融資金額（萬元）
        }
    若該日休市 / 無資料，回 None。

    tables[0] = 信用交易統計（小表），3 rows：
        0. 融資 (交易單位：股)
        1. 融券 (交易單位：股)
        2. 融資金額 (萬元)
    fields: [項目, 買進, 賣出, 現金償還(或現券), 前日餘額, 今日餘額]
    """
    url = f"{TWSE_MARGN}?date={date_str}&selectType=ALL&response=json"
    d = _http_get_json(url)
    if not d or d.get("stat") != "OK":
        return None
    tables = d.get("tables") or []
    if not tables:
        return None
    summary = tables[0]
    rows = summary.get("data") or []
    if len(rows) < 2:
        return None

    def parse_row(r):
        if not r or len(r) < 6:
            return {"buy": None, "sell": None, "repay": None, "prev_balance": None,
                    "today_balance": None, "change": None}
        prev_bal = _parse_num(r[4])
        today_bal = _parse_num(r[5])
        change = today_bal - prev_bal if (prev_bal is not None and today_bal is not None) else None
        return {
            "buy": _parse_num(r[1]),
            "sell": _parse_num(r[2]),
            "repay": _parse_num(r[3]),
            "prev_balance": prev_bal,
            "today_balance": today_bal,
            "change": change,
        }

    financing = parse_row(rows[0]) if len(rows) > 0 else None
    shorting = parse_row(rows[1]) if len(rows) > 1 else None
    financing_amount = parse_row(rows[2]) if len(rows) > 2 else None
    return {
        "date": date_str,
        "financing": financing,
        "shorting": shorting,
        "financing_amount": financing_amount,
    }


def build_macro_json(out_path: Path = OUT_FILE, max_lookback_days: int = 7):
    """
    抓最新一個有效交易日的兩個 endpoint，整合寫入 out_path。

    today 開始往前找最近一個 BFI82U stat=OK 的日期，最多回溯 max_lookback_days。
    （週六/日 / 國定假日不開盤，要 fallback；TWSE 通常下午 15:00 後出當日資料。）
    """
    today = datetime.now()
    inst = None
    margin = None
    inst_date = None
    margin_date = None

    # 法人跟融資融券各自獨立 fallback —— 因為 TWSE 兩個 endpoint 開放時間不同步
    # （法人通常 15:00 前後出；融資融券有時要 17:00 之後）
    for back in range(max_lookback_days):
        d = (today - timedelta(days=back)).strftime("%Y%m%d")
        if datetime.strptime(d, "%Y%m%d").weekday() >= 5:
            continue  # skip 週六日
        if inst is None:
            inst = fetch_institutional_total(d)
            if inst:
                inst_date = d
        if margin is None:
            margin = fetch_margin_balance(d)
            if margin:
                margin_date = d
        if inst is not None and margin is not None:
            break
        time.sleep(0.4)  # 對 TWSE 友善

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "institutional_date": inst_date,
        "margin_date": margin_date,
        "date": inst_date or margin_date,
        "institutional": inst,
        "margin": margin,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if inst_date or margin_date:
        bits = []
        if inst_date: bits.append(f"法人 {inst_date}")
        if margin_date: bits.append(f"融資融券 {margin_date}")
        print(f"✅ [macro] 寫入 {out_path} — {', '.join(bits)}")
    else:
        print(f"⚠️ [macro] 連續 {max_lookback_days} 天都抓不到資料，寫入空 payload")
    return payload


if __name__ == "__main__":
    build_macro_json()
