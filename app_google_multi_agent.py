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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
import math
import inspect
import sqlite3

# -----------------------------------------------------------------------------
# 1. 系統設定與金鑰解析
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="TradingAgents - 專業金融量化選股終端",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="auto"
)

# 注入行動端滿版 CSS：自動偵測手機螢幕並把左右邊界壓縮至極致
st.markdown("""
    <style>
    @media (max-width: 768px) {
        /* 移除手機端 Streamlit 主區塊左右預設留白 */
        .main .block-container {
            padding-left: 0.25rem !important;
            padding-right: 0.25rem !important;
            padding-top: 1rem !important;
            max-width: 100% !important;
        }
        /* 強制 Plotly 繪圖元件擴展至 100% 手機寬度 */
        div[data-testid="stPlotlyChart"] {
            width: 100% !important;
        }
        div[data-testid="stPlotlyChart"] > div {
            width: 100% !important;
        }
        .stButton > button { width: 100%; }
        h2 { font-size: 1.3rem !important; }
    }
    .block-container { padding-bottom: 4rem; }
    /* 頂部四大指數：手機 2x2、桌面 1x4 */
    .tk-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
    .tk-card { background-color: #1E222D; padding: 12px 14px; border-radius: 8px; }
    .tk-title { color: #848E9C; font-size: 13px; }
    .tk-val { font-size: clamp(20px, 5.4vw, 26px); font-weight: bold; line-height: 1.3; }
    .tk-chg { font-size: 14px; font-weight: bold; }
    .tk-note { color: #848E9C; font-size: 12px; margin: 6px 0 2px 0; line-height: 1.5; }
    /* 行情區塊更新時不變暗（Streamlit 以 data-stale 標記更新中的元素） */
    div[data-stale="true"]:has(.tk-grid), div[data-stale="true"]:has(.tk-note), div[data-stale="true"]:has(.sr-box),
    div[data-stale="true"]:has(.st-key-refresh_market_quotes), div[data-stale="true"]:has(.st-key-sector_rank_dir) { opacity: 1 !important; transition: none !important; }
    div[data-testid="stElementContainer"]:has(> iframe[height="0"]), div[data-testid="stElementContainer"]:has(iframe[height="0"]) { display: none; }
    .tk-card.wide { grid-column: 1 / -1; }
    .tk-chg small { font-weight: normal; opacity: .9; }
    .lm-row { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; margin-top: 4px; font-size: 14px; }
    .lm-row b { font-size: 18px; }
    .lm-name { color: #E0E3EB; min-width: 2.5em; }
    .sr-box { background-color: #1E222D; border-radius: 8px; padding: 10px 12px; margin-top: 10px; }
    .sr-head { color: #E0E3EB; font-size: 15px; font-weight: bold; }
    .sr-row { display: grid; grid-template-columns: 1.4em minmax(4.5em, 6.5em) 1fr 4.6em; align-items: center; gap: 6px; margin-top: 7px; font-size: 13px; }
    .sr-rank { color: #848E9C; text-align: right; }
    .sr-name { color: #E0E3EB; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .sr-bar { background: #2A2E39; height: 10px; border-radius: 5px; overflow: hidden; }
    .sr-fill { height: 100%; border-radius: 5px; }
    .sr-pct { text-align: right; font-weight: bold; font-variant-numeric: tabular-nums; }
    .tk-meta { color: #848E9C; font-size: 11px; line-height: 1.4; margin-top: 2px; overflow-wrap: anywhere; }
    </style>
""", unsafe_allow_html=True)


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


# --- 即時行情來源（多來源並行抓取，取「資料時間最新」者；任一來源失敗不影響其他來源） ---
TICKER_REFRESH_SECONDS = 60      # 頂部指數／漲跌停家數／類股排行的自動更新間隔（秒）
QUOTE_MAX_AGE_OPEN = 20          # 盤中：資料超過 20 秒就在背景重新抓取
QUOTE_MAX_AGE_CLOSED = 600       # 非交易時段：10 分鐘才重抓一次
TX_SYMBOL = re.compile(r'^TXF([A-L])(\d)-([FM])$')   # 例：TXFK6-F = 2026/11 台指期（日盤）


def rt_request(method, url, **kwargs):
    response = requests.request(method, url, timeout=(3, 6),
                                headers={'User-Agent': 'Mozilla/5.0'}, **kwargs)
    response.raise_for_status()
    return response.json()


def rt_record(value, change, source, dt=None, **extra):
    return quote_record(value, change, source,
                        dt.strftime('%Y-%m-%d') if dt else '',
                        time=dt.strftime('%H:%M:%S') if dt else '',
                        ts=dt.isoformat() if dt else '', **extra)


def parse_taipei_dt(date_text, time_text):
    try:
        return datetime.strptime(f'{date_text}{time_text}', '%Y%m%d%H%M%S').replace(tzinfo=TAIPEI)
    except (ValueError, TypeError):
        return None


def rt_twse_mis():
    payload = rt_request('GET', 'https://mis.twse.com.tw/stock/api/getStockInfo.jsp',
                         params={'ex_ch': 'tse_t00.tw|otc_o00.tw|tse_2330.tw', 'json': '1',
                                 'delay': '0', '_': int(time.time() * 1000)})
    out = {}
    for row in payload.get('msgArray', []):
        key = {'t00': 'taiex', 'o00': 'tpex', '2330': 'tsmc'}.get(str(row.get('ch', '')).split('.')[0])
        price, prev = as_number(row.get('z')), as_number(row.get('y'))
        if not key or price is None or price <= 0:
            continue
        tlong = as_number(row.get('tlong'))
        dt = datetime.fromtimestamp(tlong / 1000, TAIPEI) if tlong else None
        out[key] = rt_record(price, price - prev if prev else None, 'TWSE MIS 即時', dt)
    return out


def rt_taifex_mis():
    """期交所 MIS：同時取得日盤(MarketType=0)與夜盤(MarketType=1)，台指期近月取資料時間較新的一個。"""
    out, parsed, spot = {}, [], None
    now = taipei_now()
    for market in ('0', '1'):
        try:
            payload = rt_request('POST', 'https://mis.taifex.com.tw/futures/api/getQuoteList',
                                 json={'MarketType': market, 'SymbolType': 'F', 'KindID': '1',
                                       'CID': 'TXF', 'ExpireMonth': '', 'RowSize': '全部',
                                       'PageNo': '', 'SortColumn': '', 'AscDesc': 'A'})
        except Exception as exc:
            safe_log(f'TAIFEX MIS market {market}', exc)
            continue
        for q in (payload.get('RtData') or {}).get('QuoteList') or []:
            sid = str(q.get('SymbolID', ''))
            dt = parse_taipei_dt(q.get('CDate'), q.get('CTime'))
            price = as_number(q.get('CLastPrice'))
            if sid == 'TXF-S' and price and price > 0:     # 臺指現貨 = 加權指數即時值
                if spot is None or (dt and (spot[0] is None or dt > spot[0])):
                    spot = (dt, price, as_number(q.get('CDiff')))
            m = TX_SYMBOL.match(sid)
            if not m:
                continue
            month = 'ABCDEFGHIJKL'.index(m.group(1)) + 1
            year = now.year - now.year % 10 + int(m.group(2))
            if year < now.year - 1:
                year += 10
            parsed.append(dict(month_key=year * 100 + month, dt=dt, price=price,
                               diff=as_number(q.get('CDiff')),
                               session='一般盤' if m.group(3) == 'F' else '盤後'))
    if parsed:
        near = min(p['month_key'] for p in parsed)          # 先決定近月，再看有沒有有效報價
        pool = [p for p in parsed if p['month_key'] == near and p['price'] and p['price'] > 0]
        if pool:
            best = max(pool, key=lambda p: p['dt'].isoformat() if p['dt'] else '')
            out['futures'] = rt_record(best['price'], best['diff'], 'TAIFEX MIS 即時', best['dt'],
                                       contract=str(near), session=best['session'])
    if spot:
        out['taiex'] = rt_record(spot[1], spot[2], 'TAIFEX MIS 現貨', spot[0])
    return out


def rt_cnyes():
    payload = rt_request('GET', 'https://ws.api.cnyes.com/ws/api/v1/quote/quotes/'
                                'TWS:2330:STOCK,TWS:TSE01:INDEX,TWS:OTC01:INDEX',
                         params={'column': 'K,G'})
    mapping = {'TWS:2330:STOCK': 'tsmc', 'TWS:TSE01:INDEX': 'taiex', 'TWS:OTC01:INDEX': 'tpex'}
    out = {}
    for item in payload.get('data') or []:
        key, price, stamp = mapping.get(item.get('0')), as_number(item.get('6')), as_number(item.get('200007'))
        if key and price and price > 0:
            dt = datetime.fromtimestamp(stamp, TAIPEI) if stamp else None
            out[key] = rt_record(price, as_number(item.get('11')), '鉅亨網 即時', dt)
    return out


def rt_yahoo():
    out = {}
    for key, symbol in (('tsmc', '2330.TW'), ('taiex', '%5ETWII')):
        try:
            meta = rt_request('GET', f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}',
                              params={'interval': '1m', 'range': '1d'})['chart']['result'][0]['meta']
            price, prev = as_number(meta.get('regularMarketPrice')), as_number(meta.get('chartPreviousClose'))
            stamp = as_number(meta.get('regularMarketTime'))
            if price and price > 0:
                dt = datetime.fromtimestamp(stamp, TAIPEI) if stamp else None
                out[key] = rt_record(price, price - prev if prev else None, 'Yahoo 即時', dt)
        except Exception as exc:
            safe_log(f'Yahoo {symbol}', exc)
    return out


LIMIT_STOCK = re.compile(r'^[1-9]\d{3}[A-Z]?\.TWO?$')   # 一般股票代號（排除 ETF、權證、ETN 等）


def rt_breadth():
    """上市／上櫃的漲停、跌停家數（Yahoo 股市漲跌幅排行；每頁最多 100 檔，漲停／跌停必定排在最前面）。"""
    def one(exchange, kind):
        sort = '-changePercent' if kind == 'up' else 'changePercent'
        url = ('https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.rank;'
               f'exchange={exchange};limit=100;offset=0;period=1D;rankId=change-{kind};sortBy={sort}')
        payload = rt_request('GET', url)
        rows = payload.get('list') or []
        flag = 'limitUp' if kind == 'up' else 'limitDown'
        stocks = [r for r in rows if LIMIT_STOCK.match(str(r.get('symbol', '')))]
        count = sum(1 for r in stocks if r.get(flag))
        truncated = len(rows) >= 100 and bool(rows[-1].get(flag))   # 100 檔全是漲停／跌停 → 實際家數可能更多
        return count, truncated, payload.get('rankTime')

    jobs = {(ex, kind): (ex, kind) for ex in ('TAI', 'TWO') for kind in ('up', 'down')}
    out, stamps = {}, []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {k: pool.submit(one, *k) for k in jobs}
        for k, f in futures.items():
            count, truncated, stamp = f.result(timeout=12)
            out[k] = (count, truncated)
            if stamp:
                stamps.append(stamp)
    stamp = max(stamps) if stamps else ''
    result = {'source': 'Yahoo 股市', 'date': stamp[:10], 'time': stamp[11:19], 'ts': stamp}
    for label, ex in (('listed', 'TAI'), ('otc', 'TWO')):
        result[label] = {'up': out[(ex, 'up')][0], 'down': out[(ex, 'down')][0],
                         'up_more': out[(ex, 'up')][1], 'down_more': out[(ex, 'down')][1]}
    return {'breadth': result}


# 上市類股指數（鉅亨網）：TSE04~TSE43 之中扣除「加權／不含金融／不含電子／化學生技醫療／不含金融電子」等彙總指數，
# 再加上 TWSE 主題類指數（綠能環保、數位雲端、運動休閒、居家生活）
# 04 化學、05 生技醫療、15~20 水泥/食品/塑膠/紡織/電機/電器電纜、22~33 玻璃…其他、35 油電燃氣、36~43 電子各次類股
SECTOR_CODES = [f'TWS:TSE{n:02d}:INDEX' for n in (4, 5, *range(15, 21), *range(22, 34), *range(35, 44))] + \
               [f'TWS:IX{n:04d}:INDEX' for n in (185, 186, 187, 188)]


def rt_sectors():
    payload = rt_request('GET', 'https://ws.api.cnyes.com/ws/api/v1/quote/quotes/' + ','.join(SECTOR_CODES),
                         params={'column': 'K,G'})
    rows, stamps = [], []
    for item in payload.get('data') or []:
        pct, price, stamp = as_number(item.get('56')), as_number(item.get('6')), as_number(item.get('200007'))
        name = re.sub(r'\s+', '', str(item.get('200009') or ''))
        name = re.sub(r'(類指數|股價指數|類股)$', '', name) or name
        name = {'電子': '電子工業'}.get(name, name)
        if pct is None or not price or not name:
            continue
        rows.append({'name': name, 'pct': pct, 'price': price, 'change': as_number(item.get('11'))})
        if stamp:
            stamps.append(stamp)
    if not rows:
        raise ValueError('no sector quotes')
    dt = datetime.fromtimestamp(max(stamps), TAIPEI) if stamps else None
    return {'sectors': {'rows': rows, 'source': '鉅亨網 類股指數',
                        'date': dt.strftime('%Y-%m-%d') if dt else '', 'time': dt.strftime('%H:%M:%S') if dt else ''}}



RT_PRIORITY = {   # 同一時間時的來源優先順序；實際會先比較資料時間，取最新者
    'taiex': ('twse', 'taifex', 'cnyes', 'yahoo'),
    'tpex': ('twse', 'cnyes'),
    'futures': ('taifex',),
    'tsmc': ('twse', 'cnyes', 'yahoo'),
}


def collect_market_quotes(api_token=''):
    """純資料函式（不呼叫任何 st.*），可安全地在背景執行緒中執行。"""
    data, errors = {}, {}
    now = taipei_now()
    today_str = now.strftime('%Y-%m-%d')
    start_str = (now - timedelta(days=14)).strftime('%Y-%m-%d')

    workers = {'twse': rt_twse_mis, 'taifex': rt_taifex_mis, 'cnyes': rt_cnyes, 'yahoo': rt_yahoo,
               'breadth': rt_breadth, 'sectors': rt_sectors}
    results = {}
    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        futures = {name: pool.submit(fn) for name, fn in workers.items()}
        for name, future in futures.items():
            try:
                results[name] = future.result(timeout=12)
            except Exception as exc:
                safe_log(f'realtime source {name}', exc)
                results[name] = {}
    for key, order in RT_PRIORITY.items():
        candidates = [results[name].get(key) for name in order if results.get(name, {}).get(key)]
        if candidates:
            data[key] = max(candidates, key=lambda r: r.get('ts') or '')   # 時間最新者；同時間取優先順序較前者

    for name, key, message in (('breadth', 'breadth', '漲停／跌停家數暫時無法取得'),
                               ('sectors', 'sectors', '類股排行暫時無法取得')):
        if results.get(name, {}).get(key):
            data[key] = results[name][key]
        else:
            errors[key] = message

    # --- 以下為日行情備援：只有即時來源全部取不到時才會用到 ---
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
    if 'futures' not in data or 'tsmc' not in data:
        fm = None
        try:
            from FinMind.data import DataLoader
            fm = DataLoader()
            if api_token:
                fm.login_by_token(str(api_token).strip())
        except Exception as exc:
            safe_log('FinMind initialization', exc)
        if fm is not None and 'futures' not in data:
            try:
                frame = fm.taiwan_futures_daily(futures_id='TX', start_date=start_str, end_date=today_str)
                data['futures'] = select_tx_near_month(frame.to_dict('records'))
            except Exception as exc:
                safe_log('FinMind TX', exc)
        if fm is not None and 'tsmc' not in data:
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


# --- 行情資料倉：背景更新 + 立即回傳舊資料（stale-while-revalidate） ---
# 畫面區塊只讀取資料倉，不會被網路請求拖住；因此自動更新時 Streamlit 的「執行中」狀態極短，
# 不會讓整個畫面變暗。多位使用者共用同一份資料，也不會重複向外部來源發請求。
@st.cache_resource
def _quote_store():
    return {'lock': threading.Lock(), 'data': None, 'ts': 0.0, 'thread': None}


def _refresh_quote_store(store, api_token):
    try:
        data = collect_market_quotes(api_token)
    except Exception as exc:
        safe_log('collect_market_quotes', exc)
        return
    with store['lock']:
        store['data'], store['ts'] = data, time.time()


def fetch_realtime_market_data(api_token='', force=False):
    store = _quote_store()
    max_age = QUOTE_MAX_AGE_OPEN if is_taiwan_market_open() else QUOTE_MAX_AGE_CLOSED
    thread = store['thread']
    running = thread is not None and thread.is_alive()
    if store['data'] is None or force:
        # 第一次載入或使用者按「重新取得行情」：同步等待結果
        if not running:
            thread = threading.Thread(target=_refresh_quote_store, args=(store, api_token), daemon=True)
            store['thread'] = thread
            thread.start()
        thread.join(timeout=25)
    elif time.time() - store['ts'] > max_age:
        if not running:
            thread = threading.Thread(target=_refresh_quote_store, args=(store, api_token), daemon=True)
            store['thread'] = thread
            thread.start()
        thread.join(timeout=2.5)    # 最多等 2.5 秒；沒抓完就先顯示舊資料，下一輪再更新
    return dict(store['data'] or {}), store['ts']


# -----------------------------------------------------------------------------
# 3. 全市場自動選股引擎（5 分鐘快取）
# -----------------------------------------------------------------------------
def _num_series(df, names):
    for name in names:
        if name in df.columns:
            return pd.to_numeric(df[name], errors="coerce")
    return pd.Series(dtype=float)


def _price_slope_stage(item, token, start_str, end_str):
    """第一優先：掃描時只用 Yahoo 快速備援抓價格，避免大量 FinMind 呼叫造成限流。"""
    sid = item["股票代碼"]
    price = pd.DataFrame()
    for suffix in ("TW", "TWO"):
        price, _ = _fetch_price_yahoo_symbol(f"{sid}.{suffix}", start_str, end_str)
        if not price.empty:
            break
    if price.empty or len(price) < 26:
        return None
    price = price.sort_values("date" if "date" in price.columns else "Date")
    close = _num_series(price, ["close", "Close"]).dropna()
    if len(close) < 26:
        return None
    ma20 = close.rolling(20).mean()
    base_ma = ma20.iloc[-6]
    slope = (ma20.iloc[-1] / base_ma - 1) * 100 if pd.notna(base_ma) and base_ma > 0 else np.nan
    if pd.isna(slope) or slope <= 1.0:
        return None
    item = dict(item)
    item["月線斜率(%)"] = round(float(slope), 2)
    return item


def _chip_margin_stage(item, token, chip_start, margin_start, end_str):
    """第二階段：平行取得法人與融資，只保留主力正向且融資下降者。"""
    sid = item["股票代碼"]
    chip = fetch_chip_history_cached(sid, chip_start, end_str, token)
    margin_df = fetch_margin_history_cached(sid, margin_start, end_str, token)
    if chip.empty:
        return None
    chip = chip.copy()
    if "buy" in chip.columns and "sell" in chip.columns:
        chip["net"] = (pd.to_numeric(chip["buy"], errors="coerce").fillna(0)
                       - pd.to_numeric(chip["sell"], errors="coerce").fillna(0))
    else:
        chip["net"] = _num_series(chip, ["net_buy_sell", "NetBuySell", "buy_sell"]).fillna(0)
    date_col = "date" if "date" in chip.columns else "Date"
    daily = chip.groupby(date_col)["net"].sum().sort_index()
    if len(daily) < 10:
        return None
    chip1, chip5, chip10 = daily.tail(1).sum(), daily.tail(5).sum(), daily.tail(10).sum()
    recent_main_buy = chip5 > max(abs(daily.tail(20).mean()) * 5, 0)
    retail_sell = False
    if not margin_df.empty:
        margin = _num_series(margin_df, ["MarginPurchaseTodayBalance", "MarginPurchaseBalance",
                                         "margin_purchase_today_balance"]).dropna()
        retail_sell = len(margin) >= 6 and margin.iloc[-1] < margin.iloc[-6]
    if not (chip1 > 0 and chip5 > 0 and chip10 > 0 and recent_main_buy and retail_sell):
        return None
    item = dict(item)
    item.update({"主力1日": round(chip1 / 1000, 0), "主力5日": round(chip5 / 1000, 0),
                 "主力10日": round(chip10 / 1000, 0), "近期主力大買": "是", "近期散戶大賣": "是"})
    item["籌碼強度"] = float(chip5)
    return item


def _holder_stage(item):
    """第三階段：集保最慢，只驗證籌碼最強的少數候選股。"""
    holders = get_norway_big_shareholders(item["股票代碼"])
    if holders.empty or "Total_People" not in holders:
        return None
    people = holders["Total_People"].dropna()
    if len(people) < 2 or people.iloc[-1] >= people.iloc[-2]:
        return None
    item = dict(item)
    item["集保戶數大減"] = "是"
    item.pop("籌碼強度", None)
    return item


def _bounded_parallel(items, worker, max_workers, timeout_seconds):
    """Return completed results by deadline without waiting forever for blocked network threads."""
    if not items:
        return [], 0
    executor = ThreadPoolExecutor(max_workers=max_workers)
    futures = [executor.submit(worker, item) for item in items]
    results, timed_out = [], 0
    try:
        for future in as_completed(futures, timeout=timeout_seconds):
            try:
                value = future.result()
                if value is not None:
                    results.append(value)
            except Exception as exc:
                safe_log("market screener worker", exc)
    except TimeoutError:
        timed_out = sum(1 for f in futures if not f.done())
    finally:
        for future in futures:
            if not future.done():
                future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
    return results, timed_out


def _percentile_score(series, higher_is_better=True):
    values = pd.to_numeric(series, errors="coerce")
    if values.notna().sum() <= 1:
        return pd.Series(50.0, index=series.index)
    score = values.rank(pct=True, method="average") * 100
    return score if higher_is_better else 100 - score


def add_strategy_composite_score(df, strategy_name):
    """Add transparent 0-100 composite score, rank, and selection rationale."""
    if df is None or df.empty:
        return df
    out = df.copy()
    if strategy_name == "飆風向上":
        components = {
            "月線斜率": (_percentile_score(out["月線斜率(%)"]), 0.40),
            "主力5日": (_percentile_score(out["主力5日"]), 0.25),
            "主力10日": (_percentile_score(out["主力10日"]), 0.20),
            "成交量": (_percentile_score(out["成交量(張)"]), 0.15),
        }
        rationale = lambda r: (f"月線斜率 {r['月線斜率(%)']:.2f}%；主力5日 {r['主力5日']:,.0f}；"
                               f"主力10日 {r['主力10日']:,.0f}；成交量 {r['成交量(張)']:,.0f} 張")
    elif strategy_name == "短線強勢爆發":
        components = {
            "當日漲幅": (_percentile_score(out["漲幅(%)"]), 0.50),
            "成交量": (_percentile_score(out["成交量(張)"]), 0.30),
            "紅K實體": (_percentile_score(out["漲幅(%)"]), 0.20),
        }
        rationale = lambda r: f"當日漲幅 {r['漲幅(%)']:.2f}%；成交量 {r['成交量(張)']:,.0f} 張；收盤高於開盤"
    else:
        # Prefer strength near the upper half of the required 0.5%-3% band while rewarding liquidity.
        trend_quality = 100 - (pd.to_numeric(out["漲幅(%)"], errors="coerce") - 2.0).abs().rank(pct=True) * 100
        components = {
            "成交量": (_percentile_score(out["成交量(張)"]), 0.50),
            "波段漲幅品質": (trend_quality.fillna(50), 0.35),
            "當日漲幅": (_percentile_score(out["漲幅(%)"]), 0.15),
        }
        rationale = lambda r: f"成交量 {r['成交量(張)']:,.0f} 張；當日漲幅 {r['漲幅(%)']:.2f}%；紅K且位於波段條件區間"
    score = pd.Series(0.0, index=out.index)
    for _, (component, weight) in components.items():
        score += component.fillna(0) * weight
    out["綜合分數"] = score.round(1)
    out = out.sort_values(["綜合分數", "成交量(張)"], ascending=False).reset_index(drop=True)
    out["策略排名"] = np.arange(1, len(out) + 1)
    out["選股依據"] = out.apply(rationale, axis=1)
    return out


@st.cache_data(ttl=900, show_spinner=False)
def run_market_screener(stock_dict, strategy_type):
    """Time-boxed market scan. It always returns within about 80 seconds with status metadata."""
    started = time.monotonic()
    status = {"階段": "初始化", "訊息": "", "候選數": {}}
    url_twse = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        resp = requests.get(url_twse, timeout=(3, 10), headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        raw_data = resp.json()
    except Exception as exc:
        failed = pd.DataFrame()
        failed.attrs["scan_status"] = {"ok": False, "message": f"證交所全市場行情取得失敗：{type(exc).__name__}: {exc}"}
        return failed

    base = []
    for raw in raw_data:
        sid = str(raw.get("Code", "")).strip()
        if len(sid) != 4 or not sid.isdigit() or sid not in stock_dict:
            continue
        close_p = as_number(raw.get("ClosingPrice")) or 0
        open_p = as_number(raw.get("OpeningPrice")) or close_p
        volume = as_number(raw.get("TradeVolume")) or 0
        vol_lots = int(volume / 1000)
        change_pct = ((close_p - open_p) / open_p * 100) if open_p > 0 else 0
        row = {"股票代碼": sid, "股票名稱": stock_dict[sid], "今日收盤": close_p,
               "漲幅(%)": round(change_pct, 2), "成交量(張)": vol_lots}
        if strategy_type == "波段多頭排列":
            # 維持既有條件不變。
            if vol_lots >= 1000 and 0.5 <= change_pct <= 3.0 and close_p >= open_p:
                base.append(row)
        elif strategy_type == "短線強勢爆發":
            # 恢復先前版本：當日漲幅 >= 2%、成交量 >= 1,500 張、收盤高於開盤。
            if change_pct >= 2.0 and vol_lots >= 1500 and close_p > open_p:
                base.append(row)
        elif strategy_type == "飆風向上":
            # 目前的快速三階段漏斗，先以成交量建立候選池。
            if vol_lots > 1000:
                base.append(row)

    if strategy_type in ("短線強勢爆發", "波段多頭排列"):
        sort_col = "漲幅(%)" if strategy_type == "短線強勢爆發" else "成交量(張)"
        result = pd.DataFrame(base) if base else pd.DataFrame()
        if not result.empty:
            result = add_strategy_composite_score(result, strategy_type).head(30)
        condition_name = "舊版短線強勢條件" if strategy_type == "短線強勢爆發" else "波段多頭條件"
        result.attrs["scan_status"] = {
            "ok": True,
            "message": f"{condition_name}掃描完成，共選出 {len(result)} 檔。",
            "counts": {"符合條件": len(base)}
        }
        return result
    if not base:
        result = pd.DataFrame()
        result.attrs["scan_status"] = {"ok": True, "message": "今日沒有成交量大於 1,000 張的飆風向上候選股", "counts": {"成交量初篩": 0}}
        return result

    # Hard cap before any per-stock history request. This is the main protection for Streamlit Cloud.
    base.sort(key=lambda x: x["成交量(張)"], reverse=True)
    base_total = len(base)
    base = base[:40]
    token = get_secret("FINMIND_TOKEN", "")
    end_date = taipei_now().date()
    end_str = end_date.strftime("%Y-%m-%d")
    price_start = (end_date - timedelta(days=120)).strftime("%Y-%m-%d")
    chip_start = (end_date - timedelta(days=35)).strftime("%Y-%m-%d")
    margin_start = (end_date - timedelta(days=50)).strftime("%Y-%m-%d")

    stage1, timeout1 = _bounded_parallel(
        base, lambda x: _price_slope_stage(x, token, price_start, end_str),
        max_workers=8, timeout_seconds=35)
    stage1.sort(key=lambda x: (x["月線斜率(%)"], x["成交量(張)"]), reverse=True)
    stage1 = stage1[:15]
    if not stage1:
        result = pd.DataFrame()
        result.attrs["scan_status"] = {"ok": True, "message": "掃描完成，但沒有股票通過月線斜率 > 1% 條件。",
            "counts": {"成交量初篩": base_total, "價格深查": len(base), "月線通過": 0}, "timeouts": timeout1}
        return result

    stage2, timeout2 = _bounded_parallel(
        stage1, lambda x: _chip_margin_stage(x, token, chip_start, margin_start, end_str),
        max_workers=4, timeout_seconds=25)
    stage2.sort(key=lambda x: (x["籌碼強度"], x["月線斜率(%)"]), reverse=True)
    stage2 = stage2[:8]
    if not stage2:
        result = pd.DataFrame()
        result.attrs["scan_status"] = {"ok": True, "message": "月線條件已有候選，但沒有股票同時通過主力 1／5／10 日與融資下降條件。",
            "counts": {"成交量初篩": base_total, "價格深查": len(base), "月線通過": len(stage1), "籌碼通過": 0},
            "timeouts": timeout1 + timeout2}
        return result

    final, timeout3 = _bounded_parallel(stage2, _holder_stage, max_workers=4, timeout_seconds=15)
    final = [x for x in final if x]
    elapsed = round(time.monotonic() - started, 1)
    if final:
        result = add_strategy_composite_score(pd.DataFrame(final), "飆風向上").head(20)
        result.attrs["scan_status"] = {"ok": True, "message": f"掃描完成，耗時 {elapsed} 秒；結果已依策略綜合分數排序。",
            "counts": {"成交量初篩": base_total, "價格深查": len(base), "月線通過": len(stage1),
                       "籌碼通過": len(stage2), "集保通過": len(result)}, "timeouts": timeout1 + timeout2 + timeout3}
        return result
    result = pd.DataFrame()
    result.attrs["scan_status"] = {"ok": True, "message": f"掃描完成，耗時 {elapsed} 秒；沒有股票同時通過集保戶數下降條件。",
        "counts": {"成交量初篩": base_total, "價格深查": len(base), "月線通過": len(stage1),
                   "籌碼通過": len(stage2), "集保通過": 0}, "timeouts": timeout1 + timeout2 + timeout3}
    return result

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

PRICE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_cache.sqlite3")


def _normalize_price_df(df):
    """Convert FinMind/Yahoo data to the schema used by the existing indicators."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)
    out = out.rename(columns={
        "Date": "date", "Open": "open", "High": "max", "Low": "min",
        "Close": "close", "Volume": "Trading_Volume",
    })
    required = ["date", "open", "max", "min", "close", "Trading_Volume"]
    for col in required:
        if col not in out.columns:
            out[col] = np.nan
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for col in ["open", "max", "min", "close", "Trading_Volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return (out[required].dropna(subset=["date", "open", "max", "min", "close"])
            .sort_values("date").drop_duplicates("date").reset_index(drop=True))


def _init_price_db():
    try:
        with sqlite3.connect(PRICE_DB, timeout=5) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS daily_prices (
                stock_id TEXT NOT NULL, trade_date TEXT NOT NULL,
                open REAL, high REAL, low REAL, close REAL, volume REAL,
                source TEXT, updated_at TEXT,
                PRIMARY KEY (stock_id, trade_date)
            )""")
    except Exception as exc:
        safe_log("init price sqlite", exc)


def _read_price_db(stock_id, start_date, end_date):
    try:
        _init_price_db()
        with sqlite3.connect(PRICE_DB, timeout=5) as conn:
            rows = pd.read_sql_query(
                """SELECT trade_date AS date, open, high AS max, low AS min,
                          close, volume AS Trading_Volume, source
                   FROM daily_prices
                   WHERE stock_id=? AND trade_date BETWEEN ? AND ?
                   ORDER BY trade_date""",
                conn, params=(str(stock_id), start_date, end_date))
        if len(rows) >= 6:
            src = rows["source"].dropna().iloc[-1] if "source" in rows and not rows["source"].dropna().empty else "本地快取"
            rows = rows.drop(columns=["source"], errors="ignore")
            rows.attrs["source"] = f"本地快取（原始來源：{src}）"
            return _normalize_price_df(rows)
    except Exception as exc:
        safe_log("read price sqlite", exc)
    return pd.DataFrame()


def _write_price_db(stock_id, df, source):
    if df is None or df.empty:
        return
    try:
        _init_price_db()
        rows = _normalize_price_df(df).copy()
        now_text = taipei_now().isoformat(timespec="seconds")
        payload = [(str(stock_id), r.date.strftime("%Y-%m-%d"), float(r.open), float(r.max),
                    float(r.min), float(r.close), None if pd.isna(r.Trading_Volume) else float(r.Trading_Volume),
                    source, now_text) for r in rows.itertuples(index=False)]
        with sqlite3.connect(PRICE_DB, timeout=10) as conn:
            conn.executemany("""INSERT OR REPLACE INTO daily_prices
                (stock_id, trade_date, open, high, low, close, volume, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", payload)
    except Exception as exc:
        safe_log("write price sqlite", exc)


def _fetch_price_finmind(stock_id, start_date, end_date, api_token=""):
    try:
        from FinMind.data import DataLoader
        fm = DataLoader()
        if api_token and api_token.strip():
            fm.login_by_token(api_token.strip())
        df = _normalize_price_df(fm.taiwan_stock_daily(
            stock_id=str(stock_id), start_date=start_date, end_date=end_date))
        if len(df) >= 6:
            df.attrs["source"] = "FinMind"
            return df, None
        return pd.DataFrame(), "FinMind 回傳空資料或少於 6 筆"
    except Exception as exc:
        return pd.DataFrame(), f"FinMind {type(exc).__name__}: {exc}"


def _fetch_price_yahoo_symbol(symbol, start_date, end_date):
    """Yahoo chart endpoint fallback; no yfinance dependency required."""
    try:
        period1 = int(pd.Timestamp(start_date, tz="Asia/Taipei").timestamp())
        period2 = int((pd.Timestamp(end_date, tz="Asia/Taipei") + pd.Timedelta(days=1)).timestamp())
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        resp = requests.get(url, params={"period1": period1, "period2": period2,
                            "interval": "1d", "events": "history"},
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=(4, 15))
        resp.raise_for_status()
        chart = resp.json().get("chart", {})
        if chart.get("error"):
            return pd.DataFrame(), str(chart["error"])
        result = (chart.get("result") or [None])[0]
        if not result or not result.get("timestamp"):
            return pd.DataFrame(), f"Yahoo Finance 無 {symbol} 資料"
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        df = pd.DataFrame({
            "date": pd.to_datetime(result["timestamp"], unit="s", utc=True).tz_convert("Asia/Taipei").tz_localize(None),
            "open": quote.get("open"), "max": quote.get("high"), "min": quote.get("low"),
            "close": quote.get("close"), "Trading_Volume": quote.get("volume")})
        df = _normalize_price_df(df)
        if len(df) >= 6:
            df.attrs["source"] = f"Yahoo Finance（{symbol}）"
            return df, None
        return pd.DataFrame(), f"Yahoo Finance {symbol} 回傳少於 6 筆"
    except Exception as exc:
        return pd.DataFrame(), f"Yahoo Finance {symbol} {type(exc).__name__}: {exc}"


def fetch_stock_history_cached(stock_id, start_date, end_date, api_token=""):
    """Local DB -> FinMind -> Yahoo .TW/.TWO, and never persist a failed response."""
    local = _read_price_db(stock_id, start_date, end_date)
    # Only trust local cache when it reaches close to the requested recent date.
    if not local.empty:
        latest = pd.to_datetime(local["date"]).max().date()
        requested = pd.Timestamp(end_date).date()
        if (requested - latest).days <= 7:
            return local

    errors = []
    for attempt in range(2):
        df, err = _fetch_price_finmind(stock_id, start_date, end_date, api_token)
        if not df.empty:
            _write_price_db(stock_id, df, "FinMind")
            return df
        errors.append(err)
        if attempt == 0:
            time.sleep(1.2)

    # Automatically try listed then OTC suffix, so an incomplete stock master does not break fallback.
    for suffix in ("TW", "TWO"):
        symbol = f"{stock_id}.{suffix}"
        df, err = _fetch_price_yahoo_symbol(symbol, start_date, end_date)
        if not df.empty:
            _write_price_db(stock_id, df, f"Yahoo Finance {symbol}")
            return df
        errors.append(err)

    failed = pd.DataFrame()
    failed.attrs["errors"] = [x for x in errors if x]
    failed.attrs["source"] = "全部來源失敗"
    return failed


def _clean_number(value):
    if value is None:
        return np.nan
    text = str(value).replace(",", "").replace("+", "").strip()
    if text in ("", "--", "---", "None", "nan"):
        return np.nan
    try:
        return float(text)
    except Exception:
        return np.nan


def _pick_value(row, candidates):
    for key in candidates:
        if key in row:
            value = _clean_number(row.get(key))
            if pd.notna(value):
                return value
    return np.nan


def _pick_text(row, candidates):
    for key in candidates:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _today_trade_date():
    return taipei_now().strftime("%Y-%m-%d")


def _official_chip_snapshot(stock_id):
    """Latest official TWSE/TPEx snapshot, normalized to FinMind chip schema."""
    endpoints = [
        ("TWSE", "https://openapi.twse.com.tw/v1/exchangeReport/T86"),
        ("TPEx", "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"),
    ]
    errors = []
    for market, url in endpoints:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=(3, 12))
            r.raise_for_status()
            content_type = (r.headers.get("content-type") or "").lower()
            if "json" not in content_type and not r.text.lstrip().startswith(("[", "{")):
                errors.append(f"{market} 官方服務暫時未回傳 JSON 資料")
                continue
            try:
                rows = r.json()
            except ValueError:
                errors.append(f"{market} 官方服務回傳格式異常")
                continue
            target = None
            for row in rows if isinstance(rows, list) else []:
                code = _pick_text(row, ["Code", "證券代號", "股票代號", "SecuritiesCompanyCode", "SecuritiesCompanyCode "])
                if code == str(stock_id):
                    target = row
                    break
            if not target:
                errors.append(f"{market} 最新快照找不到 {stock_id}")
                continue
            date_text = _pick_text(target, ["Date", "日期", "TradeDate"]) or _today_trade_date()
            categories = [
                ("Foreign_Investor", ["ForeignInvestorsBuySell", "外陸資買賣超股數(不含外資自營商)", "外資及陸資(不含外資自營商)-買賣超股數", "外資及陸資買賣超股數"]),
                ("Investment_Trust", ["InvestmentTrustBuySell", "投信買賣超股數", "投信-買賣超股數"]),
                ("Dealer", ["DealerBuySell", "自營商買賣超股數", "自營商-買賣超股數", "自營商買賣超"]),
            ]
            out = []
            for name, keys in categories:
                net = _pick_value(target, keys)
                if pd.notna(net):
                    out.append({"date": date_text[:10], "name": name, "buy_sell": net})
            if out:
                df = pd.DataFrame(out)
                df.attrs["source"] = f"{market} 官方最新快照"
                return df
            errors.append(f"{market} 欄位格式無法辨識")
        except Exception as exc:
            errors.append(f"{market} {type(exc).__name__}: {exc}")
    failed = pd.DataFrame()
    failed.attrs["errors"] = errors
    return failed


def _official_margin_snapshot(stock_id):
    """Latest official TWSE/TPEx margin snapshot, normalized for the existing chart."""
    endpoints = [
        ("TWSE", "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"),
        ("TPEx", "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"),
    ]
    errors = []
    for market, url in endpoints:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=(3, 12))
            r.raise_for_status()
            content_type = (r.headers.get("content-type") or "").lower()
            if "json" not in content_type and not r.text.lstrip().startswith(("[", "{")):
                errors.append(f"{market} 官方服務暫時未回傳 JSON 資料")
                continue
            try:
                rows = r.json()
            except ValueError:
                errors.append(f"{market} 官方服務回傳格式異常")
                continue
            target = None
            for row in rows if isinstance(rows, list) else []:
                code = _pick_text(row, ["股票代號", "證券代號", "Code", "SecuritiesCompanyCode"])
                if code == str(stock_id):
                    target = row
                    break
            if not target:
                errors.append(f"{market} 融資快照找不到 {stock_id}")
                continue
            today = _pick_value(target, ["融資今日餘額", "融資餘額", "MarginPurchaseTodayBalance", "MarginBalance"])
            change = _pick_value(target, ["融資增減", "融資餘額增減", "MarginPurchaseChange", "Change"])
            yesterday = today - change if pd.notna(today) and pd.notna(change) else np.nan
            if pd.notna(today):
                df = pd.DataFrame([{
                    "date": (_pick_text(target, ["日期", "Date", "TradeDate"]) or _today_trade_date())[:10],
                    "MarginPurchaseTodayBalance": today,
                    "MarginPurchaseYesterdayBalance": yesterday if pd.notna(yesterday) else today,
                }])
                df.attrs["source"] = f"{market} 官方最新快照"
                return df
            errors.append(f"{market} 融資欄位格式無法辨識")
        except Exception as exc:
            errors.append(f"{market} {type(exc).__name__}: {exc}")
    failed = pd.DataFrame()
    failed.attrs["errors"] = errors
    return failed


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_chip_history_cached(stock_id, start_date, end_date, api_token=""):
    errors = []
    try:
        from FinMind.data import DataLoader
        fm = DataLoader()
        if api_token:
            fm.login_by_token(api_token.strip())
        df = fm.taiwan_stock_institutional_investors(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            df.attrs["source"] = "FinMind"
            return df
        errors.append("FinMind 三大法人回傳空資料")
    except Exception as exc:
        errors.append(f"FinMind 三大法人 {type(exc).__name__}: {exc}")
    df = _official_chip_snapshot(stock_id)
    if not df.empty:
        return df
    df.attrs["errors"] = errors + df.attrs.get("errors", [])
    return df


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_margin_history_cached(stock_id, start_date, end_date, api_token=""):
    errors = []
    try:
        from FinMind.data import DataLoader
        fm = DataLoader()
        if api_token:
            fm.login_by_token(api_token.strip())
        df = fm.taiwan_stock_margin_purchase_short_sale(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            df.attrs["source"] = "FinMind"
            return df
        errors.append("FinMind 融資融券回傳空資料")
    except Exception as exc:
        errors.append(f"FinMind 融資融券 {type(exc).__name__}: {exc}")
    df = _official_margin_snapshot(stock_id)
    if not df.empty:
        return df
    df.attrs["errors"] = errors + df.attrs.get("errors", [])
    return df


@st.cache_data(ttl=259200, show_spinner=False)
def get_norway_big_shareholders(stock_id):
    url = f"https://norway.twsthr.info/StockHolders.aspx?stock={stock_id}"
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=(2, 4))
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
# 5. Plotly 圖表繪製（行動裝置友善版）
#    設計原則：
#    (1) 圖例移到圖表上方橫排，不再佔用右側寬度
#    (2) K 線與成交量分成上下兩個子圖，不再疊在同一個座標內
#    (3) 預設只顯示近 40 個交易日，每根 K 棒/柱體才有足夠的寬度
#    (4) 三大法人拆成外資/投信/自營商三個獨立子圖，各自使用適合的縱軸刻度
#    (5) 神秘金字塔拆成上下兩個子圖，使用高對比色，並只標示最新一點
#    (6) 關閉圖表拖曳/縮放，避免手指上下捲動頁面時被圖表攔截
# -----------------------------------------------------------------------------
C_UP = "#FF5252"        # 台股慣例：紅漲
C_DOWN = "#00E676"      # 台股慣例：綠跌
C_TEXT = "#E6E9F0"
C_MUTED = "#9AA4B5"
C_GRID = "#262C3A"
C_BG = "#0E1117"        # 與 Streamlit 深色主題底色一致；即使切到淺色主題圖表也維持可讀
C_TITLE = "#00E676"

PLOT_CONFIG = {
    "displayModeBar": False,   # 隱藏右上角工具列（先前會蓋住標題）
    "scrollZoom": False,
    "doubleClick": False,
    "displaylogo": False,
}

def show_chart(fig):
    """相容新舊版 Streamlit 的圖表顯示函式。"""
    params = inspect.signature(st.plotly_chart).parameters
    kwargs = {"config": PLOT_CONFIG}
    if "width" in params:
        kwargs["width"] = "stretch"
    else:
        kwargs["use_container_width"] = True
    if "theme" in params:
        kwargs["theme"] = None   # 不讓 Streamlit 主題覆蓋我們指定的顏色
    st.plotly_chart(fig, **kwargs)

def chart_title(text):
    """圖表標題改用頁面文字顯示，避免與 Plotly 內部工具列或圖例重疊。"""
    st.markdown(
        f"<div style='color:{C_TITLE};font-weight:700;font-size:1.05rem;"
        f"margin:1.4rem 0 0.2rem 0;line-height:1.4;'>{text}</div>",
        unsafe_allow_html=True,
    )

def _axis_ticks(dates, max_ticks=5):
    """類別軸只標示少數幾個日期，並固定包含最新日期，標籤橫向顯示不旋轉。"""
    n = len(dates)
    if n == 0:
        return [], []
    step = max(1, math.ceil(n / max_ticks))
    idx = list(range(n - 1, -1, -step))[::-1]
    try:
        span = (pd.to_datetime(dates[-1]) - pd.to_datetime(dates[0])).days
    except Exception:
        span = 0
    fmt = "%y/%m" if span > 200 else "%m/%d"
    vals, text = [], []
    for i in idx:
        vals.append(dates[i])
        try:
            text.append(pd.to_datetime(dates[i]).strftime(fmt))
        except Exception:
            text.append(str(dates[i]))
    return vals, text

def _base_layout(fig, dates, height, top_margin=28):
    vals, text = _axis_ticks(dates)
    fig.update_layout(
        template="plotly_dark",
        height=height,
        margin=dict(l=56, r=16, t=top_margin, b=34),
        paper_bgcolor=C_BG,
        plot_bgcolor=C_BG,
        font=dict(size=12, color=C_TEXT),
        hovermode="x unified",
        hoverlabel=dict(font_size=11),
        dragmode=False,
        bargap=0.18,
        showlegend=False,
    )
    fig.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=list(dates),
        tickmode="array",
        tickvals=vals,
        ticktext=text,
        tickangle=0,
        tickfont=dict(size=11),
        showgrid=False,
        fixedrange=True,
        rangeslider_visible=False,
    )
    fig.update_yaxes(
        showgrid=True,
        gridwidth=1,
        gridcolor=C_GRID,
        zeroline=True,
        zerolinecolor="#3A4258",
        fixedrange=True,
        automargin=True,
        tickfont=dict(size=11),
    )
    return fig

def _style_subplot_titles(fig):
    """子圖標題靠左、小字、淡色。"""
    for ann in fig.layout.annotations:
        ann.update(x=0, xanchor="left", xref="paper", yshift=8,
                   font=dict(size=12, color=C_MUTED))

def _empty_fig(msg, height=160):
    fig = go.Figure()
    fig.update_layout(
        template="plotly_dark", height=height,
        paper_bgcolor=C_BG, plot_bgcolor=C_BG,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        annotations=[dict(text=msg, x=0.5, y=0.5, xref="paper", yref="paper",
                          showarrow=False, font=dict(size=13, color=C_MUTED))],
    )
    return fig

def prepare_price_view(price_df, display_start_date, n_bars=40):
    """計算指標（用完整歷史計算，避免 MA/布林在區間起點出現空值），再裁切成要顯示的區間。"""
    df_calc = calculate_indicators(price_df)
    df_calc["Date"] = df_calc["Date"].astype(str).str[:10]
    view = df_calc[df_calc["Date"] >= display_start_date].copy()
    if n_bars and n_bars > 0:
        view = view.tail(n_bars)
    return view.reset_index(drop=True)

def _fmt_signed(v, unit=""):
    return f"{v:+,.0f}{unit}"

def _kline_hover_texts(df_view):
    """每一天一段說明文字：日期由 hover 標題顯示，內容含 OHLC、漲跌、成交量與均線。"""
    texts = []
    closes = df_view["Close"].tolist()
    for i, r in enumerate(df_view.itertuples(index=False)):
        prev = closes[i - 1] if i > 0 else None
        if prev:
            chg = r.Close - prev
            pct = chg / prev * 100
            col = C_UP if chg > 0 else (C_DOWN if chg < 0 else "#FFFFFF")
            chg_txt = f"<span style='color:{col}'>{chg:+.2f} ({pct:+.2f}%)</span>"
        else:
            col = C_UP if r.Close >= r.Open else C_DOWN
            chg_txt = ""
        texts.append(
            f"<b>收 <span style='color:{col}'>{r.Close:,.2f}</span></b> {chg_txt}<br>"
            f"開 {r.Open:,.2f}　高 {r.High:,.2f}　低 {r.Low:,.2f}<br>"
            f"<b>成交量 {r.Volume_張:,.0f} 張</b>"
        )
    return texts

def plot_main_kline_chart(df_view, show_bb=True):
    if df_view.empty:
        return _empty_fig("沒有可顯示的 K 線資料")
    dates = df_view["Date"].tolist()
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.76, 0.24], vertical_spacing=0.035,
    )

    hover_texts = _kline_hover_texts(df_view)
    # 均線數值附在說明框最後一行
    for i in range(len(hover_texts)):
        parts = []
        for col, label in (("5MA", "5MA"), ("20MA", "20MA"),
                           ("BB_Upper", "布林上軌"), ("BB_Lower", "布林下軌")):
            v = df_view[col].iloc[i]
            if pd.notna(v):
                parts.append(f"{label} {v:,.2f}")
        if parts:
            hover_texts[i] += "<br>" + "　".join(parts)

    fig.add_trace(go.Candlestick(
        x=dates, open=df_view["Open"], high=df_view["High"],
        low=df_view["Low"], close=df_view["Close"], name="K線",
        increasing=dict(line=dict(color=C_UP, width=1.4), fillcolor=C_UP),
        decreasing=dict(line=dict(color=C_DOWN, width=1.4), fillcolor=C_DOWN),
        whiskerwidth=0.5, hoverinfo="skip",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(x=dates, y=df_view["5MA"], name="5MA", mode="lines",
                             line=dict(color="#FFD600", width=1.6), hoverinfo="skip"), row=1, col=1)
    fig.add_trace(go.Scatter(x=dates, y=df_view["20MA"], name="20MA(月線)", mode="lines",
                             line=dict(color="#C77DFF", width=2.0), hoverinfo="skip"), row=1, col=1)
    if show_bb:
        fig.add_trace(go.Scatter(x=dates, y=df_view["BB_Upper"], name="布林通道", mode="lines",
                                 line=dict(color="#FF9100", width=1.1, dash="dot"),
                                 legendgroup="bb", hoverinfo="skip"), row=1, col=1)
        fig.add_trace(go.Scatter(x=dates, y=df_view["BB_Lower"], name="布林下軌", mode="lines",
                                 line=dict(color="#FF9100", width=1.1, dash="dot"),
                                 legendgroup="bb", showlegend=False, hoverinfo="skip"), row=1, col=1)

    vol_colors = [C_UP if c >= o else C_DOWN for c, o in zip(df_view["Close"], df_view["Open"])]
    fig.add_trace(go.Bar(x=dates, y=df_view["Volume_張"], name="成交張數",
                         marker_color=vol_colors, marker_opacity=0.75, marker_line_width=0,
                         showlegend=False, textposition="none",
                         hovertext=hover_texts, hovertemplate="%{hovertext}<extra></extra>"), row=2, col=1)
    # 透明的「說明框專用」圖層：點選 K 棒區任何位置，都會顯示當天完整資訊（含成交量）
    fig.add_trace(go.Scatter(x=dates, y=df_view["Close"], mode="markers", name="",
                             marker=dict(size=14, opacity=0), showlegend=False,
                             hovertext=hover_texts, hovertemplate="%{hovertext}<extra></extra>"), row=1, col=1)

    # 價格軸範圍：以 K 棒與均線為主；布林通道超出時於邊緣截斷，避免把 K 棒壓扁
    lo = float(np.nanmin([df_view["Low"].min(), df_view["5MA"].min(), df_view["20MA"].min()]))
    hi = float(np.nanmax([df_view["High"].max(), df_view["5MA"].max(), df_view["20MA"].max()]))
    span = max(hi - lo, 1e-6)
    if show_bb:
        bb_lo, bb_hi = df_view["BB_Lower"].min(), df_view["BB_Upper"].max()
        if pd.notna(bb_lo): lo = min(lo, max(float(bb_lo), lo - 0.15 * span))
        if pd.notna(bb_hi): hi = max(hi, min(float(bb_hi), hi + 0.15 * span))
    pad = (hi - lo) * 0.04
    fig.update_yaxes(range=[lo - pad, hi + pad], row=1, col=1)
    fig.update_yaxes(tickformat="~s", showgrid=False, row=2, col=1)

    _base_layout(fig, dates, height=560, top_margin=44)
    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="h", x=0, xanchor="left", y=1.0, yanchor="bottom",
                    font=dict(size=11), bgcolor=C_BG,
                    itemsizing="constant", tracegroupgap=0),
        hoverlabel=dict(font_size=12, bgcolor="#1B2130", bordercolor="#3A4258", align="left"),
    )
    # 貫穿 K 線與成交量兩個子圖的垂直指示線，讓上下兩格能對齊
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                     spikethickness=1, spikedash="dot", spikecolor="#9AA4B5")
    fig.add_annotation(x=0, y=1, xref="paper", yref="y2 domain", text="成交量(張)",
                       showarrow=False, xanchor="left", yanchor="bottom",
                       font=dict(size=11, color=C_MUTED))
    return fig

def _chip_series(chip_df, dates):
    """回傳 {'外資': Series, '投信': Series, '自營商': Series}，單位：張，並對齊 K 線日期。"""
    d = chip_df.copy()
    d_col = "date" if "date" in d.columns else d.columns[0]
    d[d_col] = d[d_col].astype(str).str[:10]
    if "buy" in d.columns and "sell" in d.columns:
        d["net_buy"] = d["buy"] - d["sell"]
    else:
        d["net_buy"] = d.get("buy_sell", d.iloc[:, -1])
    name = d["name"].astype(str)
    # 外資 = Foreign_Investor + Foreign_Dealer_Self；自營商 = Dealer_self + Dealer_Hedging（不含外資自營商，避免重複計入）
    masks = {
        "外資": name.str.contains("Foreign", case=False, na=False),
        "投信": name.str.contains("Trust", case=False, na=False),
        "自營商": name.str.contains("Dealer", case=False, na=False) & ~name.str.contains("Foreign", case=False, na=False),
    }
    out = {}
    for label, m in masks.items():
        s = d[m].groupby(d_col)["net_buy"].sum() / 1000.0
        out[label] = s.reindex(dates).round(0)
    return out

def plot_chip_chart(chip_df, dates):
    if chip_df.empty or not dates:
        return _empty_fig("尚無三大法人資料")
    series = _chip_series(chip_df, dates)
    titles = []
    for label, s in series.items():
        total = float(np.nansum(s.values))
        titles.append(f"{label}　區間累計 {_fmt_signed(total, ' 張')}")
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.11,
                        subplot_titles=titles)

    def _fmt_net(v):
        if pd.isna(v):
            return "<span style='color:#848E9C'>--</span>"
        col = C_UP if v > 0 else (C_DOWN if v < 0 else "#FFFFFF")
        return f"<span style='color:{col}'>{v:+,.0f} 張</span>"

    # 每一天一段說明文字：三大法人同時列出；三個子圖共用，點任何一格都看得到全部
    hover_texts = []
    for k in range(len(dates)):
        vals = [series[lb].iloc[k] for lb in series]
        total = float(np.nansum(vals)) if not all(pd.isna(vals)) else float("nan")
        lines = [f"<b>{lb}</b>　{_fmt_net(series[lb].iloc[k])}" for lb in series]
        lines.append(f"<b>合計</b>　{_fmt_net(total)}")
        hover_texts.append("<br>".join(lines))

    for i, (label, s) in enumerate(series.items(), start=1):
        vals = s.values
        colors = [C_UP if (pd.notna(v) and v >= 0) else C_DOWN for v in vals]
        fig.add_trace(go.Bar(x=dates, y=vals, name=f"{label}(張)", marker_color=colors,
                             showlegend=False, hoverinfo="skip"), row=i, col=1)
        # 透明的說明框專用圖層（避免說明框出現單一顏色的圖例方塊）
        fig.add_trace(go.Scatter(x=dates, y=vals, mode="markers", name="", showlegend=False,
                                 marker=dict(size=14, opacity=0),
                                 hovertext=hover_texts, hovertemplate="%{hovertext}<extra></extra>"),
                      row=i, col=1)
        fig.update_yaxes(tickformat="~s", row=i, col=1)
    fig.update_traces(marker_line_width=0, selector=dict(type="bar"))
    _base_layout(fig, dates, height=520, top_margin=46)
    _style_subplot_titles(fig)
    fig.update_layout(hoverlabel=dict(font_size=12, bgcolor="#1B2130", bordercolor="#3A4258", align="left"))
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                     spikethickness=1, spikedash="dot", spikecolor="#9AA4B5")
    return fig

def plot_margin_chart(margin_df, dates):
    if margin_df.empty or not dates:
        return _empty_fig("尚無融資融券資料")
    d = margin_df.copy()
    d_col = "date" if "date" in d.columns else d.columns[0]
    d[d_col] = d[d_col].astype(str).str[:10]
    # FinMind 融資欄位本身已是「張」，不需再除以 1000
    if "MarginPurchaseTodayBalance" in d.columns and "MarginPurchaseYesterdayBalance" in d.columns:
        diff = d["MarginPurchaseTodayBalance"] - d["MarginPurchaseYesterdayBalance"]
    else:
        m_buy = [c for c in d.columns if "MarginPurchaseBuy" in c]
        m_sell = [c for c in d.columns if "MarginPurchaseSell" in c]
        if not (m_buy and m_sell):
            return _empty_fig("融資欄位不完整，無法繪圖")
        diff = d[m_buy[0]] - d[m_sell[0]]
        if "MarginPurchaseCashRepayment" in d.columns:
            diff = diff - d["MarginPurchaseCashRepayment"]
    s = pd.Series(diff.values, index=d[d_col].values).groupby(level=0).last().reindex(dates)
    total = float(np.nansum(s.values))
    fig = make_subplots(rows=1, cols=1,
                        subplot_titles=[f"融資增減　區間累計 {_fmt_signed(total, ' 張')}"])
    colors = [C_UP if (pd.notna(v) and v >= 0) else C_DOWN for v in s.values]
    fig.add_trace(go.Bar(x=dates, y=s.values, name="融資增減(張)", marker_color=colors,
                         showlegend=False), row=1, col=1)
    fig.update_yaxes(tickformat="~s")
    fig.update_traces(marker_line_width=0, selector=dict(type="bar"))
    _base_layout(fig, dates, height=300, top_margin=46)
    _style_subplot_titles(fig)
    return fig

def plot_norway_pyramid_chart(norway_df, weeks=26):
    if norway_df is None or norway_df.empty:
        return _empty_fig("尚無股東結構資料（神秘金字塔）")
    df = norway_df.copy()
    df["_dt"] = pd.to_datetime(df["Date"].astype(str), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["_dt"]).sort_values("_dt")
    if weeks and weeks > 0:
        df = df.tail(weeks)
    if df.empty:
        return _empty_fig("尚無股東結構資料（神秘金字塔）")
    dates = df["_dt"].dt.strftime("%Y-%m-%d").tolist()
    ratio = df["Big_Ratio"].astype(float).values
    people = df["Total_People"].astype(float).values

    def _delta(arr):
        return arr[-1] - arr[-2] if len(arr) > 1 else 0.0

    t1 = f"大股東持股率 (%)　最新 {ratio[-1]:.2f}%（較前週 {_delta(ratio):+.2f}）"
    t2 = f"總股東人數 (人)　最新 {people[-1]:,.0f}（較前週 {_delta(people):+,.0f}）"
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.13,
                        row_heights=[0.5, 0.5], subplot_titles=[t1, t2])

    # 說明文字：兩個子圖共用，點任何一格都同時看到大股東持股率與總股東人數（含較前週變化）
    hover_texts = []
    for k in range(len(dates)):
        dr = ratio[k] - ratio[k - 1] if k > 0 else None
        dp = people[k] - people[k - 1] if k > 0 else None
        def _chg(d, fmt):
            if d is None:
                return ""
            col = C_UP if d > 0 else (C_DOWN if d < 0 else "#FFFFFF")
            return f"　<span style='color:{col}'>({format(d, fmt)})</span>"
        hover_texts.append(
            f"<b>大股東持股率</b>　{ratio[k]:.2f}%{_chg(dr, '+.2f')}<br>"
            f"<b>總股東人數</b>　{people[k]:,.0f} 人{_chg(dp, '+,.0f')}"
        )

    # 上：大股東持股率（獨立縱軸、只在最新一點放大標記，避免滿屏圓點）
    sizes = [0] * (len(dates) - 1) + [9]
    fig.add_trace(go.Scatter(
        x=dates, y=ratio, name="大股東持股率(%)", mode="lines+markers",
        line=dict(color="#FFB300", width=2.6),
        marker=dict(size=sizes, color="#FFB300", line=dict(color="#FFFFFF", width=2)),
        showlegend=False, hoverinfo="skip"), row=1, col=1)
    fig.add_trace(go.Scatter(x=dates, y=ratio, mode="markers", name="", showlegend=False,
                             marker=dict(size=14, opacity=0),
                             hovertext=hover_texts, hovertemplate="%{hovertext}<extra></extra>"), row=1, col=1)
    r_lo, r_hi = float(np.nanmin(ratio)), float(np.nanmax(ratio))
    r_pad = max((r_hi - r_lo) * 0.25, 0.1)
    fig.update_yaxes(range=[r_lo - r_pad, r_hi + r_pad], tickformat=".1f", row=1, col=1)

    # 下：總股東人數（高對比亮藍色長條，縱軸不從 0 起算以凸顯變化）
    fig.add_trace(go.Bar(
        x=dates, y=people, name="總股東人數(人)", marker_color="#4FC3F7",
        marker_line_width=0, opacity=0.95, textposition="none",
        showlegend=False, hoverinfo="skip"), row=2, col=1)
    fig.add_trace(go.Scatter(x=dates, y=people, mode="markers", name="", showlegend=False,
                             marker=dict(size=14, opacity=0),
                             hovertext=hover_texts, hovertemplate="%{hovertext}<extra></extra>"), row=2, col=1)
    p_lo, p_hi = float(np.nanmin(people)), float(np.nanmax(people))
    p_span = max(p_hi - p_lo, p_hi * 0.01, 1.0)
    fig.update_yaxes(range=[p_lo - p_span * 0.8, p_hi + p_span * 0.15],
                     tickformat=",.0f", row=2, col=1)

    _base_layout(fig, dates, height=520, top_margin=46)
    fig.update_layout(bargap=0.3,
                      hoverlabel=dict(font_size=12, bgcolor="#1B2130", bordercolor="#3A4258", align="left"))
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                     spikethickness=1, spikedash="dot", spikecolor="#9AA4B5")
    _style_subplot_titles(fig)
    return fig

# -----------------------------------------------------------------------------
# 6. 強效連線容錯 + 平滑降級的 TradingAgents LLM 裁決引擎
# -----------------------------------------------------------------------------
def clean_and_parse_json(raw_text):
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
    
    prompt = f"你是由 TauricResearch/TradingAgents 密集的 AI 多智能體團隊，正在為台股【{stock_id} {stock_name}】（當前收盤價：{latest_price} 元）進行深度投資裁決會議。\n請根據以下數據進行內部團隊辯論與風控審核：\n【技術面數據】：{tech_summary}\n【籌碼與大股東數據】：{chip_summary}\n\n請嚴格輸出一個符合 JSON 格式的字典（不要帶額外的 Markdown 說明），格式包含以下 Key：\n{{\n  \"volume_price_volatility\": \"成交量與價格波動分析說明...\",\n  \"market_stage\": \"目前市場階段評估 (例如：拉回整理、多頭發散、高檔震盪)...\",\n  \"key_price_levels\": \"關鍵價格門檻與支撐壓力位...\",\n  \"signal_analysis\": \"技術指標 (RSI/MACD/KD) 訊號評估...\",\n  \"pattern_recognition\": \"K線圖表模式與型態識別...\",\n  \"trend_strength\": \"趨勢強度與動能綜合評估...\",\n  \"bull_bear_debate\": \"看多研究員 vs 看空研究員 辯論焦點說明...\",\n  \"trader_decision\": \"交易員最終買賣建議與推薦部位比例...\",\n  \"risk_management\": \"風控團隊與投資組合經理最終核准/否決評估、停損價與目標價設定...\"\n}}"
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
    """將 TradingAgents 多 Agent 裁決結果改為由上而下、先結論後說明的單欄立體流式排版"""
    if isinstance(res, str):
        st.info(res)
        return

    card_style = """
        background-color: #1A1E29; 
        border: 1px solid #2A2E3D; 
        border-radius: 12px; 
        padding: 20px; 
        margin-bottom: 18px;
        color: #E0E0E0;
    """

    # -------------------------------------------------------------------------
    # 頂部最顯眼區塊：【先說結論】終極裁決與投資決策結論 (Executive Summary)
    # -------------------------------------------------------------------------
    st.markdown(f"""
        <div style="{card_style}; border: 2px solid #FF5252; background-color: #241920;">
            <div style="color: #FF5252; font-weight: bold; font-size: 18px; margin-bottom: 12px; border-bottom: 1px solid #FF5252; padding-bottom: 8px;">
                🏆 終極裁決與投資決策結論 (Executive Summary)
            </div>
            <div style="font-size: 15px; line-height: 1.7; margin-bottom: 14px;">
                <span style="color: #FFD54F; font-weight: bold; font-size: 16px;">💡 交易員最終買賣建議與推薦部位比例：</span><br>
                <div style="margin-top: 6px; padding: 10px 14px; background-color: #1A1E29; border-radius: 8px; color: #FFF; border-left: 4px solid #FFD54F;">
                    {res.get('trader_decision', '數據解析中...')}
                </div>
            </div>
            <div style="font-size: 15px; line-height: 1.7;">
                <span style="color: #FF8A65; font-weight: bold; font-size: 16px;">🛡️ 風控團隊與投資組合經理最終核准/否決評估（含停損與目標價）：</span><br>
                <div style="margin-top: 6px; padding: 10px 14px; background-color: #1A1E29; border-radius: 8px; color: #FFF; border-left: 4px solid #FF5252;">
                    {res.get('risk_management', '數據解析中...')}
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # 依序加入各順序的詳細說明區塊 (由上而下縱向排版)
    # -------------------------------------------------------------------------
    
    # 1. 目前市場階段與關鍵價格門檻
    st.markdown(f"""
        <div style="{card_style}">
            <div style="color: #64B5F6; font-weight: bold; font-size: 16px; margin-bottom: 12px; border-bottom: 1px solid #2A2E3D; padding-bottom: 6px;">
                1. 🧭 目前市場階段評估與關鍵價格門檻
            </div>
            <div style="font-size: 14.5px; line-height: 1.7; margin-bottom: 12px;">
                <b style="color: #90CAF9;">【市場階段評估】：</b><br>
                <div style="margin-top: 4px; padding-left: 8px;">{res.get('market_stage', '數據解析中...')}</div>
            </div>
            <div style="font-size: 14.5px; line-height: 1.7;">
                <b style="color: #A5D6A7;">【關鍵價格門檻與支撐壓力位】：</b><br>
                <div style="margin-top: 4px; padding-left: 8px;">{res.get('key_price_levels', '數據解析中...')}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # 2. 成交量與價格波動與趨勢動能
    st.markdown(f"""
        <div style="{card_style}">
            <div style="color: #FFB74D; font-weight: bold; font-size: 16px; margin-bottom: 12px; border-bottom: 1px solid #2A2E3D; padding-bottom: 6px;">
                2. ⚡ 成交量、價格波動與趨勢動能評估
            </div>
            <div style="font-size: 14.5px; line-height: 1.7; margin-bottom: 12px;">
                <b style="color: #FFE082;">【成交量與價格波動分析】：</b><br>
                <div style="margin-top: 4px; padding-left: 8px;">{res.get('volume_price_volatility', '數據解析中...')}</div>
            </div>
            <div style="font-size: 14.5px; line-height: 1.7;">
                <b style="color: #FFF59D;">【趨勢強度與動能評估】：</b><br>
                <div style="margin-top: 4px; padding-left: 8px;">{res.get('trend_strength', '數據解析中...')}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # 3. 技術指標與型態特徵分析
    st.markdown(f"""
        <div style="{card_style}">
            <div style="color: #4DD0E1; font-weight: bold; font-size: 16px; margin-bottom: 12px; border-bottom: 1px solid #2A2E3D; padding-bottom: 6px;">
                3. 🎯 技術指標訊號與 K 線型態識別
            </div>
            <div style="font-size: 14.5px; line-height: 1.7; margin-bottom: 12px;">
                <b style="color: #80DEEA;">【技術指標 (RSI/MACD/KD) 訊號評估】：</b><br>
                <div style="margin-top: 4px; padding-left: 8px;">{res.get('signal_analysis', '數據解析中...')}</div>
            </div>
            <div style="font-size: 14.5px; line-height: 1.7;">
                <b style="color: #B2EBF2;">【K 線圖表模式與型態識別】：</b><br>
                <div style="margin-top: 4px; padding-left: 8px;">{res.get('pattern_recognition', '數據解析中...')}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # 4. 多空研究員辯論焦點
    st.markdown(f"""
        <div style="{card_style}">
            <div style="color: #BA68C8; font-weight: bold; font-size: 16px; margin-bottom: 12px; border-bottom: 1px solid #2A2E3D; padding-bottom: 6px;">
                4. ⚔️ 看多研究員 vs 看空研究員 正反辯論焦點 (Bull vs Bear Debate)
            </div>
            <div style="font-size: 14.5px; line-height: 1.7; padding-left: 8px;">
                {res.get('bull_bear_debate', '數據解析中...')}
            </div>
        </div>
    """, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 7. 共用診斷渲染引擎（行動裝置友善版）
# -----------------------------------------------------------------------------
VIEW_OPTIONS = {"近 20 日": 20, "近 40 日": 40, "近 60 日": 60, "選定區間全部": 0}
WEEK_OPTIONS = {"13 週": 13, "26 週": 26, "52 週": 52}

def _bt_max_drawdown(curve):
    if not curve:
        return np.nan
    arr = np.asarray(curve, dtype=float)
    peaks = np.maximum.accumulate(arr)
    return float(np.min(arr / peaks - 1.0) * 100)


def _historical_verdict_score(df):
    close = pd.to_numeric(df["Close"], errors="coerce")
    ret20 = close.pct_change(20)
    vol20 = close.pct_change().rolling(20).std() * np.sqrt(252)
    score = pd.Series(50.0, index=df.index)
    score += np.where(df["5MA"] > df["20MA"], 15, -15)
    score += np.where(close > df["20MA"], 10, -10)
    score += np.where((close >= df["BB_Lower"]) & (close <= df["BB_Upper"]), 5, -5)
    score += np.where(ret20 > 0, 10, -10)
    score += np.where(vol20 < 0.45, 10, -10)
    return pd.Series(np.clip(score, 0, 100), index=df.index)


def run_verdict_backtest(price_df, end_date):
    df = calculate_indicators(price_df).copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    for c in ("Open", "High", "Low", "Close", "5MA", "20MA", "BB_Upper", "BB_Lower"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Date", "Open", "High", "Low", "Close", "5MA", "20MA", "BB_Upper", "BB_Lower"]).sort_values("Date").reset_index(drop=True)
    if df.empty:
        return []
    df["裁決分數"] = _historical_verdict_score(df)
    sample_start = pd.Timestamp(end_date) - pd.DateOffset(years=1)
    buy_cost, sell_cost = 0.001425 + 0.001, 0.001425 + 0.003 + 0.001
    rows = []
    for label, horizon in (("5天", 5), ("10天", 10), ("20天", 20), ("60D", 60), ("一年", 252)):
        returns, holds, i = [], [], 0
        while i < len(df) - horizon - 1:
            if df.loc[i, "Date"] >= sample_start and df.loc[i, "裁決分數"] >= 60:
                entry_i = i + 1
                planned = min(entry_i + horizon, len(df) - 1)
                entry = df.loc[entry_i, "Open"] * (1 + buy_cost)
                peak, exit_i, exit_price = entry, planned, None
                for j in range(entry_i, planned + 1):
                    peak = max(peak, df.loc[j, "High"])
                    stop, trail = entry * 0.90, peak * 0.92
                    if df.loc[j, "Low"] <= stop:
                        exit_i, exit_price = j, min(df.loc[j, "Open"], stop)
                        break
                    if j > entry_i and df.loc[j, "Low"] <= trail:
                        exit_i, exit_price = j, min(df.loc[j, "Open"], trail)
                        break
                    if j > entry_i and df.loc[j - 1, "裁決分數"] < 40:
                        exit_i, exit_price = j, df.loc[j, "Open"]
                        break
                if exit_price is None:
                    exit_price = df.loc[exit_i, "Close"]
                r = exit_price * (1 - sell_cost) / entry - 1
                returns.append(float(r)); holds.append(exit_i - entry_i + 1)
                i = exit_i + 1
            else:
                i += 1
        wins = [r for r in returns if r > 0]; losses = [r for r in returns if r <= 0]
        curve = [1.0] + (np.cumprod([1 + r for r in returns]).tolist() if returns else [])
        std = np.std(returns, ddof=1) if len(returns) > 1 else np.nan
        pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else (np.inf if wins else np.nan)
        rows.append({"區間": label, "交易數": len(returns),
                     "勝率": len(wins)/len(returns)*100 if returns else np.nan,
                     "平均報酬": np.mean(returns)*100 if returns else np.nan,
                     "累積報酬": (curve[-1]-1)*100 if returns else np.nan,
                     "最大回撤": _bt_max_drawdown(curve),
                     "盈虧因子": pf,
                     "夏普比率": np.mean(returns)/std*np.sqrt(max(252/horizon, 1)) if pd.notna(std) and std > 0 else np.nan,
                     "平均持有日": np.mean(holds) if holds else np.nan})
    return rows


def render_verdict_backtest(results, stock_id, stock_name):
    st.markdown(f"### 🧪 {stock_id}-{stock_name}終極裁決歷史回測")
    with st.expander("📘 回測依據與交易規則", expanded=False):
        st.markdown("""
- 以 5MA/20MA、收盤相對 20MA、布林通道、20日動能與20日波動率計算 0 至 100 分的歷史裁決分數。
- 60 分以上於下一交易日開盤進場；低於 40 分、固定停損 10%、高點回落 8% 或到期時出場。
- 測試 5、10、20、60、252 個交易日持有區間；樣本使用截止日前最近一年，交易不重疊。
- 已計入買賣手續費各 0.1425%、賣出證交稅 0.3%，以及買賣各 0.1% 滑價。
- 回測只使用價格型結構化裁決，不會把今日 AI 文字或今日籌碼回填到過去，避免前視偏誤。
        """)
    if not results or all(r["交易數"] == 0 for r in results):
        st.info("最近一年沒有足夠的裁決進場訊號可供回測。")
        return
    df = pd.DataFrame(results)
    for c in ("勝率", "平均報酬", "累積報酬", "最大回撤"):
        df[c] = df[c].map(lambda v: "--" if pd.isna(v) else (f"{v:.1f}%" if c == "勝率" else f"{v:+.2f}%"))
    for c in ("盈虧因子", "夏普比率", "平均持有日"):
        df[c] = df[c].map(lambda v: "--" if pd.isna(v) else ("∞" if np.isinf(v) else f"{v:.2f}"))
    st.markdown("""<style>.bt{width:100%;border-collapse:collapse;font-size:12px;table-layout:fixed}.bt th,.bt td{padding:7px 3px;border:1px solid #444;text-align:center;word-break:break-word}.bt th{background:#302e2b}@media(max-width:640px){.bt{font-size:9px}.bt th,.bt td{padding:5px 1px}}</style>""", unsafe_allow_html=True)
    main = df[["區間","交易數","勝率","平均報酬","累積報酬","最大回撤"]]
    st.markdown(main.to_html(index=False, classes="bt", border=0, escape=True), unsafe_allow_html=True)
    with st.expander("查看進階指標"):
        adv = df[["區間","盈虧因子","夏普比率","平均持有日"]]
        st.markdown(adv.to_html(index=False, classes="bt", border=0, escape=True), unsafe_allow_html=True)


def render_diagnosis_section(stock_id, stock_name, start_date, end_date, token):
    with st.spinner(f"正在抓取 {stock_id} {stock_name} 的歷史行情與籌碼資料..."):
        s_str = start_date.strftime("%Y-%m-%d")
        e_str = end_date.strftime("%Y-%m-%d")
        b_str = (start_date - timedelta(days=120)).strftime("%Y-%m-%d")

        price_df = fetch_stock_history_cached(stock_id, b_str, e_str, token)
        chip_df = fetch_chip_history_cached(stock_id, b_str, e_str, token)
        margin_df = fetch_margin_history_cached(stock_id, b_str, e_str, token)
        norway_df = get_norway_big_shareholders(stock_id)
        backtest_start = (end_date - timedelta(days=550)).strftime("%Y-%m-%d")
        backtest_df = fetch_stock_history_cached(stock_id, backtest_start, e_str, token)

    if price_df.empty:
        st.error(f"❌ 無法取得 {stock_id} {stock_name} 的歷史 K 線資料。FinMind 與 Yahoo Finance 備援均未成功。")
        errors = price_df.attrs.get("errors", [])
        if errors:
            with st.expander("查看資料來源錯誤", expanded=True):
                for message in errors:
                    st.code(message)
        st.info(f"查詢期間：{b_str} 至 {e_str}｜FinMind Token：{'已設定' if token else '未設定'}")
        if st.button("🧹 清除價格快取並重試", key=f"clear_price_cache_{stock_id}"):
            try:
                if os.path.exists(PRICE_DB):
                    os.remove(PRICE_DB)
            except Exception as exc:
                safe_log("clear price sqlite", exc)
            st.rerun()
        return

    st.markdown(f"#### 📊 {stock_id} {stock_name}")
    source = price_df.attrs.get("source", "未知來源")
    latest_data_date = pd.to_datetime(price_df["date"], errors="coerce").max()
    st.caption(f"歷史行情來源：{source}｜最新資料日：{latest_data_date:%Y-%m-%d}")

    # --- 圖表顯示設定（手機上一眼可調整；預設 40 日，K 棒與柱體寬度最舒適） ---
    view_label = st.radio("圖表顯示區間", list(VIEW_OPTIONS.keys()), index=1,
                          horizontal=True, key="view_days_radio")
    show_bb = st.checkbox("顯示布林通道", value=True, key="show_bb_checkbox")
    n_bars = VIEW_OPTIONS[view_label]

    df_view = prepare_price_view(price_df, s_str, n_bars)
    if df_view.empty:
        st.warning("所選日期區間內沒有交易資料，請調整左側的開始/結束日期。")
        return
    dates = df_view["Date"].tolist()
    last = df_view.iloc[-1]
    prev_close = df_view["Close"].iloc[-2] if len(df_view) > 1 else last["Close"]
    chg = last["Close"] - prev_close
    chg_color = C_UP if chg > 0 else (C_DOWN if chg < 0 else "#FFFFFF")
    st.markdown(
        f"<div style='color:{C_MUTED};font-size:0.85rem;line-height:1.6;'>"
        f"{dates[0]} ～ {dates[-1]}（{len(dates)} 個交易日）　最新收盤 "
        f"<b style='color:{chg_color};font-size:1rem;'>{last['Close']:,.2f}</b> "
        f"<span style='color:{chg_color};'>{chg:+,.2f}</span></div>",
        unsafe_allow_html=True,
    )

    chart_title(f"📈 {stock_id} {stock_name} 股價 K 線與布林通道")
    show_chart(plot_main_kline_chart(df_view, show_bb=show_bb))

    chart_title("🏛️ 三大法人每日淨買賣超 (張 · 紅買綠賣)")
    if chip_df.empty:
        st.warning("三大法人資料目前暫時無法取得。個股價格、K線與回測仍可正常使用；籌碼裁決將標示為資料不足，不會當成負分。")
        if st.session_state.get("show_data_diagnostics", False) and chip_df.attrs.get("errors"):
            with st.expander("三大法人資料診斷"):
                for message in chip_df.attrs["errors"]:
                    st.code(message)
    else:
        st.caption(f"資料來源：{chip_df.attrs.get('source', 'FinMind')}。官方備援僅提供最新快照，完整歷史仍以 FinMind 為主。")
    st.caption("三家法人各自使用獨立縱軸，投信、自營商的小額買賣也能看得清楚。")
    show_chart(plot_chip_chart(chip_df, dates))

    chart_title("💳 融資餘額每日增減 (張 · 紅增綠減)")
    if margin_df.empty:
        st.warning("融資融券資料目前暫時無法取得。個股價格、K線與回測仍可正常使用；籌碼裁決將標示為資料不足，不會當成負分。")
        if st.session_state.get("show_data_diagnostics", False) and margin_df.attrs.get("errors"):
            with st.expander("融資融券資料診斷"):
                for message in margin_df.attrs["errors"]:
                    st.code(message)
    else:
        st.caption(f"資料來源：{margin_df.attrs.get('source', 'FinMind')}。官方備援僅提供最新快照，完整歷史仍以 FinMind 為主。")
    show_chart(plot_margin_chart(margin_df, dates))

    chart_title(f"🔺 {stock_id} {stock_name} 神秘金字塔：大股東持股率 vs 總股東人數")
    week_label = st.radio("股東結構顯示週數", list(WEEK_OPTIONS.keys()), index=1,
                          horizontal=True, key="pyramid_weeks_radio")
    show_chart(plot_norway_pyramid_chart(norway_df, WEEK_OPTIONS[week_label]))
    st.caption("總股東人數縱軸不從 0 起算，用以凸顯增減趨勢；請以標題列的最新數字為準。")

    st.markdown("---")
    st.markdown("## 🤖 TradingAgents 多 Agent 投資診斷會議與終極裁決")
    with st.spinner("TradingAgents 團隊（技術員/多空研究員/交易員/風控經理）連線分析中..."):
        df_calc = calculate_indicators(price_df)
        latest = df_calc.iloc[-1]
        tech_info = f"收盤價:{latest['Close']}, 5MA:{latest['5MA']}, 20MA:{latest['20MA']}, 布林上軌:{latest['BB_Upper']}, 布林下軌:{latest['BB_Lower']}"
        chip_info = f"三大法人與融資資料長度: {len(chip_df)}天"

        ai_res, err = call_trading_agents_team(stock_id, stock_name, latest['Close'], tech_info, chip_info)
        if err:
            st.error(err)
        else:
            render_trading_agents_cards(ai_res)

    st.markdown("---")
    render_verdict_backtest(run_verdict_backtest(backtest_df, end_date), stock_id, stock_name)

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
# 9. 頂部四大指數獨立區塊（僅在盤中交易時間 60 秒自動重新整理）
# -----------------------------------------------------------------------------
# 固定每 TICKER_REFRESH_SECONDS 秒執行一次（先前僅在「載入頁面當下」為盤中時才會自動更新；
# 改為固定間隔後，頁面在開盤前就開著也會在 08:45 後自動開始更新，非盤中則只讀快取、不對外請求）
@st.fragment(run_every=TICKER_REFRESH_SECONDS)
def render_market_ticker():
    # 先取資料、最後才畫出元件：取資料期間畫面上維持上一次的內容，不會清空或閃爍
    refresh_clicked = bool(st.session_state.get('refresh_market_quotes', False))
    market_data, fetched_ts = fetch_realtime_market_data(finmind_token, force=refresh_clicked)

    cards = []
    for key, title in (('taiex', '加權指數 (TAIEX)'), ('tpex', '櫃買指數 (TPEX)'),
                       ('futures', '台指近月 (TX)'), ('tsmc', '台積電 (2330)')):
        d = market_data.get(key)
        if d:
            change = d.get('change')
            color = '#FF5252' if change is not None and change > 0 else '#00E676' if change is not None and change < 0 else '#FFFFFF'
            prev_close = d['val'] - change if change is not None else None
            if change is None:
                change_text = '漲跌資料未提供'
            elif prev_close:
                change_text = f'{change:+,.2f} <small>({change / prev_close * 100:+.2f}%)</small>'
            else:
                change_text = f'{change:+,.2f}'
            label = ' | '.join(str(d.get(k, '')) for k in ('date', 'time', 'source', 'contract', 'session') if d.get(k))
            value = f"{d['val']:,.2f}"
        else:
            color, value, change_text = '#848E9C', '--', '資料取得失敗／暫無資料'
            label = market_data.get('_errors', {}).get(key, '請稍後重新整理')
        cards.append(
            f'<div class="tk-card" style="border:1px solid {color};">'
            f'<div class="tk-title">{html.escape(title)}</div>'
            f'<div class="tk-val" style="color:{color};">{value}</div>'
            f'<div class="tk-chg" style="color:{color};">{change_text}</div>'
            f'<div class="tk-meta">{html.escape(label)}</div>'
            f'</div>'
        )

    # 第五張卡片：上市／上櫃漲停、跌停家數（紅漲綠跌）
    br = market_data.get('breadth')
    if br:
        def _n(side, kind):
            more = br[side].get(f'{kind}_more')
            return f"{br[side][kind]}{'+' if more else ''}"
        rows_html = ''.join(
            f'<div class="lm-row"><span class="lm-name">{name}</span>'
            f'<span>漲停 <b style="color:#FF5252;">{_n(side, "up")}</b></span>'
            f'<span>跌停 <b style="color:#00E676;">{_n(side, "down")}</b></span></div>'
            for side, name in (('listed', '上市'), ('otc', '上櫃')))
        label = ' | '.join(str(br.get(k, '')) for k in ('date', 'time', 'source') if br.get(k))
        cards.append(f'<div class="tk-card wide" style="border:1px solid #848E9C;">'
                     f'<div class="tk-title">漲停／跌停家數（一般股票，不含 ETF）</div>{rows_html}'
                     f'<div class="tk-meta">{html.escape(label)}</div></div>')
    else:
        cards.append('<div class="tk-card wide" style="border:1px solid #848E9C;">'
                     '<div class="tk-title">漲停／跌停家數</div><div class="tk-val" style="color:#848E9C;">--</div>'
                     f'<div class="tk-meta">{html.escape(market_data.get("_errors", {}).get("breadth", "請稍後重新整理"))}</div></div>')
    st.markdown(f'<div class="tk-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

    # 上市類股漲跌幅排行（前 10 名）
    sec = market_data.get('sectors')
    sector_dir = st.session_state.get('sector_rank_dir', '強勢前 10')
    if sec:
        ranked = sorted(sec['rows'], key=lambda r: r['pct'], reverse=(sector_dir == '強勢前 10'))[:10]
        peak = max(abs(r['pct']) for r in sec['rows']) or 1
        bars = ''
        for i, r in enumerate(ranked, 1):
            c = '#FF5252' if r['pct'] > 0 else '#00E676' if r['pct'] < 0 else '#FFFFFF'
            bars += (f'<div class="sr-row"><span class="sr-rank">{i}</span>'
                     f'<span class="sr-name">{html.escape(r["name"])}</span>'
                     f'<div class="sr-bar"><div class="sr-fill" style="width:{max(abs(r["pct"]) / peak * 100, 3):.0f}%;background:{c};"></div></div>'
                     f'<span class="sr-pct" style="color:{c};">{r["pct"]:+.2f}%</span></div>')
        label = ' | '.join(str(sec.get(k, '')) for k in ('date', 'time', 'source') if sec.get(k))
        total = len(SECTOR_CODES)
        coverage = (f'已涵蓋全部 {total} 個上市類股' if len(sec['rows']) >= total
                    else f'僅取得 {len(sec["rows"])}／{total} 個類股，其餘暫無資料')
        label = f'{label} | {coverage}'
        st.markdown(f'<div class="sr-box"><div class="sr-head">上市類股漲跌幅排行 {html.escape(sector_dir)}</div>{bars}'
                    f'<div class="tk-meta">{html.escape(label)}</div></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="sr-box"><div class="sr-head">上市類股漲跌幅排行</div>'
                    f'<div class="tk-meta">{html.escape(market_data.get("_errors", {}).get("sectors", "請稍後重新整理"))}</div></div>',
                    unsafe_allow_html=True)
    st.radio('排行方向', ['強勢前 10', '弱勢前 10'], horizontal=True, key='sector_rank_dir', label_visibility='collapsed')

    note_text = ''
    if fetched_ts:
        updated = datetime.fromtimestamp(fetched_ts, TAIPEI).strftime('%H:%M:%S')
        mode = f'盤中每 {TICKER_REFRESH_SECONDS} 秒自動更新' if is_taiwan_market_open() else '目前非交易時段，不頻繁更新'
        note_text = f'行情最後抓取 {updated}｜{mode}｜各卡片最下方為該筆資料的時間與來源'
    st.markdown(f'<div class="tk-note">{note_text}</div>', unsafe_allow_html=True)
    st.button('重新取得行情', key='refresh_market_quotes')


# -----------------------------------------------------------------------------
# 手機觸控「滑過即顯示」：Plotly 預設只有點擊才會在觸控裝置顯示說明框。
# 這段腳本讓手指在圖表上水平滑動時，持續顯示游標所在日期的數值（垂直滑動仍可正常捲動頁面）。
# 腳本只安裝一次，之後新產生的圖表也會自動套用。
# -----------------------------------------------------------------------------
TOUCH_HOVER_JS = r"""
(function () {
  var P;
  try { P = window.parent; void P.document.body; } catch (e) { P = window; }
  var D = P.document;
  if (P.__plotlyTouchHover) { return; }
  P.__plotlyTouchHover = true;

  // 圖表上：垂直滑動仍可捲動頁面；水平滑動交給圖表顯示數值
  var style = D.createElement('style');
  style.textContent =
    'div[data-testid="stPlotlyChart"], div[data-testid="stPlotlyChart"] .js-plotly-plot,' +
    'div[data-testid="stPlotlyChart"] .plotly .nsewdrag, div[data-testid="stPlotlyChart"] .plotly .draglayer,' +
    'div[data-testid="stPlotlyChart"] .plotly .main-svg { touch-action: pan-y !important; }';
  D.head.appendChild(style);

  function show(ev) {
    var t = ev.touches && ev.touches[0];
    if (!t) { return; }
    var el = D.elementFromPoint(t.clientX, t.clientY);
    if (!el || !el.closest || !el.closest('.js-plotly-plot')) { return; }
    el.dispatchEvent(new P.MouseEvent('mousemove', {
      bubbles: true, cancelable: true, view: P,
      clientX: t.clientX, clientY: t.clientY, screenX: t.screenX, screenY: t.screenY
    }));
  }
  function start(ev) {
    var tg = ev.target;
    if (tg && tg.closest && tg.closest('.js-plotly-plot')) {
      ev.stopPropagation();   // 不讓 Plotly 進入「拖曳」狀態，否則拖曳期間它不會顯示說明框
    }
    show(ev);
  }
  D.addEventListener('touchstart', start, { passive: true, capture: true });
  D.addEventListener('touchmove', show, { passive: true, capture: true });
})();
"""
try:
    import streamlit.components.v1 as _components
    _components.html("<script>" + TOUCH_HOVER_JS + "</script>", height=0)
except Exception as exc:
    safe_log("touch hover script", exc)

render_market_ticker()
st.markdown("---")

def _strategy_signal_frame(price_df, strategy_name, chip_df=None, margin_df=None):
    df = calculate_indicators(price_df).copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    for c in ("Open", "High", "Low", "Close", "Trading_Volume", "20MA"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["VolumeLots"] = df.get("Trading_Volume", 0) / 1000
    df["DayChange"] = np.where(df["Open"] > 0, (df["Close"] / df["Open"] - 1) * 100, np.nan)
    df["MA20Slope5"] = (df["20MA"] / df["20MA"].shift(5) - 1) * 100
    if strategy_name == "短線強勢爆發":
        df["Signal"] = (df["DayChange"] >= 2.0) & (df["VolumeLots"] >= 1500) & (df["Close"] > df["Open"])
    elif strategy_name == "波段多頭排列":
        df["Signal"] = (df["VolumeLots"] >= 1000) & df["DayChange"].between(0.5, 3.0) & (df["Close"] >= df["Open"])
    else:
        # 飆風向上歷史訊號：價格條件完整；籌碼資料能取得時再疊加 1/5/10 日及融資下降。
        signal = (df["VolumeLots"] > 1000) & (df["MA20Slope5"] > 1.0)
        if chip_df is not None and not chip_df.empty:
            c = chip_df.copy()
            dc = "date" if "date" in c.columns else "Date"
            c["Date"] = pd.to_datetime(c[dc], errors="coerce")
            if "buy" in c.columns and "sell" in c.columns:
                c["net"] = pd.to_numeric(c["buy"], errors="coerce").fillna(0) - pd.to_numeric(c["sell"], errors="coerce").fillna(0)
            else:
                c["net"] = _num_series(c, ["buy_sell", "net_buy_sell", "NetBuySell"]).fillna(0)
            daily = c.groupby("Date")["net"].sum().sort_index()
            chip = pd.DataFrame({"Chip1": daily, "Chip5": daily.rolling(5).sum(), "Chip10": daily.rolling(10).sum()})
            df = df.merge(chip, left_on="Date", right_index=True, how="left")
            signal &= (df["Chip1"] > 0) & (df["Chip5"] > 0) & (df["Chip10"] > 0)
        if margin_df is not None and not margin_df.empty:
            m = margin_df.copy(); dc = "date" if "date" in m.columns else "Date"
            m["Date"] = pd.to_datetime(m[dc], errors="coerce")
            bal = _num_series(m, ["MarginPurchaseTodayBalance", "MarginPurchaseBalance", "margin_purchase_today_balance"])
            m["MarginBalance"] = bal
            mm = m.groupby("Date")["MarginBalance"].last().sort_index()
            df = df.merge(mm.rename("MarginBalance"), left_on="Date", right_index=True, how="left")
            signal &= df["MarginBalance"] < df["MarginBalance"].shift(5)
        df["Signal"] = signal.fillna(False)
    return df.sort_values("Date").reset_index(drop=True)


def _backtest_strategy_stock(stock_id, strategy_name, start_date, end_date, token, holding_days):
    price = fetch_stock_history_cached(stock_id, start_date, end_date, token)
    if price.empty:
        return []
    chip = margin = pd.DataFrame()
    if strategy_name == "飆風向上":
        chip = fetch_chip_history_cached(stock_id, start_date, end_date, token)
        margin = fetch_margin_history_cached(stock_id, start_date, end_date, token)
    df = _strategy_signal_frame(price, strategy_name, chip, margin)
    trades, i = [], 0
    buy_cost, sell_cost = 0.001425 + 0.001, 0.001425 + 0.003 + 0.001
    while i < len(df) - holding_days - 1:
        if bool(df.loc[i, "Signal"]):
            entry_i, exit_i = i + 1, min(i + 1 + holding_days, len(df) - 1)
            entry = df.loc[entry_i, "Open"] * (1 + buy_cost)
            exit_price = df.loc[exit_i, "Close"] * (1 - sell_cost)
            if pd.notna(entry) and entry > 0 and pd.notna(exit_price):
                trades.append({"股票代碼": stock_id, "訊號日": df.loc[i, "Date"],
                               "進場日": df.loc[entry_i, "Date"], "出場日": df.loc[exit_i, "Date"],
                               "報酬": float(exit_price / entry - 1)})
            i = exit_i + 1
        else:
            i += 1
    return trades


def run_market_strategy_backtest(df_candidates, strategy_name, token):
    """Backtest current scan cohort, capped at 10 stocks to keep Streamlit Cloud responsive."""
    if df_candidates is None or df_candidates.empty:
        return pd.DataFrame(), {"message": "請先執行市場掃描，取得候選股票後再回測。"}
    end = taipei_now().date()
    start = end - timedelta(days=550)
    ranked = df_candidates.sort_values("綜合分數", ascending=False) if "綜合分數" in df_candidates.columns else df_candidates
    ids = ranked["股票代碼"].astype(str).drop_duplicates().head(10).tolist()
    rows = []
    for horizon in (5, 10, 20):
        trades = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_backtest_strategy_stock, sid, strategy_name,
                                   start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), token, horizon) for sid in ids]
            for f in futures:
                try: trades.extend(f.result(timeout=35))
                except Exception as exc: safe_log("strategy backtest stock", exc)
        rs = [x["報酬"] for x in trades]; wins = [r for r in rs if r > 0]; losses = [r for r in rs if r <= 0]
        curve = [1.0] + (np.cumprod([1+r for r in rs]).tolist() if rs else [])
        rows.append({"持有區間": f"{horizon}天", "回測股票": len(ids), "交易數": len(rs),
                     "勝率": len(wins)/len(rs)*100 if rs else np.nan,
                     "平均報酬": np.mean(rs)*100 if rs else np.nan,
                     "累積報酬": (curve[-1]-1)*100 if rs else np.nan,
                     "最大回撤": _bt_max_drawdown(curve),
                     "盈虧因子": sum(wins)/abs(sum(losses)) if losses and sum(losses) != 0 else (np.inf if wins else np.nan)})
    note = "以本次掃描結果前 10 檔、最近約一年資料回測；訊號日收盤確認，下一交易日開盤進場，交易不重疊。"
    if strategy_name == "飆風向上":
        note += " 集保戶數缺乏逐日歷史資料，因此歷史回測不納入集保條件；法人或融資歷史取不到時，採價格條件代理並於結果中視為限制。"
    return pd.DataFrame(rows), {"message": note, "stocks": ids}


def render_market_strategy_backtest(table, strategy_name, meta):
    st.markdown(f"### 🧪 {strategy_name}策略歷史回測")
    st.caption(meta.get("message", ""))
    if table is None or table.empty or table["交易數"].sum() == 0:
        st.info("目前候選股票在回測期間沒有足夠交易訊號。")
        return
    view = table.copy()
    for c in ("勝率", "平均報酬", "累積報酬", "最大回撤"):
        view[c] = view[c].map(lambda v: "--" if pd.isna(v) else (f"{v:.1f}%" if c == "勝率" else f"{v:+.2f}%"))
    view["盈虧因子"] = view["盈虧因子"].map(lambda v: "--" if pd.isna(v) else ("∞" if np.isinf(v) else f"{v:.2f}"))
    st.dataframe(view, hide_index=True, use_container_width=True)


# -----------------------------------------------------------------------------
# 10. 主頁面模式邏輯
# -----------------------------------------------------------------------------
if app_mode == "全市場自動選股版":
    st.markdown("## 🔍 全市場策略篩選 (Market Screener)")
    strategy_choice = st.radio(
        "選擇篩選策略：",
        ["飆風向上", "短線強勢爆發", "波段多頭排列"],
        horizontal=True,
        key="market_screener_strategy",
    )

    if strategy_choice == "飆風向上":
        st.info("📌 **飆風向上**：沿用目前的快速三階段策略。先篩成交量大於 1,000 張，再優先驗證月線近 5 個交易日斜率 > 1%；接著檢查主力 1／5／10 日皆為正、近期主力大買與融資下降；最後驗證集保戶數下降。")
    elif strategy_choice == "短線強勢爆發":
        st.info("📌 **短線強勢爆發**：恢復先前版本條件，當日漲幅至少 2%、成交量至少 1,500 張，且收盤價高於開盤價；依漲幅由高至低顯示前 30 檔。")
    else:
        st.info("📌 **波段多頭排列**：維持目前條件不變，成交量至少 1,000 張、當日漲幅介於 0.5% 至 3%，且收盤價不低於開盤價；依成交量由高至低顯示前 30 檔。")

    if st.button("🚀 開始連線證交所全市場掃描", use_container_width=True):
        st.session_state["screener_running"] = True
        st.session_state.pop("screener_res", None)
        st.session_state.pop("screener_status", None)
        # A manual click always means a fresh scan; do not instantly reuse a cached empty result.
        run_market_screener.clear()
        progress = st.progress(5, text="取得證交所全市場行情並建立候選池...")
        try:
            if strategy_choice == "飆風向上":
                progress.progress(20, text="飆風向上：優先檢查成交量前 40 檔的月線斜率 > 1%...")
            elif strategy_choice == "短線強勢爆發":
                progress.progress(40, text="短線強勢爆發：檢查漲幅、成交量與紅 K 條件...")
            else:
                progress.progress(40, text="波段多頭排列：檢查成交量、漲幅區間與紅 K 條件...")
            result = run_market_screener(STOCK_DICT, strategy_choice)
            progress.progress(100, text="掃描完成")
            st.session_state["screener_res"] = result
            st.session_state["screener_status"] = result.attrs.get("scan_status", {"ok": True, "message": "掃描完成"})
        except Exception as exc:
            st.session_state["screener_res"] = pd.DataFrame()
            st.session_state["screener_status"] = {"ok": False, "message": f"掃描程式發生錯誤：{type(exc).__name__}: {exc}"}
            safe_log("market screener UI", exc)
        finally:
            st.session_state["screener_running"] = False
            time.sleep(0.2)
            st.rerun()

    df_res = st.session_state.get("screener_res", pd.DataFrame())
    scan_status = st.session_state.get("screener_status")
    if scan_status:
        message = scan_status.get("message", "掃描完成")
        if scan_status.get("ok", False):
            st.info(message)
        else:
            st.error(message)
        counts = scan_status.get("counts", {})
        if counts:
            st.caption("｜".join(f"{k}：{v} 檔" for k, v in counts.items()))
        if scan_status.get("timeouts", 0):
            st.warning(f"有 {scan_status['timeouts']} 個外部查詢超過階段時限，已跳過，不影響已完成結果。")

    if not df_res.empty:
        st.success(f"🎉 掃描完成！共挑選出 {len(df_res)} 檔達標個股。")
        display_cols = [c for c in ["策略排名", "股票代碼", "股票名稱", "綜合分數", "選股依據",
                                         "今日收盤", "漲幅(%)", "成交量(張)", "月線斜率(%)",
                                         "主力1日", "主力5日", "主力10日", "近期主力大買",
                                         "近期散戶大賣", "集保戶數大減"] if c in df_res.columns]
        st.dataframe(df_res[display_cols], hide_index=True, use_container_width=True)

        top10 = df_res.sort_values("綜合分數", ascending=False).head(10) if "綜合分數" in df_res.columns else df_res.head(10)
        st.markdown("### 🏅 回測採用前十檔與選股依據")
        st.caption("前十檔依本策略綜合分數由高至低選取。綜合分數採當次候選池內百分位排名，因此是相對強度分數，不是預測報酬率。")
        top10_cols = [c for c in ["策略排名", "股票代碼", "股票名稱", "綜合分數", "選股依據"] if c in top10.columns]
        st.dataframe(top10[top10_cols], hide_index=True, use_container_width=True)

        with st.expander("查看綜合分數計算方式"):
            if strategy_choice == "飆風向上":
                st.markdown("**月線斜率 40% + 主力5日 25% + 主力10日 20% + 成交量 15%**。所有分項先轉為當次候選池百分位分數。")
            elif strategy_choice == "短線強勢爆發":
                st.markdown("**當日漲幅 50% + 成交量 30% + 紅K實體強度 20%**。目前紅K實體以當日開收漲幅作為代理值。")
            else:
                st.markdown("**成交量 50% + 波段漲幅品質 35% + 當日漲幅 15%**。波段漲幅品質偏好接近 2% 且仍位於 0.5% 至 3% 條件內的股票。")

        st.markdown("### 🧪 策略歷史回測")
        st.caption("回測以本次掃描結果為樣本，依綜合分數由高至低取前 10 檔，避免雲端執行逾時。")
        if st.button(f"執行「{strategy_choice}」回測", key=f"run_strategy_bt_{strategy_choice}", use_container_width=True):
            with st.spinner(f"正在回測 {strategy_choice}，請稍候..."):
                bt_table, bt_meta = run_market_strategy_backtest(df_res, strategy_choice, get_secret("FINMIND_TOKEN", ""))
                st.session_state["market_strategy_bt"] = {"strategy": strategy_choice, "table": bt_table, "meta": bt_meta}
        saved_bt = st.session_state.get("market_strategy_bt")
        if saved_bt and saved_bt.get("strategy") == strategy_choice:
            render_market_strategy_backtest(saved_bt.get("table"), strategy_choice, saved_bt.get("meta", {}))
        
        st.markdown("### 🎯 從掃描結果啟動深度診斷")
        options = [f"{row['股票代碼']} {row['股票名稱']}" for idx, row in df_res.iterrows()]
        sel = st.selectbox("📌 請選擇一檔標的進行分析：", options)
        if st.button("🚀 啟動此檔個股深度分析"):
            sid = sel.split(" ")[0]
            sname = sel.split(" ")[1]
            st.session_state["diag_req"] = {"mode": app_mode, "id": sid, "name": sname}
            
else:
    filtered_options = [f"{code} {name}" for code, name in STOCK_DICT.items()]
    default_idx = next((i for i, opt in enumerate(filtered_options) if opt.startswith(st.session_state.get("selected_stock_code", "2356"))), 0)

    selected_stock_raw = st.selectbox("請選擇或搜尋股票：", options=filtered_options, index=default_idx, key="selected_stock_select")
    
    if selected_stock_raw:
        st.session_state["selected_stock_code"] = selected_stock_raw.split(" ")[0]

    stock_id = st.session_state["selected_stock_code"]
    stock_name = STOCK_DICT.get(stock_id, "")

    if st.button("🚀 啟動個股技術、籌碼與 AI 深度診斷"):
        st.session_state["diag_req"] = {"mode": app_mode, "id": stock_id, "name": stock_name}

# 診斷結果以 session_state 保存：調整顯示區間／布林通道／週數時圖表不會消失
_req = st.session_state.get("diag_req")
if _req and _req.get("mode") == app_mode:
    render_diagnosis_section(_req["id"], _req["name"], start_date, end_date, finmind_token)
