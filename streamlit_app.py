# -*- coding: utf-8 -*-
"""
streamlit_app.py — my-stock-monitor 互動 dashboard

部署目標：Streamlit Community Cloud (https://streamlit.app)
資料源：https://my-stock-monitor.pages.dev/data/manifest.json + 個股 JSON
       （由 main.py + build_web._export_kline_json 在 GH Actions 上產出，
        透過 wrangler-action 部署到 Cloudflare Pages，每日更新）

Phase 1 升級：
- 個股 JSON schema 改為 {candles, ma20, ma60, ma200, info}
- 主區用 st.tabs 拆四個視角：📊 概覽 / 📋 基本資料 / 📈 技術分析 / 🔮 籌碼/產業
- aistockmap 啟發的卡片化呈現
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
    """
    單檔個股 JSON。回 dict {candles, ma20, ma60, ma200, info}。
    向後相容：若 schema 是純 array 也能讀。
    """
    res = requests.get(f"{DATA_BASE}/{safe_id}.json", timeout=15)
    res.raise_for_status()
    payload = res.json()
    if isinstance(payload, list):
        return {"candles": payload, "ma20": None, "ma60": None, "ma200": None, "info": None}
    return payload


# ============ 工具函式 ============

def fmt_pct(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{v:+.1f}%"


def fmt_num(v, decimals=2):
    if v is None or pd.isna(v):
        return "—"
    try:
        return f"{float(v):,.{decimals}f}"
    except (ValueError, TypeError):
        return "—"


def fmt_big_num(v):
    if v is None or pd.isna(v):
        return "—"
    v = float(v)
    if v >= 1e12:
        return f"{v / 1e12:.2f} 兆"
    if v >= 1e8:
        return f"{v / 1e8:.2f} 億"
    if v >= 1e4:
        return f"{v / 1e4:.2f} 萬"
    return f"{v:,.0f}"


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

    # 行業篩選（若 manifest 有 sector 資料）
    sector_filter = None
    if "sector" in df.columns:
        sectors = sorted(df["sector"].dropna().unique().tolist())
        if sectors:
            sector_filter = st.multiselect(
                "產業類別（僅 Top 100 飆股有資料）",
                options=sectors,
                default=[],
            )

    st.divider()
    st.caption(f"manifest 共 **{len(df)}** 檔")
    if "has_info" in df.columns:
        info_count = int(df["has_info"].fillna(False).sum())
        st.caption(f"含基本面：**{info_count}** 檔（Top 100 飆股）")


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

if sector_filter:
    filtered = filtered[filtered["sector"].isin(sector_filter)]

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
    st.stop()

display_cols = ["ticker", "name", "year_high", "month_high", "week_high", "samples"]
rename_map = {
    "ticker": "代號", "name": "名稱",
    "year_high": "年漲幅%", "month_high": "月漲幅%", "week_high": "週漲幅%",
    "samples": "K 線樣本",
}
if "sector" in filtered.columns:
    display_cols.insert(2, "sector")
    rename_map["sector"] = "產業"

display = filtered[display_cols].rename(columns=rename_map)
st.dataframe(
    display,
    use_container_width=True,
    height=320,
    column_config={
        "年漲幅%": st.column_config.NumberColumn(format="%.1f"),
        "月漲幅%": st.column_config.NumberColumn(format="%.1f"),
        "週漲幅%": st.column_config.NumberColumn(format="%.1f"),
    },
    hide_index=True,
)


# ============ 個股檢視（4 tabs） ============

st.divider()
st.subheader("🔍 個股檢視")

options = filtered["ticker"].tolist()
pick = st.selectbox(
    "選一檔個股",
    options,
    format_func=lambda t: f"{t}  {filtered.loc[filtered['ticker'] == t, 'name'].values[0]}",
)

if not pick:
    st.stop()

safe_id = filtered.loc[filtered["ticker"] == pick, "safe_id"].values[0]
pick_name = filtered.loc[filtered["ticker"] == pick, "name"].values[0]
clean_code = pick.split(".")[0]

try:
    payload = load_kline(safe_id)
except Exception as e:
    st.error(f"載入 {pick} K 線失敗：{e}")
    st.markdown(
        f"備援連結："
        f"[玩股網](https://www.wantgoo.com/stock/{clean_code}/technical-chart)"
        f" · [Yahoo](https://tw.stock.yahoo.com/quote/{pick})"
    )
    st.stop()

candles_list = payload.get("candles") or []
info = payload.get("info")
ma20 = payload.get("ma20")
ma60 = payload.get("ma60")
ma200 = payload.get("ma200")
rsi14 = payload.get("rsi14")
macd_line = payload.get("macd_line")
macd_signal = payload.get("macd_signal")
macd_hist = payload.get("macd_hist")
chips = payload.get("chips")
ai_summary_data = payload.get("ai_summary")
peers = payload.get("peers")

if not candles_list:
    st.warning("此檔無 K 線資料")
    st.stop()

kline = pd.DataFrame(candles_list)
kline["time"] = pd.to_datetime(kline["time"])

last_close = kline["close"].iloc[-1]
prev_close = kline["close"].iloc[-2] if len(kline) > 1 else None
day_chg = ((last_close - prev_close) / prev_close * 100) if prev_close else None


def compute_ret(days):
    if len(kline) <= days:
        return None
    return (kline["close"].iloc[-1] - kline["close"].iloc[-days - 1]) / kline["close"].iloc[-days - 1] * 100


wk_ret = compute_ret(5)
mo_ret = compute_ret(20)
yr_ret = compute_ret(250)

# 4 個 tabs
tab_overview, tab_profile, tab_technical, tab_advanced = st.tabs(
    ["📊 概覽", "📋 基本資料", "📈 技術分析", "🔮 籌碼/產業"]
)

# ---------- Tab: 概覽 ----------
with tab_overview:
    st.markdown(f"### {pick_name}  `{pick}`")
    if info:
        tags = []
        if info.get("sector"):
            tags.append(info["sector"])
        if info.get("industry"):
            tags.append(info["industry"])
        if tags:
            st.caption(" · ".join(tags))

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("最新收盤", fmt_num(last_close))
    c2.metric("日漲跌", fmt_pct(day_chg))
    c3.metric("5 日報酬", fmt_pct(wk_ret))
    c4.metric("20 日報酬", fmt_pct(mo_ret))
    c5.metric("250 日報酬", fmt_pct(yr_ret))

    if info:
        c1, c2, c3 = st.columns(3)
        c1.metric("市值", fmt_big_num(info.get("marketCap")))
        c2.metric("本益比 (PE)", fmt_num(info.get("trailingPE")))
        dy = info.get("dividendYield")
        c3.metric("殖利率", fmt_num(dy * 100, 2) + "%" if dy else "—")

    # 縮版 K 線（最近 60 天）
    import plotly.graph_objects as go
    recent = kline.tail(60)
    fig_mini = go.Figure(data=[
        go.Candlestick(
            x=recent["time"], open=recent["open"], high=recent["high"],
            low=recent["low"], close=recent["close"],
            increasing_line_color="#d73a49", decreasing_line_color="#16a34a",
            name=pick,
        )
    ])
    fig_mini.update_layout(
        xaxis_rangeslider_visible=False,
        height=320,
        margin=dict(l=20, r=20, t=10, b=20),
        template="plotly_white",
        title="近 60 個交易日",
    )
    st.plotly_chart(fig_mini, use_container_width=True)

    st.caption(
        f"**外部資源**："
        f"[玩股網技術圖](https://www.wantgoo.com/stock/{clean_code}/technical-chart)"
        f" · [Yahoo 股市](https://tw.stock.yahoo.com/quote/{pick})"
        f" · [鉅亨網](https://www.cnyes.com/twstock/{clean_code})"
        f" · [站內 TradingView 版](https://my-stock-monitor.pages.dev/chart.html?ticker={pick}&name={pick_name})"
    )


# ---------- Tab: 基本資料 ----------
with tab_profile:
    if info:
        st.markdown(f"### {info.get('longName') or pick_name}")
        tag_cols = st.columns(3)
        if info.get("sector"):
            tag_cols[0].markdown(f"**產業類別**\n\n{info['sector']}")
        if info.get("industry"):
            tag_cols[1].markdown(f"**細項行業**\n\n{info['industry']}")
        if info.get("country"):
            tag_cols[2].markdown(f"**註冊國家**\n\n{info['country']}")

        st.divider()

        rows = []
        rows.append(("市值", fmt_big_num(info.get("marketCap"))))
        rows.append(("本益比 (TTM)", fmt_num(info.get("trailingPE"))))
        rows.append(("預估本益比", fmt_num(info.get("forwardPE"))))
        rows.append(("每股盈餘 (EPS)", fmt_num(info.get("trailingEps"))))
        dy = info.get("dividendYield")
        rows.append(("殖利率", f"{dy * 100:.2f}%" if dy else "—"))
        rows.append(("Beta", fmt_num(info.get("beta"))))
        rows.append(("52 週高點", fmt_num(info.get("fiftyTwoWeekHigh"))))
        rows.append(("52 週低點", fmt_num(info.get("fiftyTwoWeekLow"))))
        avg_vol = info.get("averageVolume")
        rows.append(("平均日成交量", f"{avg_vol:,}" if avg_vol else "—"))
        emp = info.get("fullTimeEmployees")
        rows.append(("員工人數", f"{emp:,}" if emp else "—"))
        if info.get("website"):
            rows.append(("官方網站", f"[{info['website']}]({info['website']})"))

        profile_df = pd.DataFrame(rows, columns=["項目", "數值"])
        st.dataframe(profile_df, hide_index=True, use_container_width=True, height=420)

        if info.get("longBusinessSummary"):
            st.markdown("### 公司簡介")
            st.write(info["longBusinessSummary"])
    else:
        st.info(
            "此檔暫無基本面資料。\n\n"
            "目前 yfinance.info 只對年漲幅 Top 100 飆股撈取，以節省 build 時間。\n\n"
            f"請見外部資源："
            f"[Yahoo 股市](https://tw.stock.yahoo.com/quote/{pick})"
            f" · [玩股網](https://www.wantgoo.com/stock/{clean_code}/technical-chart)"
            f" · [鉅亨網](https://www.cnyes.com/twstock/{clean_code})"
        )


# ---------- Tab: 技術分析 ----------
with tab_technical:
    st.markdown(f"### {pick_name}  `{pick}` — K 線 + 技術指標")

    c1, c2, c3, c4, c5 = st.columns(5)
    show_ma20 = c1.checkbox("MA20", value=True)
    show_ma60 = c2.checkbox("MA60", value=True)
    show_ma200 = c3.checkbox("MA200", value=False)
    show_rsi = c4.checkbox("RSI(14)", value=True)
    show_macd = c5.checkbox("MACD", value=True)

    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    # 動態決定 subplot 數量
    rows = 1
    row_heights = [0.65]
    subplot_titles = ["K 線 + 移動平均"]
    if show_rsi and rsi14:
        rows += 1
        row_heights.append(0.18)
        subplot_titles.append("RSI(14)")
    if show_macd and macd_line:
        rows += 1
        row_heights.append(0.22)
        subplot_titles.append("MACD(12,26,9)")

    # 重整 row_heights 比例
    total = sum(row_heights)
    row_heights = [h / total for h in row_heights]

    fig = make_subplots(
        rows=rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
    )

    # Row 1: K 線
    fig.add_trace(go.Candlestick(
        x=kline["time"], open=kline["open"], high=kline["high"],
        low=kline["low"], close=kline["close"],
        increasing_line_color="#d73a49", decreasing_line_color="#16a34a",
        name=pick, showlegend=False,
    ), row=1, col=1)

    if show_ma20 and ma20:
        fig.add_trace(go.Scatter(
            x=kline["time"], y=ma20, mode="lines", name="MA20",
            line=dict(color="#06b6d4", width=2)
        ), row=1, col=1)
    if show_ma60 and ma60:
        fig.add_trace(go.Scatter(
            x=kline["time"], y=ma60, mode="lines", name="MA60",
            line=dict(color="#f59e0b", width=2)
        ), row=1, col=1)
    if show_ma200 and ma200:
        fig.add_trace(go.Scatter(
            x=kline["time"], y=ma200, mode="lines", name="MA200",
            line=dict(color="#a78bfa", width=2)
        ), row=1, col=1)

    current_row = 2
    # Row 2: RSI
    if show_rsi and rsi14:
        fig.add_trace(go.Scatter(
            x=kline["time"], y=rsi14, mode="lines", name="RSI(14)",
            line=dict(color="#a78bfa", width=2),
        ), row=current_row, col=1)
        # 70 / 30 / 50 水平線
        fig.add_hline(y=70, line=dict(color="#d73a49", width=1, dash="dash"),
                      row=current_row, col=1)
        fig.add_hline(y=30, line=dict(color="#16a34a", width=1, dash="dash"),
                      row=current_row, col=1)
        fig.add_hline(y=50, line=dict(color="#94a3b8", width=1, dash="dot"),
                      row=current_row, col=1)
        fig.update_yaxes(range=[0, 100], row=current_row, col=1)
        current_row += 1

    # Row 3: MACD（histogram + DIF + DEA）
    if show_macd and macd_line:
        # Histogram，紅綠跟台股慣例（>0 紅 / <0 綠）
        if macd_hist:
            colors = ["#d73a49" if (v or 0) >= 0 else "#16a34a" for v in macd_hist]
            fig.add_trace(go.Bar(
                x=kline["time"], y=macd_hist, name="Histogram",
                marker_color=colors, showlegend=False, opacity=0.6,
            ), row=current_row, col=1)
        fig.add_trace(go.Scatter(
            x=kline["time"], y=macd_line, mode="lines", name="DIF",
            line=dict(color="#06b6d4", width=2),
        ), row=current_row, col=1)
        if macd_signal:
            fig.add_trace(go.Scatter(
                x=kline["time"], y=macd_signal, mode="lines", name="DEA",
                line=dict(color="#f59e0b", width=2),
            ), row=current_row, col=1)

    fig.update_layout(
        xaxis_rangeslider_visible=False,
        height=200 + 280 * rows,
        margin=dict(l=20, r=20, t=40, b=20),
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    # 隱藏 subplot title 的多餘背景
    fig.update_annotations(font_size=11)
    st.plotly_chart(fig, use_container_width=True)

    # 報酬率與波段高低
    st.markdown("### 近期報酬率")
    wk_high = kline["high"].tail(5).max()
    mo_high = kline["high"].tail(20).max()
    yr_high = kline["high"].tail(250).max()
    drawdown = (last_close - yr_high) / yr_high * 100 if yr_high else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("5 日報酬", fmt_pct(wk_ret), help="近 5 個交易日收盤對收盤")
    c2.metric("20 日報酬", fmt_pct(mo_ret))
    c3.metric("250 日報酬", fmt_pct(yr_ret))
    c4.metric("距 250 日高", fmt_pct(drawdown))

    c1, c2, c3 = st.columns(3)
    c1.metric("5 日高點", fmt_num(wk_high))
    c2.metric("20 日高點", fmt_num(mo_high))
    c3.metric("250 日高點", fmt_num(yr_high))


# ---------- Tab: 籌碼/產業 ----------
with tab_advanced:
    st.markdown("### 🔮 籌碼分析（三大法人買賣超）")

    if chips and len(chips) > 0:
        chips_df = pd.DataFrame(chips)
        chips_df["date"] = pd.to_datetime(chips_df["date"])
        # 股 → 張（lot）
        for col in ["foreign_net", "trust_net", "dealer_net", "total_net"]:
            chips_df[f"{col}_lot"] = chips_df[col].fillna(0) / 1000

        days = len(chips_df)
        st.caption(f"資料來源：TWSE 三大法人買賣超日報，最近 {days} 個交易日")

        # 摘要指標卡（張數）
        def fmt_lot_metric(total_lots):
            if abs(total_lots) >= 10000:
                return f"{total_lots / 10000:+.1f} 萬張"
            return f"{total_lots:+,.0f} 張"

        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"近 {days} 日外資", fmt_lot_metric(chips_df["foreign_net_lot"].sum()))
        c2.metric(f"近 {days} 日投信", fmt_lot_metric(chips_df["trust_net_lot"].sum()))
        c3.metric(f"近 {days} 日自營", fmt_lot_metric(chips_df["dealer_net_lot"].sum()))
        c4.metric(f"近 {days} 日合計", fmt_lot_metric(chips_df["total_net_lot"].sum()))

        # 三圖 stacked subplots
        from plotly.subplots import make_subplots
        import plotly.graph_objects as go

        fig_chips = make_subplots(
            rows=3, cols=1, shared_xaxes=True,
            vertical_spacing=0.05,
            subplot_titles=("🌐 外資（不含外資自營商）", "🏦 投信", "🏢 自營商"),
        )

        def add_chip_bar(row, col_name, name):
            colors = [
                "#d73a49" if (v or 0) >= 0 else "#16a34a"
                for v in chips_df[col_name]
            ]
            fig_chips.add_trace(go.Bar(
                x=chips_df["date"], y=chips_df[col_name], name=name,
                marker_color=colors, showlegend=False,
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:+,.0f} 張<extra></extra>",
            ), row=row, col=1)

        add_chip_bar(1, "foreign_net_lot", "外資")
        add_chip_bar(2, "trust_net_lot", "投信")
        add_chip_bar(3, "dealer_net_lot", "自營商")

        fig_chips.update_layout(
            height=620,
            margin=dict(l=20, r=20, t=40, b=20),
            template="plotly_white",
        )
        fig_chips.update_yaxes(title_text="張", title_standoff=2)
        fig_chips.update_annotations(font_size=12)
        st.plotly_chart(fig_chips, use_container_width=True)

        # 詳細表格
        with st.expander("📊 每日詳細資料"):
            display_df = chips_df.sort_values("date", ascending=False)[
                ["date", "foreign_net_lot", "trust_net_lot", "dealer_net_lot", "total_net_lot"]
            ].rename(columns={
                "date": "日期",
                "foreign_net_lot": "外資（張）",
                "trust_net_lot": "投信（張）",
                "dealer_net_lot": "自營（張）",
                "total_net_lot": "合計（張）",
            })
            display_df["日期"] = display_df["日期"].dt.strftime("%Y-%m-%d")
            st.dataframe(
                display_df, hide_index=True, use_container_width=True, height=400,
                column_config={
                    "外資（張）": st.column_config.NumberColumn(format="%+,.0f"),
                    "投信（張）": st.column_config.NumberColumn(format="%+,.0f"),
                    "自營（張）": st.column_config.NumberColumn(format="%+,.0f"),
                    "合計（張）": st.column_config.NumberColumn(format="%+,.0f"),
                },
            )

        st.caption(
            "資料來源：[TWSE 三大法人買賣超日報](https://www.twse.com.tw/zh/page/trading/fund/T86.html)"
        )
    else:
        st.info(
            "**此檔暫無三大法人資料**\n\n"
            "可能是上櫃個股（.TWO，目前 chips downloader 只支援 TWSE 上市），"
            "或 SQLite DB 還沒累積到此檔。"
        )

    st.divider()

    # === AI 智能摘要（Phase 3）===
    st.markdown("### 🤖 AI 智能摘要")
    if ai_summary_data and ai_summary_data.get("business"):
        gen_at = ai_summary_data.get("generated_at")
        if gen_at:
            st.caption(f"由 Gemini AI 根據 yfinance 業務描述生成，生成於 {gen_at}")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**📦 業務分析**")
            st.write(ai_summary_data["business"])
        with c2:
            st.markdown("**⭐ 競爭優勢**")
            st.write(ai_summary_data["advantage"])
        with c3:
            st.markdown("**⚠️ 主要風險**")
            st.write(ai_summary_data["risk"])
        st.caption("⚠️ AI 生成內容僅供參考，基本面變動可能未即時反映。")
    elif info:
        st.info(
            "**此檔暫無 AI 智能摘要**\n\n"
            "可能是 GEMINI_API_KEY 未設或 Gemini API 暫時無回應。"
            "AI 摘要僅對年漲幅 Top 100 飆股 + 大型股白名單生成。"
        )
    else:
        st.caption("（此檔無 yfinance 業務描述，無法生成 AI 摘要）")

    st.divider()

    # === 同產業 Top 5（Phase 3）===
    st.markdown("### 🏭 同產業 Top 5（依年漲幅）")
    if peers and len(peers) > 0:
        peers_df = pd.DataFrame(peers)[["ticker", "name", "year_high"]].rename(columns={
            "ticker": "代號", "name": "名稱", "year_high": "年漲幅%",
        })
        st.dataframe(
            peers_df,
            hide_index=True,
            use_container_width=True,
            column_config={"年漲幅%": st.column_config.NumberColumn(format="%+.1f")},
        )
        st.caption("💡 點代號可在站內 chart.html 切換到該檔。")
    else:
        st.caption("（此檔無 sector 資料或同 sector 內無其他個股）")

    st.divider()
    st.markdown("### 外部補充資源")
    st.markdown(
        f"- [玩股網籌碼面](https://www.wantgoo.com/stock/{clean_code}/major-investors)\n"
        f"- [Yahoo 股市籌碼分析](https://tw.stock.yahoo.com/quote/{pick}/broker-trading)\n"
        f"- [公開資訊觀測站](https://mops.twse.com.tw/mops/web/index)"
    )


st.divider()
st.caption(
    "Powered by Streamlit · 資料每日由 GitHub Actions 從 TWSE / yfinance 抓取，"
    "經 build_web 打包後透過 Cloudflare Pages CDN 提供。"
)
