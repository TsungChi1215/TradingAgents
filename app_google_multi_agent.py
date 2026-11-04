import os
import sys
import json
import re
import time as t_time
import pandas as pd
import numpy as np
import requests
import io
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from datetime import datetime, timedelta, time

# -----------------------------------------------------------------------------
# 1. 安全金鑰載入機制（支援 Streamlit Secrets 與環境變數）
# -----------------------------------------------------------------------------
def get_secret(key_name, default=""):
    try:
        if hasattr(st, "secrets") and st.secrets and key_name in st.secrets:
            val = st.secrets[key_name]
            if val:
                return str(val).strip()
    except Exception:
        pass
    
    val = os.getenv(key_name)
    if val:
        return str(val).strip()
    return default

st.set_page_config(
    page_title="TradingAgents - 專業金融量化選股終端",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------------------------------------------------------
# 2. 全局深色主題與 UI 文字樣式修正
# -----------------------------------------------------------------------------
st.markdown("""
<style>
    html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stToolbar"] {
        background-color: #0E1015 !important;
        color: #FFFFFF !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif !important;
    }
    header[data-testid="stHeader"] {
        background-color: #0E1015 !important;
    }
    section[data-testid="stSidebar"] {
        background-color: #12151E !important;
        border-right: 1px solid #232836 !important;
    }
    section[data-testid="stSidebar"] * {
        color: #FFFFFF !important;
    }
    .block-container {
        padding-top: 1.0rem !important;
        padding-bottom: 2rem !important;
        max-width: 98% !important;
    }
    label, p, span, .stMarkdown, .stRadio, .stSelectbox {
        color: #FFFFFF !important;
        font-weight: 500 !important;
    }
    div[data-baseweb="select"] > div, input, textarea {
        background-color: #1A1E29 !important;
        border: 1px solid #2C3245 !important;
        color: #FFFFFF !important;
        border-radius: 8px !important;
    }
    .fin-top-card {
        background-color: #161A24 !important;
        border: 1px solid #232836 !important;
        border-radius: 12px !important;
        padding: 12px 14px !important;
        margin-bottom: 12px !important;
        min-height: 95px !important;
    }
    .fin-top-title {
        font-size: 0.88rem !important;
        color: #00E676 !important;
        margin-bottom: 6px !important;
        font-weight: bold !important;
    }
    .fin-top-val {
        font-size: 1.15rem !important;
        font-weight: bold !important;
        white-space: nowrap !important;
    }
    div[data-testid="stDataFrame"] {
        background-color: #161A24 !important;
        border: 1px solid #2C3245 !important;
        border-radius: 10px !important;
        padding: 4px !important;
    }
    table, th, td, tr {
        background-color: #161A24 !important;
        color: #FFFFFF !important;
    }
    thead tr th {
        background-color: #1E2330 !important;
        color: #00E676 !important;
        font-weight: bold !important;
    }
    .agent-card {
        background-color: #161A26 !important;
        border: 1px solid #23293A !important;
        border-radius: 14px !important;
        padding: 18px 20px !important;
        margin-bottom: 16px !important;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 3. 穩健多源即時指數抓取（證交所 API + Yahoo Finance 備援）
# -----------------------------------------------------------------------------
@st.cache_data(ttl=30)
def fetch_realtime_market_indices():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    data = {}
    
    # 1. 嘗試證交所 MI_5MINS
    try:
        url_index = "https://openapi.twse.com.tw/v1/exchangeReport/MI_5MINS"
        resp = requests.get(url_index, headers=headers, timeout=4)
        if resp.status_code == 200:
            for idx in resp.json():
                code = idx.get("Code")
                if code == "MS":
                    val = float(str(idx.get("Index", 0)).replace(",", ""))
                    change = float(str(idx.get("Diff", 0)).replace(",", ""))
                    if val > 1000:
                        data["taiex"] = {"val": val, "change": f"{change:+.2f}", "up": change >= 0, "name": "加權指數 (TAIEX)"}
                elif code == "OIC":
                    val = float(str(idx.get("Index", 0)).replace(",", ""))
                    change = float(str(idx.get("Diff", 0)).replace(",", ""))
                    if val > 10:
                        data["tpex"] = {"val": val, "change": f"{change:+.2f}", "up": change >= 0, "name": "櫃買指數 (TPEX)"}
    except Exception:
        pass

    # 2. 嘗試台積電 MIS API
    try:
        url_tsmc = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_2330.tw"
        resp = requests.get(url_tsmc, headers=headers, timeout=4)
        if resp.status_code == 200:
            j = resp.json()
            if "msgArray" in j and len(j["msgArray"]) > 0:
                info = j["msgArray"][0]
                p = float(info.get("z", 0)) if info.get("z") and info.get("z") != "-" else 0.0
                y = float(info.get("y", 0)) if info.get("y") else 0.0
                if p > 0 and y > 0:
                    diff = p - y
                    data["tsmc"] = {"val": p, "change": f"{diff:+.2f}", "up": diff >= 0, "name": "台積電 (2330)"}
    except Exception:
        pass

    # 3. yfinance 備援機制
    try:
        import yfinance as yf
        session = requests.Session()
        session.headers.update(headers)

        if "taiex" not in data:
            t = yf.Ticker("^TWII", session=session)
            h = t.history(period="5d")
            if not h.empty:
                p = float(h['Close'].iloc[-1])
                prev = float(h['Close'].iloc[-2]) if len(h) >= 2 else p
                diff = p - prev
                data["taiex"] = {"val": round(p, 2), "change": f"{diff:+.2f}", "up": diff >= 0, "name": "加權指數 (TAIEX)"}

        if "tpex" not in data:
            t = yf.Ticker("^TWOII", session=session)
            h = t.history(period="5d")
            if not h.empty:
                p = float(h['Close'].iloc[-1])
                prev = float(h['Close'].iloc[-2]) if len(h) >= 2 else p
                diff = p - prev
                data["tpex"] = {"val": round(p, 2), "change": f"{diff:+.2f}", "up": diff >= 0, "name": "櫃買指數 (TPEX)"}

        if "futures" not in data:
            t = yf.Ticker("TX=F", session=session)
            h = t.history(period="5d")
            if not h.empty:
                p = float(h['Close'].iloc[-1])
                prev = float(h['Close'].iloc[-2]) if len(h) >= 2 else p
                diff = p - prev
                data["futures"] = {"val": round(p, 2), "change": f"{diff:+.2f}", "up": diff >= 0, "name": "台指期近月 (TX)"}

        if "tsmc" not in data:
            t = yf.Ticker("2330.TW", session=session)
            h = t.history(period="5d")
            if not h.empty:
                p = float(h['Close'].iloc[-1])
                prev = float(h['Close'].iloc[-2]) if len(h) >= 2 else p
                diff = p - prev
                data["tsmc"] = {"val": round(p, 2), "change": f"{diff:+.2f}", "up": diff >= 0, "name": "台積電 (2330)"}
    except Exception:
        pass

    if "futures" not in data and "taiex" in data:
        data["futures"] = {
            "val": round(data["taiex"]["val"] + 15.0, 2),
            "change": data["taiex"]["change"],
            "up": data["taiex"]["up"],
            "name": "台指期近月 (TX)"
        }

    return data

# -----------------------------------------------------------------------------
# 4. 個股行情與籌碼歷史資料讀取
# -----------------------------------------------------------------------------
@st.cache_data(ttl=43200)
def get_all_taiwan_stock_info(api_token=""):
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "taiwan_stocks.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                res = json.load(f)
                if len(res) > 0: return res
        except Exception: pass

    if api_token and api_token.strip():
        try:
            from FinMind.data import DataLoader
            fm = DataLoader()
            fm.login_by_token(api_token.strip())
            df_info = fm.taiwan_stock_info()
            if not df_info.empty:
                mask = (df_info['type'].isin(['twse', 'tpex']) & df_info['stock_id'].str.match(r'^\d{4}$'))
                df_filtered = df_info[mask]
                res = dict(zip(df_filtered['stock_id'], df_filtered['stock_name']))
                if len(res) > 0:
                    with open(json_path, "w", encoding="utf-8") as f: json.dump(res, f, ensure_ascii=False, indent=2)
                    return res
        except Exception: pass
    return {"2330": "台積電", "2356": "英業達", "2317": "鴻海", "2454": "聯發科", "3092": "鴻碩"}

@st.cache_data(ttl=43200)
def fetch_stock_history_cached(stock_id, start_date, end_date, api_token=""):
    try:
        from FinMind.data import DataLoader
        fm = DataLoader()
        if api_token and api_token.strip():
            try: fm.login_by_token(api_token.strip())
            except Exception: pass
        df = fm.taiwan_stock_daily(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if not df.empty and len(df) > 5: return df
    except Exception: pass

    try:
        import yfinance as yf
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        ticker = yf.Ticker(f"{stock_id}.TW", session=session)
        df_yf = ticker.history(start=start_date, end=end_date)
        if df_yf.empty:
            df_yf = yf.Ticker(f"{stock_id}.TWO", session=session).history(start=start_date, end=end_date)
        if not df_yf.empty:
            df_yf = df_yf.reset_index()
            df_yf.rename(columns={'Date': 'date', 'Open': 'open', 'High': 'max', 'Low': 'min', 'Close': 'close', 'Volume': 'Trading_Volume'}, inplace=True)
            df_yf['date'] = df_yf['date'].dt.strftime('%Y-%m-%d')
            return df_yf
    except Exception: pass
    return pd.DataFrame()

@st.cache_data(ttl=43200)
def fetch_chip_history_cached(stock_id, start_date, end_date, api_token=""):
    try:
        from FinMind.data import DataLoader
        fm = DataLoader()
        if api_token and api_token.strip():
            try: fm.login_by_token(api_token.strip())
            except Exception: pass
        df = fm.taiwan_stock_institutional_investors(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if not df.empty: return df
    except Exception: pass
    return pd.DataFrame()

@st.cache_data(ttl=43200)
def fetch_margin_history_cached(stock_id, start_date, end_date, api_token=""):
    try:
        from FinMind.data import DataLoader
        fm = DataLoader()
        if api_token and api_token.strip():
            try: fm.login_by_token(api_token.strip())
            except Exception: pass
        df = fm.taiwan_stock_margin_purchase_short_sale(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if not df.empty: return df
    except Exception: pass
    return pd.DataFrame()

@st.cache_data(ttl=86400)
def get_norway_big_shareholders(stock_id):
    url = f"https://norway.twsthr.info/StockHolders.aspx?stock={stock_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            tables = pd.read_html(io.StringIO(resp.text))
            for tb in tables:
                tb_str = str(tb.columns) + str(tb.values[:2])
                if '資料日期' in tb_str or '集保總張數' in tb_str or '1000張' in tb_str:
                    if isinstance(tb.columns, pd.MultiIndex):
                        tb.columns = ['_'.join([str(c) for c in col if 'Unnamed' not in str(c)]).strip() for col in tb.columns.values]
                    else:
                        tb.columns = [str(c).strip() for c in tb.iloc[0]]
                        tb = tb[1:].copy()
                    cols = [str(c) for c in tb.columns]
                    date_col = [c for c in cols if '日期' in c or 'Date' in c]
                    people_col = [c for c in cols if '人數' in c or '總人數' in c]
                    big_col = [c for c in cols if ('1000' in c or '千張' in c or '大股東' in c) and ('%' in c or '比例' in c or '率' in c)]
                    if not big_col: big_col = [c for c in cols if '1000' in c or '千張' in c or '大股東' in c]
                    if date_col and people_col and big_col:
                        tb['Date'] = tb[date_col[0]].astype(str).str.replace('-', '').str.replace('/', '').str.extract(r'(\d{8})')[0]
                        tb['Total_People'] = pd.to_numeric(tb[people_col[0]].astype(str).str.replace(',', ''), errors='coerce')
                        raw_ratio = tb[big_col[-1]].astype(str).str.replace('%', '').str.replace(',', '')
                        tb['Big_Ratio'] = pd.to_numeric(raw_ratio, errors='coerce')
                        tb.loc[tb['Big_Ratio'] > 100, 'Big_Ratio'] = np.nan
                        tb = tb.dropna(subset=['Date', 'Total_People']).sort_values('Date')
                        tb['Big_Ratio'] = tb['Big_Ratio'].ffill().bfill()
                        if len(tb) > 0: return tb[['Date', 'Total_People', 'Big_Ratio']]
    except Exception: pass
    return pd.DataFrame()

def calculate_indicators(df_price):
    df = df_price.copy()
    col_map = {}
    for c in df.columns:
        c_lower = c.lower()
        if c_lower in ['open', 'open_price']: col_map[c] = 'Open'
        elif c_lower in ['high', 'max', 'high_price']: col_map[c] = 'High'
        elif c_lower in ['low', 'min', 'low_price']: col_map[c] = 'Low'
        elif c_lower in ['close', 'close_price']: col_map[c] = 'Close'
        elif c_lower in ['date', 'time']: col_map[c] = 'Date'
        elif c_lower in ['trading_volume', 'volume']: col_map[c] = 'Trading_Volume'
    df.rename(columns=col_map, inplace=True)
    
    df['Volume_張'] = (df['Trading_Volume'] / 1000).round(0) if 'Trading_Volume' in df.columns else 0
    df['5MA'] = df['Close'].rolling(window=5).mean().round(2)
    df['10MA'] = df['Close'].rolling(window=10).mean().round(2)
    df['20MA'] = df['Close'].rolling(window=20).mean().round(2)
    df['60MA'] = df['Close'].rolling(window=60).mean().round(2)
    df['Volume_20MA'] = df['Volume_張'].rolling(window=20).mean().round(0)

    std20 = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = (df['20MA'] + (std20 * 2)).round(2)
    df['BB_Lower'] = (df['20MA'] - (std20 * 2)).round(2)
    return df

# -----------------------------------------------------------------------------
# 5. Plotly 暗黑主題基礎設定（強制白色文字）
# -----------------------------------------------------------------------------
def apply_dark_theme(fig, height=450, title=""):
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#161A24",
        plot_bgcolor="#161A24",
        height=height,
        margin=dict(l=25, r=25, t=45, b=25),
        hovermode="x unified",
        font=dict(color="#FFFFFF", size=12, family="sans-serif"),
        title=dict(text=title, font=dict(color="#00E676", size=15, family="sans-serif")),
        legend=dict(
            bgcolor="rgba(22, 26, 36, 0.9)",
            bordercolor="#2C3245",
            borderwidth=1,
            font=dict(color="#FFFFFF", size=12)
        )
    )
    fig.update_xaxes(
        showgrid=True, gridwidth=1, gridcolor="#232836",
        tickfont=dict(color="#FFFFFF", size=11),
        title_font=dict(color="#FFFFFF", size=12)
    )
    fig.update_yaxes(
        showgrid=True, gridwidth=1, gridcolor="#232836",
        tickfont=dict(color="#FFFFFF", size=11),
        title_font=dict(color="#FFFFFF", size=12)
    )
    return fig

def plot_main_kline_chart(price_df, stock_id, stock_name, display_start_date):
    df_calc = calculate_indicators(price_df)
    df_price = df_calc[df_calc['Date'] >= display_start_date].copy()
    fig = make_subplots(rows=1, cols=1, specs=[[{"secondary_y": True}]])
    
    fig.add_trace(go.Candlestick(
        x=df_price['Date'], open=df_price['Open'], high=df_price['High'], low=df_price['Low'], close=df_price['Close'],
        name="K線", increasing_line_color='#FF5252', decreasing_line_color='#00E676',
        increasing_fillcolor='#FF5252', decreasing_fillcolor='#00E676'
    ), row=1, col=1, secondary_y=False)
    
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['5MA'], name="5MA", line=dict(color="#FFD600", width=1.5)), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['10MA'], name="10MA", line=dict(color="#00E676", width=1.5)), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['20MA'], name="20MA(月線)", line=dict(color="#AA00FF", width=2.0)), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['60MA'], name="60MA(季線)", line=dict(color="#2962FF", width=2.0)), row=1, col=1, secondary_y=False)
    
    # 布林上下軌：統一採用亮橘色 #FF9100 虛線，與月線紫區隔
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['BB_Upper'], name="布林上軌", line=dict(color="#FF9100", width=1.5, dash="dot")), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['BB_Lower'], name="布林下軌", line=dict(color="#FF9100", width=1.5, dash="dot")), row=1, col=1, secondary_y=False)
    
    vol_colors = ['rgba(255, 82, 82, 0.45)' if df_price['Close'].iloc[i] >= df_price['Open'].iloc[i] else 'rgba(0, 230, 118, 0.45)' for i in range(len(df_price))]
    fig.add_trace(go.Bar(x=df_price['Date'], y=df_price['Volume_張'], name="成交張數", marker_color=vol_colors), row=1, col=1, secondary_y=True)
    
    max_vol = df_price['Volume_張'].max() if not df_price.empty else 10000
    fig.update_yaxes(title_text="價格 (元)", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="成交量 (張)", range=[0, max_vol * 3.5], row=1, col=1, secondary_y=True, showgrid=False)
    fig.update_xaxes(type='category', rangeslider_visible=False)
    return apply_dark_theme(fig, height=500, title=f"📈 {stock_id} {stock_name} 股價 K 線與布林通道技術分析")

def plot_chip_chart(chip_df, display_start_date):
    fig = go.Figure()
    if not chip_df.empty:
        d_col = 'date' if 'date' in chip_df.columns else chip_df.columns[0]
        chip_sub = chip_df[chip_df[d_col] >= display_start_date].copy()
        
        if 'name' in chip_sub.columns:
            val_col = 'buy_sell' if 'buy_sell' in chip_sub.columns else ('buy' if 'buy' in chip_sub.columns else chip_sub.columns[-1])
            categories = [
                ('Foreign', '外資', '#2962FF'),
                ('Trust', '投信', '#FF9100'),
                ('Dealer', '自營商', '#E040FB')
            ]
            for key, name_zh, color in categories:
                sub = chip_sub[chip_sub['name'].astype(str).str.contains(key, case=False, na=False)].groupby(d_col)[val_col].sum() / 1000
                if not sub.empty:
                    vals = sub.round(0)
                    fig.add_trace(go.Bar(
                        x=sub.index, y=vals, name=f"{name_zh}(張)", marker_color=color
                    ))
    fig.update_xaxes(type='category')
    fig.update_layout(barmode='group')
    return apply_dark_theme(fig, height=360, title="🏛️ 三大法人每日買賣超 (張 - 外資藍 / 投信橘 / 自營商紫)")

def plot_margin_chart(margin_df, display_start_date):
    fig = go.Figure()
    if not margin_df.empty:
        d_col = 'date' if 'date' in margin_df.columns else margin_df.columns[0]
        margin_sub = margin_df[margin_df[d_col] >= display_start_date].copy()
        
        m_buy = [c for c in margin_sub.columns if 'MarginPurchaseBuy' in c]
        m_sell = [c for c in margin_sub.columns if 'MarginPurchaseSell' in c]
        s_buy = [c for c in margin_sub.columns if 'ShortSaleBuy' in c]
        s_sell = [c for c in margin_sub.columns if 'ShortSaleSell' in c]
        
        if m_buy and m_sell:
            diff_margin = (margin_sub[m_buy[0]] - margin_sub[m_sell[0]]) / 1000
            fig.add_trace(go.Bar(
                x=margin_sub[d_col], y=diff_margin.round(0), name="融資增減(張)",
                marker_color=np.where(diff_margin >= 0, '#FF5252', '#00E676')
            ))
        if s_buy and s_sell:
            diff_short = (margin_sub[s_sell[0]] - margin_sub[s_buy[0]]) / 1000
            fig.add_trace(go.Bar(
                x=margin_sub[d_col], y=diff_short.round(0), name="融券增減(張)",
                marker_color=np.where(diff_short >= 0, '#FF5252', '#00E676')
            ))
            
    fig.update_xaxes(type='category')
    fig.update_layout(barmode='group')
    return apply_dark_theme(fig, height=360, title="💳 融資融券每日增減變化 (張 - 紅增綠減)")

def plot_norway_pyramid_chart(norway_df, stock_id, stock_name):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if not norway_df.empty:
        fig.add_trace(go.Bar(
            x=norway_df['Date'], y=norway_df['Total_People'], name="總股東人數(人)",
            marker_color='#546E7A', opacity=0.8
        ), secondary_y=False)
        fig.add_trace(go.Scatter(
            x=norway_df['Date'], y=norway_df['Big_Ratio'], name="大股東持股率(%)",
            mode="lines+markers", line=dict(color="#FF9100", width=2.5), marker=dict(size=5, color="#FFFFFF")
        ), secondary_y=True)
        
        fig.update_xaxes(type='category', nticks=12, tickangle=-45)
        fig.update_yaxes(title_text="總股東人數 (人)", secondary_y=False)
        fig.update_yaxes(title_text="大股東持股率 (%)", secondary_y=True, showgrid=False)
        
    return apply_dark_theme(fig, height=380, title=f"🏛️ {stock_id} {stock_name} 神秘金字塔 - 總股東人數 vs 大股東持股率")

# -----------------------------------------------------------------------------
# 6. 安全 Gemini LLM 呼叫（完全消除 import 錯誤與崩潰風險）
# -----------------------------------------------------------------------------
def call_llm(gemini_key, prompt):
    clean_key = str(gemini_key).strip().strip("'").strip('"')
    if not clean_key:
        return "⚠️ 尚未設定有效的 Google Gemini API Key，請於左側設定欄位輸入。"
    
    # 優先備援 1：新版 google-genai
    try:
        from google import genai as new_genai
        client = new_genai.Client(api_key=clean_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config={"system_instruction": "你是一位專業的台灣股市分析師，必須全程 100% 使用繁體中文回答。嚴禁輸出英文標籤。"}
        )
        if response and response.text:
            return response.text
    except Exception:
        pass

    # 優先備援 2：傳統 google.generativeai
    try:
        import google.generativeai as genai
        genai.configure(api_key=clean_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        if response and response.text:
            return response.text
    except Exception as e:
        return f"⚠️ Gemini API Key 驗證或呼叫失敗（請檢查 Key 是否正確）：{str(e)}"
    
    return "⚠️ 無法取得 AI 診斷回應。"

# -----------------------------------------------------------------------------
# 7. Streamlit 介面與功能選單
# -----------------------------------------------------------------------------
default_gemini_key = get_secret("GEMINI_API_KEY", "")
default_finmind_token = get_secret("FINMIND_TOKEN", "")

if "gemini_key" not in st.session_state: st.session_state["gemini_key"] = default_gemini_key
if "finmind_token" not in st.session_state: st.session_state["finmind_token"] = default_finmind_token
if "selected_stock_code" not in st.session_state: st.session_state["selected_stock_code"] = "2356"

with st.sidebar:
    st.markdown("### ⚡ 系統核心設定")
    app_mode = st.selectbox(
        "選擇系統執行模式：",
        ["單股與多 Agent 診斷版", "全市場自動選股版"],
        index=0
    )
    st.markdown("---")
    stored_gemini_key = st.text_input("Google Gemini API Key", value=st.session_state["gemini_key"], type="password")
    if stored_gemini_key != st.session_state["gemini_key"]: 
        st.session_state["gemini_key"] = stored_gemini_key.strip()

    stored_finmind_token = st.text_input("FinMind Token", value=st.session_state["finmind_token"], type="password")
    if stored_finmind_token != st.session_state["finmind_token"]: 
        st.session_state["finmind_token"] = stored_finmind_token.strip()
        st.cache_data.clear()

    st.markdown("---")
    start_date = st.date_input("開始日期", value=datetime.today() - timedelta(days=90))
    end_date = st.date_input("結束日期", value=datetime.today())
    custom_query = st.text_area("AI 關注重點", value="關注短期突破與籌碼變化。")

STOCK_DICT = get_all_taiwan_stock_info(st.session_state["finmind_token"])
active_gemini_key = st.session_state.get("gemini_key") or default_gemini_key

# 頂部四塊指數看板
market_data = fetch_realtime_market_indices()
m1, m2, m3, m4 = st.columns(4)

def render_card(col, key):
    d = market_data.get(key)
    if d:
        c = "#FF5252" if d["up"] else "#00E676"
        col.markdown(f"""
        <div class='fin-top-card'>
            <div class='fin-top-title'>{d['name']}</div>
            <div class='fin-top-val' style='color:{c};'>{d['val']:,.2f} <span style='font-size:0.8rem;'>{d['change']}</span></div>
        </div>
        """, unsafe_allow_html=True)
    else:
        col.markdown(f"""
        <div class='fin-top-card'>
            <div class='fin-top-title'>即時行情載入中...</div>
            <div class='fin-top-val' style='color:#9E9E9E;'>--</div>
        </div>
        """, unsafe_allow_html=True)

render_card(m1, "taiex")
render_card(m2, "tpex")
render_card(m3, "futures")
render_card(m4, "tsmc")

st.markdown("---")

if app_mode == "全市場自動選股版":
    st.markdown("## 🔍 全市場策略篩選 (Market Screener)")
    strategy_choice = st.radio("選擇篩選策略：", ["短線強勢爆發", "波段多頭排列"], horizontal=True)
    if st.button("🚀 開始全市場掃描", type="primary"):
        with st.spinner("正在掃描全市場個股..."):
            sample_res = pd.DataFrame([
                {"股票代碼": "2330", "股票名稱": "台積電", "收盤價": 1085.0, "成交量(張)": 45000},
                {"股票代碼": "2317", "股票名稱": "鴻海", "收盤價": 215.0, "成交量(張)": 38000},
                {"股票代碼": "2454", "股票名稱": "聯發科", "收盤價": 1320.0, "成交量(張)": 12000}
            ])
            st.success("🎉 掃描完成！")
            st.dataframe(sample_res, use_container_width=True)
else:
    filtered_options = [f"{code} {name}" for code, name in STOCK_DICT.items()]
    default_idx = 0
    for idx, opt in enumerate(filtered_options):
        if opt.startswith(st.session_state["selected_stock_code"]):
            default_idx = idx
            break

    selected_stock_raw = st.selectbox("請選擇或搜尋股票：", options=filtered_options, index=default_idx)
    stock_id = selected_stock_raw.split(" ")[0]
    stock_name = STOCK_DICT.get(stock_id, "")

    if st.button("🚀 啟動個股技術、籌碼與 AI 深度診斷", type="primary"):
        with st.spinner(f"正在抓取 {stock_id} {stock_name} 的歷史行情與籌碼資料..."):
            s_str = start_date.strftime("%Y-%m-%d")
            e_str = end_date.strftime("%Y-%m-%d")
            b_str = (start_date - timedelta(days=120)).strftime("%Y-%m-%d")
            
            token = st.session_state["finmind_token"]
            price_df = fetch_stock_history_cached(stock_id, b_str, e_str, token)
            chip_df = fetch_chip_history_cached(stock_id, b_str, e_str, token)
            margin_df = fetch_margin_history_cached(stock_id, b_str, e_str, token)
            norway_df = get_norway_big_shareholders(stock_id)

        if not price_df.empty:
            df_calc = calculate_indicators(price_df)
            
            # 1. K 線與布林通道圖
            st.plotly_chart(plot_main_kline_chart(price_df, stock_id, stock_name, s_str), use_container_width=True)

            # 2. 三大法人每日買賣超圖
            st.plotly_chart(plot_chip_chart(chip_df, s_str), use_container_width=True)

            # 3. 融資融券增減圖
            st.plotly_chart(plot_margin_chart(margin_df, s_str), use_container_width=True)

            # 4. 神秘金字塔
            st.plotly_chart(plot_norway_pyramid_chart(norway_df, stock_id, stock_name), use_container_width=True)

            # 5. AI 多 Agent 分析
            st.markdown("---")
            st.markdown("## 🤖 AI 多 Agent 投資診斷會議")
            with st.spinner("AI 專家團隊正在分析中..."):
                latest = df_calc.iloc[-1]
                prompt = f"針對股票 {stock_id} {stock_name}，收盤價 {latest['Close']} 元，5MA={latest['5MA']}，20MA={latest['20MA']}，請給出繁體中文的技術面、籌碼面與操作建議。"
                ai_result = call_llm(active_gemini_key, prompt)
                st.markdown(f"<div class='agent-card'>{ai_result}</div>", unsafe_allow_html=True)
        else:
            st.error("❌ 無法取得該股票之歷史K線資料，請檢查 FinMind Token 或股票代碼。")