# -*- coding: utf-8 -*-
"""
台股監控自動化系統（精簡版，my-stock-monitor）
基於 grissomlin/taiwan-stock-monitor 改寫，目前只保留台股，通知通道暫關。
"""
import os
import time
import argparse
import traceback
from datetime import datetime, timedelta

# 導入自定義模組
import downloader_tw
import downloader_chips
import ai_summary
import analyzer
import notifier
import build_web


def run_market_pipeline(market_id: str, market_name: str, emoji: str):
    """執行單一市場的完整管線：下載 -> 分析 -> 寄信（已暫關）"""
    print("\n" + "=" * 60)
    print(f"{emoji} 啟動管線：{market_name} ({market_id})")
    print("=" * 60)

    stats = {"total": 0, "success": 0, "fail": 0}
    agent = notifier.StockNotifier()

    # --- Step 1: 數據獲取 ---
    print(f"【Step 1: 數據獲取】正在更新 {market_name} 原始 K 線資料...")
    try:
        if market_id == "tw-share":
            res = downloader_tw.main()
        else:
            print(f"⚠️ 未知或尚未支援的市場 ID: {market_id}")
            return

        if isinstance(res, dict):
            stats = res
            print(
                f"📊 [下載報告] 總計: {stats.get('total', 0)} | "
                f"成功: {stats.get('success', 0)} | 失敗: {stats.get('fail', 0)}"
            )
        elif res is not None and hasattr(res, "__len__"):
            stats = {"total": len(res), "success": len(res), "fail": 0}
            print(f"📊 [下載報告] 已獲取 {len(res)} 檔標的。")
        else:
            print(f"⚠️ {market_name} 下載器未回傳有效數據，報告可能顯示為 0。")

    except Exception as e:
        print(f"❌ {market_name} 數據下載過程發生嚴重異常: {e}")

    # --- Step 1.5: 三大法人資料更新（Phase 2）---
    if market_id == "tw-share":
        print(f"\n【Step 1.5: 三大法人】更新 {market_name} 三大法人買賣超 SQLite...")
        try:
            fetched, total = downloader_chips.update_chips_db(days_back=60, max_fetches=80)
            print(f"📊 [chips] 探詢 {len(fetched)} 天，新寫入 {total} 筆")
        except Exception as e:
            print(f"⚠️ [chips] downloader 失敗（不影響主 pipeline）: {e}")

    # --- Step 2: 數據分析 & 繪圖 ---
    print(f"\n【Step 2: 矩陣分析】正在計算 {market_name} 動能分布並生成圖表...")
    try:
        img_paths, report_df, text_reports = analyzer.run_global_analysis(market_id=market_id)

        if report_df is None or report_df.empty:
            print(f"⚠️ {market_name} 分析結果為空 (可能是 CSV 資料不足)，跳過寄信步驟。")
            return

        print(f"✅ 分析完成！成功處理 {len(report_df)} 檔有效數據。")

        # --- Step 3: 報表發送（目前 stub，只 print 統計）---
        print(f"\n【Step 3: 報表發送】（通知通道暫關，僅 print log）")
        agent.send_stock_report(
            market_name=market_name,
            img_data=img_paths,
            report_df=report_df,
            text_reports=text_reports,
            stats=stats,
        )

        # --- Step 3.5: AI 智能摘要批次預生成（Phase 3）---
        # build_web 階段也會 cache-first call，這裡是「批次熱啟動」確保每次 build 用最新 cache。
        # 沒設 GEMINI_API_KEY 會自動跳過。
        if os.getenv("GEMINI_API_KEY") and report_df is not None and "Year_High" in report_df.columns:
            print(f"\n【Step 3.5: AI 摘要】Gemini 對 Top 100 + 大型股白名單批次生成...")
            try:
                # 撈 Top 100 + 白名單的 ticker，先撈一次 yfinance.info 給 ai_summary 用
                import yfinance as yf
                df_ranked = report_df.dropna(subset=["Year_High"]).sort_values("Year_High", ascending=False)
                top100_tickers = set(df_ranked.head(100)["Ticker"].astype(str).tolist())
                wl = top100_tickers | (set(df_ranked["Ticker"].astype(str).tolist()) & build_web.INFO_WHITELIST_TW)
                print(f"   - 共 {len(wl)} 檔需要 AI 摘要候選")

                pairs = []
                for ticker in wl:
                    cached = ai_summary._get_cache(ticker)
                    if cached:
                        continue  # cache hit，跳過 API call 也跳過 yfinance call
                    try:
                        info = yf.Ticker(ticker).info or {}
                        if info.get("longBusinessSummary"):
                            pairs.append((ticker, info))
                    except Exception:
                        pass
                if pairs:
                    print(f"   - 將對 {len(pairs)} 檔尚無 cache 的個股呼叫 Gemini")
                    ai_summary.batch_generate(pairs, max_calls=120)
                else:
                    print(f"   - 全部已有 cache 或無 longBusinessSummary，跳過")
            except Exception as e:
                print(f"⚠️ AI 摘要批次失敗（不影響後續 build）: {e}")
        else:
            print(f"\n【Step 3.5: AI 摘要】跳過（GEMINI_API_KEY 未設）")

        # --- Step 4: 產靜態站 dist/（給 Cloudflare Pages 部署）---
        print(f"\n【Step 4: 靜態站打包】產出 dist/ 給 Cloudflare Pages...")
        try:
            build_web.build(
                images=img_paths,
                report_df=report_df,
                text_reports=text_reports,
                market_id=market_id,
            )
        except Exception as e:
            print(f"⚠️ build_web 失敗（不影響資料 pipeline）: {e}")

    except Exception as e:
        print(f"❌ {market_name} 分析或寄信過程出錯:\n{traceback.format_exc()}")


def main():
    parser = argparse.ArgumentParser(description="My Stock Monitor (TW only)")
    parser.add_argument(
        "--market",
        type=str,
        default="tw-share",
        choices=["tw-share"],
        help="目前僅支援 tw-share",
    )
    args = parser.parse_args()

    start_time = time.time()
    now_utc8 = datetime.utcnow() + timedelta(hours=8)
    now_str = now_utc8.strftime("%Y-%m-%d %H:%M:%S")

    print("\n" + "🚀 " + "=" * 55)
    print(f"🚀 my-stock-monitor 啟動")
    print(f"🚀 啟動時間: {now_str} (UTC+8)")
    print(f"🚀 執行目標: {args.market}")
    print("🚀 " + "=" * 55 + "\n")

    markets_config = {
        "tw-share": {"name": "台灣股市", "emoji": "🇹🇼"},
    }

    m_info = markets_config.get(args.market)
    if m_info:
        run_market_pipeline(args.market, m_info["name"], m_info["emoji"])
    else:
        print(f"❌ 找不到對應的市場配置: {args.market}")

    end_time = time.time()
    total_duration = (end_time - start_time) / 60
    print("\n" + "=" * 60)
    print(f"🎉 任務執行完畢！總耗時: {total_duration:.2f} 分鐘")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
