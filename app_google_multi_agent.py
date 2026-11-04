import os
import sys
import json
import re
import time as t_time
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from datetime import datetime, timedelta, time
import google.generativeai as genai

# -----------------------------------------------------------------------------
# 智慧金鑰載入機制（同時支援本機 .env 與 Streamlit Cloud Secrets）
# -----------------------------------------------------------------------------
def get_secret(key_name, default=""):
    val = os.getenv(key_name)
    if val:
        return val.strip()
    try:
        if key_name in st.secrets:
            return str(st.secrets[key_name]).strip()
    except Exception:
        pass
    return default

def load_env_file():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
    except ImportError:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip("'").strip('"')

load_env_file()
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

st.set_page_config(
    page_title="TradingAgents - 專業金融量化選股終端",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------------------------------------------------------
# 全局 100% 覆蓋式深色 CSS（徹底清除所有白色殘留區塊並加強標題與文字清晰度）
# -----------------------------------------------------------------------------
st.markdown("""
<style>
    html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stToolbar"] {
        background-color: #0E1015 !important;
        color: #FFFFFF !important;
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
    div[data-baseweb="popover"] div {
        background-color: #1A1E29 !important;
        color: #FFFFFF !important;
    }
    .stAlert {
        background-color: #161A24 !important;
        color: #00E676 !important;
        border: 1px solid #2C3245 !important;
    }
    .stButton>button {
        background: linear-gradient(135deg, #00C853 0%, #009688 100%) !important;
        color: #FFFFFF !important;
        font-weight: bold !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 0.6rem 1.2rem !important;
        box-shadow: 0 4px 12px rgba(0,200,83,0.25) !important;
    }
    .stButton>button:hover {
        box-shadow: 0 0 15px rgba(0, 200, 83, 0.6) !important;
        transform: translateY(-1px);
    }
    
    /* --- 頂部四大指數卡片樣式 (強制正確中文標題與排版) --- */
    .fin-top-card {
        background-color: #161A24 !important;
        border: 1px solid #232836 !important;
        border-radius: 12px !important;
        padding: 12px 14px !important;
        margin-bottom: 12px !important;
        min-height: 85px !important;
    }
    .fin-top-title {
        font-size: 0.9rem !important;
        color: #00E676 !important;
        margin-bottom: 4px !important;
        font-weight: bold !important;
        white-space: nowrap !important;
    }
    .fin-top-val {
        font-size: 1.2rem !important;
        font-weight: bold !important;
    }

    /* --- 徹底消除表格與圖表外框的白色殘留 --- */
    div[data-testid="stDataFrame"] {
        background-color: #161A24 !important;
        border: 1px solid #2C3245 !important;
        border-radius: 10px !important;
        padding: 4px !important;
    }
    table {
        background-color: #161A24 !important;
        color: #FFFFFF !important;
    }
    thead tr th {
        background-color: #1E2330 !important;
        color: #00E676 !important;
        font-weight: bold !important;
        border-bottom: 1px solid #2C3245 !important;
    }
    tbody tr td {
        background-color: #161A24 !important;
        color: #FFFFFF !important;
        border-bottom: 1px solid #232836 !important;
    }
    tbody tr:hover td {
        background-color: #1F2533 !important;
    }

    /* --- 多 Agent 診斷卡片 --- */
    .agent-card {
        background-color: #161A26 !important;
        border: 1px solid #23293A !important;
        border-radius: 14px !important;
        padding: 18px 20px !important;
        margin-bottom: 16px !important;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important;
    }
    .agent-card-header {
        font-size: 1.1rem !important;
        font-weight: 700 !important;
        margin-bottom: 10px !important;
        display: flex !important;
        align-items: center !important;
        gap: 8px !important;
    }
    .header-yellow { color: #FFB300 !important; }
    .header-blue { color: #448AFF !important; }
    .header-purple { color: #B388FF !important; }
    .header-red { color: #FF5252 !important; }
    .header-green { color: #00E676 !important; }
    .agent-card-body {
        font-size: 1rem !important;
        line-height: 1.65 !important;
        color: #E0E6ED !important;
    }

    @media (max-width: 768px) {
        [data-testid="column"] {
            width: 100% !important;
            flex: 100% !important;
            min-width: 100% !important;
            margin-bottom: 1rem;
        }
    }
</style>
""", unsafe_allow_html=True)

def is_market_hours():
    now = datetime.now()
    if now.weekday() >= 5: return False
    return time(9, 0) <= now.time() <= time(13, 30)

def get_dynamic_ttl():
    return 180 if is_market_hours() else 43200

# -----------------------------------------------------------------------------
# 即時市場數據抓取
# -----------------------------------------------------------------------------
@st.cache_data(ttl=60)
def fetch_realtime_market_indices():
    data = {
        "taiex": {"val": 22850.12, "change": "+124.5", "up": True},
        "tpex": {"val": 268.45, "change": "+1.20", "up": True},
        "futures": {"val": 22880.00, "change": "+130.0", "up": True},
        "tsmc": {"val": 1040.00, "change": "+15.0", "up": True}
    }
    try:
        import yfinance as yf
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        
        for key, sym in [("taiex", "^TWII"), ("tpex", "^TWOII"), ("futures", "TX=F"), ("tsmc", "2330.TW")]:
            try:
                t = yf.Ticker(sym, session=session)
                hist = t.history(period="2d")
                if not hist.empty and len(hist) >= 1:
                    p = float(hist['Close'].iloc[-1])
                    prev = float(hist['Close'].iloc[-2]) if len(hist) >= 2 else p
                    diff = p - prev
                    data[key] = {"val": round(p, 2), "change": f"{diff:+.2f}", "up": diff >= 0}
            except Exception:
                pass
    except Exception:
        pass
    return data

# -----------------------------------------------------------------------------
# 1. 資料處理與指標計算
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
    return {}

@st.cache_data(ttl=86400)
def get_norway_big_shareholders(stock_id):
    url = f"https://norway.twsthr.info/StockHolders.aspx?stock={stock_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            tables = pd.read_html(resp.text)
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

def fetch_stock_history_cached(stock_id, start_date, end_date, api_token=""):
    ttl_val = get_dynamic_ttl()
    @st.cache_data(ttl=ttl_val)
    def _fetch_internal(s_id, s_date, e_date, token):
        try:
            from FinMind.data import DataLoader
            fm = DataLoader()
            if token and token.strip():
                try: fm.login_by_token(token.strip())
                except Exception: pass
            df = fm.taiwan_stock_daily(stock_id=s_id, start_date=s_date, end_date=e_date)
            if not df.empty and len(df) > 5: return df
        except Exception: pass

        try:
            import yfinance as yf
            session = requests.Session()
            session.headers.update({"User-Agent": "Mozilla/5.0"})
            ticker = yf.Ticker(f"{s_id}.TW", session=session)
            df_yf = ticker.history(start=s_date, end=e_date)
            if df_yf.empty:
                df_yf = yf.Ticker(f"{s_id}.TWO", session=session).history(start=s_date, end=e_date)
            if not df_yf.empty:
                df_yf = df_yf.reset_index()
                df_yf.rename(columns={'Date': 'date', 'Open': 'open', 'High': 'max', 'Low': 'min', 'Close': 'close', 'Volume': 'Trading_Volume'}, inplace=True)
                df_yf['date'] = df_yf['date'].dt.strftime('%Y-%m-%d')
                return df_yf
        except Exception: pass
        return pd.DataFrame()
    return _fetch_internal(stock_id, start_date, end_date, api_token)

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

    # 布林通道上下軌計算
    std20 = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = (df['20MA'] + (std20 * 2)).round(2)
    df['BB_Lower'] = (df['20MA'] - (std20 * 2)).round(2)

    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

    low_9 = df['Low'].rolling(window=9).min()
    high_9 = df['High'].rolling(window=9).max()
    rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
    rsv = rsv.fillna(50)
    k_list, d_list = [50], [50]
    for i in range(1, len(df)):
        k_list.append(2/3 * k_list[-1] + 1/3 * rsv.iloc[i])
        d_list.append(2/3 * d_list[-1] + 1/3 * k_list[-1])
    df['K'] = pd.Series(k_list, index=df.index).round(2)
    df['D'] = pd.Series(d_list, index=df.index).round(2)

    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = (100 - (100 / (1 + rs))).round(2)
    df['RSI'] = df['RSI'].fillna(50)

    df['OBV'] = (np.sign(df['Close'].diff()) * df['Trading_Volume']).fillna(0).cumsum()
    df['OBV_MA10'] = df['OBV'].rolling(window=10).mean()
    return df

# -----------------------------------------------------------------------------
# 2. 全市場選股邏輯
# -----------------------------------------------------------------------------
def update_daily_market_cache_twse(stock_dict, csv_path, today_str):
    url_twse = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    resp = requests.get(url_twse, timeout=10)
    if resp.status_code == 200:
        raw_data = resp.json()
        records = []
        for item in raw_data:
            sid = str(item.get('Code', '')).strip()
            if len(sid) == 4 and sid.isdigit() and sid in stock_dict:
                try:
                    close_p = float(str(item.get('ClosingPrice', 0)).replace(',', '')) if item.get('ClosingPrice') else 0
                    open_p = float(str(item.get('OpeningPrice', 0)).replace(',', '')) if item.get('OpeningPrice') else close_p
                    high_p = float(str(item.get('HighestPrice', 0)).replace(',', '')) if item.get('HighestPrice') else close_p
                    low_p = float(str(item.get('LowestPrice', 0)).replace(',', '')) if item.get('LowestPrice') else close_p
                    vol = float(str(item.get('TradeVolume', 0)).replace(',', '')) if item.get('TradeVolume') else 0
                    if close_p > 0:
                        records.append({'stock_id': sid, 'date': today_str, 'open': open_p, 'max': high_p, 'min': low_p, 'close': close_p, 'Trading_Volume': vol})
                except ValueError: continue
        if records:
            new_df = pd.DataFrame(records)
            if os.path.exists(csv_path):
                try:
                    old_df = pd.read_csv(csv_path)
                    old_df = old_df[old_df['date'] != today_str]
                    full_df = pd.concat([old_df, new_df], ignore_index=True)
                except Exception: full_df = new_df
            else: full_df = new_df
            full_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            return True
    return False

def run_market_screener(stock_dict, strategy_type, api_token):
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_market_cache.csv")
    today_str = datetime.now().strftime("%Y-%m-%d")
    need_update = not os.path.exists(csv_path) or datetime.fromtimestamp(os.path.getmtime(csv_path)).strftime("%Y-%m-%d") != today_str

    if need_update:
        with st.spinner("🚀 正在連線證交所 API 打包全市場今日最新數據..."):
            success = update_daily_market_cache_twse(stock_dict, csv_path, today_str)
            if success: st.toast("✅ 已成功向證交所打包今日全市場行情！", icon="💾")

    if os.path.exists(csv_path):
        df_all = pd.read_csv(csv_path)
        selected_list = []
        all_market_list = []
        
        for sid, df_raw in df_all.groupby('stock_id'):
            sid_str = str(sid).zfill(4)
            sname = stock_dict.get(sid_str, sid_str)
            if len(df_raw) < 1: continue
            close = df_raw['close'].values
            volume_lots = df_raw['Trading_Volume'].values / 1000.0
            latest_vol = volume_lots[-1]
            
            all_market_list.append({'股票代碼': sid_str, '股票名稱': sname, '收盤價': round(close[-1], 2), '成交量(張)': int(latest_vol)})
            if latest_vol < 50: continue
            
            vol_20ma = np.mean(volume_lots[-20:]) if len(volume_lots) >= 20 else latest_vol
            ma20 = np.mean(close[-20:]) if len(close) >= 20 else close[-1]
            latest_close = close[-1]
            latest_open = df_raw['open'].values[-1]
            
            if strategy_type == "短線強勢爆發":
                if not (latest_close > ma20 and latest_close > latest_open): continue
                if latest_vol < (vol_20ma * 1.5): continue
                selected_list.append({'股票代碼': sid_str, '股票名稱': sname, '收盤價': round(latest_close, 2), '成交量(張)': int(latest_vol), '20日均量': int(vol_20ma)})
            elif strategy_type == "波段多頭排列":
                if len(close) < 20: continue
                ma5 = np.mean(close[-5:]) if len(close) >= 5 else close[-1]
                ma10 = np.mean(close[-10:]) if len(close) >= 10 else close[-1]
                if not (ma5 >= ma10 >= ma20 and latest_close > ma20): continue
                selected_list.append({'股票代碼': sid_str, '股票名稱': sname, '收盤價': round(latest_close, 2), '成交量(張)': int(latest_vol), '20MA均線': round(ma20, 2)})
        
        if selected_list: 
            return pd.DataFrame(selected_list).sort_values(by='成交量(張)', ascending=False), False
        else:
            if all_market_list:
                return pd.DataFrame(all_market_list).sort_values(by='成交量(張)', ascending=False), True
    return pd.DataFrame(), True

# -----------------------------------------------------------------------------
# 3. 多 Agent LLM 呼叫機制 (強化 Key 清洗與驗證)
# -----------------------------------------------------------------------------
PURE_CHINESE_SYSTEM_INSTRUCTION = """
你是一位頂尖的台灣股市分析與投資顧問專家。
【強制規範】：
1. 必須全程 100% 使用繁體中文回答。
2. 絕對禁止輸出任何英文單字、英文說明或思考過程。
3. 嚴禁輸出 Role、Task、Constraint 等英文標籤。
"""

def force_clean_english_lines(text):
    if not text: return ""
    lines = str(text).split('\n')
    valid_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            valid_lines.append("")
            continue
        ascii_chars = sum(1 for c in stripped if ord(c) < 128)
        if (ascii_chars / len(stripped)) > 0.7 and not any(c in stripped for c in ['張', '元', '日', '線', '量', '買', '賣', '個', '股']):
            continue
        if re.match(r'^[\*\-\s]*\b(Role|Task|Constraint|Language|Target|Symbol|User Focus|Input Data)\b', stripped, re.IGNORECASE):
            continue
        valid_lines.append(line)
    result = '\n'.join(valid_lines).strip()
    return result if result else "無分析內容"

def call_llm(gemini_key, prompt):
    clean_key = str(gemini_key).strip().strip("'").strip('"')
    if not clean_key:
        raise RuntimeError("請先在左側設定有效的 Google Gemini API Key！")
    
    genai.configure(api_key=clean_key)
    candidate_models = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-2.0-flash-exp']
    last_exception = None
    for m_name in candidate_models:
        try:
            model = genai.GenerativeModel(m_name, system_instruction=PURE_CHINESE_SYSTEM_INSTRUCTION)
            res = model.generate_content(prompt)
            if res and res.text:
                cleaned = force_clean_english_lines(res.text)
                if cleaned: return cleaned
        except Exception as e:
            last_exception = e
            continue
    raise RuntimeError(f"Gemini API 呼叫失敗（請檢查您的 API Key 是否正確或額度是否足夠）：{last_exception}")

def run_multi_agent_system(stock_id, stock_name, price_df, chip_df, norway_df, gemini_key, user_query):
    df = calculate_indicators(price_df)
    latest = df.iloc[-1]
    
    norway_info = "無神秘金字塔集保資料"
    if not norway_df.empty:
        n_latest = norway_df.iloc[-1]
        norway_info = f"最新集保日期 ({n_latest['Date']})：總股東人數 {int(n_latest['Total_People']):,} 人，千張大股東持股率 {n_latest['Big_Ratio']}%"

    chip_info = "近 15 日三大法人買賣超數據未取得"
    if not chip_df.empty:
        val_col = 'buy_sell' if 'buy_sell' in chip_df.columns else ('buy' if 'buy' in chip_df.columns else chip_df.columns[-1])
        last_15 = chip_df.tail(15)
        f_sum = last_15[last_15['name'].astype(str).str.contains('Foreign', case=False, na=False)][val_col].sum() / 1000
        t_sum = last_15[last_15['name'].astype(str).str.contains('Trust', case=False, na=False)][val_col].sum() / 1000
        chip_info = f"近 15 日外資累計買賣超：{f_sum:+.0f} 張，投信累計買賣超：{t_sum:+.0f} 張"

    data_summary = f"""
    股票：{stock_name} ({stock_id}) | 最新收盤價：{latest['Close']} 元
    均線：5日線={latest['5MA']}元, 10日線={latest['10MA']}元, 20日線={latest['20MA']}元, 60日線={latest['60MA']}元
    指標：RSI={latest['RSI']}, KD=({latest['K']},{latest['D']}), MACD柱狀體={latest['MACD_Hist']:.2f}
    成交量：{latest['Volume_張']:,} 張 (二十日平均量：{latest['Volume_20MA']:,} 張)
    三大法人籌碼：{chip_info}
    大股東集保：{norway_info}
    使用者關注重點：{user_query}
    """

    results = {}
    results['tech_report'] = call_llm(gemini_key, f"請擔任技術面分析師，針對 {stock_id} {stock_name} 進行專業解析（200字以內）：\n{data_summary}")
    results['chip_report'] = call_llm(gemini_key, f"請擔任籌碼面分析師，針對 {stock_id} {stock_name} 進行專業解析（200字以內）：\n{data_summary}")
    results['bull_opinion'] = call_llm(gemini_key, f"請擔任看多研究員，提出強烈看漲理由（200字以內）：\n{data_summary}")
    results['bear_opinion'] = call_llm(gemini_key, f"請擔任看空研究員，提出風險質疑（200字以內）：\n{data_summary}")
    results['risk_report'] = call_llm(gemini_key, f"請擔任風控經理，提供進場區間、停利、停損與倉位建議（200字以內）：\n{data_summary}")
    
    prompt_pm = f"""
    請擔任投資組合經理 (PM) 統整全場討論，給出最終裁決。
    技術報告：{results['tech_report']}
    籌碼報告：{results['chip_report']}
    多方觀點：{results['bull_opinion']}
    空方質疑：{results['bear_opinion']}
    風控建議：{results['risk_report']}
    必須嚴格依照以下格式輸出：
    【PM 最終決策】：(買進 / 觀望 / 賣出)
    【核心理由總結】：(300字以內)
    """
    results['pm_decision'] = call_llm(gemini_key, prompt_pm)
    return results

# -----------------------------------------------------------------------------
# 4. 圖表繪製 (加入布林上下軌與高對比極亮文字)
# -----------------------------------------------------------------------------
def apply_dark_theme(fig, height=450):
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#161A24",
        plot_bgcolor="#161A24",
        height=height,
        margin=dict(l=20, r=20, t=40, b=20),
        hovermode="x unified",
        font=dict(color="#FFFFFF", size=13),
        title_font=dict(color="#00E676", size=15, family="sans-serif"),
        legend=dict(
            bgcolor="rgba(22, 26, 36, 0.95)",
            bordercolor="#00E676",
            borderwidth=1,
            font=dict(color="#FFFFFF", size=12)
        )
    )
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor="#232836", type='category', tickfont=dict(color="#FFFFFF", size=11))
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor="#232836", tickfont=dict(color="#FFFFFF", size=12))
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
    
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['5MA'], name="5MA", line=dict(color="#FFD600", width=1.8)), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['10MA'], name="10MA", line=dict(color="#00E676", width=1.8)), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['20MA'], name="20MA (月線)", line=dict(color="#AA00FF", width=2.2)), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['60MA'], name="60MA (季線)", line=dict(color="#2962FF", width=2.2)), row=1, col=1, secondary_y=False)
    
    # 加入布林通道上下軌
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['BB_Upper'], name="布林上軌", line=dict(color="rgba(0, 230, 118, 0.6)", width=1.2, dash="dash")), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['BB_Lower'], name="布林下軌", line=dict(color="rgba(255, 82, 82, 0.6)", width=1.2, dash="dash")), row=1, col=1, secondary_y=False)
    
    vol_colors = ['rgba(255, 82, 82, 0.4)' if df_price['Close'].iloc[i] >= df_price['Open'].iloc[i] else 'rgba(0, 230, 118, 0.4)' for i in range(len(df_price))]
    fig.add_trace(go.Bar(x=df_price['Date'], y=df_price['Volume_張'], name="成交張數", marker_color=vol_colors), row=1, col=1, secondary_y=True)
    
    max_vol = df_price['Volume_張'].max() if not df_price.empty else 10000
    fig.update_yaxes(title_text="價格 (元)", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="成交量 (張)", range=[0, max_vol * 3.5], row=1, col=1, secondary_y=True, showgrid=False)
    fig.update_xaxes(rangeslider_visible=False)
    fig.update_layout(title=f"📈 {stock_id} {stock_name} 股價 K 線與布林通道技術分析")
    return apply_dark_theme(fig, height=500)

def plot_macd_obv_chart(price_df, display_start_date):
    df_calc = calculate_indicators(price_df)
    df_price = df_calc[df_calc['Date'] >= display_start_date].copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, subplot_titles=("MACD 動能指標", "OBV 能量潮指標"))
    
    fig.add_trace(go.Bar(x=df_price['Date'], y=df_price['MACD_Hist'], name="MACD 柱狀圖", marker_color=np.where(df_price['MACD_Hist'] >= 0, '#FF5252', '#00E676')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['MACD'], name="DIF", line=dict(color="#2962FF", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['MACD_Signal'], name="DEM", line=dict(color="#FF6D00", width=1.5)), row=1, col=1)
    
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['OBV'], name="OBV 能量潮", line=dict(color="#E040FB", width=2)), row=2, col=1)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['OBV_MA10'], name="OBV MA10", line=dict(color="#FFD600", width=1.8)), row=2, col=1)
    return apply_dark_theme(fig, height=420)

def plot_chip_chart(chip_df, display_start_date):
    fig = make_subplots(rows=1, cols=1)
    if not chip_df.empty:
        d_col = 'date' if 'date' in chip_df.columns else ('Date' if 'Date' in chip_df.columns else chip_df.columns[0])
        chip_sub = chip_df[chip_df[d_col] >= display_start_date].copy()
        if 'name' in chip_sub.columns:
            val_col = 'buy_sell' if 'buy_sell' in chip_sub.columns else ('buy' if 'buy' in chip_sub.columns else chip_sub.columns[-1])
            p_foreign = chip_sub[chip_sub['name'].astype(str).str.contains('Foreign', case=False, na=False)].groupby(d_col)[val_col].sum()
            p_trust = chip_sub[chip_sub['name'].astype(str).str.contains('Trust', case=False, na=False)].groupby(d_col)[val_col].sum()
            if not p_foreign.empty: fig.add_trace(go.Bar(x=p_foreign.index, y=(p_foreign/1000).round(0), name="外資(張)", marker_color='#2962FF'))
            if not p_trust.empty: fig.add_trace(go.Bar(x=p_trust.index, y=(p_trust/1000).round(0), name="投信(張)", marker_color='#FF6D00'))
    fig.update_layout(title="🏛️ 三大法人每日買賣超 (張)")
    return apply_dark_theme(fig, height=320)

def plot_margin_chart(margin_df, display_start_date):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if not margin_df.empty:
        d_col = 'date' if 'date' in margin_df.columns else ('Date' if 'Date' in margin_df.columns else margin_df.columns[0])
        margin_sub = margin_df[margin_df[d_col] >= display_start_date].copy()
        col_margin = [c for c in margin_sub.columns if 'MarginPurchase' in c or '融資' in c]
        col_short = [c for c in margin_sub.columns if 'ShortSale' in c or '融券' in c]
        if col_margin:
            m_col = col_margin[0]
            fig.add_trace(go.Scatter(x=margin_sub[d_col], y=margin_sub[m_col], name="融資餘額(張)", line=dict(color="#FF5252", width=2)), secondary_y=False)
        if col_short:
            s_col = col_short[0]
            fig.add_trace(go.Scatter(x=margin_sub[d_col], y=margin_sub[s_col], name="融券餘額(張)", line=dict(color="#00E676", width=2)), secondary_y=True)
    fig.update_layout(title="💳 融資融券餘額變化 (張)")
    return apply_dark_theme(fig, height=320)

def plot_norway_pyramid_chart(norway_df, stock_id, stock_name):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if not norway_df.empty:
        fig.add_trace(go.Bar(x=norway_df['Date'], y=norway_df['Total_People'], name="總股東人數 (人)", marker_color='#455A64', opacity=0.85), secondary_y=False)
        fig.add_trace(go.Scatter(x=norway_df['Date'], y=norway_df['Big_Ratio'], name="大股東持有率 (%)", mode="lines+markers", line=dict(color="#FF6D00", width=2.5), marker=dict(size=6, color="#FFFFFF")), secondary_y=True)
    fig.update_layout(title=f"🏛️ {stock_id} {stock_name} 神秘金字塔 - 總股東人數 vs 大股東持有率")
    return apply_dark_theme(fig, height=360)

# -----------------------------------------------------------------------------
# 5. Streamlit 主 UI 與智慧金鑰初始化
# -----------------------------------------------------------------------------
default_gemini_key = get_secret("GEMINI_API_KEY", "")
default_finmind_token = get_secret("FINMIND_TOKEN", "")

if "gemini_key" not in st.session_state: st.session_state["gemini_key"] = default_gemini_key
if "finmind_token" not in st.session_state: st.session_state["finmind_token"] = default_finmind_token
if "selected_stock_code" not in st.session_state: st.session_state["selected_stock_code"] = "2356"
if "screener_executed" not in st.session_state: st.session_state["screener_executed"] = False

with st.sidebar:
    st.markdown("### ⚡ 系統核心設定")
    app_mode = st.selectbox(
        "選擇系統執行模式：",
        ["啟動全功能版 (全市場自動選股 + 多 Agent 辯論)", "單股診斷版 (指定個股 + 圖表辯論)"],
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
    st.markdown("### 📅 圖表分析區間")
    start_date = st.date_input("開始日期", value=datetime.today() - timedelta(days=90))
    end_date = st.date_input("結束日期", value=datetime.today())
    custom_query = st.text_area("多 Agent 關注重點", value="關注短期突破機會與籌碼大股東動態。")

STOCK_DICT = get_all_taiwan_stock_info(st.session_state["finmind_token"])
active_gemini_key = st.session_state.get("gemini_key") or default_gemini_key

# =============================================================================
# 頂部四塊核心指標看板 (加權指數、櫃買指數、台指期近月、台積電)
# =============================================================================
market_data = fetch_realtime_market_indices()
m_col1, m_col2, m_col3, m_col4 = st.columns(4)

def render_metric_card(col, title, data):
    color = "#00E676" if data["up"] else "#FF5252"
    col.markdown(f"""
    <div class='fin-top-card'>
        <div class='fin-top-title'>{title}</div>
        <div class='fin-top-val' style='color:{color};'>{data['val']:,.2f} <span style='font-size:0.8rem;'>{data['change']}</span></div>
    </div>
    """, unsafe_allow_html=True)

render_metric_card(m_col1, "📊 加權指數 (TAIEX)", market_data["taiex"])
render_metric_card(m_col2, "📈 櫃買指數 (TPEX)", market_data["tpex"])
render_metric_card(m_col3, "⚡ 台指期近月 (TX)", market_data["futures"])
render_metric_card(m_col4, "💎 台積電 (2330)", market_data["tsmc"])

if is_market_hours():
    t_time.sleep(5)
    st.rerun()

if not STOCK_DICT:
    st.error("⚠️ 無法取得台股個股清單！請檢查 `FINMIND_TOKEN` 與網路連線。")

# =============================================================================
# 模式 A：全功能版 (全市場自動選股)
# =============================================================================
if app_mode == "啟動全功能版 (全市場自動選股 + 多 Agent 辯論)":
    st.markdown("## 🔍 全市場策略篩選 (Market Screener)")
    
    col_s1, col_s2, col_s3 = st.columns([2.5, 1, 1])
    with col_s1:
        strategy_choice = st.radio("選擇篩選策略：", ["短線強勢爆發", "波段多頭排列"], horizontal=True)
    with col_s2:
        btn_run_screener = st.button("🚀 開始全市場掃描", type="primary", use_container_width=True)
    with col_s3:
        btn_refresh_cache = st.button("🔄 刷新盤中數據", use_container_width=True)

    if btn_refresh_cache:
        csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_market_cache.csv")
        if os.path.exists(csv_path): os.remove(csv_path)
        st.cache_data.clear()
        st.session_state["screener_executed"] = False
        st.toast("✅ 快取檔案已成功清除！", icon="⚡")
        st.rerun()

    if btn_run_screener:
        if STOCK_DICT:
            screener_res, is_fallback = run_market_screener(STOCK_DICT, strategy_choice, st.session_state["finmind_token"])
            st.session_state["screener_df"] = screener_res
            st.session_state["is_fallback"] = is_fallback
            st.session_state["screener_executed"] = True

    if st.session_state.get("screener_executed", False):
        df_result = st.session_state.get("screener_df", pd.DataFrame())
        is_fallback = st.session_state.get("is_fallback", False)
        
        if not df_result.empty:
            if is_fallback:
                st.info(f"📋 今日無完全符合條件個股，已列出全市場共 {len(df_result)} 檔股票供挑選：")
            else:
                st.success(f"🎉 掃描完成！共找到 {len(df_result)} 檔符合條件個股：")
            
            st.dataframe(df_result.head(100), use_container_width=True)
            if len(df_result) > 100:
                st.caption("ℹ️ 顯示前 100 筆以保持效能流暢。")
            
            screener_list = [f"{row['股票代碼']} {row['股票名稱']}" for _, row in df_result.iterrows()]
            selected_from_screener = st.selectbox("📌 請選擇要進行多 Agent 診斷的個股：", options=screener_list)
            if selected_from_screener:
                st.session_state["selected_stock_code"] = selected_from_screener.split(" ")[0]
                if st.button("🚀 對此選定個股啟動多 Agent 深度診斷", type="primary"):
                    st.session_state["run_diagnosis"] = True
                    st.rerun()
    st.markdown("---")

# =============================================================================
# 模式 B：個股與多 Agent 分析區塊 (單股診斷模式專用)
# =============================================================================
if app_mode == "單股診斷版 (指定個股 + 圖表辯論)":
    filtered_options = [f"{code} {name}" for code, name in STOCK_DICT.items()]
    default_idx = 0
    for idx, opt in enumerate(filtered_options):
        if opt.startswith(st.session_state["selected_stock_code"]):
            default_idx = idx
            break

    st.markdown("### 📊 指定個股深度診斷與多 Agent 辯論")
    col_m1, col_m2 = st.columns([3, 1])
    with col_m1:
        selected_stock_raw = st.selectbox("請選擇或搜尋股票：", options=filtered_options if filtered_options else ["無股票資料"], index=default_idx if filtered_options else 0)
        stock_id = selected_stock_raw.split(" ")[0] if filtered_options else ""
        stock_name = STOCK_DICT.get(stock_id, "") if stock_id else ""
    with col_m2:
        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
        if st.button("🚀 啟動多 Agent 診斷與全圖表", type="primary", use_container_width=True):
            st.session_state["run_diagnosis"] = True
            if stock_id:
                st.session_state["selected_stock_code"] = stock_id

# 取得目前要分析的 stock_id
current_stock_code = st.session_state.get("selected_stock_code", "2356")
current_stock_name = STOCK_DICT.get(current_stock_code, "")

# 執行診斷與圖表渲染
if st.session_state.get("run_diagnosis", False):
    if not current_stock_code:
        st.error("❌ 請先選擇有效的股票代碼！")
    elif not active_gemini_key:
        st.error("❌ 請於左側設定有效的 Google Gemini API Key！")
    else:
        s_date_str = start_date.strftime("%Y-%m-%d")
        e_date_str = end_date.strftime("%Y-%m-%d")
        buffer_start_str = (start_date - timedelta(days=120)).strftime("%Y-%m-%d")
        
        with st.spinner(f"正在抓取 {current_stock_code} {current_stock_name} 量化行情數據..."):
            token = st.session_state["finmind_token"]
            price_df = fetch_stock_history_cached(stock_id=current_stock_code, start_date=buffer_start_str, end_date=e_date_str, api_token=token)
            chip_df = fetch_chip_history_cached(stock_id=current_stock_code, start_date=buffer_start_str, end_date=e_date_str, api_token=token)
            margin_df = fetch_margin_history_cached(stock_id=current_stock_code, start_date=buffer_start_str, end_date=e_date_str, api_token=token)
            norway_df = get_norway_big_shareholders(current_stock_code)

        if not price_df.empty:
            st.plotly_chart(plot_main_kline_chart(price_df, current_stock_code, current_stock_name, s_date_str), use_container_width=True)
            st.plotly_chart(plot_macd_obv_chart(price_df, s_date_str), use_container_width=True)
            col1, col2 = st.columns(2)
            with col1: st.plotly_chart(plot_chip_chart(chip_df, s_date_str), use_container_width=True)
            with col2: st.plotly_chart(plot_margin_chart(margin_df, s_date_str), use_container_width=True)
            st.plotly_chart(plot_norway_pyramid_chart(norway_df, current_stock_code, current_stock_name), use_container_width=True)
            
            with st.spinner("🤝 多 Agent 團隊正在召開投資決策會議..."):
                try:
                    agent_res = run_multi_agent_system(current_stock_code, current_stock_name, price_df, chip_df, norway_df, active_gemini_key, custom_query)
                    
                    st.markdown("---")
                    st.markdown("## 📊 分析結果")
                    col_card1, col_card2 = st.columns(2)
                    with col_card1:
                        st.markdown(f"""<div class="agent-card"><div class="agent-card-header header-yellow">⚡ 技術面分析</div><div class="agent-card-body">{agent_res['tech_report']}</div></div>""", unsafe_allow_html=True)
                    with col_card2:
                        st.markdown(f"""<div class="agent-card"><div class="agent-card-header header-blue">🎯 籌碼面分析</div><div class="agent-card-body">{agent_res['chip_report']}</div></div>""", unsafe_allow_html=True)

                    col_card3, col_card4 = st.columns(2)
                    with col_card3:
                        st.markdown(f"""<div class="agent-card"><div class="agent-card-header header-green">📈 看多觀點</div><div class="agent-card-body">{agent_res['bull_opinion']}</div></div>""", unsafe_allow_html=True)
                    with col_card4:
                        st.markdown(f"""<div class="agent-card"><div class="agent-card-header header-purple">🔮 看空觀點</div><div class="agent-card-body">{agent_res['bear_opinion']}</div></div>""", unsafe_allow_html=True)

                    col_card5, col_card6 = st.columns(2)
                    with col_card5:
                        st.markdown(f"""<div class="agent-card"><div class="agent-card-header header-red">🛑 風險管理與部位配置</div><div class="agent-card-body">{agent_res['risk_report']}</div></div>""", unsafe_allow_html=True)
                    with col_card6:
                        st.markdown(f"""<div class="agent-card" style="border: 1px solid #00E676 !important;"><div class="agent-card-header header-green">🏆 PM 最終決策</div><div class="agent-card-body">{agent_res['pm_decision']}</div></div>""", unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"❌ 執行失敗：{e}")
        else:
            st.error(f"❌ 無法取得 {current_stock_code} 的 K 線價格資料，請檢查 API Token 或網路連線。")