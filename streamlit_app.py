# -*- coding: utf-8 -*-
"""
streamlit_app.py — my-stock-monitor 互動 dashboard

部署目標：Streamlit Community Cloud (https://streamlit.app)
資料源：https://my-stock-monitor.pages.dev/data/manifest.json + 個股 JSON
       （由 main.py + build_web._export_kline_json 在 GH Actions 上產出，
        透過 wrangler-action 部署到 Cloudflare Pages，每日更新）

跟路徑 6（chart.html）的差異：
- chart.html：純前端、TradingView Lightweight Charts、按代號逐一檢視
- streamlit_app：sidebar 篩選/搜尋/排序、Plotly K 線、跨檔比較
"""
import streamlit as st
import pandas as pd
import requests

DATA_BASE = "https://my-stock-monitor.pages.dev/data"

st.set_page_config(
    page_title="my-stock-monitor — 互動 dashboard",
    page_icon="📈",
    layout="wide",
)


# ============ 資料載入（cache） ============

@st.cache_data(ttl=3600, show_spinner=False)
def load_manifest():
    """從 CF Pages 抓飆股清單 manifest。每小時更新一次。"""
    res = requests.get(f"{DATA_BASE}/manifest.json", timeout=15)
    res.raise_for_status()
    return pd.DataFrame(res.json())


@st.cache_data(ttl=3600, show_spinner=False)
def load_kline(safe_id):
    """單檔 K 線 JSON。每小時更新一次。"""
    res = requests.get(f"{DATA_BASE}/{safe_id}.json", timeout=15)
    res.raise_for_status()
    return pd.DataFrame(res.json())


# ============ 主 UI ============

st.title("📈 my-stock-monitor — 互動 dashboard")
st.caption(
    "資料源：[my-stock-monitor.pages.dev](https://my-stock-monitor.pages.dev/) "
    "· 每日 GitHub Actions 自動更新 · "
    "[GitHub repo](https://github.com/HaveFuxk/my-stock-monitor)"
)

# 載入 manifest
try:
    with st.spinner("載入飆股清單..."):
        df = load_manifest()
except Exception as e:
    st.error(f"❌ 載入 manifest 失敗：{e}")
    st.markdown(
        f"請確認 [https://my-stock-monitor.pages.dev/data/manifest.json]"
        f"({DATA_BASE}/manifest.json) 已部署。"
    )
    st.stop()

if df.empty:
    st.warning("manifest 為空。可能 GH Actions 還沒跑過第一輪 build_web。")
    st.stop()


# ============ Sidebar 篩選 ============

with st.sidebar:
    st.header("⚙️ 篩選")

    period_label = st.radio(
        "報酬期間",
        ["年", "月", "週"],
        horizontal=True,
        help="選哪個期間的漲幅做排序與門檻篩選",
    )
    period_col = {"年": "year_high", "月": "month_high", "週": "week_high"}[period_label]

    # 動態決定 slider 範圍
    valid = df[period_col].dropna()
    if not valid.empty:
        max_val = int(valid.max()) + 10
        default_min = 50 if period_label == "年" else 20 if period_label == "月" else 10
    else:
        max_val = 500
        default_min = 50

    min_pct = st.slider(
        f"{period_label}漲幅 ≥ (%)",
        min_value=-50,
        max_value=max_val,
        value=default_min,
        step=10,
    )

    search = st.text_input(
        "搜尋（代號或名稱）",
        "",
        placeholder="例：2330 / 台積電 / 0050",
    )

    st.divider()
    st.caption(f"manifest 共 **{len(df)}** 檔（K 線資料源）")
    st.caption(f"資料覆蓋：飆股 Top 300（依年漲幅排序）")


# ============ 篩選 ============

filtered = df[df[period_col].fillna(-999) >= min_pct].copy()
if search:
    s = search.strip()
    if s:
        mask = (
            filtered["ticker"].str.contains(s, case=False, na=False)
            | filtered["name"].str.contains(s, case=False, na=False)
        )
        filtered = filtered[mask]

filtered = filtered.sort_values(period_col, ascending=False, na_position="last")


# ============ 摘要指標 ============

col1, col2, col3, col4 = st.columns(4)
col1.metric("符合條件家數", f"{len(filtered):,}")
if len(filtered) > 0:
    col2.metric(
        f"最高 {period_label}漲幅",
        f"{filtered[period_col].max():.1f}%",
    )
    col3.metric(
        f"中位 {period_label}漲幅",
        f"{filtered[period_col].median():.1f}%",
    )
    col4.metric(
        f">100% 飆股",
        f"{(filtered[period_col] >= 100).sum()} 檔",
    )


# ============ 飆股清單表格 ============

st.subheader(f"📋 飆股清單（依 {period_label}漲幅排序）")

if filtered.empty:
    st.info("無符合條件的個股，把 slider 拉低或清搜尋詞試試。")
else:
    display = filtered[["ticker", "name", "year_high", "month_high", "week_high", "samples"]].rename(
        columns={
            "ticker": "代號",
            "name": "名稱",
            "year_high": "年漲幅%",
            "month_high": "月漲幅%",
            "week_high": "週漲幅%",
            "samples": "K 線樣本",
        }
    )
    st.dataframe(
        display,
        use_container_width=True,
        height=380,
        column_config={
            "年漲幅%": st.column_config.NumberColumn(format="%.1f"),
            "月漲幅%": st.column_config.NumberColumn(format="%.1f"),
            "週漲幅%": st.column_config.NumberColumn(format="%.1f"),
        },
        hide_index=True,
    )


# ============ 個股 K 線 ============

st.subheader("📈 個股 K 線（Plotly 互動圖）")

if filtered.empty:
    st.caption("（無可選個股）")
else:
    # 用 selectbox，format 顯示「代號 名稱」
    options = filtered["ticker"].tolist()
    pick = st.selectbox(
        "選一檔",
        options,
        format_func=lambda t: f"{t}  {filtered.loc[filtered['ticker']==t, 'name'].values[0]}",
    )

    if pick:
        safe_id = filtered.loc[filtered["ticker"] == pick, "safe_id"].values[0]
        pick_name = filtered.loc[filtered["ticker"] == pick, "name"].values[0]

        try:
            kline = load_kline(safe_id)
            kline["time"] = pd.to_datetime(kline["time"])

            import plotly.graph_objects as go
            fig = go.Figure(data=[
                go.Candlestick(
                    x=kline["time"],
                    open=kline["open"],
                    high=kline["high"],
                    low=kline["low"],
                    close=kline["close"],
                    increasing_line_color="#d73a49",  # 台股紅漲
                    decreasing_line_color="#28a745",  # 台股綠跌
                    name=pick,
                )
            ])
            fig.update_layout(
                xaxis_rangeslider_visible=False,
                height=500,
                margin=dict(l=20, r=20, t=20, b=20),
                template="plotly_white",
            )
            st.plotly_chart(fig, use_container_width=True)

            # 也提供站內 chart.html 連結（TradingView 版）
            st.caption(
                f"也可看 [站內 TradingView K 線版]"
                f"(https://my-stock-monitor.pages.dev/chart.html?ticker={pick}&name={pick_name})"
            )
        except Exception as e:
            st.error(f"載入 {pick} K 線失敗：{e}")
            st.markdown(
                f"備援連結："
                f"[玩股網](https://www.wantgoo.com/stock/{pick.split('.')[0]}/technical-chart)"
                f" · [Yahoo](https://tw.stock.yahoo.com/quote/{pick})"
            )


st.divider()
st.caption(
    "Powered by Streamlit · 資料每日由 GitHub Actions 從 TWSE / yfinance 抓取，"
    "經 build_web 打包後透過 Cloudflare Pages CDN 提供。"
)
