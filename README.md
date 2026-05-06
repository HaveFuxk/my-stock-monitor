# my-stock-monitor

> 台股每日 K 線抓取 + 動能分布分析的精簡版。
>
> **Forked & trimmed from [grissomlin/taiwan-stock-monitor](https://github.com/grissomlin/taiwan-stock-monitor)** (MIT License). 感謝原作者把六大市場版本開源。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10+-blue.svg)

## 跟原版的差異

| 項目 | 原版 | 本版 |
|---|---|---|
| 監控市場 | 🇹🇼🇺🇸🇭🇰🇨🇳🇯🇵🇰🇷 六國 | 🇹🇼 台股單一 |
| 通知通道 | Resend Email + Telegram | Stub（只 print，方便先驗證資料流） |
| GitHub Actions | 排程 + 手動 | 只手動觸發（schedule 已註解） |
| 收件信箱 | 硬編碼 | env 化 (`REPORT_RECEIVER_EMAIL`) |
| TWSE 抓取 | requests 預設 | 修了兩個 bug（見下） |
| Workflow `permissions` | 未設定 | `contents: read`（最小權限） |

## 修掉的兩個原版 bug

1. **TWSE 證書缺 Subject Key Identifier**
   `isin.twse.com.tw` 的 SSL 證書缺少 SKI extension，新版 Python（3.13+）+ certifi 嚴格驗證會擋。原版用 GitHub Actions 的 Python 3.10 跑沒中招，但本機 Python 3.14 跑會直接 SSL fail。修法：對這條公開股票清單 endpoint 加 `verify=False`（內容是公開股票清單，MITM 風險可接受）。

2. **TWSE 回傳 MS950 編碼但 requests 自動猜成 utf-8**
   導致 `pd.read_html` 解析失敗回 0 表格。原版的 `try/except` 又把錯吞了所以靜默失敗。修法：抓回來後手動 `resp.encoding = 'ms950'`，並把 silent except 改成 verbose log。

> Akshare fallback 因為 `stock_tw_spot_em` 在 1.18.60 已被移除，目前進入會 raise `AttributeError`，但被 except 抓住。主路徑（TWSE JSP）已通，所以 fallback 沒實際使用。

## 怎麼跑

### 一次性設定

```bash
git clone https://github.com/HaveFuxk/my-stock-monitor.git
cd my-stock-monitor
pip install -r requirements.txt
```

### 抓資料 + 分析

```bash
python main.py --market tw-share
```

實際耗時約 **15–20 分鐘**（抓 ~2500 檔台股的兩年日 K）。流程：

1. **Step 1 數據獲取** — TWSE JSP 抓上市/上櫃/興櫃/ETF/DR 清單，再用 yfinance 抓兩年日 K，存成 `data/tw-share/dayK/{code}_{name}.csv`
2. **Step 2 矩陣分析** — 計算每檔週(5D)/月(20D)/年(250D) 的最高/收盤/最低報酬率，畫 9 張直方圖到 `output/images/tw-share/`
3. **Step 3 報表** — 目前只 print 到 stdout（Notifier 是 stub）

### 開啟通知（之後）

1. 到 [resend.com](https://resend.com) 申請 API key
2. 設環境變數：
   ```bash
   set RESEND_API_KEY=re_xxx
   set REPORT_RECEIVER_EMAIL=you@example.com
   ```
3. `notifier.py` 把 `NOTIFY_ENABLED = True`，補回 Resend / Telegram 呼叫
4. GitHub Actions 加 secrets，workflow 解開 env 註解

## 檔案結構

```
my-stock-monitor/
├── .github/workflows/daily_report.yml   # 手動觸發 only
├── analyzer.py                           # 直方圖 + 文字報表
├── downloader_tw.py                      # TWSE 清單 + yfinance K 線
├── main.py                               # pipeline 編排
├── notifier.py                           # stub 通知器（只 print）
├── requirements.txt
├── LICENSE                               # MIT (原作者)
└── README.md                             # 本檔
```

## TODO（Roadmap）

- [ ] ETF 過濾器（`00` 開頭跳過，避免反向 ETF 混進飆股榜）
- [ ] 把 requirements.txt 全部 pin `==`
- [ ] HTML email 模板加 `html.escape()`（為了之後開通知）
- [ ] 加 LINE Notify / Discord webhook 選項
- [ ] 加技術指標（MA / RSI / MACD）

## License

MIT — 保留原作者 `grissomlin` 的 copyright（[LICENSE](LICENSE)）。
