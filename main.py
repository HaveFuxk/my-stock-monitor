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
import analyzer
import notifier


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
