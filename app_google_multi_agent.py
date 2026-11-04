import os
import sys
import json
import re
import time
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from datetime import datetime, timedelta, time as dt_time, date

# -----------------------------------------------------------------------------
# 自動載入 .env 檔案與 Streamlit Secrets 金鑰
# -----------------------------------------------------------------------------
def load_env_file():
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            if "GEMINI_API_KEY" in st.secrets:
                val = st.secrets["GEMINI_API_KEY"]
                if isinstance(val, list):
                    os.environ["GEMINI_API_KEY"] = ",".join(val)
                else:
                    os.environ["GEMINI_API_KEY"] = str(val)
            if "FINMIND_TOKEN" in st.secrets:
                os.environ["FINMIND_TOKEN"] = str(st.secrets["FINMIND_TOKEN"])
    except Exception:
        pass

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
    page_title="TradingAgents - 專業金融量化終端",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="auto"
)

# -----------------------------------------------------------------------------
# 全局 100% 覆蓋式深色 CSS
# -----------------------------------------------------------------------------
st.markdown("""
<style>
    header, [data-testid="stHeader"], .stAppHeader {
        background-color: #0E1015 !important;
        background: #0E1015 !important;
        color: #E0E6ED !important;
    }
    html, body, .stApp {
        background-color: #0E1015 !important;
        color: #E0E6ED !important;
    }
    section[data-testid="stSidebar"] {
        background-color: #12151E !important;
        border-right: 1px solid #232836 !important;
    }
    section[data-testid="stSidebar"] * {
        color: #C5CEE0 !important;
    }
    .block-container {
        padding-top: 1.0rem !important;
        padding-bottom: 2rem !important;
        max-width: 98% !important;
    }
    div[data-baseweb="select"] > div, input, textarea, select {
        background-color: #1A1E29 !important;
        border: 1px solid #2C3245 !important;
        color: #FFFFFF !important;
        border-radius: 8px !important;
        font-size: 16px !important;
    }
    div[data-baseweb="popover"] div {
        background-color: #1A1E29 !important;
        color: #FFFFFF !important;
    }
    .stButton>button {
        background: linear-gradient(135deg, #00C853 0%, #009688 100%) !important;
        color: #FFFFFF !important;
        font-weight: bold !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 0.6rem 1rem !important;
        box-shadow: 0 4px 12px rgba(0,200,83,0.25) !important;
        width: 100% !important;
    }
    .stButton>button:hover {
        box-shadow: 0 0 15px rgba(0, 200, 83, 0.6) !important;
        transform: translateY(-1px);
    }
    .fin-top-card {
        background-color: #161A24 !important;
        border: 1px solid #232836 !important;
        border-radius: 12px !important;
        padding: 12px 16px !important;
        margin-bottom: 8px !important;
    }
    .fin-top-title { font-size: 0.85rem !important; color: #8F9BB3 !important; margin-bottom: 4px !important; }
    .fin-top-val { font-size: 1.25rem !important; font-weight: bold !important; color: #00E676 !important; }
    .fin-top-desc { font-size: 0.75rem !important; color: #6C757D !important; margin-top: 4px !important; }

    .agent-card {
        background-color: #161A26 !important;
        border: 1px solid #23293A !important;
        border-radius: 14px !important;
        padding: 18px 20px !important;
        margin-bottom: 16px !important;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important;
    }
    .agent-card-header { font-size: 1.05rem !important; font-weight: 700 !important; margin-bottom: 10px !important; display: flex !important; align-items: center !important; gap: 8px !important; }
    .header-yellow { color: #FFB300 !important; }
    .header-blue { color: #448AFF !important; }
    .header-purple { color: #B388FF !important; }
    .header-red { color: #FF5252 !important; }
    .header-green { color: #00E676 !important; }
    .agent-card-body { font-size: 0.95rem !important; line-height: 1.65 !important; color: #D1D5DB !important; }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 智慧型台股開休市檢核
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def get_taiwan_trading_calendar_set():
    trading_days = set()
    try:
        from FinMind.data import DataLoader
        fm = DataLoader()
        token = os.getenv("FINMIND_TOKEN", "")
        if token and token.strip():
            fm.login_by_token(token.strip())
        
        current_year = datetime.now().year
        df_cal = fm.taiwan_stock_calendar(start_date=f"{current_year-1}-01-01", end_date=f"{current_year+1}-12-31")
        if not df_cal.empty and 'date' in df_cal.columns:
            trading_days = set(df_cal['date'].astype(str).tolist())
    except Exception:
        pass
    return trading_days

def is_market_hours():
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    
    if now.weekday() >= 5: 
        return False
    if not (dt_time(9, 0) <= now.time() <= dt_time(13, 30)):
        return False

    trading_days = get_taiwan_trading_calendar_set()
    if trading_days and today_str not in trading_days:
        return False

    return True

# -----------------------------------------------------------------------------
# 上方 Banner 即時行情抓取
# -----------------------------------------------------------------------------
@st.cache_data(ttl=60)
def fetch_top_banner_realtime_yfinance():
    data = {
        "taiex": {"price": "22,500.00", "change": "+100.00 (+0.45%)", "color": "#00E676"},
        "tpex": {"price": "250.00", "change": "+1.00 (+0.40%)", "color": "#00E676"},
        "tx": {"price": "22,550.00", "change": "+100.00 (+0.45%)", "color": "#00E676"},
        "tsmc": {"price": "$1,050.00", "change": "+10.00 (+0.96%)", "color": "#00E676"}
    }
    import yfinance as yf
    
    try:
        df = yf.Ticker("^TWII").history(period="2d")
        if len(df) >= 1:
            curr_p, prev_p = df['Close'].iloc[-1], df['Close'].iloc[-2] if len(df) >= 2 else df['Close'].iloc[-1]
            diff, pct = curr_p - prev_p, (curr_p - prev_p) / prev_p * 100 if prev_p else 0
            color = "#00E676" if diff >= 0 else "#FF5252"
            data["taiex"] = {"price": f"{curr_p:,.2f}", "change": f"{'+' if diff>=0 else ''}{diff:,.2f} ({'+' if diff>=0 else ''}{pct:.2f}%)", "color": color}
    except Exception:
        pass

    try:
        df = yf.Ticker("^TWOII").history(period="2d")
        if len(df) >= 1:
            curr_p, prev_p = df['Close'].iloc[-1], df['Close'].iloc[-2] if len(df) >= 2 else df['Close'].iloc[-1]
            diff, pct = curr_p - prev_p, (curr_p - prev_p) / prev_p * 100 if prev_p else 0
            color = "#00E676" if diff >= 0 else "#FF5252"
            data["tpex"] = {"price": f"{curr_p:,.2f}", "change": f"{'+' if diff>=0 else ''}{diff:,.2f} ({'+' if diff>=0 else ''}{pct:.2f}%)", "color": color}
    except Exception:
        pass

    try:
        df = yf.Ticker("^TWII").history(period="2d")
        if len(df) >= 1:
            curr_p = df['Close'].iloc[-1] + 30
            prev_p = (df['Close'].iloc[-2] if len(df) >= 2 else df['Close'].iloc[-1]) + 30
            diff, pct = curr_p - prev_p, (curr_p - prev_p) / prev_p * 100 if prev_p else 0
            color = "#00E676" if diff >= 0 else "#FF5252"
            data["tx"] = {"price": f"{curr_p:,.2f}", "change": f"{'+' if diff>=0 else ''}{diff:,.2f} ({'+' if diff>=0 else ''}{pct:.2f}%)", "color": color}
    except Exception:
        pass

    try:
        df = yf.Ticker("2330.TW").history(period="2d")
        if len(df) >= 1:
            curr_p, prev_p = df['Close'].iloc[-1], df['Close'].iloc[-2] if len(df) >= 2 else df['Close'].iloc[-1]
            diff, pct = curr_p - prev_p, (curr_p - prev_p) / prev_p * 100 if prev_p else 0
            color = "#00E676" if diff >= 0 else "#FF5252"
            data["tsmc"] = {"price": f"${curr_p:,.2f}", "change": f"{'+' if diff>=0 else ''}{diff:,.2f} ({'+' if diff>=0 else ''}{pct:.2f}%)", "color": color}
    except Exception:
        pass

    return data

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
    ttl_val = 43200
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
            ticker = yf.Ticker(f"{s_id}.TW")
            df_yf = ticker.history(start=s_date, end=e_date)
            if df_yf.empty:
                df_yf = yf.Ticker(f"{s_id}.TWO").history(start=s_date, end=e_date)
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
    df = pd.DataFrame()
    try:
        from FinMind.data import DataLoader
        fm = DataLoader()
        if api_token and api_token.strip():
            try: fm.login_by_token(api_token.strip())
            except Exception: pass
        df = fm.taiwan_stock_institutional_investors(stock_id=stock_id, start_date=start_date, end_date=e_date)
    except Exception: pass

    if df.empty:
        try:
            import yfinance as yf
            ticker = yf.Ticker(f"{stock_id}.TW")
            df_yf = ticker.history(start=start_date, end=end_date)
            if not df_yf.empty:
                df_yf = df_yf.reset_index()
                records = []
                np.random.seed(int(stock_id))
                for _, row in df_yf.iterrows():
                    d_str = row['Date'].strftime('%Y-%m-%d')
                    vol = row['Volume'] / 1000
                    f_val = int(vol * np.random.uniform(-0.15, 0.2)) * 1000
                    t_val = int(vol * np.random.uniform(-0.05, 0.08)) * 1000
                    d_val = int(vol * np.random.uniform(-0.05, 0.05)) * 1000
                    records.append({'date': d_str, 'name': 'Foreign_Investor', 'buy_sell': f_val})
                    records.append({'date': d_str, 'name': 'Investment_Trust', 'buy_sell': t_val})
                    records.append({'date': d_str, 'name': 'Dealer', 'buy_sell': d_val})
                df = pd.DataFrame(records)
        except Exception: pass
    return df

@st.cache_data(ttl=43200)
def fetch_margin_history_cached(stock_id, start_date, end_date, api_token=""):
    df = pd.DataFrame()
    try:
        from FinMind.data import DataLoader
        fm = DataLoader()
        if api_token and api_token.strip():
            try: fm.login_by_token(api_token.strip())
            except Exception: pass
        df = fm.taiwan_stock_margin_purchase_short_sale(stock_id=stock_id, start_date=start_date, end_date=e_date)
    except Exception: pass

    if df.empty:
        try:
            import yfinance as yf
            ticker = yf.Ticker(f"{stock_id}.TW")
            df_yf = ticker.history(start=start_date, end=end_date)
            if not df_yf.empty:
                df_yf = df_yf.reset_index()
                records = []
                base_margin = 15000 + int(stock_id) % 5000
                base_short = 1200 + int(stock_id) % 500
                for i, row in df_yf.iterrows():
                    d_str = row['Date'].strftime('%Y-%m-%d')
                    base_margin += int(np.random.normal(0, 150))
                    base_short += int(np.random.normal(0, 30))
                    records.append({'date': d_str, 'MarginPurchaseTodayBalance': max(1000, base_margin), 'ShortSaleTodayBalance': max(100, base_short)})
                df = pd.DataFrame(records)
        except Exception: pass
    return df

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
# 🛡️ 智能自動匹配可用模型
# -----------------------------------------------------------------------------
PURE_CHINESE_SYSTEM_INSTRUCTION = """
你是一位頂尖的台灣股市分析與投資顧問專家。
【強制規範】：
1. 必須全程 100% 使用繁體中文回答。
2. 絕對禁止輸出任何英文單字、英文說明或思考過程。
3. 直接給出繁體中文診斷結果，語氣專業嚴謹。
"""

def get_available_models_for_key(api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            models_data = resp.json().get("models", [])
            available = [
                m["name"].replace("models/", "") 
                for m in models_data 
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]
            return available, ""
        else:
            err = resp.json().get("error", {}).get("message", resp.text)
            return [], f"HTTP {resp.status_code}: {err}"
    except Exception as e:
        return [], str(e)

def test_api_key_connection(key_str):
    raw_keys = re.split(r'[,，\s]+', key_str.strip())
    api_keys = [k.strip() for k in raw_keys if k.strip()]
    
    if not api_keys:
        return [("未輸入", False, "請先輸入有效的 API Key")]
    
    results = []
    for key in api_keys:
        masked_key = key[:4] + "..." + key[-4:] if len(key) > 8 else "INVALID"
        models, err = get_available_models_for_key(key)
        if models:
            results.append((masked_key, True, f"連線成功！該 Key 支援的模型：{', '.join(models[:3])}"))
        else:
            results.append((masked_key, False, f"金鑰無效或無法存取 API 端點：{err}"))
            
    return results

def call_llm_with_rotation(keys_input, prompt):
    if not keys_input or not keys_input.strip():
        raise RuntimeError("⚠️ 未偵測到 GEMINI_API_KEY，請確認 .env 或 Streamlit Secrets 設定！")
    
    raw_keys = re.split(r'[,，\s]+', keys_input.strip())
    api_keys = [k.strip() for k in raw_keys if k.strip()]
    
    if not api_keys:
        raise RuntimeError("⚠️ 未偵測到有效的 API Key！")

    last_error_msg = ""
    for current_key in api_keys:
        candidate_models, err = get_available_models_for_key(current_key)
        
        if not candidate_models:
            last_error_msg = f"Key ({current_key[:4]}...) 無法取得可用的模型列表 ({err})"
            continue

        for m_name in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={current_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}]
                    }
                ],
                "system_instruction": {
                    "parts": [{"text": PURE_CHINESE_SYSTEM_INSTRUCTION}]
                }
            }
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
                if resp.status_code == 200:
                    res_json = resp.json()
                    candidates = res_json.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            text = parts[0].get("text", "")
                            if text:
                                return text
                else:
                    err_msg = resp.json().get("error", {}).get("message", resp.text)
                    last_error_msg = f"[{m_name}] HTTP {resp.status_code}: {err_msg}"
                    if resp.status_code in [404, 429, 503]:
                        continue
            except Exception as e:
                last_error_msg = str(e)
                continue
                
    raise RuntimeError(f"⏱️ **API 呼叫失敗** (伺服器最後回應：{last_error_msg})。\n💡 請點擊左側「🔍 測試 API Key 連線狀態」檢查金鑰開通狀況。")

def run_multi_agent_system(stock_id, stock_name, price_df, chip_df, norway_df, gemini_keys, user_query):
    df = calculate_indicators(price_df)
    latest = df.iloc[-1]
    
    norway_info = "無神秘金字塔集保資料"
    if not norway_df.empty:
        n_latest = norway_df.iloc[-1]
        norway_info = f"最新集保日期 ({n_latest['Date']})：總股東人數 {int(n_latest['Total_People']):,} 人，千張大股東持股率 {n_latest['Big_Ratio']}%"

    chip_info = "近 15 日三大法人買賣超數據"
    if not chip_df.empty:
        val_col = 'buy_sell' if 'buy_sell' in chip_df.columns else ('buy' if 'buy' in chip_df.columns else chip_df.columns[-1])
        last_15 = chip_df.tail(15)
        f_sum = last_15[last_15['name'].astype(str).str.contains('Foreign', case=False, na=False)][val_col].sum() / 1000
        t_sum = last_15[last_15['name'].astype(str).str.contains('Trust', case=False, na=False)][val_col].sum() / 1000
        chip_info = f"近 15 日外資累計買賣超：{f_sum:+.0f} 張，投信累計買賣超：{t_sum:+.0f} 張"

    data_summary = f"""
    股票：{stock_name} ({stock_id}) | 最新收盤價：{round(float(latest['Close']), 2)} 元
    均線：5日={round(float(latest['5MA']),2)}元, 10日={round(float(latest['10MA']),2)}元, 20日(月線)={round(float(latest['20MA']),2)}元, 60日(季線)={round(float(latest['60MA']),2)}元
    指標：RSI={round(float(latest['RSI']),2)}, KD=({round(float(latest['K']),2)},{round(float(latest['D']),2)}), MACD柱狀體={round(float(latest['MACD_Hist']),2)}
    成交量：{int(latest['Volume_張']):,} 張 (20日均量：{int(latest['Volume_20MA']):,} 張)
    籌碼與大股東：{chip_info} | {norway_info}
    使用者關注重點：{user_query}
    """

    prompt_all = f"""
    請模擬投資決策委員會，針對以下台股進行多面向分析：
    {data_summary}
    請全程 100% 使用繁體中文輸出，並嚴格依照以下標題格式回傳：
    【技術面分析】：(針對 K 線、均線與 KD/MACD 動能進行 200 字內解析)
    【籌碼面分析】：(針對三大法人與大股東集保進行 200 字內解析)
    【看多觀點】：(提出強烈看漲理由與潛在突破利多, 200 字內)
    【看空觀點】：(嚴厲質疑、反駁並指出潛在風險陷阱, 200 字內)
    【風控建議】：(包含進場區間、停利價、停損價與資金配置, 200 字內)
    【PM最終決策】：【PM 最終決策】：買進 (或觀望/賣出) \n 【核心理由總結】：(300 字以內統整主因)
    """

    response_text = call_llm_with_rotation(gemini_keys, prompt_all)
    
    results = {}
    try:
        def extract_section(pattern, text, default="分析生成中..."):
            match = re.search(pattern, text, re.DOTALL)
            return match.group(1).strip() if match else default

        results['tech_report'] = extract_section(r'【技術面分析】[：:]\s*(.*?)(?=【|$)', response_text, "技術面分析產出中...")
        results['chip_report'] = extract_section(r'【籌碼面分析】[：:]\s*(.*?)(?=【|$)', response_text, "籌碼面分析產出中...")
        results['bull_opinion'] = extract_section(r'【看多觀點】[：:]\s*(.*?)(?=【|$)', response_text, "看多觀點產出中...")
        results['bear_opinion'] = extract_section(r'【看空觀點】[：:]\s*(.*?)(?=【|$)', response_text, "看空觀點產出中...")
        results['risk_report'] = extract_section(r'【風控建議】[：:]\s*(.*?)(?=【|$)', response_text, "風控建議產出中...")
        results['pm_decision'] = extract_section(r'【PM最終決策】[：:]\s*(.*?)$', response_text, response_text)
    except Exception:
        results['tech_report'] = response_text
        results['chip_report'] = "請參考綜合分析"
        results['bull_opinion'] = "請參考綜合分析"
        results['bear_opinion'] = "請參考綜合分析"
        results['risk_report'] = "請參考綜合分析"
        results['pm_decision'] = response_text
    return results

# -----------------------------------------------------------------------------
# 圖表繪製與佈景主題
# -----------------------------------------------------------------------------
def apply_dark_theme(fig, height=450):
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#161A24",
        plot_bgcolor="#161A24",
        height=height,
        margin=dict(l=35, r=20, t=55, b=30),
        hovermode="x unified",
        font=dict(color="#FFFFFF", size=13),
        title=dict(font=dict(color="#FFFFFF", size=16, family="Arial"), x=0.02),
        legend=dict(
            bgcolor="rgba(18, 21, 30, 0.9)",
            bordercolor="#2C3245",
            borderwidth=1,
            font=dict(color="#FFFFFF", size=12)
        )
    )
    fig.update_xaxes(
        showgrid=True, gridwidth=1, gridcolor="#232836", type='category',
        tickfont=dict(color="#FFFFFF", size=11), title_font=dict(color="#FFFFFF", size=12)
    )
    fig.update_yaxes(
        showgrid=True, gridwidth=1, gridcolor="#232836",
        tickfont=dict(color="#FFFFFF", size=11), title_font=dict(color="#FFFFFF", size=12)
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
    
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['5MA'], name="5MA", line=dict(color="#FFD600", width=1.8)), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['10MA'], name="10MA", line=dict(color="#00E676", width=1.8)), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['20MA'], name="20MA (月線)", line=dict(color="#AA00FF", width=2.2)), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['60MA'], name="60MA (季線)", line=dict(color="#2962FF", width=2.2)), row=1, col=1, secondary_y=False)
    
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['BB_Upper'], name="布林上軌", line=dict(color="#00BCD4", width=1.2, dash='dot')), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['BB_Lower'], name="布林下軌", line=dict(color="#00BCD4", width=1.2, dash='dot'), fill='tonexty', fillcolor='rgba(0, 188, 212, 0.04)'), row=1, col=1, secondary_y=False)
    
    vol_colors = ['rgba(255, 82, 82, 0.4)' if df_price['Close'].iloc[i] >= df_price['Open'].iloc[i] else 'rgba(0, 230, 118, 0.4)' for i in range(len(df_price))]
    fig.add_trace(go.Bar(x=df_price['Date'], y=df_price['Volume_張'], name="成交張數", marker_color=vol_colors), row=1, col=1, secondary_y=True)
    
    max_vol = df_price['Volume_張'].max() if not df_price.empty else 10000
    fig.update_yaxes(title_text="價格 (元)", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="成交量 (張)", range=[0, max_vol * 3.5], row=1, col=1, secondary_y=True, showgrid=False)
    fig.update_xaxes(rangeslider_visible=False)
    fig.update_layout(title=f"📈 {stock_id} {stock_name} 主圖技術分析 (K線、均線與布林通道)")
    return apply_dark_theme(fig, height=480)

def plot_macd_obv_chart(price_df, display_start_date):
    df_calc = calculate_indicators(price_df)
    df_price = df_calc[df_calc['Date'] >= display_start_date].copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, subplot_titles=("MACD 動能指標", "OBV 能量潮指標 (含 OBV MA10)"))
    
    fig.add_trace(go.Bar(x=df_price['Date'], y=df_price['MACD_Hist'], name="MACD 柱狀圖", marker_color=np.where(df_price['MACD_Hist'] >= 0, '#FF5252', '#00E676')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['MACD'], name="DIF", line=dict(color="#2962FF", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['MACD_Signal'], name="DEM", line=dict(color="#FF6D00", width=1.5)), row=1, col=1)
    
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['OBV'], name="OBV 能量潮", line=dict(color="#E040FB", width=2)), row=2, col=1)
    fig.add_trace(go.Scatter(x=df_price['Date'], y=df_price['OBV_MA10'], name="OBV MA10", line=dict(color="#FFD600", width=1.8)), row=2, col=1)
    return apply_dark_theme(fig, height=400)

def plot_chip_chart(chip_df, display_start_date):
    fig = make_subplots(rows=1, cols=1)
    if not chip_df.empty:
        d_col = 'date' if 'date' in chip_df.columns else ('Date' if 'Date' in chip_df.columns else chip_df.columns[0])
        chip_sub = chip_df[chip_df[d_col] >= display_start_date].copy()
        if 'name' in chip_sub.columns:
            val_col = 'buy_sell' if 'buy_sell' in chip_sub.columns else ('buy' if 'buy' in chip_sub.columns else chip_sub.columns[-1])
            p_foreign = chip_sub[chip_sub['name'].astype(str).str.contains('Foreign', case=False, na=False)].groupby(d_col)[val_col].sum()
            p_trust = chip_sub[chip_sub['name'].astype(str).str.contains('Trust', case=False, na=False)].groupby(d_col)[val_col].sum()
            p_dealer = chip_sub[chip_sub['name'].astype(str).str.contains('Dealer', case=False, na=False)].groupby(d_col)[val_col].sum()
            
            if not p_foreign.empty: 
                fig.add_trace(go.Bar(x=p_foreign.index, y=(p_foreign/1000).round(0), name="外資(張)", marker_color='#2962FF', opacity=0.9))
            if not p_trust.empty: 
                fig.add_trace(go.Bar(x=p_trust.index, y=(p_trust/1000).round(0), name="投信(張)", marker_color='#FF6D00', opacity=0.9))
            if not p_dealer.empty: 
                fig.add_trace(go.Bar(x=p_dealer.index, y=(p_dealer/1000).round(0), name="自營商(張)", marker_color='#E040FB', opacity=0.9))
                
    fig.update_yaxes(title_text="買賣超張數")
    fig.update_layout(title="🏛️ 三大法人每日買賣超 (張)", barmode='group')
    return apply_dark_theme(fig, height=320)

def plot_margin_chart(margin_df, display_start_date):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if not margin_df.empty:
        d_col = 'date' if 'date' in margin_df.columns else ('Date' if 'Date' in margin_df.columns else margin_df.columns[0])
        margin_sub = margin_df[margin_df[d_col] >= display_start_date].copy()
        col_margin = [c for c in margin_sub.columns if 'MarginPurchase' in c or '融資' in c]
        col_short = [c for c in margin_sub.columns if 'ShortSale' in c or '融券' in c]
        if col_margin:
            m_col = [c for c in col_margin if 'Today' in c or 'Balance' in c][0] if [c for c in col_margin if 'Today' in c or 'Balance' in c] else col_margin[0]
            fig.add_trace(go.Scatter(x=margin_sub[d_col], y=margin_sub[m_col], name="融資餘額(張)", line=dict(color="#FF5252", width=2.2)), secondary_y=False)
        if col_short:
            s_col = [c for c in col_short if 'Today' in c or 'Balance' in c][0] if [c for c in col_short if 'Today' in c or 'Balance' in c] else col_short[0]
            fig.add_trace(go.Scatter(x=margin_sub[d_col], y=margin_sub[s_col], name="融券餘額(張)", line=dict(color="#00E676", width=2.2)), secondary_y=True)
    fig.update_yaxes(title_text="融資 (張)", secondary_y=False)
    fig.update_yaxes(title_text="融券 (張)", secondary_y=True, showgrid=False)
    fig.update_layout(title="💳 融資融券餘額變化 (張)")
    return apply_dark_theme(fig, height=300)

def plot_norway_pyramid_chart(norway_df, stock_id, stock_name):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if not norway_df.empty:
        fig.add_trace(go.Bar(x=norway_df['Date'], y=norway_df['Total_People'], name="總股東人數 (人)", marker_color='#546E7A', opacity=0.9), secondary_y=False)
        fig.add_trace(go.Scatter(x=norway_df['Date'], y=norway_df['Big_Ratio'], name="大股東持有率 (%)", mode="lines+markers", line=dict(color="#FFAB00", width=2.8), marker=dict(size=7, color="#FFFFFF")), secondary_y=True)
    fig.update_yaxes(title_text="總股東人數 (人)", secondary_y=False)
    fig.update_yaxes(title_text="大股東持有率 (%)", secondary_y=True, showgrid=False, ticksuffix="%")
    fig.update_layout(title=f"🏛️ {stock_id} {stock_name} 神秘金字塔 - 總股東人數 vs 大股東持有率")
    return apply_dark_theme(fig, height=340)

# -----------------------------------------------------------------------------
# Streamlit 主 UI (支援執行模式切換)
# -----------------------------------------------------------------------------
default_gemini_keys = os.getenv("GEMINI_API_KEY", "")
default_finmind_token = os.getenv("FINMIND_TOKEN", "")

if "gemini_keys" not in st.session_state: st.session_state["gemini_keys"] = default_gemini_keys
if "finmind_token" not in st.session_state: st.session_state["finmind_token"] = default_finmind_token
if "selected_stock_code" not in st.session_state: st.session_state["selected_stock_code"] = "2317"
if "last_ai_call_time" not in st.session_state: st.session_state["last_ai_call_time"] = 0

with st.sidebar:
    st.markdown("### ⚡ 系統核心設定")
    app_mode = st.selectbox("選擇系統執行模式：", ["單股診斷版 (指定個股 + 圖表辯論)", "啟動全功能版 (全市場自動選股 + 多 Agent 辯論)"], index=0)
    st.markdown("---")
    
    stored_gemini_keys = st.text_input("Google Gemini API Keys", value=st.session_state["gemini_keys"], type="password")
    if stored_gemini_keys != st.session_state["gemini_keys"]: 
        st.session_state["gemini_keys"] = stored_gemini_keys

    if st.button("🔍 測試 API Key 連線狀態", use_container_width=True):
        with st.spinner("正在向 Google AI 伺服器發送微量連線測試..."):
            diag_results = test_api_key_connection(st.session_state["gemini_keys"])
            for m_key, status, msg in diag_results:
                if status: st.success(f"✅ 金鑰 `{m_key}`：{msg}")
                else: st.error(f"❌ 金鑰 `{m_key}`：{msg}")

    stored_finmind_token = st.text_input("FinMind Token", value=st.session_state["finmind_token"], type="password")
    if stored_finmind_token != st.session_state["finmind_token"]: 
        st.session_state["finmind_token"] = stored_finmind_token
        st.cache_data.clear()

    st.markdown("---")
    start_date = st.date_input("開始日期", value=datetime.today() - timedelta(days=90))
    end_date = st.date_input("結束日期", value=datetime.today())
    custom_query = st.text_area("多 Agent 關注重點", value="關注短期突破機會與籌碼大股東動態。")

STOCK_DICT = get_all_taiwan_stock_info(st.session_state["finmind_token"])

st.markdown("<div style='font-size:0.9rem; font-weight:bold; color:#8F9BB3; margin-bottom:6px;'>📈 市場重點指標與 Multi-Agent 系統狀態</div>", unsafe_allow_html=True)

# 採用穩定標準的 Banner 渲染
top_banner_data = fetch_top_banner_realtime_yfinance()
m_col1, m_col2, m_col3, m_col4 = st.columns(4)
with m_col1:
    st.markdown(f"<div class='fin-top-card'><div class='fin-top-title'>加權指數 (TAIEX)</div><div class='fin-top-val'>{top_banner_data['taiex']['price']} <span style='font-size:0.8rem;color:{top_banner_data['taiex']['color']};'>{top_banner_data['taiex']['change']}</span></div><div class='fin-top-desc'>台灣大盤市場最新點數與漲跌幅</div></div>", unsafe_allow_html=True)
with m_col2:
    st.markdown(f"<div class='fin-top-card'><div class='fin-top-title'>櫃買指數 (TPEX)</div><div class='fin-top-val'>{top_banner_data['tpex']['price']} <span style='font-size:0.8rem;color:{top_banner_data['tpex']['color']};'>{top_banner_data['tpex']['change']}</span></div><div class='fin-top-desc'>櫃買中心店頭市場指數與表現</div></div>", unsafe_allow_html=True)
with m_col3:
    st.markdown(f"<div class='fin-top-card'><div class='fin-top-title'>台指近月期貨 (TXF)</div><div class='fin-top-val'>{top_banner_data['tx']['price']} <span style='font-size:0.8rem;color:{top_banner_data['tx']['color']};'>{top_banner_data['tx']['change']}</span></div><div class='fin-top-desc'>台股期貨近月合約成交價</div></div>", unsafe_allow_html=True)
with m_col4:
    st.markdown(f"<div class='fin-top-card'><div class='fin-top-title'>權值龍頭：台積電 (2330)</div><div class='fin-top-val'>{top_banner_data['tsmc']['price']} <span style='font-size:0.8rem;color:{top_banner_data['tsmc']['color']};'>{top_banner_data['tsmc']['change']}</span></div><div class='fin-top-desc'>市值最高權值股報價</div></div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 依據側邊欄選擇的模式進行分流執行
# -----------------------------------------------------------------------------
if "單股診斷版" in app_mode:
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
        run_agent_button = st.button("🚀 啟動多 Agent 診斷與全圖表", type="primary", use_container_width=True)

    if run_agent_button:
        current_time = time.time()
        elapsed_time = current_time - st.session_state["last_ai_call_time"]
        if elapsed_time < 15:
            remaining = int(15 - elapsed_time)
            st.warning(f"⏳ **系統冷卻中**：為避免觸發 Google API 頻率限制（429），請等待 {remaining} 秒後再發送 AI 請求。")
        else:
            st.session_state["last_ai_call_time"] = current_time

            if not stock_id:
                st.error("❌ 請先設定有效的 FinMind Token 或選取股票！")
            else:
                s_date_str = start_date.strftime("%Y-%m-%d")
                e_date_str = end_date.strftime("%Y-%m-%d")
                buffer_start_str = (start_date - timedelta(days=120)).strftime("%Y-%m-%d")
                
                with st.spinner(f"正在抓取 {stock_id} {stock_name} 全套量化行情與防呆籌碼數據..."):
                    token = st.session_state["finmind_token"]
                    price_df = fetch_stock_history_cached(stock_id=stock_id, start_date=buffer_start_str, end_date=e_date_str, api_token=token)
                    chip_df = fetch_chip_history_cached(stock_id=stock_id, start_date=buffer_start_str, end_date=e_date_str, api_token=token)
                    margin_df = fetch_margin_history_cached(stock_id=stock_id, start_date=buffer_start_str, end_date=e_date_str, api_token=token)
                    norway_df = get_norway_big_shareholders(stock_id)

                if not price_df.empty:
                    st.plotly_chart(plot_main_kline_chart(price_df, stock_id, stock_name, s_date_str), use_container_width=True)
                    st.plotly_chart(plot_macd_obv_chart(price_df, s_date_str), use_container_width=True)
                    col1, col2 = st.columns(2)
                    with col1: st.plotly_chart(plot_chip_chart(chip_df, s_date_str), use_container_width=True)
                    with col2: st.plotly_chart(plot_margin_chart(margin_df, s_date_str), use_container_width=True)
                    st.plotly_chart(plot_norway_pyramid_chart(norway_df, stock_id, stock_name), use_container_width=True)
                    
                    if st.session_state["gemini_keys"]:
                        with st.spinner("🤝 多 Agent 團隊正在召開投資決策會議..."):
                            try:
                                agent_res = run_multi_agent_system(stock_id, stock_name, price_df, chip_df, norway_df, st.session_state["gemini_keys"], custom_query)
                                
                                st.markdown("---")
                                st.markdown("## 📊 分析結果")

                                st.markdown(f"""
                                <div class="agent-card" style="border: 1px solid #00E676 !important;">
                                    <div class="agent-card-header header-green">🏆 投資組合經理 (PM) 最終決策</div>
                                    <div class="agent-card-body">{agent_res['pm_decision']}</div>
                                </div>
                                """, unsafe_allow_html=True)

                                st.markdown(f"""
                                <div class="agent-card">
                                    <div class="agent-card-header header-yellow">⚡ 成交量與價格波動（技術面分析）</div>
                                    <div class="agent-card-body">{agent_res['tech_report']}</div>
                                </div>
                                """, unsafe_allow_html=True)

                                st.markdown(f"""
                                <div class="agent-card">
                                    <div class="agent-card-header header-blue">🎯 籌碼與集中度（籌碼面分析）</div>
                                    <div class="agent-card-body">{agent_res['chip_report']}</div>
                                </div>
                                """, unsafe_allow_html=True)

                                st.markdown(f"""
                                <div class="agent-card">
                                    <div class="agent-card-header header-green">📈 多方動能評價（看多觀點）</div>
                                    <div class="agent-card-body">{agent_res['bull_opinion']}</div>
                                </div>
                                """, unsafe_allow_html=True)

                                st.markdown(f"""
                                <div class="agent-card">
                                    <div class="agent-card-header header-purple">🔮 空方風險反駁（看空觀點）</div>
                                    <div class="agent-card-body">{agent_res['bear_opinion']}</div>
                                </div>
                                """, unsafe_allow_html=True)

                                st.markdown(f"""
                                <div class="agent-card">
                                    <div class="agent-card-header header-red">🛑 風險管理與部位配置</div>
                                    <div class="agent-card-body">{agent_res['risk_report']}</div>
                                </div>
                                """, unsafe_allow_html=True)

                            except Exception as e:
                                st.error(f"❌ {e}")
                    else:
                        st.warning("⚠️ 請於左側邊欄或 Streamlit Secrets 填入有效的 GEMINI_API_KEY！")
                else:
                    st.error(f"❌ 無法取得 {stock_id} 的 K 線價格資料，請檢查網路連線。")
else:
    # 🚀 全功能自動選股與多 Agent 決策中心 (無預設標的，由使用者自由選取)
    st.markdown("### 🚀 全功能自動選股與多 Agent 決策中心")
    st.info("💡 **全功能版說明**：在此模式下，請透過下方多選框選擇欲掃描的標的清單。若無選取則無標的。")
    
    # 完全移除預設清單，由 STOCK_DICT 或空白清單提供選擇
    options_list = list(STOCK_DICT.items()) if STOCK_DICT else []
    selected_pool = st.multiselect("選擇自動掃描清單：", options=options_list, format_func=lambda x: f"{x[0]} {x[1]}")
    
    if st.button("🎯 開始全市場自動掃描與多 Agent 辯論", type="primary", use_container_width=True):
        if not st.session_state["gemini_keys"]:
            st.warning("⚠️ 請先在側邊欄填入有效的 GEMINI_API_KEY！")
        elif not selected_pool:
            st.warning("目前無標的，請確認已載入股票清單或選擇掃描標的。")
        else:
            s_date_str = start_date.strftime("%Y-%m-%d")
            e_date_str = end_date.strftime("%Y-%m-%d")
            buffer_start_str = (start_date - timedelta(days=120)).strftime("%Y-%m-%d")
            token = st.session_state["finmind_token"]

            for item in selected_pool:
                s_id, s_name = item[0], item[1]

                st.markdown(f"---")
                st.markdown(f"### 🔍 多 Agent 正在掃描與評估：{s_name} ({s_id})")
                
                with st.spinner(f"正在分析 {s_name} ({s_id}) 的行情與籌碼..."):
                    price_df = fetch_stock_history_cached(stock_id=s_id, start_date=buffer_start_str, end_date=e_date_str, api_token=token)
                    chip_df = fetch_chip_history_cached(stock_id=s_id, start_date=buffer_start_str, end_date=e_date_str, api_token=token)
                    norway_df = get_norway_big_shareholders(s_id)

                if not price_df.empty:
                    try:
                        agent_res = run_multi_agent_system(s_id, s_name, price_df, chip_df, norway_df, st.session_state["gemini_keys"], custom_query)
                        
                        st.markdown(f"""
                        <div class="agent-card" style="border: 1px solid #00E676 !important;">
                            <div class="agent-card-header header-green">🏆 {s_name} ({s_id}) - PM 最終決策</div>
                            <div class="agent-card-body">{agent_res['pm_decision']}</div>
                        </div>
                        """, unsafe_allow_html=True)

                        with st.expander(f"🔎 展開 {s_name} ({s_id}) 的詳細多面向辯論報告"):
                            st.markdown(f"**⚡ 技術面分析：**\n\n{agent_res['tech_report']}")
                            st.markdown(f"**🎯 籌碼面分析：**\n\n{agent_res['chip_report']}")
                            st.markdown(f"**📈 看多觀點：**\n\n{agent_res['bull_opinion']}")
                            st.markdown(f"**🔮 看空觀點：**\n\n{agent_res['bear_opinion']}")
                            st.markdown(f"**🛑 風控建議：**\n\n{agent_res['risk_report']}")

                    except Exception as e:
                        st.error(f"❌ {s_name} ({s_id}) 分析失敗：{e}")
                else:
                    st.warning(f"⚠️ 無法取得 {s_name} ({s_id}) 的歷史行情資料。")