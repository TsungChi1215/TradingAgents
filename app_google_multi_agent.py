import os
import json
import re
import pandas as pd
import numpy as np
import requests
import io
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from datetime import datetime, timedelta, timezone
import logging
import time
import random
import hashlib
import html

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
    """Refresh window only; this is not a holiday-calendar validator."""
    now = taipei_now()
    weekday, minutes = now.weekday(), now.hour * 60 + now.minute
    if weekday <= 4 and 8 * 60 + 45 <= minutes <= 13 * 60 + 45:
        return True
    if weekday <= 4 and minutes >= 15 * 60:
        return True
    return weekday in (1, 2, 3, 4, 5) and minutes <= 5 * 60


# -----------------------------------------------------------------------------
# 2. 四大指數與台積電三重備援抓取（證交所/櫃買中心/期交所 官方 API 串接）
# -----------------------------------------------------------------------------
TAIPEI = timezone(timedelta(hours=8))
logger = logging.getLogger("trading_agents")


def taipei_now():
    return datetime.now(TAIPEI)


def safe_log(source, error):
    # Never log exception text, request objects, headers or response bodies.
    logger.warning("%s failed (%s)", source, type(error).__name__)


def as_number(value):
    if value is None:
        return None
    text = str(value).strip().replace(',', '').replace('−', '-').replace('＋', '+')
    if text in ('', '--', '-', 'None', 'nan', 'NaN'):
        return None
    try:
        number = float(text)
        return number if np.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def first_field(row, *names):
    for name in names:
        if name in row and row[name] not in (None, ''):
            return row[name]
    return None


def market_json(url, **kwargs):
    response = requests.get(url, timeout=(5, 12),
                            headers={'User-Agent': 'Mozilla/5.0'}, **kwargs)
    response.raise_for_status()
    return response.json()


def quote_record(value, change, source, date='', **extra):
    value = as_number(value)
    if value is None or value <= 0:
        raise ValueError('No valid positive price')
    return dict(val=value, change=as_number(change), source=source,
                date=str(date or ''), **extra)


def select_tx_near_month(rows, official=False):
    candidates = []
    for row in rows:
        contract = first_field(row, 'Contract', 'futures_id', 'stock_id')
        if str(contract).strip() != 'TX':
            continue
        month = str(first_field(row, 'ContractMonth(Week)', 'contract_date') or '').strip()
        # Exclude spreads and weekly contracts; only monthly outright contracts.
        if not re.fullmatch(r'\d{6}', month):
            continue
        price = as_number(first_field(row, 'Close', 'close'))
        if price is None or price <= 0:
            continue
        date = str(first_field(row, 'Date', 'date') or '')
        date_key = re.sub(r'\D', '', date)
        if len(date_key) == 7:
            date_key = str(int(date_key[:3]) + 1911) + date_key[3:]
        session = str(first_field(row, 'TradingSession', 'trading_session') or '')
        rank = 0 if session.lower() in ('position', '一般', '一般交易時段', 'regular') else 1
        candidates.append((date_key, month, rank, row, session))
    if not candidates:
        raise ValueError('No valid TX monthly contract')
    latest = max(item[0] for item in candidates)
    subset = [item for item in candidates if item[0] == latest]
    _, month, _, row, session = min(subset, key=lambda item: (item[1], item[2]))
    change = first_field(row, 'Change', 'spread')
    return quote_record(first_field(row, 'Close', 'close'), change,
                        'TAIFEX 日行情' if official else 'FinMind 日行情',
                        first_field(row, 'Date', 'date'), contract=month, session=session)


@st.cache_data(ttl=15, show_spinner=False)
def fetch_realtime_market_data(api_token=''):
    data, errors = {}, {}
    now = taipei_now()
    today_str = now.strftime('%Y-%m-%d')
    start_str = (now - timedelta(days=14)).strftime('%Y-%m-%d')
    # Official index quotes: do not use individual-stock or total-return indices.
    try:
        payload = market_json('https://mis.twse.com.tw/stock/api/getStockInfo.jsp',
                              params={'ex_ch': 'tse_t00.tw|otc_o00.tw', 'json': '1', 'delay': '0'})
        for row in payload.get('msgArray', []):
            key = {'t00': 'taiex', 'o00': 'tpex'}.get(str(row.get('ch', '')).split('.')[0])
            if not key:
                continue
            value, previous = as_number(row.get('z')), as_number(row.get('y'))
            if value is not None and value > 0:
                data[key] = quote_record(value, value - previous if previous else None,
                                         'TWSE MIS 指數報價', row.get('d', ''), time=row.get('t', ''))
    except Exception as exc:
        safe_log('official index quotes', exc)
    if 'taiex' not in data:
        try:
            rows = market_json('https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK')
            row = max(rows, key=lambda r: re.sub(r'\D', '', str(r.get('Date', ''))))
            data['taiex'] = quote_record(row.get('INDEXTAIEX'), row.get('Change'),
                                         'TWSE 日行情', row.get('Date'))
        except Exception as exc:
            errors['taiex'] = '加權指數來源暫時無法取得有效資料'
            safe_log('TWSE TAIEX', exc)
    if 'tpex' not in data:
        try:
            rows = market_json('https://www.tpex.org.tw/openapi/v1/tpex_index')
            if not isinstance(rows, list):
                raise ValueError('Unexpected TPEx response')
            matches = []
            for row in rows:
                name = str(first_field(row, 'IndexName', 'Name', '指數名稱') or '').strip()
                code = str(first_field(row, 'IndexCode', 'Code') or '').strip()
                if name in ('櫃買指數', '櫃買加權指數', 'TPEX', 'TPEx Index',
                            'TPEx Exchange Capitalization Weighted Stock Index') or code == '101':
                    matches.append(row)
            if not matches:
                raise ValueError('TPEx index schema/name not recognized')
            row = max(matches, key=lambda r: str(first_field(r, 'Date', '日期') or ''))
            data['tpex'] = quote_record(first_field(row, 'Close', 'Index', 'ClosingIndex', '收盤指數'),
                                        first_field(row, 'Change', '漲跌'), 'TPEx 指數日行情',
                                        first_field(row, 'Date', '日期'))
        except Exception as exc:
            errors['tpex'] = '櫃買指數來源暫時無法取得有效資料'
            safe_log('TPEx index', exc)
    fm = None
    try:
        from FinMind.data import DataLoader
        fm = DataLoader()
        if api_token:
            fm.login_by_token(str(api_token).strip())
    except Exception as exc:
        safe_log('FinMind initialization', exc)
    if fm is not None:
        try:
            frame = fm.taiwan_futures_daily(futures_id='TX', start_date=start_str, end_date=today_str)
            data['futures'] = select_tx_near_month(frame.to_dict('records'))
        except Exception as exc:
            safe_log('FinMind TX', exc)
        try:
            frame = fm.taiwan_stock_daily(stock_id='2330', start_date=start_str, end_date=today_str)
            frame = frame.copy()
            frame['close'] = pd.to_numeric(frame['close'], errors='coerce')
            frame = frame[frame['close'] > 0].sort_values('date')
            row = frame.iloc[-1]
            change = as_number(row.get('spread'))
            if change is None and len(frame) > 1:
                change = float(row['close']) - float(frame.iloc[-2]['close'])
            data['tsmc'] = quote_record(row['close'], change, 'FinMind 日行情', row['date'])
        except Exception as exc:
            safe_log('FinMind 2330', exc)
    if 'futures' not in data:
        try:
            rows = market_json('https://openapi.taifex.com.tw/v1/DailyMarketReportFut')
            data['futures'] = select_tx_near_month(rows, official=True)
        except Exception as exc:
            errors['futures'] = '台指期來源暫時無法取得有效資料'
            safe_log('TAIFEX TX', exc)
    if 'tsmc' not in data:
        try:
            rows = market_json('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL')
            row = next(r for r in rows if str(r.get('Code', '')).strip() == '2330')
            data['tsmc'] = quote_record(row.get('ClosingPrice'), row.get('Change'),
                                        'TWSE 日行情', row.get('Date'))
        except Exception as exc:
            errors['tsmc'] = '台積電來源暫時無法取得有效資料'
            safe_log('TWSE 2330', exc)
    data['_errors'] = errors
    data['_fetched_at'] = now.isoformat()
    return data


# -----------------------------------------------------------------------------
# 3. 全市場自動選股引擎（優化 4：加上 5 分鐘快取）
# -----------------------------------------------------------------------------
@st.cache_data(ttl=300)
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
# 6. 強效連線容錯 + 平滑降級的 TradingAgents LLM 裁決引擎 (優化 1 & 2: 快取與智慧直連)
# -----------------------------------------------------------------------------
def clean_and_parse_json(raw_text):
    """強效 JSON 清洗與容錯解析"""
    if not raw_text:
        return None
    txt = raw_text.strip()
    if txt.startswith("```json"): txt = txt[7:]
    if txt.startswith("```"): txt = txt[3:]
    if txt.endswith("```"): txt = txt[:-3]
    txt = txt.strip()
    
    try:
        return json.loads(txt)
    except Exception:
        match = re.search(r'\{.*\}', txt, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception: pass
    return None

class GeminiCallError(Exception):
    def __init__(self, status, category):
        self.status = status
        self.category = category
        super().__init__(category)


def gemini_request(method, path, key, deadline=None, **kwargs):
    transient = {429, 500, 502, 503, 504}
    for attempt in range(3):
        remaining = (deadline - time.monotonic()) if deadline is not None else 30
        if remaining <= 1:
            raise GeminiCallError(0, 'timeout')
        try:
            response = requests.request(
                method, 'https://generativelanguage.googleapis.com/v1beta/' + path,
                headers={'x-goog-api-key': key, 'Content-Type': 'application/json'},
                timeout=(min(5, remaining / 2), min(25, remaining / 2)), **kwargs)
        except requests.RequestException as exc:
            safe_log('Gemini transport', exc)
            if attempt == 2:
                raise GeminiCallError(0, 'network') from None
        else:
            status = response.status_code
            if status == 200:
                try:
                    return response.json()
                except ValueError:
                    raise GeminiCallError(status, 'invalid_response') from None
            logger.warning('Gemini request failed HTTP=%s attempt=%s', status, attempt + 1)
            if status not in transient or attempt == 2:
                category = ('rate_limit' if status == 429 else 'busy' if status in transient
                            else 'auth' if status in (401, 403) else 'model' if status == 404 else 'request')
                raise GeminiCallError(status, category)
        delay = min(2 ** attempt + random.uniform(0, 0.5), 5)
        if deadline is not None and time.monotonic() + delay >= deadline:
            raise GeminiCallError(0, 'timeout')
        time.sleep(delay)


@st.cache_data(ttl=3600, show_spinner=False)
def discover_gemini_models(_api_key, key_fingerprint):
    models, page_token = [], None
    deadline = time.monotonic() + 45
    for _ in range(10):
        params = {'pageSize': 100}
        if page_token:
            params['pageToken'] = page_token
        result = gemini_request('GET', 'models', _api_key, deadline=deadline, params=params)
        for model in result.get('models', []):
            name = model.get('name', '')
            if 'generateContent' in model.get('supportedGenerationMethods', []) and name.startswith('models/gemini-'):
                # Image/audio-only models are not suitable for text JSON diagnosis.
                if not any(word in name.lower() for word in ('image', 'tts', 'audio', 'robotics')):
                    models.append(name)
        page_token = result.get('nextPageToken')
        if not page_token:
            return sorted(set(models))
    raise GeminiCallError(0, 'model_list_incomplete')


def call_trading_agents_team(stock_id, stock_name, latest_price, tech_summary, chip_summary):
    keys_list = list(dict.fromkeys(parse_api_keys(get_secret('GEMINI_API_KEY', ''))))
    if not keys_list:
        return None, '未設定 GEMINI_API_KEY，請至 Streamlit Secrets 設定。'
    configured = parse_api_keys(get_secret('GEMINI_MODELS', ''))
    config_id = hashlib.sha256(('\0'.join(keys_list + configured)).encode()).hexdigest()
    cache_key = hashlib.sha256(json.dumps(
        [config_id, stock_id, stock_name, latest_price, tech_summary, chip_summary],
        ensure_ascii=False, default=str).encode()).hexdigest()
    cached = st.session_state.get('_agent_success_cache', {})
    if cache_key in cached and time.time() - cached[cache_key][0] < 1800:
        return cached[cache_key][1], None
    prompt = f"""
    你是由 TauricResearch/TradingAgents 密集的 AI 多智能體團隊，正在為台股【{stock_id} {stock_name}】（當前收盤價：{latest_price} 元）進行深度投資裁決會議。
    請根據以下數據進行內部團隊辯論與風控審核：
    【技術面數據】：{tech_summary}
    【籌碼與大股東數據】：{chip_summary}

    請嚴格輸出一個符合 JSON 格式的字典（不要帶額外的 Markdown 說明），格式包含以下 Key：
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
    prompt += '\n僅依提供數據判斷；未提供或未計算的指標須明確標示資料不足，不得捏造。'
    failures = []
    start_idx = int(st.session_state.get('last_working_key_idx', 0)) % len(keys_list)
    indices = list(range(start_idx, len(keys_list))) + list(range(start_idx))
    deadline = time.monotonic() + 120
    for key_idx in indices:
        if time.monotonic() >= deadline:
            failures.append('timeout')
            break
        key = keys_list[key_idx]
        fingerprint = hashlib.sha256(key.encode()).hexdigest()
        try:
            available = discover_gemini_models(key, fingerprint)
        except GeminiCallError as exc:
            failures.append(exc.category)
            continue
        if configured:
            preferred = [m if m.startswith('models/') else 'models/' + m for m in configured]
            candidates = [m for m in preferred if m in available]
        else:
            candidates = sorted(available, key=lambda m: (
                'flash' not in m, any(w in m for w in ('preview', 'exp', 'latest')), m))[:3]
        if not candidates:
            failures.append('model')
            continue
        for model in candidates:
            try:
                result = gemini_request('POST', model + ':generateContent', key, deadline=deadline,
                    json={'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                          'generationConfig': {'responseMimeType': 'application/json'}})
                candidates_result = result.get('candidates', [])
                parts = candidates_result[0].get('content', {}).get('parts', []) if candidates_result else []
                text = ''.join(p.get('text', '') for p in parts if not p.get('thought', False))
                parsed = clean_and_parse_json(text)
                if not isinstance(parsed, dict) or not parsed:
                    failures.append('invalid_response')
                    continue
                st.session_state['last_working_key_idx'] = key_idx
                cached[cache_key] = (time.time(), parsed)
                st.session_state['_agent_success_cache'] = dict(list(cached.items())[-20:])
                st.session_state['_agent_last_model'] = model
                return parsed, None
            except GeminiCallError as exc:
                failures.append(exc.category)
                if exc.category == 'model':
                    discover_gemini_models.clear()
                if exc.category in ('auth', 'rate_limit', 'timeout'):
                    break
    labels = {'busy': '模型服務暫時繁忙', 'rate_limit': '請求頻率或額度限制',
              'auth': '金鑰或專案權限問題', 'model': '無可用的指定模型',
              'network': '網路連線失敗', 'timeout': '已達本次等待上限',
              'invalid_response': '模型未回傳有效 JSON', 'request': '請求設定不被接受',
              'model_list_incomplete': '模型清單未完整取得'}
    reasons = '、'.join(dict.fromkeys(labels.get(x, '模型查詢失敗') for x in failures))
    return None, 'AI 裁決暫時無法完成：' + (reasons or '未取得有效回應') + '。請稍後重試或檢查設定；此訊息不代表所有 API Key 均無效。'


def render_trading_agents_cards(res):
    """將 TradingAgents 多 Agent 裁決結果渲染為深色卡片」"""
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
        st.markdown(f"""
            <div style="{card_style}">
                <div style="color: #FFB74D; font-weight: bold; font-size: 16px; margin-bottom: 8px;">⚡ 成交量和價格波動</div>
                <div style="font-size: 14px; line-height: 1.6;">{res.get('volume_price_volatility', '數據解析中...')}</div>
            </div>
            <div style="{card_style}">
                <div style="color: #64B5F6; font-weight: bold; font-size: 16px; margin-bottom: 8px;">🧭 目前市場階段</div>
                <div style="font-size: 14px; line-height: 1.6;">{res.get('market_stage', '數據解析中...')}</div>
            </div>
            <div style="{card_style}">
                <div style="color: #81C784; font-weight: bold; font-size: 16px; margin-bottom: 8px;">🚪 關鍵價格門檻</div>
                <div style="font-size: 14px; line-height: 1.6;">{res.get('key_price_levels', '數據解析中...')}</div>
            </div>
            <div style="{card_style}">
                <div style="color: #BA68C8; font-weight: bold; font-size: 16px; margin-bottom: 8px;">⚔️ 多空研究員正反辯論</div>
                <div style="font-size: 14px; line-height: 1.6;">{res.get('bull_bear_debate', '數據解析中...')}</div>
            </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
            <div style="{card_style}">
                <div style="color: #FF8A65; font-weight: bold; font-size: 16px; margin-bottom: 8px;">🎯 訊號分析 (RSI/MACD)</div>
                <div style="font-size: 14px; line-height: 1.6;">{res.get('signal_analysis', '數據解析中...')}</div>
            </div>
            <div style="{card_style}">
                <div style="color: #4DD0E1; font-weight: bold; font-size: 16px; margin-bottom: 8px;">📊 圖表模式識別</div>
                <div style="font-size: 14px; line-height: 1.6;">{res.get('pattern_recognition', '數據解析中...')}</div>
            </div>
            <div style="{card_style}">
                <div style="color: #FFD54F; font-weight: bold; font-size: 16px; margin-bottom: 8px;">⚡ 趨勢強度評估</div>
                <div style="font-size: 14px; line-height: 1.6;">{res.get('trend_strength', '數據解析中...')}</div>
            </div>
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
        with st.spinner("TradingAgents 團隊（技術員/多空研究員/交易員/風控經理）連線分析中..."):
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
    start_date = st.date_input("開始日期", value=taipei_now() - timedelta(days=90))
    end_date = st.date_input("結束日期", value=taipei_now())

# -----------------------------------------------------------------------------
# 9. 頂部四大指數獨立區塊（優化 3：僅在盤中交易時間 60 秒自動重新整理）
# -----------------------------------------------------------------------------
run_interval = 60 if is_taiwan_market_open() else None

@st.fragment(run_every=run_interval)
def render_market_ticker():
    market_data = fetch_realtime_market_data(finmind_token)
    columns = st.columns(4)
    for col, key, title in zip(columns, ('taiex', 'tpex', 'futures', 'tsmc'),
                               ('加權指數 (TAIEX)', '櫃買指數 (TPEX)', '台指近月 (TX)', '台積電 (2330)')):
        d = market_data.get(key)
        if d:
            change = d.get('change')
            color = '#FF5252' if change is not None and change > 0 else '#00E676' if change is not None and change < 0 else '#FFFFFF'
            change_text = f'{change:+,.2f}' if change is not None else '漲跌資料未提供'
            label = ' | '.join(str(d.get(k, '')) for k in ('date', 'time', 'source', 'contract', 'session') if d.get(k))
            value = f"{d['val']:,.2f}"
        else:
            color, value, change_text = '#848E9C', '--', '資料取得失敗／暫無資料'
            label = market_data.get('_errors', {}).get(key, '請稍後重新整理')
        col.markdown(f'''
            <div style="background-color:#1E222D;padding:15px;border-radius:8px;border:1px solid {color};">
                <span style="color:#848E9C;font-size:14px;">{html.escape(title)}</span><br>
                <span style="color:{color};font-size:26px;font-weight:bold;">{value}</span><br>
                <span style="color:{color};font-size:15px;">{change_text}</span><br>
                <span style="color:#848E9C;font-size:11px;">{html.escape(label)}</span>
            </div>
        ''', unsafe_allow_html=True)
    st.caption('指數報價與日行情可能有延遲；請以資料日期、來源及契約為準。期貨同一交易日優先一般盤。')
    if st.button('重新取得行情', key='refresh_market_quotes'):
        fetch_realtime_market_data.clear()
        st.rerun()


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