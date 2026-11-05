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
# 1. 系統設定與金鑰解析
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

def is_taiwan_market_open():
    """判斷當前是否處於台股一般交易時段 (08:45 - 13:45) 或期貨夜盤 (15:00 - 05:00)"""
    now = datetime.now()
    # 周六(5)、周日(6) 不運作
    if now.weekday() in [5, 6]:
        return False
    
    t = now.time()
    day_open = datetime.strptime("08:45", "%H:%M").time()
    day_close = datetime.strptime("13:45", "%H:%M").time()
    night_open = datetime.strptime("15:00", "%H:%M").time()
    night_close = datetime.strptime("05:00", "%H:%M").time()
    
    if day_open <= t <= day_close:
        return True
    if t >= night_open or t <= night_close:
        return True
    return False

# -----------------------------------------------------------------------------
# 2. 四大指數與台積電獨立抓取（強效雙重備援，徹底解除崩潰連鎖）
# -----------------------------------------------------------------------------
@st.cache_data(ttl=15)
def fetch_realtime_market_data(api_token=""):
    data = {}
    today_str = datetime.today().strftime("%Y-%m-%d")
    start_str = (datetime.today() - timedelta(days=14)).strftime("%Y-%m-%d")
    
    from FinMind.data import DataLoader
    fm = DataLoader()
    if api_token: 
        try: fm.login_by_token(api_token.strip())
        except Exception: pass

    # 1. 加權指數 (TAIEX) 獨立抓取
    try:
        df_taiex = fm.taiwan_stock_daily(stock_id="TAIEX", start_date=start_str, end_date=today_str)
        if df_taiex.empty:
            df_taiex = fm.taiwan_stock_daily(stock_id="001", start_date=start_str, end_date=today_str)
        if not df_taiex.empty:
            val = float(df_taiex['close'].iloc[-1])
            prev = float(df_taiex['close'].iloc[-2]) if len(df_taiex) > 1 else val
            data["taiex"] = {"val": val, "change": val - prev, "name": "加權指數 (TAIEX)"}
    except Exception:
        try:
            import yfinance as yf
            ticker = yf.Ticker("^TWII")
            hist = ticker.history(period="5d")
            if not hist.empty:
                val = float(hist['Close'].iloc[-1])
                prev = float(hist['Close'].iloc[-2]) if len(hist) > 1 else val
                data["taiex"] = {"val": val, "change": val - prev, "name": "加權指數 (TAIEX)"}
        except Exception: pass

    # 2. 櫃買指數 (TPEX) 獨立抓取
    try:
        df_tpex = fm.taiwan_stock_daily(stock_id="TPEX", start_date=start_str, end_date=today_str)
        if df_tpex.empty:
            df_tpex = fm.taiwan_stock_daily(stock_id="101", start_date=start_str, end_date=today_str)
        if not df_tpex.empty:
            val = float(df_tpex['close'].iloc[-1])
            prev = float(df_tpex['close'].iloc[-2]) if len(df_tpex) > 1 else val
            data["tpex"] = {"val": val, "change": val - prev, "name": "櫃買指數 (TPEX)"}
    except Exception:
        try:
            import yfinance as yf
            ticker = yf.Ticker("^TWOII")
            hist = ticker.history(period="5d")
            if not hist.empty:
                val = float(hist['Close'].iloc[-1])
                prev = float(hist['Close'].iloc[-2]) if len(hist) > 1 else val
                data["tpex"] = {"val": val, "change": val - prev, "name": "櫃買指數 (TPEX)"}
        except Exception: pass

    # 3. 台指期近月 (TX) 獨立抓取
    try:
        df_futures = fm.taiwan_futures_daily(start_date=start_str, end_date=today_str)
        if not df_futures.empty:
            col_id = 'futures_id' if 'futures_id' in df_futures.columns else 'stock_id'
            if col_id in df_futures.columns:
                df_tx = df_futures[df_futures[col_id] == "TX"].copy()
                if not df_tx.empty:
                    latest_date = df_tx['date'].max()
                    df_tx_latest = df_tx[df_tx['date'] == latest_date]
                    if not df_tx_latest.empty:
                        val = float(df_tx_latest['close'].iloc[0])
                        prev = float(df_tx_latest['spread'].iloc[0]) if 'spread' in df_tx_latest.columns else 0.0
                        data["futures"] = {"val": val, "change": prev, "name": "台指近月 (TX)"}
    except Exception: pass

    # 4. 台積電 (2330) 獨立抓取
    try:
        df_tsmc = fm.taiwan_stock_daily(stock_id="2330", start_date=start_str, end_date=today_str)
        if not df_tsmc.empty:
            val = float(df_tsmc['close'].iloc[-1])
            prev = float(df_tsmc['close'].iloc[-2]) if len(df_tsmc) > 1 else val
            data["tsmc"] = {"val": val, "change": val - prev, "name": "台積電 (2330)"}
    except Exception:
        try:
            import yfinance as yf
            ticker = yf.Ticker("2330.TW")
            hist = ticker.history(period="5d")
            if not hist.empty:
                val = float(hist['Close'].iloc[-1])
                prev = float(hist['Close'].iloc[-2]) if len(hist) > 1 else val
                data["tsmc"] = {"val": val, "change": val - prev, "name": "台積電 (2330)"}
        except Exception: pass

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
# 6. TradingAgents 多 Agent 模型對話與 JSON 格式化裁決引擎
# -----------------------------------------------------------------------------
def call_trading_agents_team(stock_id, stock_name, latest_price, tech_summary, chip_summary):
    raw_keys = get_secret("GEMINI_API_KEY", "")
    keys_list = parse_api_keys(raw_keys)
    
    if not keys_list:
        return None, "⚠️ 系統未偵測到任何 Gemini API Key，請至 Streamlit Secrets 設定 `GEMINI_API_KEY`。"
    
    prompt = f"""
你是由 TauricResearch/TradingAgents 密集的 AI 多智能體團隊，正在為台股【{stock_id} {stock_name}】（當前收盤價：{latest_price} 元）進行深度投資裁決會議。
請根據以下數據進行內部團隊辯論與風控審核：
【技術面數據】：{tech_summary}
【籌碼與大股東數據】：{chip_summary}

請嚴格輸出一個符合 JSON 格式的字典（不要帶額外的 Markdown codeblock 說明），格式包含以下 Key：
{{
  "volume_price_volatility": "成交量與價格波動分析說明...",
  "market_stage": "目前市場階段評估 (例如：拉回整理、多頭發散、高檔震盪)...",
  "key_price_levels": "關鍵價格門檻與支撐壓力位...",
  "signal_analysis": "技術指標 (RSI/MACD/KD) 訊號評估...",
  "pattern_recognition": "K線圖表模式與型態識別...",
  "trend_strength": "趨勢強度與動能綜合評估...",
  "bull_bear_debate": "看多研究員 vs 看空研究員 辯論焦點說明...",
  "trader_decision": "交易員最終買賣建議與推薦部位比例...",
  "risk_management": "風控團隊與投資組合經理最終核准/否決評估、停損價與目標價設定..."
}}
"""
    models_to_try = ['gemini-3.8-flash', 'gemini-2.5-flash', 'gemini-2.0-flash-exp', 'gemini-1.5-flash-latest']
    
    for idx, clean_key in enumerate(keys_list):
        for m in models_to_try:
            try:
                from google import genai
                client = genai.Client(api_key=clean_key)
                response = client.models.generate_content(
                    model=m,
                    contents=prompt
                )
                if response and response.text:
                    txt = response.text.strip()
                    if txt.startswith("```json"): txt = txt[7:]
                    if txt.startswith("```"): txt = txt[3:]
                    if txt.endswith("```"): txt = txt[:-3]
                    try:
                        res_json = json.loads(txt.strip())
                        return res_json, None
                    except Exception:
                        return {"volume_price_volatility": txt}, None
            except Exception:
                try:
                    url = f"[https://generativelanguage.googleapis.com/v1beta/models/](https://generativelanguage.googleapis.com/v1beta/models/){m}:generateContent?key={clean_key}"
                    headers = {"Content-Type": "application/json"}
                    payload = {"contents": [{"parts": [{"text": prompt}]}]}
                    resp = requests.post(url, headers=headers, json=payload, timeout=15)
                    if resp.status_code == 200:
                        res_json = resp.json()
                        if 'candidates' in res_json:
                            txt = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
                            if txt.startswith("```json"): txt = txt[7:]
                            if txt.startswith("```"): txt = txt[3:]
                            if txt.endswith("```"): txt = txt[:-3]
                            try:
                                parsed = json.loads(txt.strip())
                                return parsed, None
                            except Exception:
                                return {"volume_price_volatility": txt}, None
                except Exception: pass

    return None, "❌ 所有 Secrets 中的 API Key 均連線失敗。"

def render_trading_agents_cards(res):
    """將 TradingAgents 多 Agent 裁決結果渲染為 image_a7c469.jpg 風格的深色卡片」"""
    if isinstance(res, str):
        st.info(res)
        return

    col1, col2 = st.columns(2)
    
    card_style = """
        background-color: #1A1E29; 
        border: 1px solid #2A2E3D; 
        border-radius: 12px; 
        padding: 16px; 
        margin-bottom: 16px;
        color: #E0E0E0;
    """
    
    with col1:
        # 卡片 1: 成交量和價格波動
        st.markdown(f"""
            <div style="{card_style}">
                <div style="color: #FFB74D; font-weight: bold; font-size: 16px; margin-bottom: 8px;">⚡ 成交量和價格波動</div>
                <div style="font-size: 14px; line-height: 1.6;">{res.get('volume_price_volatility', '數據載入中...')}</div>
            </div>
        """, unsafe_allow_html=True)
        
        # 卡片 2: 目前市場階段
        st.markdown(f"""
            <div style="{card_style}">
                <div style="color: #64B5F6; font-weight: bold; font-size: 16px; margin-bottom: 8px;">🧭 目前市場階段</div>
                <div style="font-size: 14px; line-height: 1.6;">{res.get('market_stage', '數據載入中...')}</div>
            </div>
        """, unsafe_allow_html=True)

        # 卡片 3: 關鍵價格門檻
        st.markdown(f"""
            <div style="{card_style}">
                <div style="color: #81C784; font-weight: bold; font-size: 16px; margin-bottom: 8px;">🚪 關鍵價格門檻</div>
                <div style="font-size: 14px; line-height: 1.6;">{res.get('key_price_levels', '數據載入中...')}</div>
            </div>
        """, unsafe_allow_html=True)

        # 卡片 4: 看多 vs 看空團隊辯論 (TradingAgents 特色)
        st.markdown(f"""
            <div style="{card_style}">
                <div style="color: #BA68C8; font-weight: bold; font-size: 16px; margin-bottom: 8px;">⚔️ 多空研究員正反辯論</div>
                <div style="font-size: 14px; line-height: 1.6;">{res.get('bull_bear_debate', '數據載入中...')}</div>
            </div>
        """, unsafe_allow_html=True)

    with col2:
        # 卡片 5: 訊號分析
        st.markdown(f"""
            <div style="{card_style}">
                <div style="color: #FF8A65; font-weight: bold; font-size: 16px; margin-bottom: 8px;">🎯 訊號分析 (RSI/MACD)</div>
                <div style="font-size: 14px; line-height: 1.6;">{res.get('signal_analysis', '數據載入中...')}</div>
            </div>
        """, unsafe_allow_html=True)

        # 卡片 6: 圖表模式識別
        st.markdown(f"""
            <div style="{card_style}">
                <div style="color: #4DD0E1; font-weight: bold; font-size: 16px; margin-bottom: 8px;">📊 圖表模式識別</div>
                <div style="font-size: 14px; line-height: 1.6;">{res.get('pattern_recognition', '數據載入中...')}</div>
            </div>
        """, unsafe_allow_html=True)

        # 卡片 7: 趨勢強度評估
        st.markdown(f"""
            <div style="{card_style}">
                <div style="color: #FFD54F; font-weight: bold; font-size: 16px; margin-bottom: 8px;">⚡ 趨勢強度評估</div>
                <div style="font-size: 14px; line-height: 1.6;">{res.get('trend_strength', '數據載入中...')}</div>
            </div>
        """, unsafe_allow_html=True)

        # 卡片 8: 交易員與風控團隊最終裁決 (TradingAgents 特色)
        st.markdown(f"""
            <div style="{card_style}; border: 1px solid #FF5252;">
                <div style="color: #FF5252; font-weight: bold; font-size: 16px; margin-bottom: 8px;">🛡️ 風險管理與交易員裁決</div>
                <div style="font-size: 14px; line-height: 1.6;">
                    <b>交易員決策：</b>{res.get('trader_decision', '')}<br><br>
                    <b>風控團隊審核：</b>{res.get('risk_management', '')}
                </div>
            </div>
        """, unsafe_allow_html=True)

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
        st.markdown("## 🤖 TradingAgents 多 Agent 投資診斷會議與終極裁決")
        with st.spinner("TradingAgents 團隊（技術員/多空研究員/交易員/風控經理）開會辯論中..."):
            latest = df_calc.iloc[-1]
            tech_info = f"收盤價:{latest['Close']}, 5MA:{latest['5MA']}, 20MA:{latest['20MA']}, 布林上軌:{latest['BB_Upper']}, 布林下軌:{latest['BB_Lower']}"
            chip_info = f"三大法人與融資資料長度: {len(chip_df)}天"
            
            ai_res, err = call_trading_agents_team(stock_id, stock_name, latest['Close'], tech_info, chip_info)
            if err:
                st.error(err)
            else:
                render_trading_agents_cards(ai_res)
    else:
        st.error("❌ 無法取得該股票之歷史K線資料，請檢查 FinMind Token 或股票代碼。")

# -----------------------------------------------------------------------------
# 8. Streamlit 主程式介面
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
# 9. 頂部四大指數獨立區塊（僅在盤中交易時間 5 秒自動重新整理）
# -----------------------------------------------------------------------------
run_interval = 5 if is_taiwan_market_open() else None

@st.fragment(run_every=run_interval)
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
                    <span style="color: #848E9C; font-size: 15px; font-weight: bold;">數據載入中...</span>
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