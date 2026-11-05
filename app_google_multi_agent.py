import os
import json
import pandas as pd
import numpy as np
import requests
import io
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from datetime import datetime, timedelta

# -----------------------------------------------------------------------------
# 1. 系統設定與強效金鑰清洗解析
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="TradingAgents - 專業金融量化選股終端",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

if "selected_stock_code" not in st.session_state:
    st.session_state["selected_stock_code"] = "2356"

def get_secret(key_name, default=""):
    try:
        if hasattr(st, "secrets") and st.secrets and key_name in st.secrets:
            val = st.secrets[key_name]
            if val: return val
    except Exception: pass
    val = os.getenv(key_name)
    if val: return str(val).strip()
    return default

def parse_api_keys(raw_input):
    if not raw_input:
        return []
    if isinstance(raw_input, list):
        keys = []
        for k in raw_input:
            clean = str(k).strip().replace("[", "").replace("]", "").replace("'", "").replace('"', "").strip()
            if clean: keys.append(clean)
        return keys
        
    cleaned = str(raw_input).strip()
    cleaned = cleaned.replace("[", "").replace("]", "").replace("'", "").replace('"', "")
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    if not parts and cleaned:
        parts = [cleaned]
    return [p for p in parts if p]

# -----------------------------------------------------------------------------
# 2. 四大指數與台積電即時行情抓取（零預設假數字、純即時 FinMind 抓取）
# -----------------------------------------------------------------------------
def fetch_realtime_market_data(api_token=""):
    data = {}
    today_str = datetime.today().strftime("%Y-%m-%d")
    start_str = (datetime.today() - timedelta(days=10)).strftime("%Y-%m-%d")
    
    try:
        from FinMind.data import DataLoader
        fm = DataLoader()
        if api_token: fm.login_by_token(api_token.strip())

        # 1. 加權指數 (代號 001)
        df_taiex = fm.taiwan_stock_daily(stock_id="001", start_date=start_str, end_date=today_str)
        if not df_taiex.empty:
            val = float(df_taiex['close'].iloc[-1])
            prev = float(df_taiex['close'].iloc[-2]) if len(df_taiex) > 1 else val
            data["taiex"] = {"val": val, "change": val - prev, "name": "加權指數 (TAIEX)"}

        # 2. 櫃買指數 (代號 101)
        df_tpex = fm.taiwan_stock_daily(stock_id="101", start_date=start_str, end_date=today_str)
        if not df_tpex.empty:
            val = float(df_tpex['close'].iloc[-1])
            prev = float(df_tpex['close'].iloc[-2]) if len(df_tpex) > 1 else val
            data["tpex"] = {"val": val, "change": val - prev, "name": "櫃買指數 (TPEX)"}

        # 3. 台指期近月 (代號 TX)
        df_futures = fm.taiwan_futures_daily(start_date=start_str, end_date=today_str)
        if not df_futures.empty:
            df_tx = df_futures[df_futures["stock_id"] == "TX"].copy()
            if not df_tx.empty:
                latest_date = df_tx['date'].max()
                df_tx_latest = df_tx[df_tx['date'] == latest_date]
                if not df_tx_latest.empty:
                    val = float(df_tx_latest['close'].iloc[0])
                    prev = float(df_tx_latest['spread'].iloc[0]) if 'spread' in df_tx_latest.columns else 0.0
                    data["futures"] = {"val": val, "change": prev, "name": "台指近月 (TX)"}

        # 4. 台積電 (代號 2330)
        df_tsmc = fm.taiwan_stock_daily(stock_id="2330", start_date=start_str, end_date=today_str)
        if not df_tsmc.empty:
            val = float(df_tsmc['close'].iloc[-1])
            prev = float(df_tsmc['close'].iloc[-2]) if len(df_tsmc) > 1 else val
            data["tsmc"] = {"val": val, "change": val - prev, "name": "台積電 (2330)"}
            
    except Exception as e: 
        print(f"Fetch Market Data Error: {e}")

    return data

# -----------------------------------------------------------------------------
# 3. 全市場自動選股引擎
# -----------------------------------------------------------------------------
def run_market_screener(stock_dict, strategy_type):
    url_twse = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        resp = requests.get(url_twse, timeout=10)
        if resp.status_code == 200:
            raw_data = resp.json()
            selected_list = []
            for item in raw_data:
                sid = str(item.get('Code', '')).strip()
                if len(sid) == 4 and sid.isdigit() and sid in stock_dict:
                    close_p = float(str(item.get('ClosingPrice', 0)).replace(',', '')) if item.get('ClosingPrice') else 0
                    open_p = float(str(item.get('OpeningPrice', 0)).replace(',', '')) if item.get('OpeningPrice') else close_p
                    vol = float(str(item.get('TradeVolume', 0)).replace(',', '')) if item.get('TradeVolume') else 0
                    vol_lots = int(vol / 1000)
                    
                    if vol_lots < 800: continue
                    sname = stock_dict.get(sid, sid)
                    change_pct = ((close_p - open_p) / open_p) * 100 if open_p > 0 else 0
                    
                    if strategy_type == "短線強勢爆發":
                        if change_pct >= 2.0 and vol_lots >= 1500 and close_p > open_p:
                            selected_list.append({'股票代碼': sid, '股票名稱': sname, '今日收盤': close_p, '漲幅(%)': round(change_pct, 2), '成交量(張)': vol_lots})
                    elif strategy_type == "波段多頭排列":
                        if 0.5 <= change_pct <= 3.0 and vol_lots >= 1000 and close_p >= open_p:
                            selected_list.append({'股票代碼': sid, '股票名稱': sname, '今日收盤': close_p, '漲幅(%)': round(change_pct, 2), '成交量(張)': vol_lots})
            
            if selected_list:
                df_res = pd.DataFrame(selected_list)
                sort_col = '漲幅(%)' if strategy_type == "短線強勢爆發" else '成交量(張)'
                return df_res.sort_values(by=sort_col, ascending=False).head(30)
    except Exception: pass
    return pd.DataFrame()

# -----------------------------------------------------------------------------
# 4. 個股資料抓取與技術指標計算
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
    return {"2330": "台積電", "2356": "英業達", "2317": "鴻海", "2454": "聯發科"}

@st.cache_data(ttl=43200)
def fetch_stock_history_cached(stock_id, start_date, end_date, api_token=""):
    try:
        from FinMind.data import DataLoader
        fm = DataLoader()
        if api_token: fm.login_by_token(api_token.strip())
        df = fm.taiwan_stock_daily(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if not df.empty and len(df) > 5: return df
    except Exception: pass
    return pd.DataFrame()

@st.cache_data(ttl=43200)
def fetch_chip_history_cached(stock_id, start_date, end_date, api_token=""):
    try:
        from FinMind.data import DataLoader
        fm = DataLoader()
        if api_token: fm.login_by_token(api_token.strip())
        df = fm.taiwan_stock_institutional_investors(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if not df.empty: return df
    except Exception: pass
    return pd.DataFrame()

@st.cache_data(ttl=43200)
def fetch_margin_history_cached(stock_id, start_date, end_date, api_token=""):
    try:
        from FinMind.data import DataLoader
        fm = DataLoader()
        if api_token: fm.login_by_token(api_token.strip())
        df = fm.taiwan_stock_margin_purchase_short_sale(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if not df.empty: return df
    except Exception: pass
    return pd.DataFrame()

@st.cache_data(ttl=86400)
def get_norway_big_shareholders(stock_id):
    url = f"https://norway.twsthr.info/StockHolders.aspx?stock={stock_id}"
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        if resp.status_code == 200:
            tables = pd.read_html(io.StringIO(resp.text))
            for tb in tables:
                tb_str = str(tb.columns) + str(tb.values[:2])
                if '集保總張數' in tb_str or '1000張' in tb_str:
                    if isinstance(tb.columns, pd.MultiIndex):
                        tb.columns = ['_'.join([str(c) for c in col if 'Unnamed' not in str(c)]).strip() for col in tb.columns.values]
                    else:
                        tb.columns = [str(c).strip() for c in tb.iloc[0]]
                        tb = tb[1:].copy()
                    cols = [str(c) for c in tb.columns]
                    date_col = [c for c in cols if '日期' in c or 'Date' in c]
                    people_col = [c for c in cols if '人數' in c or '總人數' in c]
                    big_col = [c for c in cols if ('1000' in c or '千張' in c or '大股東' in c) and ('%' in c or '比例' in c or '率' in c)]
                    if not big_col: big_col = [c for c in cols if '1000' in c or '大股東' in c]
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
    col_map = {c: c.capitalize() if c.lower() in ['open', 'high', 'low', 'close', 'date'] else c for c in df.columns}
    if 'max' in df.columns: col_map['max'] = 'High'
    if 'min' in df.columns: col_map['min'] = 'Low'
    if 'Trading_Volume' in df.columns: col_map['Trading_Volume'] = 'Trading_Volume'
    df.rename(columns=col_map, inplace=True)
    
    df['Volume_張'] = (df['Trading_Volume'] / 1000).round(0) if 'Trading_Volume' in df.columns else 0
    df['5MA'] = df['Close'].rolling(window=5).mean().round(2)
    df['10MA'] = df['Close'].rolling(window=10).mean().round(2)
    df['20MA'] = df['Close'].rolling(window=20).mean().round(2)
    
    std20 = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = (df['20MA'] + (std20 * 2)).round(2)
    df['BB_Lower'] = (df['20MA'] - (std20 * 2)).round(2)
    return df

# -----------------------------------------------------------------------------
# 5. Plotly 圖表繪製
# -----------------------------------------------------------------------------
def apply_dark_theme(fig, height=450, title=""):
    fig.update_layout(
        template="plotly_dark", height=height, margin=dict(l=25, r=25, t=45, b=25),
        hovermode="x unified", title=dict(text=title, font=dict(color="#00E676", size=15))
    )
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor="#232836", type='category')
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor="#232836")
    return fig

def plot_main_kline_chart(price_df, stock_id, stock_name, display_start_date):
    df_calc = calculate_indicators(price_df)
    df_price = df_calc[df_calc['Date'] >= display_start_date].copy()
    fig = make_subplots(rows=1, cols=1, specs=[[{"secondary_y": True}]])
    
    fig.add_trace(go.Candlestick(x=df_price['Date'], open=df_price['Open'], high=df_price['High'], low=df_price['Low'], close=df_price['Close'], name="K線", increasing_line_color='#FF5252', decreasing_line_color='#00E676'), secondary_y=False)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['5MA'], name="5MA", line=dict(color="#FFD600", width=1.5)), secondary_y=False)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['20MA'], name="20MA(月線)", line=dict(color="#AA00FF", width=2.0)), secondary_y=False)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['BB_Upper'], name="布林上軌", line=dict(color="#FF9100", width=1.5, dash="dot")), secondary_y=False)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['BB_Lower'], name="布林下軌", line=dict(color="#FF9100", width=1.5, dash="dot")), secondary_y=False)
    
    vol_colors = ['rgba(255, 82, 82, 0.45)' if df_price['Close'].iloc[i] >= df_price['Open'].iloc[i] else 'rgba(0, 230, 118, 0.45)' for i in range(len(df_price))]
    fig.add_trace(go.Bar(x=df_price['Date'], y=df_price['Volume_張'], name="成交張數", marker_color=vol_colors), secondary_y=True)
    
    max_vol = df_price['Volume_張'].max() if not df_price.empty else 10000
    fig.update_yaxes(title_text="價格 (元)", secondary_y=False)
    fig.update_yaxes(title_text="成交量 (張)", range=[0, max_vol * 3.5], secondary_y=True, showgrid=False)
    fig.update_xaxes(rangeslider_visible=False)
    return apply_dark_theme(fig, height=500, title=f"📈 {stock_id} {stock_name} 股價 K 線與布林通道")

def plot_chip_chart(chip_df, display_start_date):
    fig = go.Figure()
    if not chip_df.empty:
        d_col = 'date' if 'date' in chip_df.columns else chip_df.columns[0]
        chip_sub = chip_df[chip_df[d_col] >= display_start_date].copy()
        
        if 'buy' in chip_sub.columns and 'sell' in chip_sub.columns:
            chip_sub['net_buy'] = chip_sub['buy'] - chip_sub['sell']
        else:
            chip_sub['net_buy'] = chip_sub.get('buy_sell', chip_sub.iloc[:, -1])
            
        categories = [('Foreign', '外資', '#2962FF'), ('Trust', '投信', '#FF9100'), ('Dealer', '自營商', '#E040FB')]
        for key, name_zh, color in categories:
            sub = chip_sub[chip_sub['name'].astype(str).str.contains(key, case=False, na=False)].groupby(d_col)['net_buy'].sum() / 1000
            if not sub.empty:
                vals = sub.round(0)
                colors = np.where(vals >= 0, '#FF5252', '#00E676')
                fig.add_trace(go.Bar(x=sub.index, y=vals, name=f"{name_zh}(張)", marker_color=colors))
    fig.update_layout(barmode='group')
    return apply_dark_theme(fig, height=360, title="🏛️ 三大法人每日淨買賣超 (張 - 紅買綠賣)")

def plot_margin_chart(margin_df, display_start_date):
    fig = go.Figure()
    if not margin_df.empty:
        d_col = 'date' if 'date' in margin_df.columns else margin_df.columns[0]
        margin_sub = margin_df[margin_df[d_col] >= display_start_date].copy()
        m_buy = [c for c in margin_sub.columns if 'MarginPurchaseBuy' in c]
        m_sell = [c for c in margin_sub.columns if 'MarginPurchaseSell' in c]
        
        if m_buy and m_sell:
            diff = (margin_sub[m_buy[0]] - margin_sub[m_sell[0]]) / 1000
            fig.add_trace(go.Bar(x=margin_sub[d_col], y=diff.round(0), name="融資增減(張)", marker_color=np.where(diff >= 0, '#FF5252', '#00E676')))
    fig.update_layout(barmode='group')
    return apply_dark_theme(fig, height=360, title="💳 融資餘額每日增減變化 (張 - 紅增綠減)")

def plot_norway_pyramid_chart(norway_df, stock_id, stock_name):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if not norway_df.empty:
        fig.add_trace(go.Bar(x=norway_df['Date'], y=norway_df['Total_People'], name="總股東人數(人)", marker_color='#546E7A', opacity=0.8), secondary_y=False)
        fig.add_trace(go.Scatter(x=norway_df['Date'], y=norway_df['Big_Ratio'], name="大股東持股率(%)", mode="lines+markers", line=dict(color="#FF9100", width=2.5), marker=dict(size=5, color="#FFFFFF")), secondary_y=True)
    return apply_dark_theme(fig, height=380, title=f"🏛️ {stock_id} {stock_name} 神秘金字塔 - 總股東人數 vs 大股東持股率")

# -----------------------------------------------------------------------------
# 6. 純同步 REST API 呼叫 Gemini（完美支援 gemini-1.5-flash / gemini-1.5-pro）
# -----------------------------------------------------------------------------
def call_gemini_with_keys_rotation(prompt):
    raw_keys = get_secret("GEMINI_API_KEY", "")
    keys_list = parse_api_keys(raw_keys)
    
    if not keys_list:
        return "⚠️ 系統未偵測到任何 Gemini API Key，請至 Streamlit Secrets 設定 `GEMINI_API_KEY`。"
    
    error_log = []
    models_to_try = ['gemini-1.5-flash', 'gemini-1.5-pro']
    
    for idx, clean_key in enumerate(keys_list):
        for m in models_to_try:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={clean_key}"
                headers = {"Content-Type": "application/json"}
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "systemInstruction": {"parts": [{"text": "你是一位專業的台灣股市分析師，請全程使用繁體中文回答。"}]}
                }
                
                resp = requests.post(url, headers=headers, json=payload, timeout=25)
                if resp.status_code == 200:
                    res_json = resp.json()
                    if 'candidates' in res_json:
                        return res_json['candidates'][0]['content']['parts'][0]['text']
                else:
                    error_log.append(f"Key #{idx+1} ({m}) -> HTTP {resp.status_code}")
            except Exception as e:
                error_log.append(f"Key #{idx+1} ({m}) -> 異常: {e}")
            
    detailed_reasons = " | ".join(error_log)
    return f"❌ **所有 Secrets 中的 API Key 均測試失敗**。\n詳細測試紀錄：\n{detailed_reasons}"

# -----------------------------------------------------------------------------
# 7. 共用診斷渲染引擎
# -----------------------------------------------------------------------------
def render_diagnosis_section(stock_id, stock_name, start_date, end_date, token):
    with st.spinner(f"正在抓取 {stock_id} {stock_name} 的歷史行情與籌碼資料..."):
        s_str = start_date.strftime("%Y-%m-%d")
        e_str = end_date.strftime("%Y-%m-%d")
        b_str = (start_date - timedelta(days=120)).strftime("%Y-%m-%d")
        
        price_df = fetch_stock_history_cached(stock_id, b_str, e_str, token)
        chip_df = fetch_chip_history_cached(stock_id, b_str, e_str, token)
        margin_df = fetch_margin_history_cached(stock_id, b_str, e_str, token)
        norway_df = get_norway_big_shareholders(stock_id)

    if not price_df.empty:
        df_calc = calculate_indicators(price_df)
        
        st.plotly_chart(plot_main_kline_chart(price_df, stock_id, stock_name, s_str))
        st.plotly_chart(plot_chip_chart(chip_df, s_str))
        st.plotly_chart(plot_margin_chart(margin_df, s_str))
        st.plotly_chart(plot_norway_pyramid_chart(norway_df, stock_id, stock_name))

        st.markdown("---")
        st.markdown("## 🤖 AI 多 Agent 投資診斷會議")
        with st.spinner("AI 專家團隊正在透過同步 REST API 連線 Gemini 分析中..."):
            latest = df_calc.iloc[-1]
            prompt = f"針對股票 {stock_id} {stock_name}，收盤價 {latest['Close']} 元組合技術與籌碼面，請給出繁體中文的專業分析與操作建議。"
            ai_result = call_gemini_with_keys_rotation(prompt)
            st.info(ai_result)
    else:
        st.error("❌ 無法取得該股票之歷史K線資料，請檢查 FinMind Token 或股票代碼。")

# -----------------------------------------------------------------------------
# 8. Streamlit 主程式介面與安全狀態初始化
# -----------------------------------------------------------------------------
finmind_token = get_secret("FINMIND_TOKEN", "")
STOCK_DICT = get_all_taiwan_stock_info(finmind_token)

with st.sidebar:
    st.markdown("### ⚡ 系統核心設定")
    app_mode = st.selectbox("選擇系統執行模式：", ["單股與多 Agent 診斷版", "全市場自動選股版"], index=0)
    st.markdown("---")
    st.info("🔒 Gemini API Key 與 FinMind Token 已全數由系統密鑰庫 (Streamlit Secrets) 安全自動載入。")
    st.markdown("---")
    start_date = st.date_input("開始日期", value=datetime.today() - timedelta(days=90))
    end_date = st.date_input("結束日期", value=datetime.today())

# -----------------------------------------------------------------------------
# 9. 頂部四大指數獨立區塊（每 5 秒自動重新整理，零預設假值）
# -----------------------------------------------------------------------------
@st.fragment(run_every=5)
def render_market_ticker():
    market_data = fetch_realtime_market_data(finmind_token)
    m1, m2, m3, m4 = st.columns(4)
    
    def render_taiwan_metric(col, title, d):
        if d:
            val = d["val"]
            change = d["change"]
            
            if change > 0:
                color = "#FF5252"  # 紅色 (漲)
                sign = "+"
            elif change < 0:
                color = "#00E676"  # 綠色 (跌)
                sign = ""
            else:
                color = "#FFFFFF"  # 白色 (平盤)
                sign = ""
                
            col.markdown(f"""
                <div style="background-color: #1E222D; padding: 15px; border-radius: 8px; border: 1px solid {color};">
                    <span style="color: #848E9C; font-size: 14px;">{title}</span><br>
                    <span style="color: {color}; font-size: 26px; font-weight: bold;">{val:,.2f}</span><br>
                    <span style="color: {color}; font-size: 15px; font-weight: bold;">{sign}{change:,.2f}</span>
                </div>
            """, unsafe_allow_html=True)
        else:
            col.markdown(f"""
                <div style="background-color: #1E222D; padding: 15px; border-radius: 8px; border: 1px solid #848E9C;">
                    <span style="color: #848E9C; font-size: 14px;">{title}</span><br>
                    <span style="color: #848E9C; font-size: 26px; font-weight: bold;">--</span><br>
                    <span style="color: #848E9C; font-size: 15px; font-weight: bold;">等待即時數據...</span>
                </div>
            """, unsafe_allow_html=True)

    render_taiwan_metric(m1, "加權指數 (TAIEX)", market_data.get("taiex"))
    render_taiwan_metric(m2, "櫃買指數 (TPEX)", market_data.get("tpex"))
    render_taiwan_metric(m3, "台指近月 (TX)", market_data.get("futures"))
    render_taiwan_metric(m4, "台積電 (2330)", market_data.get("tsmc"))

render_market_ticker()
st.markdown("---")

# -----------------------------------------------------------------------------
# 10. 主頁面模式邏輯
# -----------------------------------------------------------------------------
if app_mode == "全市場自動選股版":
    st.markdown("## 🔍 全市場策略篩選 (Market Screener)")
    strategy_choice = st.radio("選擇篩選策略：", ["短線強勢爆發", "波段多頭排列"], horizontal=True)
    
    if strategy_choice == "短線強勢爆發":
        st.info("📌 **當前篩選條件**：當日漲幅大於 2%、成交量暴增（大於 1,500 張）、且收盤價突破開盤價。")
    else:
        st.info("📌 **當前篩選條件**：中價位穩定、成交量大於 1,000 張、且漲幅保持在 0.5% ~ 3% 之間的穩健多頭標的。")

    if st.button("🚀 開始連線證交所全市場掃描"):
        with st.spinner("正從證交所開放 API 撈取今日全市場資料進行運算..."):
            st.session_state["screener_res"] = run_market_screener(STOCK_DICT, strategy_choice)

    df_res = st.session_state.get("screener_res", pd.DataFrame())
    if not df_res.empty:
        st.success(f"🎉 掃描完成！共挑選出 {len(df_res)} 檔達標個股。")
        st.dataframe(df_res)
        
        st.markdown("### 🎯 從掃描結果啟動深度診斷")
        options = [f"{row['股票代碼']} {row['股票名稱']}" for idx, row in df_res.iterrows()]
        sel = st.selectbox("📌 請選擇一檔標的進行分析：", options)
        if st.button("🚀 啟動此檔個股深度分析"):
            sid = sel.split(" ")[0]
            sname = sel.split(" ")[1]
            render_diagnosis_section(sid, sname, start_date, end_date, finmind_token)
            
else:
    filtered_options = [f"{code} {name}" for code, name in STOCK_DICT.items()]
    default_idx = next((i for i, opt in enumerate(filtered_options) if opt.startswith(st.session_state.get("selected_stock_code", "2356"))), 0)

    selected_stock_raw = st.selectbox("請選擇或搜尋股票：", options=filtered_options, index=default_idx, key="selected_stock_select")
    
    if selected_stock_raw:
        st.session_state["selected_stock_code"] = selected_stock_raw.split(" ")[0]

    stock_id = st.session_state["selected_stock_code"]
    stock_name = STOCK_DICT.get(stock_id, "")

    if st.button("🚀 啟動個股技術、籌碼與 AI 深度診斷"):
        render_diagnosis_section(stock_id, stock_name, start_date, end_date, finmind_token)