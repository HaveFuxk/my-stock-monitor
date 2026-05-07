# -*- coding: utf-8 -*-
"""
ai_summary.py — 用 Gemini 對個股做中文產業分析摘要

策略：
  1. 對 build_web 階段選定的 ticker（通常是 Top 100 飆股 + 白名單大型股），
     呼叫 Gemini API 把 yfinance.info.longBusinessSummary（英文業務描述）
     轉成中文三段摘要：業務分析 / 競爭優勢 / 主要風險
  2. 結果 cache 到 SQLite `data/ai_summary.db`，14 天過期
  3. 沒設 GEMINI_API_KEY env 時整個跳過（不阻塞 build），UI 端 fallback
  4. Free tier RPM 限制 ~15，內建 0.5s sleep 規避
  5. cache 失敗或無資料時不 raise，回 None 給 build_web

Gemini Free tier: https://aistudio.google.com/app/apikey
  - gemini-2.0-flash 或 gemini-1.5-flash 皆可
  - Free tier: 15 RPM / 1M TPM / 1500 RPD（2026-05 當前）
"""
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB_PATH = Path("data") / "ai_summary.db"
CACHE_TTL_DAYS = 14
MODEL_NAME = os.getenv("AI_SUMMARY_MODEL", "gemini-2.0-flash")
RPM_SLEEP = 4.5  # 4.5s/call ≈ 13 RPM，留 buffer 不撞 free tier 15 RPM

PROMPT_TEMPLATE = """你是台股產業分析師，根據以下英文業務描述（來自 Yahoo Finance / yfinance.info），用繁體中文產出三段精簡分析。

公司：{company_name}（{ticker}）
產業類別：{sector} / {industry}
英文業務描述：
{business_summary}

要求：
1. 三段：業務分析（公司主要做什麼）/ 競爭優勢（與同業相比的特點）/ 主要風險（投資人應關注的下行風險）
2. 每段 60-90 字，繁體中文，不要分點 / 不要 markdown / 不要 emoji
3. 業務分析直接從產品線、客戶、地理分布切入，不要廢話開場
4. 競爭優勢請具體（譬如「先進製程市占過半」），避免空洞詞
5. 風險側重結構性（譬如「客戶集中度」、「終端需求週期」），避免短期股價波動

務必用以下純 JSON 格式輸出，三個 key：
{{
  "business": "...",
  "advantage": "...",
  "risk": "..."
}}"""


def _ensure_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS summaries (
            ticker TEXT PRIMARY KEY,
            business TEXT,
            advantage TEXT,
            risk TEXT,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def _get_cache(ticker, ttl_days=CACHE_TTL_DAYS):
    """命中 cache 且未過期 → 回 dict；否則 None。"""
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT business, advantage, risk, updated_at FROM summaries WHERE ticker = ?",
        (ticker,)
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    business, advantage, risk, updated_at = row
    try:
        dt = datetime.fromisoformat(updated_at)
    except (ValueError, TypeError):
        return None
    if datetime.utcnow() - dt > timedelta(days=ttl_days):
        return None
    return {
        "business": business,
        "advantage": advantage,
        "risk": risk,
        "generated_at": updated_at[:10],
    }


def _set_cache(ticker, business, advantage, risk):
    conn = _ensure_db()
    conn.execute(
        "INSERT OR REPLACE INTO summaries (ticker, business, advantage, risk, updated_at) VALUES (?,?,?,?,?)",
        (ticker, business, advantage, risk, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


def _call_gemini(prompt: str, api_key: str):
    """單次 Gemini call。回 dict {business, advantage, risk} 或 None。"""
    try:
        import google.generativeai as genai
    except ImportError:
        print("⚠️  [ai_summary] 沒裝 google-generativeai，跳過")
        return None

    genai.configure(api_key=api_key)
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.4,
                "max_output_tokens": 800,
            },
        )
        text = response.text or ""
    except Exception as e:
        print(f"   ⚠️ Gemini call 失敗: {type(e).__name__}: {e}")
        return None

    # 解 JSON
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 有時 LLM 回會帶 ```json ... ``` 包裹，剝開試試
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip().rstrip("`").strip()
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            print(f"   ⚠️ JSON 解析失敗，原始：{text[:200]}")
            return None

    business = (data.get("business") or "").strip()
    advantage = (data.get("advantage") or "").strip()
    risk = (data.get("risk") or "").strip()
    if not business or not advantage or not risk:
        return None
    return {"business": business, "advantage": advantage, "risk": risk}


def get_summary(ticker: str, info: dict, api_key=None, force_refresh=False):
    """
    對單檔個股取得（cache 或新生成）AI 摘要。

    ticker: 含 .TW 後綴的代號
    info: yfinance.info dict，需有 longBusinessSummary
    api_key: 不傳則讀 GEMINI_API_KEY env
    force_refresh: True 則跳過 cache，強制重 call

    回 dict {business, advantage, risk, generated_at} 或 None。
    """
    # cache hit?
    if not force_refresh:
        cached = _get_cache(ticker)
        if cached:
            return cached

    # 沒 longBusinessSummary 跳過
    summary_text = (info or {}).get("longBusinessSummary") or ""
    if not summary_text or len(summary_text) < 30:
        return None

    if api_key is None:
        api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    prompt = PROMPT_TEMPLATE.format(
        company_name=info.get("longName") or ticker,
        ticker=ticker,
        sector=info.get("sector") or "—",
        industry=info.get("industry") or "—",
        business_summary=summary_text[:3000],  # 限制 input size
    )
    result = _call_gemini(prompt, api_key)
    if result is None:
        return None

    _set_cache(ticker, result["business"], result["advantage"], result["risk"])
    result["generated_at"] = datetime.utcnow().isoformat()[:10]
    return result


def batch_generate(ticker_info_pairs, api_key=None, max_calls=120):
    """
    批次對 list of (ticker, info) 跑 AI 摘要。
    內建 RPM_SLEEP 規避 free tier rate limit。

    回 (success, fail, cached_hits)
    """
    if api_key is None:
        api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("⚠️  [ai_summary] GEMINI_API_KEY 未設，跳過批次")
        return 0, 0, 0

    success = 0
    fail = 0
    cached_hits = 0
    new_calls = 0

    for ticker, info in ticker_info_pairs:
        if new_calls >= max_calls:
            print(f"   ⏸  達到 max_calls={max_calls}，停止繼續")
            break
        cached = _get_cache(ticker)
        if cached:
            cached_hits += 1
            continue

        # 沒 info / 沒英文摘要的跳過
        if not info or not info.get("longBusinessSummary"):
            continue

        result = get_summary(ticker, info, api_key=api_key, force_refresh=False)
        if result:
            success += 1
            print(f"   ✅ {ticker} {info.get('longName', '')[:30]}")
        else:
            fail += 1
            print(f"   ❌ {ticker} 失敗")
        new_calls += 1

        # RPM 規避
        time.sleep(RPM_SLEEP)

    print(f"\n📊 [ai_summary] cache hits={cached_hits} / new success={success} / fail={fail}")
    return success, fail, cached_hits


if __name__ == "__main__":
    # CLI usage: python ai_summary.py <ticker>
    # 用 yfinance 即時撈 info 然後生成摘要（測試用）
    if len(sys.argv) < 2:
        print("用法：python ai_summary.py <ticker>（如 2330.TW）")
        sys.exit(1)

    ticker = sys.argv[1]
    print(f"測試 AI 摘要：{ticker}")
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
    except Exception as e:
        print(f"yfinance 失敗：{e}")
        sys.exit(1)

    if not info.get("longBusinessSummary"):
        print("此檔無 longBusinessSummary，跳過")
        sys.exit(0)

    result = get_summary(ticker, info)
    if result:
        print(f"\n業務分析：{result['business']}")
        print(f"\n競爭優勢：{result['advantage']}")
        print(f"\n主要風險：{result['risk']}")
        print(f"\n（generated_at: {result['generated_at']}）")
    else:
        print("生成失敗（API key 未設或 LLM 回應異常）")
