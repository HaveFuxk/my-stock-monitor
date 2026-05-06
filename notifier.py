# -*- coding: utf-8 -*-
"""
StockNotifier (stub 版)

目前通知通道暫關 — 不寄 Email、不發 Telegram。
保留與原版相同的類別介面 (`StockNotifier.send_stock_report(...)`)，
讓 main.py 不需大改。實際只把統計與報酬分布以 print 形式輸出到終端機。

之後要打開通知，把 NOTIFY_ENABLED 改為 True，並設定環境變數：
  - RESEND_API_KEY
  - REPORT_RECEIVER_EMAIL  （收件信箱，env 化避免硬編碼）
  - TELEGRAM_BOT_TOKEN
  - TELEGRAM_CHAT_ID
然後把下面 `if NOTIFY_ENABLED:` 區塊填回 Resend / Telegram 呼叫即可。
"""
import os
from datetime import datetime, timedelta

NOTIFY_ENABLED = False  # 先關閉，跑通本機資料流再說


class StockNotifier:
    def __init__(self):
        # 環境變數讀取（即使現在不寄信，仍預先讀，方便日後啟用）
        self.tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.tg_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.resend_api_key = os.getenv("RESEND_API_KEY")
        self.receiver_email = os.getenv("REPORT_RECEIVER_EMAIL")  # 已 env 化

    @staticmethod
    def get_now_time_str() -> str:
        """獲取 UTC+8 台北時間字串"""
        now_utc8 = datetime.utcnow() + timedelta(hours=8)
        return now_utc8.strftime("%Y-%m-%d %H:%M:%S")

    def send_stock_report(self, market_name, img_data, report_df, text_reports, stats=None):
        """
        Stub：只把統計與每段文字報表 print 到終端機，不發任何外部通知。
        """
        report_time = self.get_now_time_str()
        stats = stats or {}

        total_count = stats.get("total", len(report_df))
        success_count = stats.get("success", len(report_df))
        try:
            total_val = int(total_count)
            success_val = int(success_count)
            success_rate = (
                f"{(success_val / total_val) * 100:.1f}%" if total_val > 0 else "0.0% (清單獲取異常)"
            )
        except Exception:
            success_rate = "N/A"

        print("\n" + "=" * 60)
        print(f"📨 [Notifier Stub] {market_name} 監控報告")
        print(f"   生成時間: {report_time} (台北時間)")
        print(f"   應收標的: {total_count}")
        print(f"   更新成功(含快取): {success_count}")
        print(f"   今日覆蓋率: {success_rate}")
        print(f"   產生圖表數量: {len(img_data)}")
        if img_data:
            print("   圖表清單：")
            for img in img_data:
                print(f"     - {img.get('label', img.get('id', '?'))} → {img.get('path')}")
        print("=" * 60)

        # --- 文字報酬分布（只 print 前幾行避免洗版）---
        if text_reports:
            for period, report in text_reports.items():
                p_name_zh = {"Week": "週", "Month": "月", "Year": "年"}.get(period, period)
                print(f"\n📊 [{p_name_zh} K 最高-進攻 報酬分布]（前 15 行）")
                lines = report.splitlines()
                for line in lines[:15]:
                    print("  " + line)
                if len(lines) > 15:
                    print(f"  ... (共 {len(lines)} 行，省略 {len(lines) - 15} 行)")

        if NOTIFY_ENABLED:
            # 之後要開啟通知時，在這裡呼叫 Resend / Telegram。目前 stub，不執行。
            pass

        return True
