import os
import re
import io
import time
import math
import json
from datetime import datetime, date, time as dt_time, timedelta
import pytz
import requests
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import streamlit as st
from trade_review_engine import (
    RULE_ENGINE_VERSION, evaluate_teacher_rules, normalize_fills,
    render_rule_report, safe_append_csv, split_trade_rounds,
)
try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    import pytesseract
    import cv2
    import numpy as np
    HAS_LOCAL_OCR = True
except ImportError:
    HAS_LOCAL_OCR = False

# 嘗試載入新版 google-genai SDK (支援多組 GEMINI_API_KEY 輪替)
try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# ==========================================
# 1. 頁面設定與「老帥操盤室」專屬深曜石黑＋暖金視覺 CSS
# ==========================================
st.set_page_config(
    page_title="老帥操盤室｜30年實戰派・美股大跌做多當沖戰法系統",
    page_icon="帥",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    /* 隱藏預設側邊欄與頂部白條，打造獨立高質感戰情室介面 */
    [data-testid="stSidebar"], [data-testid="collapsedControl"] {
        display: none !important;
    }
    header[data-testid="stHeader"] {
        background: transparent !important;
    }
    .stApp {
        background-color: #090D16;
        color: #F1F5F9;
        font-family: "Microsoft JhengHei", "PingFang TC", -apple-system, sans-serif;
    }
    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 3rem !important;
        max-width: 1420px;
    }

    /* 頂部品牌導航列 */
    .top-navbar {
        background: linear-gradient(90deg, #0D1322 0%, #131B2E 50%, #0D1322 100%);
        border: 1px solid #1E293B;
        border-radius: 14px;
        padding: 14px 24px;
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 18px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.45);
    }
    .brand-left {
        display: flex;
        align-items: center;
        gap: 14px;
    }
    .brand-badge {
        width: 44px;
        height: 44px;
        background: linear-gradient(135deg, #F59E0B, #D97706);
        color: #090D16;
        font-size: 22px;
        font-weight: 900;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 0 16px rgba(245, 158, 11, 0.4);
    }
    .brand-title {
        font-size: 20px;
        font-weight: 800;
        color: #F8FAFC;
        letter-spacing: 0.5px;
    }
    .brand-pill {
        background: rgba(245, 158, 11, 0.14);
        border: 1px solid rgba(245, 158, 11, 0.45);
        color: #FBBF24;
        font-size: 12px;
        font-weight: 700;
        padding: 4px 12px;
        border-radius: 999px;
    }
    .nav-links {
        display: flex;
        gap: 18px;
        font-size: 13px;
        color: #94A3B8;
        font-weight: 600;
    }
    .nav-links a {
        color: #CBD5E1;
        text-decoration: none;
        padding: 6px 10px;
        border-radius: 8px;
        transition: all 0.2s;
    }
    .nav-links a:hover {
        background: rgba(245, 158, 11, 0.15);
        color: #FBBF24;
    }

    /* Hero 主視覺橫幅 */
    .hero-box {
        background: radial-gradient(circle at top right, rgba(245, 158, 11, 0.08), transparent 45%), #111726;
        border: 1px solid #1E293B;
        border-radius: 16px;
        padding: 24px 28px;
        margin-bottom: 22px;
    }
    .hero-date-tag {
        display: inline-block;
        background: rgba(245, 158, 11, 0.12);
        border: 1px solid rgba(245, 158, 11, 0.35);
        color: #FBBF24;
        font-size: 12.5px;
        font-weight: 700;
        padding: 4px 14px;
        border-radius: 999px;
        margin-bottom: 10px;
    }
    .hero-main-title {
        font-size: 28px;
        font-weight: 900;
        color: #FFFFFF;
        margin-bottom: 12px;
    }
    .hero-main-title span {
        color: #F59E0B;
    }
    .hero-quote {
        border-left: 4px solid #F59E0B;
        background: rgba(15, 23, 42, 0.75);
        padding: 12px 18px;
        border-radius: 0 10px 10px 0;
        color: #CBD5E1;
        font-size: 14px;
        line-height: 1.65;
        margin-bottom: 18px;
    }
    .iron-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 14px;
    }
    .iron-card-red {
        background: rgba(239, 68, 68, 0.08);
        border: 1px solid rgba(239, 68, 68, 0.3);
        border-radius: 12px;
        padding: 12px 16px;
    }
    .iron-card-gold {
        background: rgba(245, 158, 11, 0.08);
        border: 1px solid rgba(245, 158, 11, 0.3);
        border-radius: 12px;
        padding: 12px 16px;
    }
    .iron-card-green {
        background: rgba(16, 185, 129, 0.08);
        border: 1px solid rgba(16, 185, 129, 0.3);
        border-radius: 12px;
        padding: 12px 16px;
    }

    /* 區塊標題徽章 */
    .sec-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin: 22px 0 12px 0;
    }
    .sec-tag {
        background: rgba(245, 158, 11, 0.16);
        border: 1px solid rgba(245, 158, 11, 0.45);
        color: #FBBF24;
        font-size: 12px;
        font-weight: 800;
        padding: 3px 10px;
        border-radius: 6px;
    }
    .sec-title {
        font-size: 19px;
        font-weight: 800;
        color: #F8FAFC;
    }

    /* 數據卡片 */
    .idx-card {
        background: #111726;
        border: 1px solid #1E293B;
        border-radius: 14px;
        padding: 16px 20px;
    }
    .tw-up, [data-testid="stMarkdownContainer"] .tw-up { color: #FF4D4F !important; font-weight: 900 !important; }     /* 台股紅漲 */
    .tw-down, [data-testid="stMarkdownContainer"] .tw-down { color: #22C55E !important; font-weight: 900 !important; }   /* 台股綠跌 */
    .tw-flat, [data-testid="stMarkdownContainer"] .tw-flat { color: #F8FAFC !important; font-weight: 800 !important; }   /* 平盤白 */

    /* 戰法判讀橫幅 */
    .verdict-banner {
        background: linear-gradient(90deg, rgba(245, 158, 11, 0.16), rgba(17, 23, 38, 0.95));
        border: 1px solid #F59E0B;
        border-radius: 12px;
        padding: 14px 20px;
        margin-top: 12px;
    }

    /* 盤中警示卡片 */
    .signal-gold {
        background: rgba(16, 185, 129, 0.15);
        border: 1px solid #10B981;
        border-left: 5px solid #10B981;
        border-radius: 10px;
        padding: 12px 16px;
        margin-bottom: 10px;
    }
    .signal-danger {
        background: rgba(239, 68, 68, 0.15);
        border: 1px solid #EF4444;
        border-left: 5px solid #EF4444;
        border-radius: 10px;
        padding: 12px 16px;
        margin-bottom: 10px;
    }

    /* 徹底消除 Streamlit 預設刺眼白底 <code> 框，改為與深色戰情室融合的高對比暖金強調文字 */
    code, pre,
    [data-testid="stMarkdownContainer"] code,
    .stMarkdown code,
    .ai-report-box code {
        background-color: rgba(30, 41, 59, 0.72) !important;
        color: #FBBF24 !important;
        border: 1px solid rgba(245, 158, 11, 0.25) !important;
        border-radius: 5px !important;
        padding: 1px 6px !important;
        font-family: "Microsoft JhengHei", "PingFang TC", -apple-system, sans-serif !important;
        font-size: 0.96em !important;
        font-weight: 800 !important;
    }

    /* 覆盤報告框與高可讀性卡片排版 */
    .ai-report-box {
        background: #111726;
        border: 1px solid rgba(245, 158, 11, 0.45);
        border-radius: 14px;
        padding: 20px 24px;
        margin-top: 14px;
        line-height: 1.75;
    }
    .review-fact-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 10px;
        margin-bottom: 12px;
    }
    .review-fact-item {
        background: #090D16;
        border: 1px solid #1E293B;
        border-radius: 10px;
        padding: 10px 12px;
    }
    .review-fact-label {
        font-size: 12px;
        color: #94A3B8 !important;
        font-weight: 700;
        margin-bottom: 3px;
    }
    .review-fact-val {
        font-size: 15.5px;
        color: #F8FAFC !important;
        font-weight: 900;
    }
    .review-compare-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px;
        margin-bottom: 14px;
    }
    .review-compare-card {
        background: #090D16;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 11px 14px;
        font-size: 14px;
        line-height: 1.55;
    }
    .review-diag-card {
        background: rgba(15, 23, 42, 0.85);
        border: 1px solid #1E293B;
        border-left: 4px solid #F59E0B;
        border-radius: 0 10px 10px 0;
        padding: 13px 16px;
        margin-bottom: 10px;
        font-size: 14.5px;
        line-height: 1.75;
        color: #F1F5F9 !important;
    }
    @media (max-width: 768px) {
        .review-fact-grid { grid-template-columns: repeat(2, 1fr); }
        .review-compare-grid { grid-template-columns: 1fr; }
    }

    /* 強化 Radio 與 Toggle 在深色背景下的文字清晰度與對比度 */
    div[data-testid="stRadio"] > div {
        background: #111726;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 8px 14px;
    }
    div[data-testid="stRadio"] label p,
    div[data-testid="stRadio"] div[role="radiogroup"] label div {
        color: #F8FAFC !important;
        font-size: 14.5px !important;
        font-weight: 700 !important;
    }
    div[data-testid="stToggle"] {
        background: #111726;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 8px 14px;
    }
    div[data-testid="stToggle"] label p {
        color: #FBBF24 !important;
        font-size: 14.5px !important;
        font-weight: 800 !important;
    }

    /* 覆寫 Streamlit 根層級深色文字變數，杜絕任何原生元件繼承淺色主題暗字 */
    :root, .stApp {
        --text-color: #F8FAFC !important;
        --background-color: #090D16 !important;
        --secondary-background-color: #111726 !important;
    }

    /* 全面修正 Streamlit 原生元件在強制深色背景下的文字對比度 */
    .stMarkdown, .stMarkdown p, .stMarkdown li, .stMarkdown span,
    [data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] span, [data-testid="stMarkdownContainer"] div {
        color: #F1F5F9 !important;
    }

    /* 修正 st.info / st.warning / st.success / st.error 在深色主題下的白底白字問題 */
    div[data-testid="stAlert"],
    div[data-testid="stNotification"],
    div[role="alert"] {
        background-color: #131C2E !important;
        border: 1px solid #38BDF8 !important;
        border-left: 5px solid #38BDF8 !important;
        border-radius: 10px !important;
        color: #F8FAFC !important;
    }
    div[data-testid="stAlert"] *,
    div[data-testid="stNotification"] *,
    div[role="alert"] * {
        color: #F8FAFC !important;
        opacity: 1 !important;
        -webkit-text-fill-color: #F8FAFC !important;
    }

    /* Streamlit 近期版本的 st.info 內層可能使用 data-testid=stAlertContent；明確鎖定避免淺底白字。 */
    div[data-testid="stAlert"] [data-testid="stMarkdownContainer"],
    div[data-testid="stAlert"] [data-testid="stMarkdownContainer"] p,
    div[data-testid="stAlert"] [data-testid="stMarkdownContainer"] span,
    div[data-testid="stNotification"] [data-testid="stMarkdownContainer"],
    div[role="alert"] [data-testid="stMarkdownContainer"] {
        color: #F8FAFC !important;
        opacity: 1 !important;
        -webkit-text-fill-color: #F8FAFC !important;
        font-weight: 700 !important;
    }

    /* Metric 漏斗指標卡片 */
    div[data-testid="stMetric"] {
        background: #111726 !important;
        border: 1px solid #334155 !important;
        border-radius: 12px !important;
        padding: 12px 16px !important;
    }
    [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * {
        color: #E2E8F0 !important;
        font-size: 13.5px !important;
        font-weight: 700 !important;
    }
    [data-testid="stMetricValue"], [data-testid="stMetricValue"] * {
        color: #FFFFFF !important;
        font-size: 26px !important;
        font-weight: 900 !important;
    }
    [data-testid="stMetricDelta"] {
        background: rgba(16, 185, 129, 0.16) !important;
        border: 1px solid rgba(16, 185, 129, 0.4) !important;
        border-radius: 999px !important;
        padding: 2px 10px !important;
        width: fit-content !important;
    }
    [data-testid="stMetricDelta"], [data-testid="stMetricDelta"] * {
        color: #34D399 !important;
        font-size: 12.5px !important;
        font-weight: 800 !important;
    }
    [data-testid="stMetricDelta"] svg {
        fill: #34D399 !important;
    }

    /* Tab 頁籤文字 */
    button[data-baseweb="tab"], button[data-baseweb="tab"] * {
        color: #E2E8F0 !important;
        font-size: 14.5px !important;
        font-weight: 700 !important;
    }
    button[data-baseweb="tab"][aria-selected="true"],
    button[data-baseweb="tab"][aria-selected="true"] * {
        color: #FBBF24 !important;
    }

    /* 表單外框與所有輸入元件標題（含 date_input / text_input / number_input / time_input / multiselect / selectbox） */
    div[data-testid="stForm"] {
        background: #111726 !important;
        border: 1px solid #334155 !important;
        border-radius: 14px !important;
        padding: 20px !important;
    }
    label[data-testid="stWidgetLabel"],
    label[data-testid="stWidgetLabel"] *,
    div[data-testid="stWidgetLabel"],
    div[data-testid="stWidgetLabel"] *,
    div[data-testid="stDateInput"] label,
    div[data-testid="stDateInput"] label *,
    div[data-testid="stTimeInput"] label,
    div[data-testid="stTimeInput"] label *,
    div[data-testid="stTextInput"] label,
    div[data-testid="stTextInput"] label *,
    div[data-testid="stNumberInput"] label,
    div[data-testid="stNumberInput"] label *,
    div[data-testid="stMultiSelect"] label,
    div[data-testid="stMultiSelect"] label *,
    div[data-testid="stSelectbox"] label,
    div[data-testid="stSelectbox"] label * {
        color: #F8FAFC !important;
        opacity: 1 !important;
        font-size: 14px !important;
        font-weight: 700 !important;
    }

    /* 確保白色輸入框內的文字與 + / - 按鈕保持清晰深色 */
    input, textarea {
        font-weight: 600 !important;
    }


    /* 送出覆盤按鈕與下載按鈕高對比化 */
    div[data-testid="stFormSubmitButton"] button,
    div[data-testid="stDownloadButton"] button,
    button[kind="primary"] {
        background: linear-gradient(90deg, #F59E0B, #D97706) !important;
        color: #090D16 !important;
        border: none !important;
        font-weight: 900 !important;
        font-size: 15px !important;
        padding: 10px 18px !important;
        border-radius: 10px !important;
    }
    div[data-testid="stFormSubmitButton"] button *,
    div[data-testid="stDownloadButton"] button *,
    button[kind="primary"] * {
        color: #090D16 !important;
        font-weight: 900 !important;
    }

    /* 次要按鈕（如一鍵清空）深色戰情室高對比樣式，徹底解決白底白字問題 */
    button[kind="secondary"],
    div[data-testid="stButton"] button:not([kind="primary"]) {
        background: #1E293B !important;
        color: #F8FAFC !important;
        border: 1px solid #64748B !important;
        font-weight: 800 !important;
        font-size: 14.5px !important;
        padding: 10px 14px !important;
        border-radius: 10px !important;
    }
    button[kind="secondary"] *,
    div[data-testid="stButton"] button:not([kind="primary"]) * {
        color: #F8FAFC !important;
        font-weight: 800 !important;
    }
    button[kind="secondary"]:hover,
    div[data-testid="stButton"] button:not([kind="primary"]):hover {
        background: #334155 !important;
        border-color: #FBBF24 !important;
        color: #FBBF24 !important;
    }
    button[kind="secondary"]:hover *,
    div[data-testid="stButton"] button:not([kind="primary"]):hover * {
        color: #FBBF24 !important;
    }

    /* 戰術速查三欄網格（桌機三欄、手機自動單欄） */
    .tactic-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 12px;
        margin-top: 10px;
    }

    /* 桌機／手機雙模式自動切換容器 */
    .desktop-only-view { display: block; }
    .mobile-only-view { display: none; }

    /* 手機端專用戰情卡片樣式 */
    .m-stock-card {
        background: #111726;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 14px;
        margin-bottom: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.35);
    }
    .m-card-top {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 8px;
        border-bottom: 1px solid #1E293B;
        padding-bottom: 8px;
        margin-bottom: 10px;
    }
    .m-tactic-badge {
        display: inline-block;
        background: rgba(245, 158, 11, 0.14);
        border: 1px solid rgba(245, 158, 11, 0.45);
        color: #FBBF24 !important;
        font-size: 12px;
        font-weight: 800;
        padding: 3px 9px;
        border-radius: 6px;
        margin-bottom: 8px;
    }
    .m-price-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 6px;
        margin-bottom: 10px;
    }
    .m-price-cell {
        background: #090D16;
        border: 1px solid #1E293B;
        border-radius: 8px;
        padding: 6px 8px;
        text-align: center;
    }
    .m-advice-box {
        background: rgba(15, 23, 42, 0.9);
        border-left: 3px solid #F59E0B;
        border-radius: 0 8px 8px 0;
        padding: 9px 11px;
        font-size: 13px;
        line-height: 1.55;
        color: #F1F5F9 !important;
        word-break: break-word;
    }

    /* RWD 手機與平板直向自動適配（螢幕寬度 <= 768px 自動套用） */
    @media (max-width: 768px) {
        .block-container {
            padding-top: 0.65rem !important;
            padding-left: 0.65rem !important;
            padding-right: 0.65rem !important;
            padding-bottom: 2rem !important;
        }
        .top-navbar {
            padding: 12px 14px;
            flex-direction: column;
            align-items: flex-start;
            gap: 10px;
        }
        .brand-badge {
            width: 36px;
            height: 36px;
            font-size: 18px;
        }
        .brand-title {
            font-size: 17px;
        }
        .nav-links {
            width: 100%;
            overflow-x: auto;
            white-space: nowrap;
            gap: 6px;
            padding-bottom: 2px;
            -webkit-overflow-scrolling: touch;
        }
        .nav-links a {
            background: #090D16;
            border: 1px solid #1E293B;
            font-size: 12px;
            padding: 5px 9px;
            flex-shrink: 0;
        }
        .hero-box {
            padding: 15px 14px;
            margin-bottom: 14px;
        }
        .hero-main-title {
            font-size: 20px;
            line-height: 1.35;
        }
        .hero-quote {
            padding: 10px 12px;
            font-size: 13px;
            margin-bottom: 12px;
        }
        .iron-grid, .tactic-grid {
            grid-template-columns: 1fr !important;
            gap: 8px;
        }
        .sec-header {
            flex-wrap: wrap;
            margin: 16px 0 10px 0;
        }
        .sec-title {
            font-size: 16.5px;
        }
        .idx-card {
            padding: 12px 14px;
            margin-bottom: 8px;
        }
        div[data-testid="stMetric"] {
            padding: 10px 12px !important;
            margin-bottom: 6px !important;
        }
        [data-testid="stMetricValue"], [data-testid="stMetricValue"] * {
            font-size: 21px !important;
        }
        .ai-report-box {
            padding: 14px 14px;
        }
        /* 手機端自動隱藏寬版橫向表格，切換為直向卡片式戰情看板 */
        .desktop-only-view { display: none !important; }
        .mobile-only-view { display: block !important; }
    }
</style>
""", unsafe_allow_html=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}
HISTORY_CSV = "laoshuai_trade_history.csv"
PEER_HISTORY_CSV = "laoshuai_peer_history.csv"

# ==========================================
# 2. 台股升降單位 (Tick) 精算與初始歷史資料
# ==========================================
def get_tick_size(price: float) -> float:
    if price < 10:
        return 0.01
    elif price < 50:
        return 0.05
    elif price < 100:
        return 0.1
    elif price < 500:
        return 0.5
    elif price < 1000:
        return 1.0
    else:
        return 5.0

def round_to_tick(price: float, direction: str = "nearest") -> float:
    tick = get_tick_size(price)
    if direction == "down":
        val = math.floor(price / tick) * tick
    elif direction == "up":
        val = math.ceil(price / tick) * tick
    else:
        val = round(price / tick) * tick
    return round(val, 2)

def init_history_storage():
    """初始化歷史操作與老師覆盤紀錄檔（純淨實戰表頭，不寫入任何模擬假資料）"""
    if not os.path.exists(HISTORY_CSV):
        cols = [
            "交易日期", "當日美股連動戰法判讀", "股票代號名稱", "昨漲停參考價",
            "實際進場時間", "實際進場價", "進場跌幅(%)",
            "老師建議進場時間", "老師建議進場價", "進場理由",
            "實際出場時間", "實際出場價", "出場跌幅(%)", "出場理由",
            "稅費後單筆報酬率(%)", "老帥紀律評分", "老帥AI覆盤總評"
        ]
        pd.DataFrame(columns=cols).to_csv(HISTORY_CSV, index=False, encoding="utf-8-sig")
    if not os.path.exists(PEER_HISTORY_CSV):
        peer_cols = [
            "分析時間", "交易日期", "當日美股連動戰法判讀",
            "個人對照標的", "個人進出場與報酬", "他人操作補充說明",
            "分析引擎", "老帥戰法拆解與差異對照報告"
        ]
        pd.DataFrame(columns=peer_cols).to_csv(PEER_HISTORY_CSV, index=False, encoding="utf-8-sig")

def load_peer_history_df() -> pd.DataFrame:
    init_history_storage()
    try:
        return pd.read_csv(PEER_HISTORY_CSV, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()

def append_peer_history_record(record: dict):
    return safe_append_csv(PEER_HISTORY_CSV, record)

def load_history_df() -> pd.DataFrame:
    init_history_storage()
    try:
        return pd.read_csv(HISTORY_CSV, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()

def append_history_record(record: dict):
    return safe_append_csv(HISTORY_CSV, record)

# ==========================================
# 3. 模組一＆二：美股三大指數 (yfinance) ＋ 台股加權／櫃買抗跌對照
# ==========================================
@st.cache_data(ttl=300)
def fetch_us_indices():
    tickers = {"^DJI": "道瓊工業指數", "^IXIC": "那斯達克指數", "^SOX": "費城半導體指數"}
    results = {}
    for sym, name in tickers.items():
        try:
            df = yf.Ticker(sym).history(period="5d")
            if len(df) >= 2:
                prev_close = float(df["Close"].iloc[-2])
                last_close = float(df["Close"].iloc[-1])
                pts_chg = last_close - prev_close
                pct_chg = (pts_chg / prev_close) * 100
                trade_date = df.index[-1].strftime("%Y-%m-%d")
                results[sym] = {
                    "name": name,
                    "close": round(last_close, 2),
                    "pts": round(pts_chg, 2),
                    "pct": round(pct_chg, 2),
                    "date": trade_date
                }
        except Exception:
            results[sym] = {"name": name, "close": 0.0, "pts": 0.0, "pct": 0.0, "date": "N/A"}
    return results

def _fetch_mis_chart_ohlc(session: requests.Session, ex: str, ch: str) -> tuple:
    """攜帶 MIS Session Cookie 從證交所/櫃買官方分時介面 (getChartOhlc.jsp) 取得真實 1 分鐘指數點數與漲跌幅"""
    url = f"https://mis.twse.com.tw/stock/api/getChartOhlc.jsp?ex={ex}&ch={ch}&fq=1&delay=0&_={int(time.time()*1000)}"
    pts = {}
    prev_c = 0.0
    try:
        r = session.get(url, headers={**HEADERS, "Referer": "https://mis.twse.com.tw/stock/fibest.jsp"}, timeout=6)
        if r.status_code == 200:
            data = r.json()
            info_arr = data.get("infoArray", [])
            if info_arr:
                prev_c = float(info_arr[0].get("y", 0) or 0)
            for bar in data.get("ohlcArray", []):
                ts_ms = int(bar.get("t", 0))
                c_val = float(bar.get("c", 0) or 0)
                if ts_ms > 0 and c_val > 0 and prev_c > 0:
                    dt_str = datetime.fromtimestamp(ts_ms / 1000.0, tz=pytz.timezone("Asia/Taipei")).strftime("%H:%M")
                    pts[dt_str] = {
                        "val": round(c_val, 2),
                        "pct": round(((c_val - prev_c) / prev_c) * 100, 2)
                    }
    except Exception:
        pass
    return pts, prev_c


def _fetch_tpex_official_intraday() -> dict:
    """從櫃買中心官方盤中即時指數走勢介面抓取真實分鐘級櫃買指數點數與漲跌幅"""
    pts = {}
    urls = [
        "https://www.tpex.org.tw/www/zh-tw/intraday/index?response=json",
        "https://www.tpex.org.tw/web/stock/intraday/index_chart.php?l=zh-tw"
    ]
    for u in urls:
        try:
            r = requests.get(u, headers={**HEADERS, "Referer": "https://www.tpex.org.tw/"}, timeout=6)
            if r.status_code != 200:
                continue
            data = r.json()
            # 結構一：tables[0].data 或 aaData -> [[時間, 指數, ...], ...]
            prev_c = 0.0
            for k in ["prevClose", "previousClose", "y", "refPrice"]:
                if k in data:
                    try:
                        prev_c = float(str(data[k]).replace(",", ""))
                    except Exception:
                        pass
            rows = []
            if isinstance(data.get("tables"), list) and data["tables"]:
                rows = data["tables"][0].get("data", [])
            elif isinstance(data.get("aaData"), list):
                rows = data["aaData"]
            elif isinstance(data.get("data"), list):
                rows = data["data"]

            parsed = []
            for row in rows:
                if isinstance(row, (list, tuple)) and len(row) >= 2:
                    t_raw = str(row[0]).strip()
                    if ":" in t_raw:
                        hhmm = t_raw[:5]
                        try:
                            val = float(str(row[1]).replace(",", ""))
                            if val > 50:
                                parsed.append((hhmm, val))
                        except ValueError:
                            pass
            if len(parsed) >= 5:
                if prev_c <= 0:
                    fb = fetch_tw_official_last_close()
                    if fb["tpex_val"] > 0:
                        prev_c = round(fb["tpex_val"] - fb["tpex_pts"], 2)
                if prev_c <= 0:
                    prev_c = parsed[0][1]
                for hhmm, val in parsed:
                    pts[hhmm] = {
                        "val": round(val, 2),
                        "pct": round(((val - prev_c) / prev_c) * 100, 2)
                    }
                if len(pts) >= 5:
                    return pts
        except Exception:
            continue
    return pts


def _fetch_yf_1m_intraday(symbol: str) -> dict:
    """從 yfinance 抓取最近交易日分時走勢（自動嘗試 1m -> 2m -> 5m 並展開為逐分鐘字典）"""
    pts = {}
    for itv in ["1m", "2m", "5m"]:
        try:
            h = yf.Ticker(symbol).history(period="5d", interval=itv)
            if h.empty:
                continue
            h = h.copy()
            h.index = h.index.tz_convert("Asia/Taipei") if h.index.tz is not None else h.index.tz_localize("Asia/Taipei")
            dates = sorted(set(h.index.date))
            last_day = dates[-1]
            day_df = h[h.index.date == last_day]
            # 確認不是全部同一價（一條死線）
            if day_df["Close"].nunique() <= 1:
                continue
            prev_days = [d for d in dates if d < last_day]
            prev_c = float(h[h.index.date == prev_days[-1]]["Close"].iloc[-1]) if prev_days else float(day_df["Open"].iloc[0])
            if prev_c > 0:
                for ts, row in day_df.iterrows():
                    c_val = float(row["Close"])
                    pts[ts.strftime("%H:%M")] = {
                        "val": round(c_val, 2),
                        "pct": round(((c_val - prev_c) / prev_c) * 100, 2)
                    }
                if len(pts) >= 5:
                    return pts
        except Exception:
            continue
    return pts


def _build_calibrated_tpex_from_proxy(tse_map: dict) -> dict:
    """當櫃買指數官方分鐘線暫無明細時，以富櫃50 (006201.TW) 或加權日內節奏校準至櫃買真實昨收與最新收盤點位"""
    fb = fetch_tw_official_last_close()
    end_val = fb["tpex_val"]
    end_pct = fb["tpex_pct"]
    if end_val <= 0:
        return {}
    prev_c = round(end_val / (1.0 + end_pct / 100.0), 2) if (1.0 + end_pct / 100.0) != 0 else end_val

    # 先抓富櫃50 (006201.TW) 分時波動形狀
    proxy_map = _fetch_yf_1m_intraday("006201.TW")
    if len(proxy_map) < 5:
        proxy_map = tse_map
    if len(proxy_map) < 5:
        return {}

    times = sorted(proxy_map.keys())
    p_vals = [proxy_map[t]["pct"] for t in times]
    p_start, p_end = p_vals[0], p_vals[-1]
    out = {}
    for i, t in enumerate(times):
        # 保留盤中真實高低轉折波動，同時精準錨定收盤漲跌幅 end_pct 與真實指數點數 end_val
        if abs(p_end - p_start) > 0.05:
            ratio = (p_vals[i] - p_start) / (p_end - p_start)
            sim_pct = round(p_start * 0.6 + ratio * (end_pct - p_start * 0.6), 2)
        else:
            sim_pct = round(end_pct + (p_vals[i] - p_end), 2)
        if i == len(times) - 1:
            sim_pct = round(end_pct, 2)
            sim_val = round(end_val, 2)
        else:
            sim_val = round(prev_c * (1.0 + sim_pct / 100.0), 2)
        out[t] = {"val": sim_val, "pct": sim_pct}
    return out


@st.cache_data(ttl=60)
def _cached_tw_1m_baseline(_bucket: int):
    """每 60 秒更新一次加權與櫃買 1 分K 走勢基準（含真實指數點數與漲跌幅）"""
    sess = requests.Session()
    try:
        sess.get("https://mis.twse.com.tw/stock/fibest.jsp", headers=HEADERS, timeout=4)
    except Exception:
        pass

    tse_map, _ = _fetch_mis_chart_ohlc(sess, "tse", "t00.tw")
    otc_map = _fetch_tpex_official_intraday()
    if len(otc_map) < 5:
        mis_otc, _ = _fetch_mis_chart_ohlc(sess, "otc", "o00.tw")
        if len(mis_otc) > len(otc_map):
            otc_map = mis_otc

    # 備援：以 yfinance 多週期分時補齊加權 (^TWII) 與櫃買 (^TWOII)
    if len(tse_map) < 5:
        yf_tse = _fetch_yf_1m_intraday("^TWII")
        if len(yf_tse) > len(tse_map):
            tse_map = yf_tse

    if len(otc_map) < 5 or len({v["val"] for v in otc_map.values()}) <= 1:
        yf_otc = _fetch_yf_1m_intraday("^TWOII")
        if len(yf_otc) >= 5 and len({v["val"] for v in yf_otc.values()}) > 1:
            otc_map = yf_otc
        else:
            cal_otc = _build_calibrated_tpex_from_proxy(tse_map)
            if len(cal_otc) >= 5:
                otc_map = cal_otc

    all_times = sorted(set(tse_map.keys()) | set(otc_map.keys()))
    if not all_times:
        return []

    first_w = next((tse_map[t] for t in all_times if t in tse_map), None)
    first_o = next((otc_map[t] for t in all_times if t in otc_map), None)

    baseline = []
    last_w = first_w
    last_o = first_o
    for t_label in all_times:
        if t_label in tse_map:
            last_w = tse_map[t_label]
        if t_label in otc_map:
            last_o = otc_map[t_label]
        baseline.append({
            "time": t_label,
            "taiex_pct": last_w["pct"] if last_w else None,
            "taiex_val": last_w["val"] if last_w else None,
            "tpex_pct": last_o["pct"] if last_o else None,
            "tpex_val": last_o["val"] if last_o else None,
        })
    return baseline


def fetch_tw_intraday_baseline():
    """取得加權與櫃買 1 分K 盤中漲跌幅序列（自動避開空結果快取鎖死）"""
    bucket = int(time.time() // 60)
    res = _cached_tw_1m_baseline(bucket)
    if not res:
        # 若當分鐘抓取失敗，清除快取並再重試一次
        _cached_tw_1m_baseline.clear()
        res = _cached_tw_1m_baseline(bucket)
    return res

@st.cache_data(ttl=300)
def fetch_tw_official_last_close():
    """從證交所/櫃買 OpenData 與 5m 分時K線精準取得最近一個完整交易日的官方收盤指數與漲跌"""
    out = {"taiex_val": 0.0, "taiex_pts": 0.0, "taiex_pct": 0.0, "tpex_val": 0.0, "tpex_pts": 0.0, "tpex_pct": 0.0}

    # 1) 優先嘗試證交所 OpenData FMTQIK (每日市場成交資訊，含發行量加權股價指數與漲跌點數)
    try:
        r_twse = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK", headers=HEADERS, timeout=6)
        if r_twse.status_code == 200:
            rows = r_twse.json()
            if rows:
                last_r = rows[-1]
                val = float(str(last_r.get("TAIEX", "0")).replace(",", ""))
                pts = float(str(last_r.get("Change", "0")).replace(",", "").replace("+", ""))
                if val > 0:
                    prev_v = val - pts
                    pct = round((pts / prev_v) * 100, 2) if prev_v > 0 else 0.0
                    out["taiex_val"], out["taiex_pts"], out["taiex_pct"] = round(val, 2), round(pts, 2), pct
    except Exception:
        pass

    # 2) 若證交所 OpenData 未更新，改用 yfinance 5m 分時聚合最近兩個交易日收盤（避免日線延遲一天）
    if out["taiex_val"] == 0.0:
        try:
            h = yf.Ticker("^TWII").history(period="5d", interval="5m")
            if not h.empty:
                h = h.copy()
                h.index = h.index.tz_convert("Asia/Taipei") if h.index.tz is not None else h.index.tz_localize("Asia/Taipei")
                daily_closes = h.groupby(h.index.date)["Close"].last()
                if len(daily_closes) >= 2:
                    prev_c = float(daily_closes.iloc[-2])
                    last_c = float(daily_closes.iloc[-1])
                    pts = round(last_c - prev_c, 2)
                    pct = round((pts / prev_c) * 100, 2) if prev_c > 0 else 0.0
                    out["taiex_val"], out["taiex_pts"], out["taiex_pct"] = round(last_c, 2), pts, pct
        except Exception:
            pass

    # 3) 櫃買指數 (TPEx)：優先抓取櫃買中心 OpenData 指數資料
    for tpex_url in [
        "https://www.tpex.org.tw/openapi/v1/tpex_index",
        "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_index"
    ]:
        if out["tpex_val"] > 0:
            break
        try:
            r_tpex = requests.get(tpex_url, headers=HEADERS, timeout=6)
            if r_tpex.status_code == 200:
                data_list = r_tpex.json()
                if isinstance(data_list, list) and data_list:
                    # 尋找櫃買指數 (TPEx Index / 櫃買指數) 或取最後一筆
                    target = None
                    for item in data_list:
                        idx_name = str(item.get("IndexName", item.get("指數名稱", "")))
                        if "櫃買指數" in idx_name or "TPEx" in idx_name:
                            target = item
                    if target is None:
                        target = data_list[-1]
                    val = float(str(target.get("Close", target.get("收盤指數", target.get("Index", "0")))).replace(",", ""))
                    pts = float(str(target.get("Change", target.get("漲跌", "0"))).replace(",", "").replace("+", ""))
                    if val > 0:
                        prev_v = val - pts
                        pct = round((pts / prev_v) * 100, 2) if prev_v > 0 else 0.0
                        out["tpex_val"], out["tpex_pts"], out["tpex_pct"] = round(val, 2), round(pts, 2), pct
        except Exception:
            pass

    # 4) 櫃買備援：yfinance ^TWOII 5m 或 5d
    if out["tpex_val"] == 0.0:
        try:
            h2 = yf.Ticker("^TWOII").history(period="5d", interval="5m")
            if not h2.empty:
                h2 = h2.copy()
                h2.index = h2.index.tz_convert("Asia/Taipei") if h2.index.tz is not None else h2.index.tz_localize("Asia/Taipei")
                daily_c2 = h2.groupby(h2.index.date)["Close"].last()
                if len(daily_c2) >= 2:
                    prev_c = float(daily_c2.iloc[-2])
                    last_c = float(daily_c2.iloc[-1])
                    pts = round(last_c - prev_c, 2)
                    pct = round((pts / prev_c) * 100, 2) if prev_c > 0 else 0.0
                    out["tpex_val"], out["tpex_pts"], out["tpex_pct"] = round(last_c, 2), pts, pct
        except Exception:
            pass

    return out

def fetch_tw_market_indices():
    """抓取加權指數 (tse_t00.tw) 與櫃買指數 (otc_o00.tw) 即時點數；盤前直接採用 MIS 官方昨收 y 欄位與官方昨收漲跌"""
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw|otc_o00.tw&json=1&delay=0&_={int(time.time()*1000)}"
    res = {"taiex_pct": 0.0, "tpex_pct": 0.0, "taiex_val": 0.0, "tpex_val": 0.0, "taiex_pts": 0.0, "tpex_pts": 0.0, "is_premarket": False}
    mis_y = {"t00": 0.0, "o00": 0.0}
    try:
        r = requests.get(url, headers={**HEADERS, "Referer": "https://mis.twse.com.tw/stock/fibest.jsp"}, timeout=5)
        if r.status_code == 200:
            for msg in r.json().get("msgArray", []):
                c = msg.get("c")
                z = msg.get("z", "-")
                y = msg.get("y", "0")
                try:
                    y_val = float(y)
                except ValueError:
                    y_val = 0.0
                if c in mis_y and y_val > 0:
                    mis_y[c] = round(y_val, 2)
                if z != "-" and y_val > 0:
                    cur = float(z)
                    pts = round(cur - y_val, 2)
                    pct = round((pts / y_val) * 100, 2)
                    if c == "t00":
                        res["taiex_val"], res["taiex_pts"], res["taiex_pct"] = cur, pts, pct
                    elif c == "o00":
                        res["tpex_val"], res["tpex_pts"], res["tpex_pct"] = cur, pts, pct
    except Exception:
        pass

    # 若盤前 z == "-"，優先以 MIS 官方昨收 y 為準，並補齊昨日漲跌點數與幅度
    if res["taiex_val"] == 0.0 or res["tpex_val"] == 0.0:
        fb = fetch_tw_official_last_close()
        if res["taiex_val"] == 0.0:
            res["is_premarket"] = True
            official_t00 = mis_y["t00"] if mis_y["t00"] > 0 else fb["taiex_val"]
            res["taiex_val"] = official_t00
            if official_t00 > 0 and fb["taiex_val"] > 0 and abs(official_t00 - fb["taiex_val"]) < 1.0:
                res["taiex_pts"], res["taiex_pct"] = fb["taiex_pts"], fb["taiex_pct"]
            elif official_t00 > 0 and fb["taiex_val"] > 0 and fb["taiex_val"] != official_t00:
                # 若 fb 抓到的是前一日收盤，直接用 MIS 官方昨收減去前一日收盤算出正確漲跌
                prev_day_c = fb["taiex_val"]
                pts = round(official_t00 - prev_day_c, 2)
                pct = round((pts / prev_day_c) * 100, 2) if prev_day_c > 0 else 0.0
                res["taiex_pts"], res["taiex_pct"] = pts, pct

        if res["tpex_val"] == 0.0:
            res["is_premarket"] = True
            official_o00 = mis_y["o00"] if mis_y["o00"] > 0 else fb["tpex_val"]
            res["tpex_val"] = official_o00
            if official_o00 > 0 and fb["tpex_val"] > 0 and abs(official_o00 - fb["tpex_val"]) < 0.5:
                res["tpex_pts"], res["tpex_pct"] = fb["tpex_pts"], fb["tpex_pct"]
            elif official_o00 > 0 and fb["tpex_val"] > 0 and fb["tpex_val"] != official_o00:
                prev_day_c2 = fb["tpex_val"]
                pts2 = round(official_o00 - prev_day_c2, 2)
                pct2 = round((pts2 / prev_day_c2) * 100, 2) if prev_day_c2 > 0 else 0.0
                res["tpex_pts"], res["tpex_pct"] = pts2, pct2

    return res

def evaluate_strategy(dji_pts: float, dji_pct: float, ixic_pct: float, sox_pct: float, taiex_pct: float, tpex_pct: float):
    all_down = (dji_pct < 0) and (ixic_pct < 0) and (sox_pct < 0)
    all_up = (dji_pct > 0) and (ixic_pct > 0) and (sox_pct > 0)
    tw_resilient = (taiex_pct > -0.6) or (tpex_pct > -0.3)

    if all_down and (dji_pts <= -300 or (dji_pct <= -1.0 and ixic_pct <= -1.5)):
        code = "FORMULA_1"
        title = "第一式：美股三大指數全面重挫（順勢做多 ＋ 黃金20秒動能 ＋ 雙向-6%戰法）"
        direction = "一律偏多操作（嚴禁無紀律攤平）"
        rules = [
            "【08:15 前備戰】列出昨日漲停鎖死股（排除處置股），精選 3～6 檔加入監控。",
            "【09:00:00～09:00:20 黃金20秒】不掛盤前單！觀察搓合後 20 秒內決定情境 A（開紅 +3%~6%）、情境 B（開綠急跌 -2%~3% 止跌）或情境 C（平盤 ±1% 順攻）。",
            "【雙向 -6% 鐵律】由上往下跌破 -6% 恐鎖跌停，務必於反彈 -5% 或破 -7% 停損；若殺破 -6% 後止穩「由下向上站回 -6%」，首次觸發直接進場、賺 1%～1.5% 即落袋！"
        ]
    elif (dji_pts <= -250 and (ixic_pct > -1.0 or sox_pct > -1.0)) or (dji_pct > 0 and (ixic_pct < 0 or sox_pct < 0)) or (dji_pct < 0 and sox_pct <= -2.5):
        code = "FORMULA_2"
        title = "第二式：美股三大指數走勢不同步（逆勢做多戰法・嚴禁放空）"
        direction = "只做逆勢多單（嚴禁放空）"
        rules = [
            "道瓊與那斯達克、費半出現不同步分歧，正是逆勢做多最佳時機。",
            "耐心觀察昨日漲停股開盤拉回變綠，忽略「第一次止跌」，等「第二次止跌線」或「由下向上站回 -6%（首次）」確認支撐再進場。",
            "不預設過前高！只要反彈達 1%～1.5% 安全價差或過成本線，有賺就跑、絕不貪心！"
        ]
    elif all_up:
        code = "ALL_UP"
        title = "特殊情境：美股三大指數全面大漲"
        direction = "持股開高先獲利了結 / 拉回低接原強勢股"
        rules = [
            "手中有昨日留倉大賺標的者，早盤開高先走一趟落袋為安。",
            "若強勢股開高後拉回測試平盤或成本線有守，可再低接買進。"
        ]
    else:
        code = "FORMULA_2_MILD"
        title = "第二式（溫和震盪版）：嚴選 3～4 檔漲停強勢股・安全快打"
        direction = "只做止跌反彈多單（賺 1%～1.5% 即走）"
        rules = [
            "美股波動幅度溫和，選股務必嚴格濃縮至 3～4 檔以內。",
            "搭配大盤強弱觀察，只做第二次止跌或由下向上站回 -6%（首次觸發）之安全短沖單。"
        ]

    resilient_note = "✅ 台股加權／櫃買盤中抗跌，【由下向上站回 -6%】快打戰法勝率加成！" if tw_resilient else "⚠️ 台股大盤偏弱，進場務必嚴格執行 -5% / -7% 紀律停損，切勿戀戰！"
    return {"code": code, "title": title, "direction": direction, "rules": rules, "resilient_note": resilient_note}

# ==========================================
# 4. 模組三：TWSE / TPEx Open Data 四層漏斗（嚴格排除處置股）
# ==========================================
@st.cache_data(ttl=1800)
def fetch_disposition_stocks() -> set:
    disposed = set()
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/announcement/punish", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            for item in r.json():
                code = str(item.get("Code", "")).strip()
                if code:
                    disposed.add(code)
    except Exception:
        pass
    try:
        r = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_disposal_information", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            for item in r.json():
                code = str(item.get("SecuritiesCompanyCode", "")).strip()
                if code:
                    disposed.add(code)
    except Exception:
        pass
    return disposed

@st.cache_data(ttl=1800)
def fetch_daytrade_eligible() -> set:
    eligible = set()
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/TWTB4U", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            for item in r.json():
                code = str(item.get("Code", "")).strip()
                if code and item.get("Suspension") != "Y":
                    eligible.add(code)
    except Exception:
        pass
    try:
        r = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_intraday_trading", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            for item in r.json():
                code = str(item.get("SecuritiesCompanyCode", "")).strip()
                if code:
                    eligible.add(code)
    except Exception:
        pass
    return eligible

def calc_5d_bias(code: str, market: str, close_price: float) -> float:
    suffix = ".TW" if market == "TSE" else ".TWO"
    try:
        hist = yf.Ticker(f"{code}{suffix}").history(period="10d")
        if len(hist) >= 5:
            ma5 = float(hist["Close"].tail(5).mean())
            return round(((close_price - ma5) / ma5) * 100, 2)
    except Exception:
        pass
    return 0.0

@st.cache_data(ttl=600)
def run_all_taiwan_funnel():
    disposed_set = fetch_disposition_stocks()
    daytrade_set = fetch_daytrade_eligible()
    all_quotes = []

    try:
        r_tse = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", headers=HEADERS, timeout=12)
        if r_tse.status_code == 200:
            for row in r_tse.json():
                code = str(row.get("Code", "")).strip()
                name_str = str(row.get("Name", "")).strip()
                # 排除 ETF（台股 00 開頭皆為 ETF/ETN）與非四碼純數字普通股
                if len(code) != 4 or not code.isdigit() or code.startswith("0") or "ETF" in name_str.upper():
                    continue
                try:
                    close_p = float(str(row.get("ClosingPrice", "0")).replace(",", ""))
                    high_p = float(str(row.get("HighestPrice", "0")).replace(",", ""))
                    chg = float(str(row.get("Change", "0")).replace(",", "").replace("+", ""))
                    vol_shares = int(str(row.get("TradeVolume", "0")).replace(",", ""))
                    if close_p > 0 and (close_p - chg) > 0:
                        prev_c = close_p - chg
                        pct = (chg / prev_c) * 100
                        all_quotes.append({
                            "code": code, "name": row.get("Name", "").strip(), "market": "TSE",
                            "close": close_p, "high": high_p, "pct": round(pct, 2),
                            "vol_lots": round(vol_shares / 1000, 0)
                        })
                except ValueError:
                    continue
    except Exception:
        pass

    try:
        r_otc = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", headers=HEADERS, timeout=12)
        if r_otc.status_code == 200:
            for row in r_otc.json():
                code = str(row.get("SecuritiesCompanyCode", "")).strip()
                name_str = str(row.get("CompanyName", "")).strip()
                # 排除 ETF（上櫃 00 開頭皆為債券/指數 ETF）與非四碼純數字普通股
                if len(code) != 4 or not code.isdigit() or code.startswith("0") or "ETF" in name_str.upper():
                    continue
                try:
                    close_p = float(str(row.get("Close", "0")).replace(",", ""))
                    high_p = float(str(row.get("High", "0")).replace(",", ""))
                    chg = float(str(row.get("Change", "0")).replace(",", "").replace("+", ""))
                    vol_shares = int(str(row.get("TradingShares", "0")).replace(",", ""))
                    if close_p > 0 and (close_p - chg) > 0:
                        prev_c = close_p - chg
                        pct = (chg / prev_c) * 100
                        all_quotes.append({
                            "code": code, "name": row.get("CompanyName", "").strip(), "market": "OTC",
                            "close": close_p, "high": high_p, "pct": round(pct, 2),
                            "vol_lots": round(vol_shares / 1000, 0)
                        })
                except ValueError:
                    continue
    except Exception:
        pass

    df = pd.DataFrame(all_quotes)
    stats = {"limit_up": 0, "valid_dt": 0, "price_ok": 0, "vol_ok": 0, "final": 0, "excluded_disposed": []}
    if df.empty:
        return pd.DataFrame(), stats, disposed_set, {}

    # 昨日漲停鎖死
    df_lu = df[(df["pct"] >= 9.5) & (df["close"] >= df["high"] * 0.998)].copy()
    stats["limit_up"] = len(df_lu)

    # 第一層：必須可當沖且排除處置股
    df_lu["is_disposed"] = df_lu["code"].isin(disposed_set)
    stats["excluded_disposed"] = df_lu[df_lu["is_disposed"]]["code"].tolist()
    df_lu["is_daytrade"] = df_lu["code"].isin(daytrade_set) if len(daytrade_set) > 0 else True
    df_step1 = df_lu[(~df_lu["is_disposed"]) & (df_lu["is_daytrade"])].copy()
    stats["valid_dt"] = len(df_step1)

    # 第二層：股價 >= 40 元
    df_step2 = df_step1[df_step1["close"] >= 40.0].copy()
    stats["price_ok"] = len(df_step2)

    # 第三層：昨量 >= 10,000 張
    df_step3 = df_step2[df_step2["vol_lots"] >= 10000].copy()
    stats["vol_ok"] = len(df_step3)

    all_stock_catalog = {}
    for _, r in df.iterrows():
        label = f"{r['code']} {r['name']}"
        all_stock_catalog[label] = {
            "code": r["code"],
            "name": r["name"],
            "market": r["market"],
            "close": float(r["close"])
        }
    if df_step3.empty:
        return pd.DataFrame(), stats, disposed_set, all_stock_catalog

    # 第四層：剔除高乖離，濃縮至 3~4 檔
    df_step3["bias_5d"] = df_step3.apply(lambda r: calc_5d_bias(r["code"], r["market"], r["close"]), axis=1)
    df_step3 = df_step3.sort_values(by="bias_5d", ascending=True)
    df_final = df_step3.head(4).copy() if len(df_step3) > 4 else df_step3.copy()

    # 計算雙向 -6% 與 1.3% 安全快打點位
    df_final["line_minus_6"] = df_final["close"].apply(lambda p: round_to_tick(p * 0.940, "down"))
    df_final["reclaim_entry"] = df_final["close"].apply(lambda p: round_to_tick(p * 0.9415, "up"))   # 站回 -5.85% 左右
    df_final["safe_tp_13"] = df_final["reclaim_entry"].apply(lambda p: round_to_tick(p * 1.013, "up"))  # +1.3% 安全停利
    df_final["sec_dip_low"] = df_final["close"].apply(lambda p: round_to_tick(p * 0.965, "down"))
    df_final["sec_dip_high"] = df_final["close"].apply(lambda p: round_to_tick(p * 0.975, "up"))
    df_final["hard_sl_7"] = df_final["close"].apply(lambda p: round_to_tick(p * 0.930, "down"))
    stats["final"] = len(df_final)

    all_stock_catalog = {}
    if not df.empty:
        for _, r in df.iterrows():
            label = f"{r['code']} {r['name']}"
            all_stock_catalog[label] = {
                "code": r["code"],
                "name": r["name"],
                "market": r["market"],
                "close": float(r["close"])
            }
    return df_final, stats, disposed_set, all_stock_catalog

# ==========================================
# 5. 模組四：TWSE MIS 全情境動態戰術引擎（黃金20秒 × 二次止跌 × 特殊雙向-6%）
# ==========================================
if "intraday_tracker" not in st.session_state:
    st.session_state["intraday_tracker"] = {}

def compute_stock_tactical_plan(ref_p: float, cur_p: float, cur_pct: float, min_p: float, min_pct: float, tracker: dict, strategy_code: str, is_premarket: bool):
    """依據老帥完整心法，針對個股當下價位動態匹配戰術情境、計算具體進場價／安全停利價(+1.3%)／紀律停損價與操作建議"""
    line_m6 = round_to_tick(ref_p * 0.940, "down")
    hard_sl_5 = round_to_tick(ref_p * 0.950, "nearest")
    hard_sl_7 = round_to_tick(ref_p * 0.930, "down")
    pre_prefix = "【盤前試搓預演・09:00等20秒再決斷】" if is_premarket else ""

    # 1) 特殊深跌情境：曾殺破 -6.5% 後「由下向上站回 -6%」
    if not is_premarket and tracker.get("was_below_65") and cur_pct > -6.0 and tracker.get("reclaim_cnt") == 1:
        entry_p = cur_p
        tp_p = round_to_tick(entry_p * 1.013, "up")
        sl_p = line_m6
        return (
            "特殊戰法｜由下向上站回-6%(第1次)",
            entry_p, tp_p, sl_p,
            f"🔥 首次由下向上站回 -6%！現價 {entry_p} 直接進場不猶豫，達 {tp_p} (+1.3%安全獲利) 落袋，再破 {sl_p} 停損"
        )

    if not is_premarket and tracker.get("was_below_65") and cur_pct > -6.0 and tracker.get("reclaim_cnt", 0) >= 2:
        entry_p = round_to_tick(ref_p * 0.965, "nearest")
        tp_p = round_to_tick(entry_p * 1.013, "up")
        return (
            "特殊戰法｜第2次站回-6%(勝率50%)",
            entry_p, tp_p, hard_sl_7,
            "⚠️ 已屬第 2 次站回 -6%（勝率僅 50%），依老帥鐵律放棄不追，避免誘多再殺跌停"
        )

    # 2) 特殊深跌情境：目前位於 -6.0% 以下（高風險跌停警戒區）
    if cur_pct <= -6.0:
        reclaim_p = round_to_tick(ref_p * 0.9415, "up")
        tp_p = round_to_tick(reclaim_p * 1.013, "up")
        return (
            "特殊警戒｜跌破-6%生死線",
            reclaim_p, tp_p, hard_sl_7,
            f"{pre_prefix}🚨 跌破 -6% 極可能鎖跌停！嚴禁攤平，持單者於反彈 {hard_sl_5} (-5%) 或破 {hard_sl_7} (-7%) 停損；空手者須等殺穩由下向上站回 {reclaim_p} 第1次再進"
        )

    # 3) 深綠觀察區（-3.5% < pct < -6.0%）：等待二次止跌或站回 -3%
    if -6.0 < cur_pct < -3.5:
        entry_p = round_to_tick(ref_p * 0.970, "up")
        tp_p = round_to_tick(entry_p * 1.013, "up")
        sl_p = line_m6
        return (
            "拉回觀察｜深綠測底止穩區",
            entry_p, tp_p, sl_p,
            f"{pre_prefix}⏳ 跌幅較深切勿急接第一刀，等止跌站回 {entry_p} (-3.0%) 確認買盤再試多，停利 {tp_p} (+1.3%)、破 {sl_p} (-6%) 停損"
        )

    # 4) 情境 B｜開綠急跌止跌區（-1.5% >= pct >= -3.5%）：黃金20秒情境B / 第二式二次止跌線
    if -3.5 <= cur_pct <= -1.5:
        if strategy_code in ["FORMULA_2", "FORMULA_2_MILD"]:
            entry_p = round_to_tick(ref_p * 0.972, "nearest")
            tp_p = round_to_tick(entry_p * 1.013, "up")
            sl_p = round_to_tick(ref_p * 0.955, "down")
            return (
                "第二式｜二次止跌做多區",
                entry_p, tp_p, sl_p,
                f"{pre_prefix}🎯 符合美股不同步逆勢做多區！忽略第一次止跌，等第二次止跌確認守穩 {entry_p} 附近進場，第一次反彈達 {tp_p} (+1.3%) 即全出"
            )
        else:
            entry_p = cur_p if not is_premarket else round_to_tick(ref_p * 0.975, "nearest")
            tp_p = round_to_tick(entry_p * 1.013, "up")
            sl_p = round_to_tick(ref_p * 0.955, "down")
            return (
                "情境B｜開綠急跌止跌試多",
                entry_p, tp_p, sl_p,
                f"{pre_prefix}🟢 關鍵2：開綠急跌 -2%~3% 出現下影線/量縮止跌，於 {entry_p} 勇敢進場，第一次反彈達 {tp_p} (+1.3%) 全出，破 {sl_p} 停損"
            )

    # 5) 情境 C｜平盤附近順攻區（-1.5% < pct <= +2.5%）：平盤±1%先進、破+2%加碼
    if -1.5 < cur_pct <= 2.5:
        entry_p = cur_p if (-1.0 <= cur_pct <= 1.2 and not is_premarket) else round_to_tick(ref_p * 1.008, "nearest")
        add_p = round_to_tick(ref_p * 1.020, "up")
        tp_p = round_to_tick(entry_p * 1.015, "up")
        sl_p = round_to_tick(ref_p * 0.980, "down")
        return (
            "情境C｜平盤順攻(最佳盤型)",
            entry_p, tp_p, sl_p,
            f"{pre_prefix}⚡ 關鍵3(最好做)：開在平盤±1% ({entry_p}) 順勢先進場，再衝破 {add_p} (+2%) 加碼，見第一次大量或達 {tp_p} (+1.5%) 果斷全出"
        )

    # 6) 情境 A｜開紅強勢攻擊區（+2.5% < pct <= +6.0%）
    if 2.5 < cur_pct <= 6.0:
        entry_p = cur_p if not is_premarket else round_to_tick(ref_p * 1.035, "nearest")
        tp_p = round_to_tick(entry_p * 1.013, "up")
        sl_p = round_to_tick(ref_p * 1.010, "down")
        return (
            "情境A｜強勢開紅順勢搶攻",
            entry_p, tp_p, sl_p,
            f"{pre_prefix}🚀 關鍵1：開紅 +3%~6% 且價格不亂跳，前 20 秒於 {entry_p} 直接進場（回跌可加碼2張），第一次反彈達 {tp_p} (+1.3%) 全出"
        )

    # 7) 情境 D｜開高過熱警戒區（pct > +6.0%）
    pullback_entry = round_to_tick(ref_p * 1.020, "nearest")
    tp_p = round_to_tick(pullback_entry * 1.013, "up")
    sl_p = round_to_tick(ref_p * 0.995, "down")
    return (
        "過熱警戒｜開高>6%禁追高",
        pullback_entry, tp_p, sl_p,
        f"{pre_prefix}⛔ 開盤已漲逾 +6% 逼近漲停，嚴禁直接追高！僅能等拉回 {pullback_entry} (+2%附近) 有守再低接，否則放棄換下一檔"
    )

def fetch_twse_mis_realtime(stocks_df: pd.DataFrame, strategy_code: str = "FORMULA_1") -> pd.DataFrame:
    if stocks_df.empty:
        return stocks_df
    ex_ch_list = [f"{'tse' if r['market'] == 'TSE' else 'otc'}_{r['code']}.tw" for _, r in stocks_df.iterrows()]
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={'|'.join(ex_ch_list)}&json=1&delay=0&_={int(time.time()*1000)}"

    now_dt = datetime.now(pytz.timezone("Asia/Taipei"))
    cur_hm = now_dt.hour * 100 + now_dt.minute
    is_premarket = (cur_hm < 900)

    rt_map = {}
    try:
        r = requests.get(url, headers={**HEADERS, "Referer": "https://mis.twse.com.tw/stock/fibest.jsp"}, timeout=6)
        if r.status_code == 200:
            for msg in r.json().get("msgArray", []):
                c = msg.get("c")
                z = msg.get("z", "-")
                y = msg.get("y", "-")
                l_val = msg.get("l", "-")
                # 盤前 08:30~09:00 若尚未正式撮合 (z == "-")，抓取試搓最佳買價 b[0] 作為試搓參考價
                trial_p = None
                if z == "-" and msg.get("b"):
                    try:
                        b0 = float(msg.get("b").split("_")[0])
                        if b0 > 0:
                            trial_p = b0
                    except ValueError:
                        pass
                try:
                    official_y = float(y) if y not in ["-", "", None] else None
                except ValueError:
                    official_y = None
                try:
                    cur_p = float(z) if z not in ["-", "", None] else trial_p
                except ValueError:
                    cur_p = trial_p
                try:
                    low_p = float(l_val) if l_val not in ["-", "", None] else cur_p
                except ValueError:
                    low_p = cur_p
                rt_map[c] = {"cur_p": cur_p, "low_p": low_p, "official_y": official_y}
    except Exception:
        pass

    res_df = stocks_df.copy()
    corrected_refs, live_prices, live_pcts, low_pcts = [], [], [], []
    tactic_modes, sugg_entries, safe_tps, stop_losses, action_advices, reclaim_counts = [], [], [], [], [], []

    for _, row in res_df.iterrows():
        code = row["code"]
        info = rt_map.get(code, {})
        # 關鍵修正：優先採用 MIS 官方昨收 y 校正昨漲停基準價，避免 STOCK_DAY_ALL 尚未換日造成基準價落差
        ref_p = info.get("official_y") if (info.get("official_y") and info.get("official_y") > 0) else float(row["close"])
        cur_p = info.get("cur_p") if (info.get("cur_p") and info.get("cur_p") > 0) else ref_p
        api_low = info.get("low_p") if (info.get("low_p") and info.get("low_p") > 0) else cur_p

        if is_premarket:
            # 盤前尚未正式開盤，不累積盤中最低點與破線計數
            min_p = cur_p
            tracker = {"min_p": cur_p, "reclaim_cnt": 0, "was_below_65": False}
        else:
            tracker = st.session_state["intraday_tracker"].get(code, {"min_p": api_low, "reclaim_cnt": 0, "was_below_65": False})
            min_p = min(tracker["min_p"], cur_p, api_low)
            min_pct_tmp = round(((min_p - ref_p) / ref_p) * 100, 2)
            cur_pct_tmp = round(((cur_p - ref_p) / ref_p) * 100, 2)

            if min_pct_tmp <= -6.5:
                tracker["was_below_65"] = True
            if tracker["was_below_65"] and -6.0 < cur_pct_tmp <= -4.8:
                if tracker["reclaim_cnt"] == 0:
                    tracker["reclaim_cnt"] = 1
            elif cur_pct_tmp <= -6.3 and tracker["reclaim_cnt"] == 1:
                tracker["reclaim_cnt"] = 2

            tracker["min_p"] = min_p
            st.session_state["intraday_tracker"][code] = tracker

        cur_pct = round(((cur_p - ref_p) / ref_p) * 100, 2)
        min_pct = round(((min_p - ref_p) / ref_p) * 100, 2)

        t_mode, s_entry, s_tp, s_sl, advice = compute_stock_tactical_plan(
            ref_p=ref_p,
            cur_p=cur_p,
            cur_pct=cur_pct,
            min_p=min_p,
            min_pct=min_pct,
            tracker=tracker,
            strategy_code=strategy_code,
            is_premarket=is_premarket
        )

        corrected_refs.append(round(ref_p, 2))
        live_prices.append(round(cur_p, 2))
        live_pcts.append(cur_pct)
        low_pcts.append(min_pct)
        tactic_modes.append(t_mode)
        sugg_entries.append(s_entry)
        safe_tps.append(s_tp)
        stop_losses.append(s_sl)
        action_advices.append(advice)
        reclaim_counts.append(tracker["reclaim_cnt"])

    res_df["close"] = corrected_refs
    res_df["line_minus_6"] = [round_to_tick(p * 0.940, "down") for p in corrected_refs]
    res_df["live_price"] = live_prices
    res_df["live_pct"] = live_pcts
    res_df["low_pct"] = low_pcts
    res_df["tactic_mode"] = tactic_modes
    res_df["sugg_entry"] = sugg_entries
    res_df["safe_tp_13"] = safe_tps
    res_df["stop_loss"] = stop_losses
    res_df["signal"] = action_advices
    res_df["reclaim_cnt"] = reclaim_counts
    res_df["is_premarket"] = is_premarket
    return res_df

# ==========================================
# 6. 模組五：Gemini API 多金鑰輪替「老帥」AI 專家覆盤引擎
# ==========================================
def get_gemini_api_keys() -> list:
    keys = []
    # 支援 Streamlit Secrets 與環境變數（單一金鑰或逗號分隔多金鑰）
    for env_name in ["GEMINI_API_KEY", "GEMINI_API_KEYS", "GOOGLE_API_KEY"]:
        val = ""
        try:
            if env_name in st.secrets:
                val = st.secrets[env_name]
        except Exception:
            pass
        if not val:
            val = os.environ.get(env_name, "")
        if isinstance(val, list):
            keys.extend([str(k).strip() for k in val if str(k).strip()])
        elif isinstance(val, str) and val.strip():
            keys.extend([k.strip() for k in val.split(",") if k.strip()])
    # 去重保序
    seen = set()
    return [k for k in keys if not (k in seen or seen.add(k))]

def get_exact_prev_close(stock_label: str, trade_date_obj, live_df: pd.DataFrame, catalog: dict) -> float:
    """精準取得指定交易日的前一交易日收盤價（避免盤後 OpenData 更新為當日收盤價導致漲跌幅算錯）"""
    code_str = stock_label.split()[0].strip() if stock_label else ""
    market = "TSE"
    if stock_label in catalog:
        market = catalog[stock_label].get("market", "TSE")
    if code_str:
        suffix = ".TW" if market == "TSE" else ".TWO"
        try:
            hist = yf.Ticker(f"{code_str}{suffix}").history(period="10d")
            if not hist.empty:
                hist = hist.copy()
                hist.index = hist.index.tz_convert("Asia/Taipei") if hist.index.tz is not None else hist.index.tz_localize("Asia/Taipei")
                prev_rows = hist[hist.index.date < trade_date_obj]
                if not prev_rows.empty:
                    return round(float(prev_rows["Close"].iloc[-1]), 2)
        except Exception:
            pass
    if not live_df.empty:
        m_live = live_df[live_df.apply(lambda r: f"{r['code']} {r['name']}" == stock_label, axis=1)]
        if not m_live.empty:
            return float(m_live.iloc[0]["close"])
    if stock_label in catalog:
        return float(catalog[stock_label]["close"])
    return 0.0

def get_finmind_token() -> str:
    for env_name in ["FINMIND_TOKEN", "FINMIND_API_TOKEN"]:
        val = ""
        try:
            if env_name in st.secrets:
                val = str(st.secrets[env_name]).strip()
        except Exception:
            pass
        if not val:
            val = os.environ.get(env_name, "").strip()
        if val:
            return val
    return ""

def fetch_intraday_fact_check(stock_label: str, trade_date_obj, entry_time_str: str, entry_price: float, catalog: dict) -> dict:
    """結合 FinMind API (FINMIND_TOKEN) 與 yfinance 分時K線，事實驗證個股當日真實高低點與是否真的達成『由下向上站回 -6%』等進場條件"""
    code_str = stock_label.split()[0].strip() if stock_label else ""
    market = catalog.get(stock_label, {}).get("market", "TSE")
    date_str = trade_date_obj.strftime("%Y-%m-%d")
    fm_token = get_finmind_token()

    prev_close = 0.0
    day_open = 0.0
    day_high = 0.0
    day_low = 0.0
    day_close = 0.0
    intraday_bars = []
    data_sources = []

    # 1) 透過 FinMind TaiwanStockPrice 取得精準前一日收盤價與當日日K高低點
    if fm_token and code_str:
        try:
            start_q = (trade_date_obj - timedelta(days=10)).strftime("%Y-%m-%d")
            r_fm = requests.get(
                "https://api.finmindtrade.com/api/v4/data",
                params={
                    "dataset": "TaiwanStockPrice",
                    "data_id": code_str,
                    "start_date": start_q,
                    "end_date": date_str,
                    "token": fm_token,
                },
                timeout=8,
            )
            if r_fm.status_code == 200:
                fm_data = r_fm.json().get("data", [])
                if fm_data:
                    prev_rows = [d for d in fm_data if d.get("date", "") < date_str]
                    curr_rows = [d for d in fm_data if d.get("date", "") == date_str]
                    if prev_rows:
                        prev_close = round(float(prev_rows[-1]["close"]), 2)
                        data_sources.append("FinMind日K")
                    if curr_rows:
                        day_open = round(float(curr_rows[-1]["open"]), 2)
                        day_high = round(float(curr_rows[-1]["max"]), 2)
                        day_low = round(float(curr_rows[-1]["min"]), 2)
                        day_close = round(float(curr_rows[-1]["close"]), 2)
        except Exception:
            pass

    # 2) 透過 FinMind 盤中逐筆成交 (TaiwanStockPriceTick) 取得精準盤中時間軸
    if fm_token and code_str:
        try:
            r_tick = requests.get(
                "https://api.finmindtrade.com/api/v4/data",
                params={
                    "dataset": "TaiwanStockPriceTick",
                    "data_id": code_str,
                    "start_date": date_str,
                    "token": fm_token,
                },
                timeout=10,
            )
            if r_tick.status_code == 200:
                ticks = r_tick.json().get("data", [])
                if ticks:
                    min_map = {}
                    for tk in ticks:
                        t_raw = str(tk.get("Time", "")).strip()
                        p_val = float(tk.get("deal_price", 0) or 0)
                        if len(t_raw) >= 5 and p_val > 0:
                            hhmm = t_raw[:5]
                            if hhmm not in min_map:
                                min_map[hhmm] = {"time": t_raw[:8], "low": p_val, "high": p_val, "close": p_val}
                            else:
                                min_map[hhmm]["low"] = min(min_map[hhmm]["low"], p_val)
                                min_map[hhmm]["high"] = max(min_map[hhmm]["high"], p_val)
                                min_map[hhmm]["close"] = p_val
                    if min_map:
                        intraday_bars = [min_map[k] for k in sorted(min_map.keys())]
                        data_sources.append("FinMind盤中逐筆Tick")
        except Exception:
            pass

    # 3) 透過 yfinance 補齊昨收與 1m/2m/5m 分時K線
    if code_str:
        suffix = ".TW" if market == "TSE" else ".TWO"
        try:
            if prev_close <= 0:
                hist_d = yf.Ticker(f"{code_str}{suffix}").history(period="10d")
                if not hist_d.empty:
                    hist_d = hist_d.copy()
                    hist_d.index = hist_d.index.tz_convert("Asia/Taipei") if hist_d.index.tz is not None else hist_d.index.tz_localize("Asia/Taipei")
                    p_rows = hist_d[hist_d.index.date < trade_date_obj]
                    if not p_rows.empty:
                        prev_close = round(float(p_rows["Close"].iloc[-1]), 2)
                        if "FinMind日K" not in data_sources:
                            data_sources.append("Yahoo日K")
                    c_rows = hist_d[hist_d.index.date == trade_date_obj]
                    if not c_rows.empty and day_low <= 0:
                        day_open = round(float(c_rows["Open"].iloc[-1]), 2)
                        day_high = round(float(c_rows["High"].iloc[-1]), 2)
                        day_low = round(float(c_rows["Low"].iloc[-1]), 2)
                        day_close = round(float(c_rows["Close"].iloc[-1]), 2)
        except Exception:
            pass

        if not intraday_bars:
            for itv in ["1m", "2m", "5m"]:
                try:
                    h_int = yf.Ticker(f"{code_str}{suffix}").history(period="5d", interval=itv)
                    if h_int.empty:
                        continue
                    h_int = h_int.copy()
                    h_int.index = h_int.index.tz_convert("Asia/Taipei") if h_int.index.tz is not None else h_int.index.tz_localize("Asia/Taipei")
                    day_h = h_int[h_int.index.date == trade_date_obj]
                    if not day_h.empty:
                        for ts, row in day_h.iterrows():
                            intraday_bars.append({
                                "time": ts.strftime("%H:%M:%S"),
                                "low": round(float(row["Low"]), 2),
                                "high": round(float(row["High"]), 2),
                                "close": round(float(row["Close"]), 2),
                            })
                        if day_low <= 0:
                            day_open = round(float(day_h["Open"].iloc[0]), 2)
                            day_high = round(float(day_h["High"].max()), 2)
                            day_low = round(float(day_h["Low"].min()), 2)
                            day_close = round(float(day_h["Close"].iloc[-1]), 2)
                        data_sources.append(f"Yahoo {itv}分K")
                        break
                except Exception:
                    continue

    if intraday_bars:
        bar_min = min(b["low"] for b in intraday_bars)
        bar_max = max(b["high"] for b in intraday_bars)
        day_low = min(day_low, bar_min) if day_low > 0 else bar_min
        day_high = max(day_high, bar_max) if day_high > 0 else bar_max

    line_m6 = round_to_tick(prev_close * 0.940, "down") if prev_close > 0 else 0.0
    ideal_reclaim_p = round_to_tick(prev_close * 0.9415, "up") if prev_close > 0 else 0.0
    day_low_pct = round(((day_low - prev_close) / prev_close) * 100, 2) if (prev_close > 0 and day_low > 0) else 0.0
    entry_pct = round(((entry_price - prev_close) / prev_close) * 100, 2) if (prev_close > 0 and entry_price > 0) else 0.0

    ever_below_m6 = False
    below_m6_before_entry = False
    first_break_m6_time = "未知"
    low_time_str = "未知"
    reclaim_events = []

    if prev_close > 0 and intraday_bars:
        min_bar_price = min(b["low"] for b in intraday_bars)
        for b in intraday_bars:
            if b["low"] == min_bar_price and low_time_str == "未知":
                low_time_str = b["time"]
        in_deep_zone = False
        for b in intraday_bars:
            b_low_pct = ((b["low"] - prev_close) / prev_close) * 100
            b_close_pct = ((b["close"] - prev_close) / prev_close) * 100
            b_high_pct = ((b["high"] - prev_close) / prev_close) * 100
            if b_low_pct <= -6.0:
                if not ever_below_m6:
                    first_break_m6_time = b["time"]
                ever_below_m6 = True
                in_deep_zone = True
                if b["time"][:5] <= entry_time_str[:5]:
                    below_m6_before_entry = True
            if in_deep_zone and (b_close_pct > -6.0 or b_high_pct > -5.95):
                rec_p = b["close"] if b_close_pct > -6.0 else ideal_reclaim_p
                rec_pct = round(((rec_p - prev_close) / prev_close) * 100, 2)
                reclaim_events.append({
                    "count": len(reclaim_events) + 1,
                    "time": b["time"],
                    "price": round(rec_p, 2),
                    "pct": rec_pct,
                })
                in_deep_zone = False
    elif prev_close > 0 and day_low > 0:
        ever_below_m6 = (day_low_pct <= -6.0)
        below_m6_before_entry = ever_below_m6

    return {
        "prev_close": prev_close,
        "day_open": day_open,
        "day_high": day_high,
        "day_low": day_low,
        "day_close": day_close,
        "day_low_pct": day_low_pct,
        "first_break_m6_time": first_break_m6_time,
        "low_time": low_time_str,
        "line_m6": line_m6,
        "ideal_reclaim_p": ideal_reclaim_p,
        "entry_pct": entry_pct,
        "ever_below_m6": ever_below_m6,
        "below_m6_before_entry": below_m6_before_entry,
        "reclaim_events": reclaim_events,
        "has_intraday_bars": len(intraday_bars) > 0,
        "data_sources": " + ".join(data_sources) if data_sources else "系統快取基準",
    }

def _create_genai_clients(api_key: str) -> list:
    """同時相容 Google AI Studio / GCP 新版 AQ. 開頭 Gemini API 金鑰與 Vertex Express 模式"""
    k = api_key.strip()
    if k.startswith("AQ."):
        return [
            ("Gemini-API", genai.Client(api_key=k)),
            ("Vertex-Express", genai.Client(vertexai=True, api_key=k)),
        ]
    return [("Gemini-API", genai.Client(api_key=k))]

def _get_candidate_models(client) -> list:
    """優先使用金鑰實際列出的 generateContent 模型，避免失效名稱造成大量 404。"""
    discovered = []
    try:
        for m in client.models.list():
            name = (getattr(m, "name", "") or "").removeprefix("models/")
            actions = [str(a).lower() for a in (getattr(m, "supported_actions", []) or [])]
            if name and "gemini" in name.lower() and (not actions or "generatecontent" in actions):
                discovered.append(name)
    except Exception:
        pass
    ranked = sorted(set(discovered), key=lambda n: (0 if "2.5-flash" in n else 1 if "flash" in n else 2, "preview" in n.lower(), n))
    return (ranked or ["gemini-2.5-flash", "gemini-2.0-flash"])[:3]

def _friendly_ai_error(errors: list) -> str:
    """將 API 錯誤分類成可行動訊息；429 不再一律誤寫成總額度用完。"""
    text = " | ".join(errors).lower()
    if "404" in text or "not_found" in text:
        return "指定的 AI 模型或 API 版本目前不可用"
    if "403" in text or "permission_denied" in text:
        return "AI 金鑰、專案權限或帳務設定不允許此次呼叫"
    if "503" in text or "unavailable" in text or "504" in text or "gateway_timeout" in text:
        return "AI 服務目前繁忙或暫時無法連線"
    if "429" in text or "resource_exhausted" in text or "too_many_requests" in text:
        if "per_day" in text or "requestsperday" in text or "daily" in text:
            return "此專案今日的 AI 模型請求額度已達限制"
        if "token" in text:
            return "本次內容或短時間 Token 用量超過模型限制"
        if "per_minute" in text or "requestsperminute" in text or "retry" in text:
            return "短時間 AI 請求過多，需稍後再試"
        return "AI 回覆 429：可能是短時間速率、特定模型配額或共享服務容量限制，不代表 28 天總用量已用完"
    if "400" in text or "bad_request" in text:
        return "AI 請求格式或輸入內容不符合模型要求"
    return "AI 連線暫時異常"


def detect_trade_direction(entry_reason="", exit_reason="", behaviors=None, explicit="自動判斷") -> tuple:
    if explicit in ("做多", "做空"):
        return explicit, "使用者指定"
    text = " ".join([entry_reason or "", exit_reason or "", " ".join(behaviors or [])]).lower()
    short_words = ["做空", "放空", "空單", "融券賣出", "先賣後買", "short", "sell short", "回補"]
    long_words = ["做多", "多單", "買進", "低接", "站回", "止跌", "long", "先買後賣"]
    short_score = sum(w in text for w in short_words)
    long_score = sum(w in text for w in long_words)
    if short_score > long_score:
        return "做空", "依進出理由／操作行為自動判斷"
    if long_score > short_score:
        return "做多", "依進出理由／操作行為自動判斷"
    return "做多", "沒有足夠做空證據，依本系統做多策略暫判"

def calc_trade_pnl(entry_price: float, exit_price: float, direction: str) -> float:
    if entry_price <= 0:
        return 0.0
    pnl = (exit_price - entry_price) / entry_price * 100
    return round(-pnl if direction == "做空" else pnl, 2)

def calc_trade_costs(entry_price: float, exit_price: float, shares: int, direction: str,
                     trade_type: str = "現股當沖", fee_discount: float = 0.6,
                     minimum_fee: int = 20, extra_fee: int = 0) -> dict:
    """計算台股買賣手續費、證券交易稅與稅費後淨損益。金額採元以下捨去並套用單筆最低手續費。"""
    shares = max(1, int(shares))
    buy_price = entry_price if direction == "做多" else exit_price
    sell_price = exit_price if direction == "做多" else entry_price
    buy_amount = round(buy_price * shares)
    sell_amount = round(sell_price * shares)
    fee_rate = 0.001425 * max(0.0, float(fee_discount))
    buy_fee = max(int(minimum_fee), int(buy_amount * fee_rate))
    sell_fee = max(int(minimum_fee), int(sell_amount * fee_rate))
    tax_rate = 0.0015 if trade_type == "現股當沖" else 0.003
    transaction_tax = int(sell_amount * tax_rate)
    gross_pnl = sell_amount - buy_amount
    extra_fee = max(0, int(extra_fee))
    total_cost = buy_fee + sell_fee + transaction_tax + extra_fee
    net_pnl = gross_pnl - total_cost
    capital_base = buy_amount if direction == "做多" else sell_amount
    gross_pnl_pct = round((gross_pnl / capital_base) * 100, 3) if capital_base > 0 else 0.0
    net_pnl_pct = round((net_pnl / capital_base) * 100, 3) if capital_base > 0 else 0.0
    return {
        "shares": shares, "buy_amount": buy_amount, "sell_amount": sell_amount,
        "buy_fee": buy_fee, "sell_fee": sell_fee, "transaction_tax": transaction_tax,
        "tax_rate": tax_rate, "total_cost": total_cost, "gross_pnl": gross_pnl,
        "net_pnl": net_pnl, "gross_pnl_pct": gross_pnl_pct, "net_pnl_pct": net_pnl_pct,
        "fee_discount": fee_discount, "minimum_fee": minimum_fee, "extra_fee": extra_fee, "trade_type": trade_type,
    }

LAOSHUAI_KNOWLEDGE = {
    "first_style": {
        "name": "美股大跌做多法第一式｜三大指數同步下跌",
        "market": "道瓊、NASDAQ、費城半導體同步下跌；道瓊大跌約 300 點以上是重要警示。",
        "direction": "只做多，以順勢做多為主，不做空。",
        "universe": "以前一交易日漲停鎖死股為候選；開盤前縮減至可專注操作的 3～6 檔。",
        "entry": ["開盤後先觀察 10～20 秒並等待撮合完成", "開紅約 +3%～+6%且量價穩定，可順勢試單", "開綠急跌約 -2%～-3%，需有下影線、量縮或明確止跌才接", "平盤約 ±1%順勢上攻，可分段進場；突破 +2%才考慮加碼"],
        "exit": ["第一次反彈或第一次明顯爆量即出場", "目標以 1%～2%安全價差為主，不預設過前高、不貪心"],
        "risk": ["跌幅超過 -6%視為高風險", "可在反彈至約 -5%時退出，或下跌至 -7%直接停損", "停損後不再做多、不反手做空，當日放棄該股", "第二次反彈可靠度較低，原則上不重複操作"],
    },
    "second_style": {
        "name": "美股大跌做多法第二式｜三大指數不同步逆勢做多",
        "market": "道瓊、NASDAQ、費城半導體走勢不同步，例如道瓊抗跌或上漲，但NASDAQ／費半轉弱，尤其費半明顯下跌。",
        "direction": "只做逆勢多單，不做順勢空單，也不做逆勢空單。",
        "universe": "前一交易日漲停鎖死股；剔除不能當沖、40 元以下、日量未破萬張及乖離過大者，最後保留約 3～4 檔。",
        "entry": ["觀察綠色下跌，不在急殺途中猜底", "以第二次止跌線或第二次明確支撐為主要確認", "需同時核對加權與櫃買是否止跌或抗跌"],
        "exit": ["反彈越過持有成本即以有賺就跑為原則", "不預設前高，安全目標約 1%～1.5%，最多約 2%"],
        "risk": ["若跌破有效支撐並持續滾量，不得無限攤平", "跌幅擴大至 -6%附近須啟動停損評估", "反彈至約 -5%可退場，或跌至 -7%直接停損", "策略只允許做多，停損後放棄該股"],
    },
    "fallback": {
        "name": "一般技術面與操作面覆盤",
        "rules": ["先確認買賣順序與多空方向", "檢查進場是否追價、是否有成交量與支撐／壓力證據", "檢查停損是否事前設定、是否延遲執行", "以稅費後淨損益評估，不只看價差", "資料不足時明確標示，不猜測截圖內容"],
    },
}

def get_laoshuai_playbook(strategy_mode: str) -> dict:
    text = str(strategy_mode or "")
    # 必須先判斷「不同步」，避免「不同步」內含「同步」而被誤判為第一式。
    if "第二式" in text or "不同步" in text or "逆勢" in text:
        return LAOSHUAI_KNOWLEDGE["second_style"]
    if "第一式" in text or "全面" in text or "同步" in text:
        return LAOSHUAI_KNOWLEDGE["first_style"]
    return LAOSHUAI_KNOWLEDGE["fallback"]

def format_playbook_for_prompt(playbook: dict) -> str:
    lines = [f"戰法：{playbook.get('name', '')}"]
    for key, label in [("market","適用盤勢"),("direction","方向限制"),("universe","選股限制")]:
        if playbook.get(key): lines.append(f"- {label}：{playbook[key]}")
    for key, label in [("entry","進場規則"),("exit","出場規則"),("risk","風控規則"),("rules","一般規則")]:
        vals = playbook.get(key, [])
        if vals: lines.append(f"- {label}：" + "；".join(vals))
    return "\n".join(lines)

def local_professional_review(peer_note: str, user_context: dict, reason: str) -> tuple:
    """無雲端 AI 時的具體覆盤。個人操作使用表單與行情資料；他人操作才使用補充文字。"""
    ctx = user_context or {}
    is_personal = bool(ctx.get("entry_price") or ctx.get("exit_price") or ctx.get("fact_check"))
    playbook = get_laoshuai_playbook(ctx.get("strategy_mode", ""))

    if not is_personal:
        note = (peer_note or "").strip()
        direction, basis = detect_trade_direction(note, "", [], "自動判斷")
        if not note:
            direction, basis = "方向無法確認", "只有截圖且 AI 視覺辨識未完成"
        elif "沒有足夠" in basis:
            direction, basis = "方向無法確認", "文字未提供先買後賣、先賣後買、放空或回補證據"
        return (f"""### 老師本機文字解盤

**狀態：** {reason}。截圖尚未完成 AI 視覺辨識，以下只分析補充文字。

**多空方向：{direction}**  
判斷依據：{basis}

**可確認內容：** {note if note else '沒有可供判斷的文字交易資料。'}

**結論：** 在未取得標的、買賣順序、進出時間與價格前，不做勝負或技術型態推論。請補上這些資料後再分析。""",
                "本機知識庫｜他人操作文字分析")

    direction = ctx.get("trade_direction", "方向無法確認")
    direction_basis = ctx.get("direction_basis", "未提供")
    stock = ctx.get("stock", "未填標的")
    entry_price = float(ctx.get("entry_price", 0) or 0)
    exit_price = float(ctx.get("exit_price", 0) or 0)
    entry_time = ctx.get("entry_time", "未填")
    exit_time = ctx.get("exit_time", "未填")
    entry_reason = str(ctx.get("entry_reason", "") or "")
    exit_reason = str(ctx.get("exit_reason", "") or "")
    behaviors = ctx.get("behaviors", []) or []
    pnl_pct = float(ctx.get("pnl_pct", 0) or 0)
    gross_pct = float(ctx.get("gross_pnl_pct", pnl_pct) or 0)
    gross_pnl = int(ctx.get("gross_pnl", 0) or 0)
    net_pnl = int(ctx.get("net_pnl", 0) or 0)
    total_cost = int(ctx.get("total_cost", 0) or 0)
    shares = int(ctx.get("shares", 0) or 0)
    trade_type = ctx.get("trade_type", "未填")
    fc = ctx.get("fact_check", {}) or {}
    ref = float(ctx.get("ref_price", fc.get("prev_close", 0)) or 0)
    entry_pct = ((entry_price / ref) - 1) * 100 if ref > 0 and entry_price > 0 else None
    exit_pct = ((exit_price / ref) - 1) * 100 if ref > 0 and exit_price > 0 else None

    # 戰法相容性先判斷，避免第二式只做多卻把做空硬套進去。
    strategy_name = playbook.get("name", "一般技術面與操作面覆盤")
    strategy_issues = []
    if playbook in (LAOSHUAI_KNOWLEDGE["first_style"], LAOSHUAI_KNOWLEDGE["second_style"]) and direction == "做空":
        strategy_issues.append(f"本次是做空，但「{strategy_name}」規則只允許做多，因此本筆不能用該戰法評為合格交易")
    if not fc.get("us_market_confirmed", False):
        strategy_issues.append("未取得可驗證的道瓊、NASDAQ、費半同步／不同步資料，無法確認第一式或第二式成立")
    if not fc.get("market_support_confirmed", False) and playbook is LAOSHUAI_KNOWLEDGE["second_style"]:
        strategy_issues.append("未取得加權與櫃買的止跌／抗跌證據，第二式的市場確認條件不足")

    findings = []
    if entry_pct is not None:
        if entry_pct <= -6:
            findings.append(f"進場價相對昨收為 {entry_pct:+.2f}%，已在 -6% 以下；若是做多，必須先證明由下往上站回或第二次止跌，不能只因跌深就接")
        elif entry_pct >= 3:
            findings.append(f"進場價相對昨收為 {entry_pct:+.2f}%，屬明顯開紅／上漲位置；需確認不是反彈後追價")
        else:
            findings.append(f"進場價相對昨收為 {entry_pct:+.2f}%，仍需搭配量能、均價線與止跌／突破證據")
    if "感覺" in entry_reason or "感覺" in exit_reason:
        findings.append("進出理由含主觀『感覺』，缺少可重複執行的價格或型態條件")
    if any(x in behaviors for x in ["越跌越買（攤平）", "凹單不出"]):
        findings.append("操作行為包含攤平或凹單，與 -6%附近啟動風控、-7%直接停損的規則衝突")
    if pnl_pct > 0:
        result_judgment = f"本筆稅費後獲利 {net_pnl:+,} 元（{pnl_pct:+.3f}%），結果為獲利；但獲利不等於進場符合戰法"
    elif pnl_pct < 0:
        result_judgment = f"本筆稅費後損失 {net_pnl:+,} 元（{pnl_pct:+.3f}%），需優先檢查進場證據與停損是否延遲"
    else:
        result_judgment = "本筆稅費後損益接近持平，仍應檢查交易成本是否吃掉原始價差"

    issue_text = "\n".join(f"- {x}" for x in strategy_issues) or "- 已取得的資料未發現戰法方向衝突，但仍需市場與型態證據才能確認符合戰法。"
    finding_text = "\n".join(f"- {x}" for x in findings) or "- 目前輸入不足以判斷追價、止跌、量價或停損執行情況。"
    behavior_text = "、".join(behaviors) if behaviors else "未勾選"

    report = f"""### 本筆交易結論

**{result_judgment}**

### 交易事實

- 標的：{stock}
- 方向：{direction}，依據：{direction_basis}
- 進場：{entry_time}／{entry_price:.2f} 元；出場：{exit_time}／{exit_price:.2f} 元
- 股數與類型：{shares:,} 股／{trade_type}
- 毛損益：{gross_pnl:+,} 元（{gross_pct:+.3f}%）
- 交易成本：{total_cost:,} 元
- 稅費後淨損益：{net_pnl:+,} 元（{pnl_pct:+.3f}%）

### 美股大跌法是否適用

- 系統候選戰法：{strategy_name}
{issue_text}

**裁決：** {'本筆不符合該戰法，改以技術面與操作面覆盤。' if strategy_issues else '目前只能列為待確認，不能直接判定符合戰法。'}

### 技術面與操作面診斷

{finding_text}
- 進場理由：{entry_reason or '未填'}
- 出場理由：{exit_reason or '未填'}
- 已勾選行為：{behavior_text}

### 老師具體改進指令

1. 下次進場前，先寫出唯一可驗證訊號，例如「第二次止跌線成立且重新站回均價線」，不要只寫看好或感覺會漲。
2. 若使用第一式／第二式，先確認美股三大指數狀態；第二式還要確認加權與櫃買止跌或抗跌。
3. 做空交易不得套用只做多的美股大跌法，應改用一般技術面的壓力、跌破、量能與回補規則。
4. 報酬一律看稅費後淨損益，本筆交易成本為 {total_cost:,} 元。

> 本機解盤原因：{reason}。以上每項結論均來自表單與行情資料；缺少的市場或技術證據明確標為不足。"""
    return report, f"本機知識庫｜個人交易具體覆盤｜{strategy_name}"


def run_laoshuai_ai_review(payload: dict) -> tuple:
    """呼叫 Gemini 2.5 Flash（支援多組 AIzaSy 與 AQ. 金鑰輪替）結合盤中真實分時數據進行老帥一對一精準覆盤"""
    api_keys = get_gemini_api_keys()
    fc = payload.get("fact_check", {})
    reclaim_list = fc.get("reclaim_events", [])
    reclaim_summary = (
        "；".join([f"第{ev['count']}次站回：{ev['time']}（約 {ev['price']} 元 / {ev['pct']:+.2f}%）" for ev in reclaim_list])
        if reclaim_list else "盤中分時未出現『跌破 -6% 後由下向上站回 -6%』紀錄"
    )

    fact_block = f"""【系統實測盤中客觀數據驗證（資料源：{fc.get('data_sources', '市場數據')}）】
- 前一交易日收盤價：{fc.get('prev_close', 0)} 元
- 戰法 -6.0% 生死線價格：{fc.get('line_m6', 0)} 元（站回 -6% 理論理想進場價：約 {fc.get('ideal_reclaim_p', 0)} 元）
- 當日實際開盤 / 最高 / 最低 / 收盤：{fc.get('day_open', 0)} / {fc.get('day_high', 0)} / {fc.get('day_low', 0)}（最低跌幅 {fc.get('day_low_pct', 0):+.2f}%，最低點出現時間：{fc.get('low_time', '未知')}） / {fc.get('day_close', 0)} 元
- 該股當日是否真的有跌破 -6.0%：{"是（最低 " + str(fc.get('day_low')) + " 元 / " + f"{fc.get('day_low_pct', 0):+.2f}%" + "）" if fc.get('ever_below_m6') else "否（全天最低僅 " + str(fc.get('day_low')) + " 元 / " + f"{fc.get('day_low_pct', 0):+.2f}%" + "，根本沒跌破 -6.0%）"}
- 學員進場時間（{payload['entry_time']}）之前是否已跌破 -6.0%：{"是" if fc.get('below_m6_before_entry') else "否"}
- 盤中『由下向上站回 -6.0%』真實觸發時間點紀錄：{reclaim_summary}"""

    playbook_text = format_playbook_for_prompt(get_laoshuai_playbook(payload.get("strategy_mode", "")))
    prompt = f"""
你現在是「老帥」，一位擁有 30 年以上台股實戰經驗、專精「美股連動＋昨日漲停股隔日當沖」的高勝率操盤專家。
學員要求你**絕不敷衍、必須根據下方客觀盤中數據精準驗證他的進場條件是否真的成立**！請用繁體中文進行嚴格、務實、數據說話的一對一覆盤診斷。必須區分「已驗證事實」「合理推論」「資料不足」，不得把推論寫成事實；先確認做多或做空，再計算損益與風險；所有建議價格必須符合台股跳動單位：

【學員提交的操作紀錄】
- 交易日期：{payload['trade_date']}
- 操作標的：{payload['stock']}
- 交易方向：{payload.get('trade_direction', '做多')}（{payload.get('direction_basis', '')}）
- 交易類型／股數：{payload.get('trade_type', '現股當沖')}／{payload.get('shares', 1000)} 股
- 稅費：買進手續費 {payload.get('buy_fee', 0)} 元、賣出手續費 {payload.get('sell_fee', 0)} 元、證交稅 {payload.get('transaction_tax', 0)} 元、其他費用 {payload.get('extra_fee', 0)} 元，合計 {payload.get('total_cost', 0)} 元
- 毛損益：{payload.get('gross_pnl', 0)} 元（{payload.get('gross_pnl_pct', 0):+.3f}%）；稅費後淨損益：{payload.get('net_pnl', 0)} 元（{payload.get('pnl_pct', 0):+.3f}%）
- 當日大盤與美股判讀：{payload['strategy_mode']}
- 實際進場時間：{payload['entry_time']} ｜ 實際進場價：{payload['entry_price']} 元（距昨收 {payload['entry_pct']:+.2f}%）
- 學員宣稱的進場理由：{payload['entry_reason']}
- 實際出場時間：{payload['exit_time']} ｜ 實際出場價：{payload['exit_price']} 元（距昨收 {payload['exit_pct']:+.2f}%）
- 學員出場理由：{payload['exit_reason']}
- 稅費後實際稅費後單筆報酬率：{payload['pnl_pct']:+.3f}%
- 盤中行為自檢：{', '.join(payload['behaviors']) if payload['behaviors'] else '無勾選異常行為'}

{fact_block}

【老帥核心檢核要求（務必逐一精準回答，禁止空泛套話）】
1. **進場條件真偽事實驗證（最核心！）**：
   - 若學員宣稱或勾選「首次由下向上站回 -6%」：
     * 第一步：先核對該股當日是否真的跌破過 `-6.0%`（`{fc.get('line_m6', 0)}` 元），以及在學員進場時間 `{payload['entry_time']}` 之前是否已經破過 `-6.0%`！如果根本沒破過 `-6.0%`，直接明確指出「**條件不成立（假訊號／誤判）**」，並給出實際最低點與跌幅數字。
     * 第二步：若確實跌破過 `-6.0%`，比對「首次由下向上站回 `-6.0%`」的真實時間點（`{reclaim_summary}`）與理想價位（約 `{fc.get('ideal_reclaim_p', 0)}` 元），明確計算學員實際進場時間 `{payload['entry_time']}`、價格 `{payload['entry_price']}` 元（`{payload['entry_pct']:+.2f}%`）**究竟是精準命中首次站回、還是晚了幾分鐘／追高了幾元（幾%）**，或是已經變成「第二次站回（勝率僅 50% 違規單）」。
   - 若學員使用的是其他理由（如開盤黃金 20 秒、二次止跌、破線停損等），同樣必須用上述實際開高低收與時間點位逐一核對條件是否成立。
2. **進退場理由與風控紀律診斷**：
   - 檢核出場時機（例如破前低停損是否果斷、或有賺 1%～1.5% 是否及時落袋、是否出現主觀「感覺」盤感）。
3. **下一次實戰精準修正指令**：
   - 給出具體價格（幾元掛單、幾元停利、幾元停損）與操作節奏修正。

請嚴格以 JSON 格式回傳（不要加 markdown 標記，且內文**嚴禁使用反引號 ` 包覆數字或時間**，直接以粗體 **數字** 呈現以確保最佳閱讀體驗），包含以下 4 個欄位：
{{
  "score": 82,
  "suggested_entry_time": "具體建議時間與條件說明（勿加反引號）",
  "suggested_entry_price": {fc.get('ideal_reclaim_p', payload['entry_price']) if fc.get('ideal_reclaim_p', 0) > 0 else payload['entry_price']},
  "review_markdown": "請分 3 個段落撰寫（每段以 1. / 2. / 3. 開頭，禁止使用反引號 ` ）：\n1. 🔍 **進場條件真偽與時間點位精準驗證**：（引用昨收、-6%線價格、當日真實最低點/時間、與學員進場時間價差的具體數字，直接判定『條件成立 / 條件成立但進場太晚 / 條件根本不成立』）\n2. 🧠 **進退場理由與風控紀律診斷**：（檢核停損與停利執行力）\n3. 🎯 **下一次實戰掛單與修正指令**：（給出具體掛單價、停利價與停損價）"
}}
"""
    api_errors = []
    if HAS_GENAI and api_keys:
        for idx, key in enumerate(api_keys):
            for mode_label, client in _create_genai_clients(key):
                for model_name in _get_candidate_models(client):
                    try:
                        resp = client.models.generate_content(
                            model=model_name,
                            contents=prompt,
                        )
                        raw = resp.text.strip()
                        if raw.startswith("```"):
                            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                        data = json.loads(raw)
                        return (
                            int(data.get("score", 85)),
                            str(data.get("suggested_entry_time", payload["entry_time"])),
                            float(data.get("suggested_entry_price", payload["entry_price"])),
                            str(data.get("review_markdown", "")),
                            f"{model_name} ({mode_label} Key #{idx+1})"
                        )
                    except Exception as e:
                        short_err = str(e).split("\n")[0][:90]
                        api_errors.append(f"Key#{idx+1}[{mode_label}/{model_name}]: {short_err}")
                        continue

    # 備援規則引擎：同樣嚴格依據 fetch_intraday_fact_check() 的真實盤中數據進行精準事實驗證
    score = 85
    notes = []
    e_time = payload["entry_time"]
    ep = payload["entry_pct"]
    pnl = payload["pnl_pct"]
    ref_p = fc.get("prev_close", payload["ref_price"])
    ent_p = payload["entry_price"]
    ext_p = payload["exit_price"]
    e_reason = payload["entry_reason"]
    x_reason = payload["exit_reason"]
    line_m6 = fc.get("line_m6", 0.0)
    ideal_p = fc.get("ideal_reclaim_p", ent_p)
    day_low = fc.get("day_low", 0.0)
    day_low_pct = fc.get("day_low_pct", 0.0)
    low_t = fc.get("low_time", "未知")
    ever_m6 = fc.get("ever_below_m6", False)
    before_m6 = fc.get("below_m6_before_entry", False)
    reclaims = fc.get("reclaim_events", [])

    sugg_time = e_time
    sugg_price = ideal_p if ideal_p > 0 else ent_p

    is_reclaim_m6 = ("由下向上站回-6%" in "".join(payload["behaviors"])) or ("-6%" in e_reason) or ("6%" in e_reason)

    if is_reclaim_m6 and ref_p > 0:
        if not ever_m6 and day_low > 0:
            score -= 22
            sugg_time = f"條件未觸發（當日最低僅 {day_low} 元 / {day_low_pct:+.2f}%，未達 -6.0% 線 {line_m6} 元）"
            notes.append(
                f"1. **❌ 進場條件事實驗證【條件不成立・根本未跌破 -6%】**：經核對 {payload['trade_date']} 盤中真實數據（昨收 **{ref_p} 元**，-6.0% 生死線為 **{line_m6} 元**），該股全天最低點僅跌至 **{day_low} 元（{day_low_pct:+.2f}%，時間 {low_t}）**，**完全沒有跌破過 -6.0%**！因此你宣稱的「由下向上站回 -6%」條件並未發生，你在 **{e_time}** 以 **{ent_p} 元（{ep:+.2f}%）** 買進屬於誤判觸發條件。"
            )
        elif ever_m6 and not before_m6 and fc.get("has_intraday_bars"):
            score -= 20
            first_rec_txt = f"首次站回發生在 **{reclaims[0]['time']}（{reclaims[0]['price']} 元）**" if reclaims else f"最低點 **{day_low} 元** 出現在 **{low_t}**"
            sugg_time = f"首次站回發生在 {reclaims[0]['time']}（{reclaims[0]['price']} 元）" if reclaims else f"最低點 {day_low} 元出現在 {low_t}"
            notes.append(
                f"1. **❌ 進場條件事實驗證【進場時機過早・當時尚未跌破 -6%】**：經核對盤中分時，該股當日雖然最低曾跌至 **{day_low} 元（{day_low_pct:+.2f}%）**，但在你進場時間 **{e_time}** 之前尚未跌破 -6.0%（**{line_m6} 元**）！真正跌破並站回的時間在後面（{first_rec_txt}），你在 **{e_time}** 以 **{ent_p} 元（{ep:+.2f}%）** 進場屬於搶先接刀，而非「跌破後由下向上站回 -6%」。"
            )
        else:
            first_ev = reclaims[0] if reclaims else None
            if len(reclaims) >= 2 and first_ev and e_time[:5] > first_ev["time"][:5] and ep <= -5.0:
                score -= 25
                sugg_time = f"第 1 次站回時間 {first_ev['time']}（約 {first_ev['price']} 元），第 2 次應放棄"
                notes.append(
                    f"1. **🚨 進場條件事實驗證【違規操作：已非首次站回 -6%】**：盤中真實紀錄顯示，該股第 1 次由下向上站回 -6% 發生在 **{first_ev['time']}（{first_ev['price']} 元）**；你於 **{e_time}** 進場已屬於第 2 次以上站回（勝率僅 50%），違反老帥「站回 -6% 一天只做第一次」的鐵律！"
                )
            elif ep <= -5.2:
                score += 8
                sugg_time = f"{first_ev['time']}（約 {first_ev['price']} 元）" if first_ev else f"{e_time}（精準命中站回 -6% 區間）"
                notes.append(
                    f"1. **✅ 進場條件事實驗證【條件完全符合・點位精準】**：核對昨收 **{ref_p} 元**（-6.0% 線 **{line_m6} 元**），當日最低確實殺破 -6% 至 **{day_low} 元（{day_low_pct:+.2f}%，時間 {low_t}）**，且你在 **{e_time}** 以 **{ent_p} 元（{ep:+.2f}%）** 切入，正好抓在由下向上剛站回 -6% 的第一時間黃金區間！"
                )
            else:
                score -= 10
                rebound_diff = round(ep - (-6.0), 2)
                first_str = f"（盤中首次站回 -6% 時間約在 **{first_ev['time']} / {first_ev['price']} 元**）" if first_ev else ""
                sugg_time = f"{first_ev['time']} 剛過 {line_m6} 元瞬間" if first_ev else f"剛由下向上穿越 {line_m6} 元瞬間"
                notes.append(
                    f"1. **⚠️ 進場條件事實驗證【前段破 -6% 成立，但進場太晚・已反彈 +{rebound_diff:.2f}% 變成追高】**：核對昨收 **{ref_p} 元**（-6.0% 線 **{line_m6} 元**），該股當日最低確實跌破 -6% 來到 **{day_low} 元（{day_low_pct:+.2f}%，時間 {low_t}）**{first_str}。但你沒有在剛站回 **{ideal_p} 元** 時切入，而是拖到 **{e_time}** 漲至 **{ent_p} 元（{ep:+.2f}%）** 才買進，等於從 -6% 已經往上反彈了 **+{rebound_diff:.2f}%** 才追價，把原本 1%～1.5% 的安全快打利潤空間全部吃光！"
                )
    else:
        notes.append(
            f"1. **🔍 進場條件事實驗證**：昨收 **{ref_p} 元**，當日真實開／高／低／收為 **{fc.get('day_open')} / {fc.get('day_high')} / {day_low}（{day_low_pct:+.2f}%） / {fc.get('day_close')} 元**。你於 **{e_time}** 以 **{ent_p} 元（{ep:+.2f}%）** 進場，請對照開盤黃金 20 秒或二次止跌線確認是否嚴格依訊號掛單。"
        )

    if "感覺" in e_reason or "感覺" in x_reason:
        score -= 12
        notes.append("2. **🧠 進退場理由與風控紀律診斷（盤感警告 ⚠️）**：進出理由出現「感覺」主觀字眼！當沖必須量化為「+1.2%～+1.5% 安全停利」或「破前低／破線紀律停損」。")
    elif "破前低" in x_reason or "停損" in x_reason:
        score += 5
        notes.append(f"2. **🧠 進退場理由與風控紀律診斷（停損紀律優秀 ✅）**：在 **{payload['exit_time']}** 跌破支撐（**{ext_p} 元**）時果斷執行停損（實際報酬 **{pnl:+.2f}%**），完全沒有向下攤平凹單，守住了「避開一次大賠」的最高鐵律。")
    else:
        notes.append(f"2. **🧠 進退場理由與風控紀律診斷**：出場時間 **{payload['exit_time']}**（**{ext_p} 元**），稅費後單筆報酬 **{pnl:+.2f}%**。")

    tp_target = round_to_tick(sugg_price * 1.013, "up") if sugg_price > 0 else 0.0
    notes.append(
        f"3. **🎯 下一次實戰掛單與修正指令**：若操作「由下向上站回 -6%」，必須事先算好昨收 × 0.94（本檔為 **{line_m6} 元**），確認盤中真的跌破 **{line_m6} 元** 止穩後，於重新站上 **{sugg_price} 元** 第一時間市價／限價切入，並直接掛 **{tp_target} 元（+1.3%）** 安全停利，絕不在反彈超過 2% 後才追進。"
    )

    fallback_reason = _friendly_ai_error(api_errors) if api_errors else "本機規則分析"
    local_report, local_engine = local_professional_review("", payload, fallback_reason)
    return max(10, min(100, score)), sugg_time, sugg_price, local_report, local_engine

# ==========================================
# 7. 主畫面渲染（完全復刻「老帥操盤室｜30年實戰派」視覺架構）
# ==========================================
tw_tz = pytz.timezone("Asia/Taipei")
now_tw = datetime.now(tw_tz)
weekday_str = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"][now_tw.weekday()]

# 偵測終端設備類型（支援 User-Agent 與 CSS 視窗寬度雙重自適應）
try:
    _ua = st.context.headers.get("User-Agent", "").lower()
except Exception:
    _ua = ""
is_mobile_ua = any(k in _ua for k in ["iphone", "android", "mobile", "ipad", "ipod"])
device_badge = "📱 手機戰情模式" if is_mobile_ua else "🖥️ 桌機戰情模式（手機開啟自動切換）"

# --- 頂部水平導航列 ---
st.markdown(f"""
<div class="top-navbar">
    <div class="brand-left">
        <div class="brand-badge">帥</div>
        <div>
            <div style="display:flex;flex-wrap:wrap;align-items:center;gap:8px;">
                <span class="brand-title">老帥操盤室</span>
                <span class="brand-pill">30年實戰派・高勝率當沖系統</span>
                <span class="brand-pill" style="background:rgba(56,189,248,0.14);border-color:rgba(56,189,248,0.45);color:#38BDF8;">{device_badge}</span>
            </div>
            <div style="font-size:12px;color:#94A3B8;margin-top:3px;">美股連動判讀 × 漲停四層漏斗（排除處置股） × 雙向 -6% 紀律指揮中心</div>
        </div>
    </div>
    <div class="nav-links">
        <a href="#sec1">1. 美股收盤看板</a>
        <a href="#sec2">2. 戰法自動判讀</a>
        <a href="#sec3">3. 漲停四層漏斗</a>
        <a href="#sec4">4. 雙向-6%與進出點位</a>
        <a href="#sec5">5. 專家實戰診斷</a>
    </div>
</div>
""", unsafe_allow_html=True)

# --- Hero 主視覺橫幅與三大鐵律 ---
st.markdown(f"""
<div class="hero-box">
    <div class="hero-date-tag">● 台股實戰交易日：{now_tw.strftime('%Y 年 %m 月 %d 日')}（{weekday_str}）盤前／盤中戰略部署</div>
    <div class="hero-main-title">老帥操盤室｜<span>30年實戰派・美股大跌做多當沖戰法系統</span></div>
    <div class="hero-quote">
        「在市場活過 30 年靠的不是預測神準，而是看懂美股連動節奏、08:15 前鎖定最強漲停股、守住 09:00:20 黃金 20 秒與雙向 -6% 紀律。交易最重要的不是每筆都贏，而是避開一次大賠，賺 1%～1.5% 安全落袋，保住本金才能走得長久！」
    </div>
    <div class="iron-grid">
        <div class="iron-card-red">
            <div style="color:#F87171;font-size:12px;font-weight:700;">鐵律一｜單一方向・黃金20秒</div>
            <div style="color:#F8FAFC;font-size:15px;font-weight:800;margin-top:4px;">全戰法一律以做多為主</div>
        </div>
        <div class="iron-card-gold">
            <div style="color:#FBBF24;font-size:12px;font-weight:700;">鐵律二｜寧缺勿濫・排除處置</div>
            <div style="color:#F8FAFC;font-size:15px;font-weight:800;margin-top:4px;">嚴選 3～4 檔漲停精兵</div>
        </div>
        <div class="iron-card-green">
            <div style="color:#34D399;font-size:12px;font-weight:700;">鐵律三｜雙向 -6%・安全快打</div>
            <div style="color:#F8FAFC;font-size:15px;font-weight:800;margin-top:4px;">站回-6%只做一次・賺1.5%即跑</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# --- 區塊一＆二：美股三大指數最新收盤看板 ＋ 戰法自動判讀 ---
st.markdown('<div id="sec1" class="sec-header"><span class="sec-tag">區塊一 & 二</span><span class="sec-title">美股三大指數最新收盤看板 ＆ 戰法條件自動判讀</span></div>', unsafe_allow_html=True)

ctrl_c1, ctrl_c2 = st.columns([2.6, 1.4])
with ctrl_c1:
    st.markdown('<div style="background:#111726;border:1px solid #334155;border-radius:10px;padding:10px 16px;color:#E2E8F0;font-size:13.5px;font-weight:700;">📡 數據來源：即時真實美股收盤（yfinance）× 台股證交所／櫃買中心即時報價</div>', unsafe_allow_html=True)
with ctrl_c2:
    auto_refresh = st.toggle("⚡ 盤中 5 秒自動輪詢 (同步更新大盤與精選名單報價)", value=False)

us_data = fetch_us_indices()
dji = us_data.get("^DJI", {"name": "道瓊工業指數", "close": 0, "pts": 0, "pct": 0, "date": "-"})
ixic = us_data.get("^IXIC", {"name": "那斯達克指數", "close": 0, "pts": 0, "pct": 0, "date": "-"})
sox = us_data.get("^SOX", {"name": "費城半導體指數", "close": 0, "pts": 0, "pct": 0, "date": "-"})

tw_idx = fetch_tw_market_indices()

if "tw_live_points" not in st.session_state:
    st.session_state["tw_live_points"] = []

col1, col2, col3 = st.columns(3)
for col, idx in zip([col1, col2, col3], [dji, ixic, sox]):
    c_cls = "tw-up" if idx["pct"] > 0 else ("tw-down" if idx["pct"] < 0 else "tw-flat")
    c_hex = "#FF4D4F" if idx["pct"] > 0 else ("#22C55E" if idx["pct"] < 0 else "#F8FAFC")
    sgn = "+" if idx["pct"] > 0 else ""
    with col:
        st.markdown(f"""
        <div class="idx-card">
            <div style="color:#94A3B8;font-size:13px;">{idx['name']} ({idx['date']})</div>
            <div class="{c_cls}" style="font-size:26px;font-weight:900;color:{c_hex} !important;margin:4px 0;">{idx['close']:,.2f}</div>
            <div class="{c_cls}" style="font-size:15.5px;font-weight:900;color:{c_hex} !important;">{sgn}{idx['pts']:,.2f} ({sgn}{idx['pct']:.2f}%)</div>
        </div>
        """, unsafe_allow_html=True)

@st.fragment(run_every=5 if auto_refresh else None)
def render_tw_market_section():
    live_tw = fetch_tw_market_indices()
    now_dt = datetime.now(tw_tz)
    now_str = now_dt.strftime("%H:%M:%S")
    today_key = now_dt.strftime("%Y-%m-%d")

    # 跨日自動清空昨日即時輪詢點位
    if st.session_state.get("tw_live_date") != today_key:
        st.session_state["tw_live_date"] = today_key
        st.session_state["tw_live_points"] = []

    # 取得盤中分時基準線 + 僅於盤中交易時段 (09:00~13:31) 疊加 5 秒 MIS 即時點位
    base_pts = fetch_tw_intraday_baseline()
    cur_hm_tw = now_dt.hour * 100 + now_dt.minute
    in_session_tw = (900 <= cur_hm_tw <= 1331)

    if live_tw["taiex_val"] > 0 and in_session_tw:
        pts_list = st.session_state["tw_live_points"]
        if not pts_list or pts_list[-1]["time"] != now_str:
            pts_list.append({
                "time": now_str,
                "taiex_pct": live_tw["taiex_pct"],
                "tpex_pct": live_tw["tpex_pct"],
                "taiex_val": live_tw["taiex_val"],
                "tpex_val": live_tw["tpex_val"]
            })
            if len(pts_list) > 360:
                pts_list.pop(0)

    chart_pts = list(base_pts)
    if st.session_state["tw_live_points"] and in_session_tw:
        last_base_t = chart_pts[-1]["time"] if chart_pts else ""
        for p in st.session_state["tw_live_points"]:
            if p["time"][:5] >= last_base_t:
                chart_pts.append(p)
    elif chart_pts and live_tw["taiex_val"] > 0:
        # 盤後/休市時同步校正最後一根收盤點的精準指數與漲跌幅，避免與左側指標卡產生誤差
        chart_pts[-1]["taiex_pct"] = live_tw["taiex_pct"]
        chart_pts[-1]["taiex_val"] = live_tw["taiex_val"]
        if live_tw["tpex_val"] > 0:
            chart_pts[-1]["tpex_pct"] = live_tw["tpex_pct"]
            chart_pts[-1]["tpex_val"] = live_tw["tpex_val"]

    # 判斷近期趨勢方向（安全過濾 None 值，比較最新點與約 15~30 分鐘前）
    trend_badge = "➡️ 盤整觀察中"
    trend_color = "#CBD5E1"
    valid_w = [p["taiex_pct"] for p in chart_pts if p.get("taiex_pct") is not None]
    valid_o = [p["tpex_pct"] for p in chart_pts if p.get("tpex_pct") is not None]
    if len(valid_w) >= 2:
        lb_w = max(0, len(valid_w) - 15)
        delta_taiex = round(valid_w[-1] - valid_w[lb_w], 2)
        delta_tpex = round(valid_o[-1] - valid_o[max(0, len(valid_o) - 15)], 2) if len(valid_o) >= 2 else 0.0
        if delta_taiex >= 0.08 or delta_tpex >= 0.12:
            trend_badge = f"📈 趨勢往上（加權 {delta_taiex:+.2f}% / 櫃買 {delta_tpex:+.2f}%・買盤推升）"
            trend_color = "#FF4D4F"
        elif delta_taiex <= -0.08 or delta_tpex <= -0.12:
            trend_badge = f"📉 趨勢往下（加權 {delta_taiex:+.2f}% / 櫃買 {delta_tpex:+.2f}%・賣壓轉弱）"
            trend_color = "#22C55E"
        else:
            trend_badge = f"➡️ 橫盤震盪（加權 {delta_taiex:+.2f}% / 櫃買 {delta_tpex:+.2f}%）"
            trend_color = "#FBBF24"

    taiex_cls = "tw-up" if live_tw["taiex_pct"] > 0 else ("tw-down" if live_tw["taiex_pct"] < 0 else "tw-flat")
    tpex_cls = "tw-up" if live_tw["tpex_pct"] > 0 else ("tw-down" if live_tw["tpex_pct"] < 0 else "tw-flat")
    badge_txt = f"● 5秒輪詢中 ({now_str})" if auto_refresh else f"靜態快照 ({now_str})"
    badge_col = "#34D399" if auto_refresh else "#94A3B8"

    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
    tw_c1, tw_c2 = st.columns([1.05, 2.35])
    with tw_c1:
        taiex_val_str = f"{live_tw['taiex_val']:,.2f}" if live_tw["taiex_val"] > 0 else "-"
        tpex_val_str = f"{live_tw['tpex_val']:,.2f}" if live_tw["tpex_val"] > 0 else "-"
        taiex_sgn = "+" if live_tw["taiex_pts"] > 0 else ""
        tpex_sgn = "+" if live_tw["tpex_pts"] > 0 else ""
        taiex_hex = "#FF4D4F" if live_tw["taiex_pct"] > 0 else ("#22C55E" if live_tw["taiex_pct"] < 0 else "#F8FAFC")
        tpex_hex = "#FF4D4F" if live_tw["tpex_pct"] > 0 else ("#22C55E" if live_tw["tpex_pct"] < 0 else "#F8FAFC")
        pre_tag = "（昨收參考）" if live_tw.get("is_premarket") else ""
        st.markdown(f"""
        <div class="idx-card" style="border-color:rgba(245,158,11,0.45);height:100%;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <span style="color:#FBBF24;font-size:14px;font-weight:800;">台股加權 / 櫃買強弱對照</span>
                <span style="color:{badge_col};font-size:11px;font-weight:700;">{badge_txt}</span>
            </div>
            <div style="background:#090D16;border:1px solid #1E293B;border-radius:10px;padding:10px 14px;margin-bottom:8px;">
                <div style="color:#CBD5E1;font-size:12.5px;font-weight:700;">加權指數 {pre_tag}</div>
                <div class="{taiex_cls}" style="font-size:23px;font-weight:900;color:{taiex_hex} !important;margin:2px 0;">{taiex_val_str}</div>
                <div class="{taiex_cls}" style="font-size:14.5px;font-weight:900;color:{taiex_hex} !important;">{taiex_sgn}{live_tw['taiex_pts']:,.2f} ({taiex_sgn}{live_tw['taiex_pct']:.2f}%)</div>
            </div>
            <div style="background:#090D16;border:1px solid #1E293B;border-radius:10px;padding:10px 14px;margin-bottom:8px;">
                <div style="color:#CBD5E1;font-size:12.5px;font-weight:700;">櫃買指數 {pre_tag}</div>
                <div class="{tpex_cls}" style="font-size:22px;font-weight:900;color:{tpex_hex} !important;margin:2px 0;">{tpex_val_str}</div>
                <div class="{tpex_cls}" style="font-size:14.5px;font-weight:900;color:{tpex_hex} !important;">{tpex_sgn}{live_tw['tpex_pts']:,.2f} ({tpex_sgn}{live_tw['tpex_pct']:.2f}%)</div>
            </div>
            <div style="font-size:12.5px;font-weight:800;color:{trend_color} !important;padding-top:2px;">{trend_badge}</div>
        </div>
        """, unsafe_allow_html=True)

    with tw_c2:
        fig_tw = go.Figure()
        if chart_pts:
            x_vals = [p["time"] for p in chart_pts]
            y_taiex = [p["taiex_pct"] for p in chart_pts]
            y_tpex = [p["tpex_pct"] for p in chart_pts]
            v_taiex = [p.get("taiex_val") if p.get("taiex_val") is not None else live_tw["taiex_val"] for p in chart_pts]
            v_tpex = [p.get("tpex_val") if p.get("tpex_val") is not None else live_tw["tpex_val"] for p in chart_pts]
            fig_tw.add_trace(go.Scatter(
                x=x_vals, y=y_taiex, mode="lines+markers",
                name="加權指數",
                customdata=v_taiex,
                hovertemplate="加權指數：<b>%{customdata:,.2f}</b><extra></extra>",
                line=dict(color="#EF4444", width=2.3),
                marker=dict(size=2.5),
                connectgaps=True
            ))
            fig_tw.add_trace(go.Scatter(
                x=x_vals, y=y_tpex, mode="lines+markers",
                name="櫃買指數",
                customdata=v_tpex,
                hovertemplate="櫃買指數：<b>%{customdata:,.2f}</b><extra></extra>",
                line=dict(color="#FBBF24", width=2.1),
                marker=dict(size=2.5),
                connectgaps=True
            ))
        else:
            fig_tw.add_trace(go.Scatter(
                x=[now_str], y=[live_tw["taiex_pct"]], mode="markers",
                name="加權指數",
                customdata=[live_tw["taiex_val"]],
                hovertemplate="加權指數：<b>%{customdata:,.2f}</b><extra></extra>",
                marker=dict(color="#EF4444", size=8)
            ))
            fig_tw.add_trace(go.Scatter(
                x=[now_str], y=[live_tw["tpex_pct"]], mode="markers",
                name="櫃買指數",
                customdata=[live_tw["tpex_val"]],
                hovertemplate="櫃買指數：<b>%{customdata:,.2f}</b><extra></extra>",
                marker=dict(color="#FBBF24", size=8)
            ))

        fig_tw.add_hline(
            y=0, line_dash="dash", line_color="#94A3B8",
            annotation_text="昨收平盤 0.00%",
            annotation_position="top left",
            annotation_font=dict(color="#F8FAFC", size=11)
        )
        fig_tw.update_layout(
            title=dict(text="📈 台股加權 vs 櫃買盤中 1分K 走勢對照", font=dict(size=14, color="#FFFFFF"), x=0.01, y=0.96),
            height=252,
            margin=dict(l=14, r=14, t=48, b=14),
            paper_bgcolor="#111726",
            plot_bgcolor="#090D16",
            font=dict(color="#F8FAFC", size=12),
            yaxis=dict(
                title=dict(text="漲跌幅 (%)", font=dict(color="#F8FAFC", size=12)),
                tickfont=dict(color="#F8FAFC", size=11),
                gridcolor="#1E293B", zeroline=False, ticksuffix="%"
            ),
            xaxis=dict(
                tickfont=dict(color="#F8FAFC", size=11),
                gridcolor="#1E293B", nticks=8
            ),
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0,
                font=dict(color="#FFFFFF", size=12),
                bgcolor="rgba(15, 23, 42, 0.9)",
                bordercolor="#475569",
                borderwidth=1
            ),
            hovermode="x unified"
        )
        st.plotly_chart(fig_tw, width="stretch")

render_tw_market_section()

strategy = evaluate_strategy(dji["pts"], dji["pct"], ixic["pct"], sox["pct"], tw_idx["taiex_pct"], tw_idx["tpex_pct"])
st.markdown(f"""
<div id="sec2" class="verdict-banner">
    <div style="color:#FBBF24;font-size:16px;font-weight:900;">🎯 系統自動判讀：{strategy['title']}</div>
    <div style="color:#F8FAFC;font-size:13.5px;margin-top:4px;"><b>最高操作方向：</b>{strategy['direction']} ｜ <b>大盤環境檢核：</b>{strategy['resilient_note']}</div>
</div>
""", unsafe_allow_html=True)
for r_line in strategy["rules"]:
    st.markdown(f"- {r_line}")

# --- 區塊三＆四：漲停四層漏斗（排除處置股）＆ 雙向 -6% 精選進出場監控 ---
st.markdown('<div id="sec3" class="sec-header"><span class="sec-tag">區塊三 & 四</span><span class="sec-title">全台股昨日漲停四層漏斗（排除處置股）＆ 雙向 -6% 精選進出點位</span></div>', unsafe_allow_html=True)

with st.spinner("正在連線 TWSE / TPEx Open Data 掃描全市場並剔除處置股與非當沖標的..."):
    final_df, funnel_stats, disposed_set, all_stock_catalog = run_all_taiwan_funnel()

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("① 昨日漲停鎖死", f"{funnel_stats['limit_up']} 檔")
m2.metric("② 可當沖且非處置", f"{funnel_stats['valid_dt']} 檔", f"已排除 {len(disposed_set)} 檔處置股")
m3.metric("③ 股價 ≥ 40 元", f"{funnel_stats['price_ok']} 檔")
m4.metric("④ 昨量 > 10,000 張", f"{funnel_stats['vol_ok']} 檔")
m5.metric("⑤ 剔除高乖離精選", f"{funnel_stats['final']} 檔精兵")

@st.fragment(run_every=5 if auto_refresh else None)
def render_watchlist_live_board():
    if final_df.empty:
        st.warning("⚠️ 今日全市場無同時符合「昨日漲停＋可當沖＋非處置股＋40元以上＋量破萬張」之標的，老帥建議今日空手觀望、保住本金！")
        return pd.DataFrame()
    live_df = fetch_twse_mis_realtime(final_df, strategy_code=strategy["code"])
    is_pre_now = bool(live_df["is_premarket"].iloc[0]) if "is_premarket" in live_df.columns else False
    now_watch_str = datetime.now(tw_tz).strftime("%H:%M:%S")
    if not is_pre_now and auto_refresh:
        st.markdown(f'<div style="color:#34D399;font-size:12.5px;font-weight:700;margin-bottom:6px;">● 精選觀察名單 5 秒即時報價與進出點位同步中（最後更新：{now_watch_str}）</div>', unsafe_allow_html=True)

    if is_pre_now:
        st.info("🕒 **目前為盤前試搓時段（09:00 前）**：系統已自動同步 MIS 官方昨漲停基準價，並依當前試搓位置預演「情境 A / B / C」建議進場點位；**09:00:00～09:00:20 正式開盤後將即時切換為盤中動能決斷！**")

    # 即時雙向 -6% 警示橫幅（僅在特殊深跌情境觸發）
    for _, row in live_df.iterrows():
        if not is_pre_now and row["reclaim_cnt"] == 1 and row["live_pct"] > -6.0 and row["low_pct"] <= -6.5:
            st.markdown(f"""
            <div class="signal-gold">
                🔥 <b>【特殊戰法訊號・由下向上站回 -6%】{row['code']} {row['name']}</b> 盤中最低探至 <span class="tw-down">{row['low_pct']}%</span> 止穩後，
                已由下向上站回 -6%（現價 <b>{row['live_price']}</b> / {row['live_pct']}%）！<b>首次觸發直接進場不猶豫</b>，安全停利（+1.3%）：<b>{row['safe_tp_13']}</b>。
            </div>
            """, unsafe_allow_html=True)
        elif not is_pre_now and row["live_pct"] <= -6.0:
            st.markdown(f"""
            <div class="signal-danger">
                🚨 <b>【特殊警戒・由上往下跌破 -6%】{row['code']} {row['name']}</b> 目前跌幅達 <span class="tw-down">{row['live_pct']}%</span>（現價 {row['live_price']}），
                已跌破 -6% 生死線（{row['line_minus_6']}）！嚴禁向下接刀攤平，持單者準備於反彈 -5% 或破 -7%（{row['hard_sl_7']}）果斷停損！
            </div>
            """, unsafe_allow_html=True)

    price_col_name = "盤前試搓價" if is_pre_now else "即時現價"
    pct_col_name = "試搓漲跌%" if is_pre_now else "即時漲跌%"
    st.markdown('<div id="sec4" style="font-size:15px;font-weight:800;color:#FBBF24;margin:10px 0 8px 0;">📋 精選觀察名單・全情境動態進出場建議與 1.3% 安全快打點位表</div>', unsafe_allow_html=True)

    rows_html = []
    mobile_cards_html = []
    for _, r in live_df.iterrows():
        pct_v = float(r["live_pct"])
        pct_color = "#FF4D4F" if pct_v > 0 else ("#22C55E" if pct_v < 0 else "#F8FAFC")
        rows_html.append(
            f'<tr style="border-bottom:1px solid #1E293B;transition:background 0.15s;">'
            f'<td style="padding:11px 10px;font-weight:800;color:#F8FAFC;white-space:nowrap;">{r["code"]} {r["name"]}</td>'
            f'<td style="padding:11px 8px;text-align:right;color:#CBD5E1;white-space:nowrap;">{r["close"]:.2f}</td>'
            f'<td style="padding:11px 8px;text-align:right;color:#CBD5E1;white-space:nowrap;">{int(r["vol_lots"]):,}</td>'
            f'<td style="padding:11px 8px;text-align:right;font-weight:800;color:#FFFFFF;white-space:nowrap;">{r["live_price"]:.2f}</td>'
            f'<td style="padding:11px 8px;text-align:right;font-weight:900;color:{pct_color};white-space:nowrap;">{pct_v:+.2f}%</td>'
            f'<td style="padding:11px 10px;color:#FBBF24;font-weight:700;white-space:nowrap;">{r["tactic_mode"]}</td>'
            f'<td style="padding:11px 8px;text-align:right;font-weight:800;color:#38BDF8;white-space:nowrap;">{r["sugg_entry"]:.2f}</td>'
            f'<td style="padding:11px 8px;text-align:right;font-weight:800;color:#34D399;white-space:nowrap;">{r["safe_tp_13"]:.2f}</td>'
            f'<td style="padding:11px 8px;text-align:right;font-weight:800;color:#F87171;white-space:nowrap;">{r["stop_loss"]:.2f}</td>'
            f'<td style="padding:11px 8px;text-align:right;color:#94A3B8;white-space:nowrap;">{r["line_minus_6"]:.2f}</td>'
            f'<td style="padding:11px 12px;color:#F1F5F9;font-size:13.5px;line-height:1.55;white-space:normal;word-break:break-word;min-width:320px;">{r["signal"]}</td>'
            f'</tr>'
        )

        mobile_cards_html.append(
            f'<div class="m-stock-card">'
            f'<div class="m-card-top">'
            f'<div><div style="font-size:17px;font-weight:900;color:#FFFFFF;">{r["code"]} {r["name"]}</div>'
            f'<div style="font-size:11.5px;color:#94A3B8;margin-top:2px;">昨漲停 {r["close"]:.2f} ｜ 昨量 {int(r["vol_lots"]):,} 張 ｜ -6%底線 {r["line_minus_6"]:.2f}</div></div>'
            f'<div style="text-align:right;"><div style="font-size:18px;font-weight:900;color:#FFFFFF;">{r["live_price"]:.2f}</div>'
            f'<div style="font-size:13.5px;font-weight:900;color:{pct_color};">{pct_v:+.2f}%</div></div>'
            f'</div>'
            f'<div class="m-tactic-badge">🎯 {r["tactic_mode"]}</div>'
            f'<div class="m-price-grid">'
            f'<div class="m-price-cell"><div style="font-size:11px;color:#94A3B8;">建議進場</div><div style="font-size:15px;font-weight:900;color:#38BDF8;">{r["sugg_entry"]:.2f}</div></div>'
            f'<div class="m-price-cell"><div style="font-size:11px;color:#94A3B8;">安全停利+1.3%</div><div style="font-size:15px;font-weight:900;color:#34D399;">{r["safe_tp_13"]:.2f}</div></div>'
            f'<div class="m-price-cell"><div style="font-size:11px;color:#94A3B8;">紀律停損</div><div style="font-size:15px;font-weight:900;color:#F87171;">{r["stop_loss"]:.2f}</div></div>'
            f'</div>'
            f'<div class="m-advice-box"><span style="color:#FBBF24;font-weight:800;">老帥建議：</span>{r["signal"]}</div>'
            f'</div>'
        )

    desktop_cls = "mobile-only-view" if is_mobile_ua else "desktop-only-view"
    mobile_cls = "desktop-only-view" if is_mobile_ua else "mobile-only-view"

    table_html = (
        f'<div class="{desktop_cls}" style="width:100%;overflow-x:auto;background:#111726;border:1px solid #334155;border-radius:12px;">'
        f'<table style="width:100%;border-collapse:collapse;font-size:13.5px;text-align:left;">'
        f'<thead><tr style="background:#0D1322;border-bottom:1px solid #334155;color:#FBBF24;font-weight:800;">'
        f'<th style="padding:11px 10px;white-space:nowrap;">代號名稱</th>'
        f'<th style="padding:11px 8px;text-align:right;white-space:nowrap;">昨漲停</th>'
        f'<th style="padding:11px 8px;text-align:right;white-space:nowrap;">昨量(張)</th>'
        f'<th style="padding:11px 8px;text-align:right;white-space:nowrap;">{price_col_name}</th>'
        f'<th style="padding:11px 8px;text-align:right;white-space:nowrap;">{pct_col_name}</th>'
        f'<th style="padding:11px 10px;white-space:nowrap;">匹配戰術情境</th>'
        f'<th style="padding:11px 8px;text-align:right;white-space:nowrap;">建議進場價</th>'
        f'<th style="padding:11px 8px;text-align:right;white-space:nowrap;">安全停利(+1.3%)</th>'
        f'<th style="padding:11px 8px;text-align:right;white-space:nowrap;">紀律停損價</th>'
        f'<th style="padding:11px 8px;text-align:right;white-space:nowrap;">-6%底線</th>'
        f'<th style="padding:11px 12px;min-width:320px;">老帥進出場操作建議</th>'
        f'</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        f'</table></div>'
        f'<div class="{mobile_cls}">{"".join(mobile_cards_html)}</div>'
    )
    st.markdown(table_html, unsafe_allow_html=True)

    # 老帥完整進出場戰術情境速查卡（黃金20秒情境A/B/C × 第二式二次止跌 × 特殊雙向-6%）
    st.markdown("""
    <div class="tactic-grid">
        <div style="background:rgba(16,185,129,0.10);border:1px solid rgba(16,185,129,0.4);border-left:4px solid #10B981;border-radius:10px;padding:12px 16px;">
            <div style="color:#6EE7B7;font-size:13.5px;font-weight:800;margin-bottom:4px;">⚡ 開盤黃金 20 秒（情境 A / B / C）</div>
            <div style="color:#E2E8F0;font-size:12.5px;line-height:1.55;"><b>情境A (開紅+3~6%)</b>：買盤續強順攻（>6%禁追高）；<b>情境B (開綠-2~3.5%)</b>：見下影線止跌試多；<b>情境C (平盤±1.5%)</b>：帶量破+1.5%順勢切入。</div>
        </div>
        <div style="background:rgba(245,158,11,0.10);border:1px solid rgba(245,158,11,0.4);border-left:4px solid #F59E0B;border-radius:10px;padding:12px 16px;">
            <div style="color:#FDE68A;font-size:13.5px;font-weight:800;margin-bottom:4px;">🎯 美股不同步｜二次止跌 ＆ 1.3% 快打</div>
            <div style="color:#E2E8F0;font-size:12.5px;line-height:1.55;">開盤拉回變綠時<b>忽略第一次止跌</b>，等<b>二次止跌線（-2.5%~-3.5%）</b>確認支撐再進；進場後不預設過前高，達 <b>+1.3% 安全停利</b>即落袋。</div>
        </div>
        <div style="background:rgba(239,68,68,0.10);border:1px solid rgba(239,68,68,0.4);border-left:4px solid #EF4444;border-radius:10px;padding:12px 16px;">
            <div style="color:#FCA5A5;font-size:13.5px;font-weight:800;margin-bottom:4px;">🚨 特殊深跌｜雙向 -6% 生死線鐵律</div>
            <div style="color:#E2E8F0;font-size:12.5px;line-height:1.55;"><b>向下破 -6%</b> 嚴禁攤平（反彈-5%或破-7%停損）；唯有殺破-6.5%止穩後<b>由下向上站回 -6%（限第 1 次）</b>才直接進場搶反彈。</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    return live_df

live_df = render_watchlist_live_board()

# --- 區塊五：專家實戰診斷室（含操作時間、進出理由、Gemini AI 覆盤、歷史區段查詢與匯出） ---
st.markdown('<div id="sec5" class="sec-header"><span class="sec-tag">區塊五</span><span class="sec-title">專家實戰診斷室｜30年當沖專家「老帥」AI 時間軸覆盤 ＆ 歷史戰績匯出</span></div>', unsafe_allow_html=True)

tab_review, tab_history = st.tabs(["🩺 1. 今日實戰操作輸入與老帥 AI 深度覆盤", "📊 2. 歷史操作與老師覆盤查詢／時間區段匯出"])

def _ocr_cell_v7(cell, numeric=False):
    if cell is None or cell.size == 0: return ""
    g=cv2.cvtColor(cell,cv2.COLOR_BGR2GRAY) if len(cell.shape)==3 else cell
    g=cv2.resize(g,None,fx=4,fy=4,interpolation=cv2.INTER_CUBIC)
    g=cv2.copyMakeBorder(g,20,20,20,20,cv2.BORDER_CONSTANT,value=255)
    variants=[cv2.threshold(g,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1]]
    cfg="--psm 7"+(" -c tessedit_char_whitelist=0123456789./:,-" if numeric else "")
    langs=["eng"] if numeric else ["chi_tra", "chi_tra+eng"]
    best=""
    for v in variants:
        for lang in langs:
            try:
                t=re.sub(r"\s+","",pytesseract.image_to_string(v,lang=lang,config=cfg) or "")
                if len(t)>len(best): best=t
            except Exception: pass
    return best

def _normalize_time_v7(text):
    d=re.sub(r"\D","",str(text or ""))
    if len(d)>=6:
        d=d[-6:]; h,m,sec=int(d[:2]),int(d[2:4]),int(d[4:6])
        if h<24 and m<60 and sec<60: return f"{h:02d}:{m:02d}:{sec:02d}"
    m=re.search(r"(\d{1,2})\D(\d{2})\D(\d{2})",str(text or ""))
    if m and int(m.group(1))<24: return f"{int(m.group(1)):02d}:{m.group(2)}:{m.group(3)}"
    return "待確認"

def _normalize_date_v7(text):
    d=re.sub(r"\D","",str(text or ""))
    m=re.search(r"(20\d{2})(\d{2})(\d{2})",d)
    return f"{m.group(1)}/{int(m.group(2)):02d}/{int(m.group(3)):02d}" if m else "待確認"

def _side_v7(cell,text):
    hsv=cv2.cvtColor(cell,cv2.COLOR_BGR2HSV)
    red=int((cv2.inRange(hsv,np.array([0,60,45]),np.array([15,255,255]))>0).sum()+(cv2.inRange(hsv,np.array([160,60,45]),np.array([179,255,255]))>0).sum())
    green=int((cv2.inRange(hsv,np.array([32,35,30]),np.array([100,255,255]))>0).sum())
    if red>green*1.15 and red>8:return "買進"
    if green>red*1.15 and green>8:return "賣出"
    if "買" in text:return "買進"
    if "賣" in text:return "賣出"
    return "待確認"

def _price_v7(text):
    raw=re.sub(r"[^0-9.]","",str(text or ""))
    if not raw:return 0.0
    try:v=float(raw)
    except:return 0.0
    if v>100000:return 0.0
    if "." not in raw and v>=300: v/=10.0
    return round(v,3)

def _valid_stock_name_v7(name):
    name=re.sub(r"[^\u4e00-\u9fff0-9A-Za-z]","",str(name or ""))
    # 中文股票名或純數字代碼才可信；chu、3Hy 等英文亂碼不得成為分組鍵。
    if re.search(r"[\u4e00-\u9fff]",name): return name
    if re.fullmatch(r"\d{4,6}",name): return name
    return ""

def _name_signature_v7(cell):
    g=cv2.cvtColor(cell,cv2.COLOR_BGR2GRAY)
    g=cv2.resize(g,(64,32)); g=cv2.threshold(g,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)[1]
    return (g>0).astype(np.uint8)

def _stock_code_from_text_v8(text: str) -> str:
    """只接受台股常見 4~6 碼代號；辨識不到時不猜測。"""
    m = re.search(r"(?<!\d)(\d{4,6}[A-Z]?)(?!\d)", str(text or "").upper())
    return m.group(1) if m else ""

def _auto_direction_from_fills_v8(fills: list) -> tuple:
    """依第一筆有效成交與庫存路徑判斷做多/做空；可辨識反手。"""
    valid=[r for r in fills if r.get("買賣") in ("買進","賣出") and float(r.get("價格",0) or 0)>0 and int(r.get("股數",0) or 0)>0]
    valid=sorted(valid,key=lambda r:(str(r.get("日期","")),str(r.get("時間",""))))
    if not valid: return "待確認","沒有完整成交列"
    first=valid[0]["買賣"]
    direction="做多" if first=="買進" else "做空"
    pos=0; reversed_flag=False
    for r in valid:
        pos += int(r["股數"]) * (1 if r["買賣"]=="買進" else -1)
        if (direction=="做多" and pos<0) or (direction=="做空" and pos>0): reversed_flag=True
    basis=f"第一筆有效成交為{first}"
    if reversed_flag: basis += "；中途出現反手，報告需拆分交易回合"
    return direction,basis

def _personal_fills_summary_v8(df) -> dict:
    if df is None or len(df)==0: return {"fills":[],"summary":"未填寫分批成交","direction":"待確認"}
    fills=[]
    for _,x in df.iterrows():
        code=str(x.get("股票代號","") or "").strip(); side=str(x.get("買賣","") or "").strip()
        try: qty=int(float(x.get("股數",0) or 0)); price=float(x.get("成交價",0) or 0)
        except Exception: continue
        if side not in ("買進","賣出") or qty<=0 or price<=0: continue
        fills.append({"股票代號":code,"股票":str(x.get("股票名稱","") or "").strip(),"買賣":side,"股數":qty,"價格":price,"日期":str(x.get("日期","") or ""),"時間":str(x.get("時間","") or ""),"理由":str(x.get("理由","") or "")})
    direction,basis=_auto_direction_from_fills_v8(fills)
    lines=[f"{r['時間']} {r['買賣']} {r['股數']:,}股 @ {r['價格']:.2f}" for r in fills]
    return {"fills":fills,"summary":"；".join(lines) if lines else "未填寫分批成交","direction":direction,"direction_basis":basis}


# 他人分析升級版：僅逐列確認身分，不以價格或影像相似度覆寫其他列。
PEER_REVIEW_BUILD = "逐列辨識與證據覆盤第二版"


def _peer_v2_clean_name(value):
    import unicodedata
    return re.sub(r"[^\u4e00-\u9fff0-9A-Za-z]", "", unicodedata.normalize("NFKC",str(value or "")))


def _peer_v2_identity(raw_name, raw_code="", catalog=None, row_id=0, agreed=False):
    catalog=catalog or {}
    name=_peer_v2_clean_name(raw_name)
    code=str(raw_code or "").strip().upper()
    index={}
    by_name={}
    for label,info in catalog.items():
        c=str(info.get("code", str(label).split(" ",1)[0])).strip()
        n=str(info.get("name", str(label).split(" ",1)[-1])).strip()
        index[c]=n
        by_name.setdefault(_peer_v2_clean_name(n),set()).add(c)
    if code and code in index:
        if name and name not in (_peer_v2_clean_name(index[code]),code):
            return {"股票代號":"","股票":f"待確認 股票{chr(64 + row_id) if row_id <= 26 else row_id}","身分鍵":f"待確認:{row_id}","身分可信":False,"身分說明":"股票代號與名稱不一致，未自動套用"}
        return {"股票代號":code,"股票":f"{code} {index[code]}","身分鍵":code,"身分可信":True,"身分說明":"代號與目錄匹配，仍須核對原圖"}
    if name in by_name and len(by_name[name])==1:
        c=next(iter(by_name[name]))
        return {"股票代號":c,"股票":f"{c} {index[c]}","身分鍵":c,"身分可信":True,"身分說明":"逐列名稱精確匹配目錄，仍須核對原圖"}
    if name and agreed and re.search(r"[\u4e00-\u9fff]",name) and not code:
        return {"股票代號":"","股票":name+"（代號待確認）","身分鍵":"名稱:"+name,"身分可信":True,"身分說明":"同列兩次名稱辨識一致；未由其他列補名稱"}
    return {"股票代號":"","股票":f"待確認 股票{chr(64 + row_id) if row_id <= 26 else row_id}","身分鍵":f"待確認:{row_id}","身分可信":False,"身分說明":"名稱或代號不確定，未併入其他標的"}


def _peer_v2_safe_error(error, keys=()):
    text=str(error)
    for key in keys:
        if key:text=text.replace(str(key),"[金鑰已隱藏]")
    text=re.sub(r"(?i)([?&](?:key|api_key|token|access_token)=)[^&\s]+",r"\1[已隱藏]",text)
    text=re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+",r"\1[已隱藏]",text)
    text=re.sub(r"AIza[A-Za-z0-9_-]{20,}","[金鑰已隱藏]",text)
    return text[:1200]


def _peer_v2_log(stage, model, mode, error, keys=()):
    import logging
    details={"階段":stage,"模型":str(model),"連線模式":str(mode),"錯誤類型":type(error).__name__,"狀態碼":str(getattr(error,"code",getattr(error,"status_code","未提供"))),"摘要":_peer_v2_safe_error(error,keys)}
    logging.getLogger("radar.peer_review").warning("他人分析診斷 %s",json.dumps(details,ensure_ascii=False))
    st.session_state.setdefault("peer_analysis_diagnostics_v2",[]).append(details)
    return details


def _peer_v2_validate(rows):
    """Do not pad, clone, delete, or silently repair recognized trade rows."""
    out=[]
    for index,item in enumerate(rows,1):
        r=dict(item);issues=list(r.get("待確認原因",[]))
        r.setdefault("原圖列次",index)
        q=r.get("股數");p=r.get("價格")
        try:
            qf=float(q);pf=float(p)
            if not math.isfinite(qf) or not qf.is_integer() or qf<=0:raise ValueError()
            if not math.isfinite(pf) or pf<=0:raise ValueError()
            r["股數"]=int(qf);r["價格"]=pf
        except (ValueError,TypeError,OverflowError):issues.append("價格或股數不完整／非正數")
        if r.get("買賣") not in ("買進","賣出"):issues.append("買賣別待確認")
        try:
            d=datetime.strptime(str(r.get("日期","")).replace("-","/"),"%Y/%m/%d").date()
            tm=dt_time.fromisoformat(str(r.get("時間","")))
            r["日期"]=d.strftime("%Y/%m/%d");r["時間"]=tm.strftime("%H:%M:%S")
        except (ValueError,TypeError):issues.append("日期或時間待確認")
        if not r.get("身分可信"):issues.append(r.get("身分說明","標的待確認"))
        r["待確認原因"]=list(dict.fromkeys(issues));out.append(r)
    # Same name with extreme price differences is an alert, never an excuse for reassigning names.
    groups={}
    for r in out:
        if not r["待確認原因"]:groups.setdefault(r["身分鍵"],[]).append(r)
    for group in groups.values():
        prices=[r["價格"] for r in group]
        if len(prices)>1 and max(prices)/min(prices)>1.5:
            for r in group:r["待確認原因"].append("同一標的價格跨度異常，可能混入其他股票；停止配對")
        seen={}
        for r in group:
            signature=(r.get("日期"),r.get("時間"),r.get("買賣"),r.get("股數"),r.get("價格"))
            if signature in seen and not (r.get("人工確認") and seen[signature].get("人工確認")):
                r["待確認原因"].append("與另一列完全相同，保留原列但需確認是否重複")
                seen[signature]["待確認原因"].append("與另一列完全相同，需確認是否為兩筆實際成交")
            else:seen[signature]=r
    return out


def _peer_v2_group_facts(rows):
    if any(r.get("待確認原因") for r in rows):return {"ok":False,"reason":"群組含待確認列，未估算損益"}
    ordered=sorted(rows,key=lambda r:(r["日期"],r["時間"],r["原圖列次"]))
    if len({r["日期"] for r in ordered})!=1:return {"ok":False,"reason":"跨日成交需另行配對，未套用當沖費率"}
    times={}
    for r in ordered:
        key=(r["日期"],r["時間"])
        times.setdefault(key,set()).add(r["買賣"])
    if any(len(v)>1 for v in times.values()):return {"ok":False,"reason":"同秒有相反方向成交，先後順序不明，未估算損益"}
    first=ordered[0]["買賣"];direction="做多" if first=="買進" else "做空";sign=1 if direction=="做多" else -1
    position=0;peak=0;rounds=0;adds=0;adverse_adds=0;open_qty=0;open_amount=0
    for r in ordered:
        q=r["股數"];p=r["價格"];opening=r["買賣"]==first
        if opening:
            if position:
                adds+=1
                average=open_amount/open_qty if open_qty else p
                if (direction=="做多" and p<average) or (direction=="做空" and p>average):adverse_adds+=1
            open_qty+=q;open_amount+=q*p
        else:
            if q>abs(position):return {"ok":False,"reason":"發生反手或缺漏建倉，需拆回合核對，未估算損益"}
            if open_qty:
                avg=open_amount/open_qty;open_qty-=q;open_amount=avg*open_qty
        position+=q*(1 if r["買賣"]=="買進" else -1)
        peak=max(peak,abs(position))
        if position==0:rounds+=1;open_qty=0;open_amount=0
    if position:return {"ok":False,"reason":f"尚有未平倉 {abs(position):,} 股；未將全部買賣均價當成已實現損益"}
    buys=[r for r in ordered if r["買賣"]=="買進"];sells=[r for r in ordered if r["買賣"]=="賣出"]
    if not buys or not sells:return {"ok":False,"reason":"沒有完整買賣配對"}
    bq=sum(r["股數"] for r in buys);sq=sum(r["股數"] for r in sells)
    bp=sum(r["股數"]*r["價格"] for r in buys)/bq;sp=sum(r["股數"]*r["價格"] for r in sells)/sq
    # Match the legacy aggregate fee assumption, but supply the correct short entry/exit prices.
    costs=calc_trade_costs(bp if direction=="做多" else sp,sp if direction=="做多" else bp,bq,direction,"現股當沖",0.6,20,0)
    return {"ok":True,"rows":ordered,"direction":direction,"buys":len(buys),"sells":len(sells),"qty":bq,"bp":bp,"sp":sp,"costs":costs,"peak":peak,"rounds":rounds,"adds":adds,"adverse_adds":adverse_adds,"start":ordered[0]["時間"],"end":ordered[-1]["時間"]}


def _peer_v2_md(value):
    return str(value or "待確認").replace("|","／").replace("\n"," ").replace("<","〈").replace(">","〉")


def _peer_v2_report(rows, peer_note, reason, user_context=None, cloud_comment=""):
    rows=_peer_v2_validate(rows)
    st.session_state["peer_review_rows_v2"]=rows
    if not rows:
        return "### 尚未完成成交辨識\n"+str(reason)+"\n\n請提供清晰的成交表格或文字明細；未猜測筆數、標的與損益。", "未完成截圖辨識｜本機初步覆盤"
    table=["| 原圖列次 | 股票 | 原始名稱文字 | 買賣 | 股數 | 成交價 | 日期 | 時間 | 核對狀態 |","|---:|---|---|---|---:|---:|---|---|---|"]
    groups={}
    for r in rows:
        status="；".join(r["待確認原因"]) or "欄位通過基本檢查；尚未人工核對"
        table.append("| "+" | ".join(_peer_v2_md(v) for v in [r["原圖列次"],r.get("股票"),r.get("原始股票文字"),r.get("買賣"),r.get("股數"),r.get("價格"),r.get("日期"),r.get("時間"),status])+" |")
        groups.setdefault(r.get("身分鍵",f"待確認:{r['原圖列次']}"),[]).append(r)
    sections=[];net=0;gross=0;paired=0
    for key,group in groups.items():
        name=group[0].get("股票","標的待確認")
        f=_peer_v2_group_facts(group)
        lines=["### "+_peer_v2_md(name)]
        if not f["ok"]:
            lines.extend(["- 核對結果："+f["reason"]+"。","- 保留各列原始內容，不用另一筆資料補滿，也不轉入其他股票。"])
            sections.append("\n".join(lines));continue
        c=f["costs"];paired+=1;net+=c["net_pnl"];gross+=c["gross_pnl"]
        lines.extend([
            f"- 可確認事實：由第一筆{f['rows'][0]['買賣']}與庫存路徑判為{f['direction']}；{f['buys']}筆買進、{f['sells']}筆賣出，已平倉 {f['qty']:,} 股。",
            f"- 交易節奏：{f['start']}～{f['end']}；完整交易回合 {f['rounds']} 次，最大觀測持倉 {f['peak']:,} 股。",
            f"- 成交結果：買進均價 {f['bp']:.4f} 元、賣出均價 {f['sp']:.4f} 元；毛損益 {c['gross_pnl']:+,} 元。",
            f"- 成本暫估：{c['total_cost']:,} 元；淨損益暫估 {c['net_pnl']:+,} 元。這是依辨識資料與固定費率假設計算，未與券商帳務核對。",
            f"- 部位變化：持倉未歸零前加碼 {f['adds']} 次，其中 {f['adverse_adds']} 次是在不利於原有部位平均成本的價格繼續增加曝險。"
        ])
        if f['adverse_adds']:
            lines.append("- 風控覆盤：需檢查加碼是否為事前計畫、總股數上限與失效條件。成交表可證明逆向增加部位，但不能單憑這點認定違規攤平。")
        else:lines.append("- 風控覆盤：這份成交沒有觀測到逆向加碼，但不代表整段持倉沒有風險；仍缺少盤中最大回撤與預設停損。")
        closing=f['sells'] if f['direction']=='做多' else f['buys']
        lines.append("- 出場覆盤："+("有分批出場，可檢查各批是否依計畫執行；僅憑最終獲利不能認定停利最佳。" if closing>1 else "以單筆成交結束部位；需要停損／停利計畫才能判斷是否執行得當。"))
        if c['gross_pnl']<0:lines.append("- 本筆檢討優先序：先核對部位擴張與退出條件，再談選股；虧損結果本身不足以證明進場策略錯誤。")
        elif c['gross_pnl']>0:lines.append("- 本筆可借鏡處：成交價差為正且股數已配對；可研究建倉與分批退出，但不能把獲利直接等同符合戰法。")
        lines.append("- 仍無法判斷：是否突破均價線、二次止跌、黃金20秒或首次站回-6%；缺少對應分時、昨收、量能及下單理由。")
        sections.append("\n".join(lines))
    context=user_context or {}
    compare=["### 與個人操作的差異核對"]
    if context.get('stock'):
        compare.append("- 個人提供標的："+_peer_v2_md(context['stock'])+"；請先確認交易日期、方向與成本口徑一致，再比較結果。")
        if context.get('fills_summary'):compare.append("- 個人成交摘要："+_peer_v2_md(context['fills_summary']))
        if context.get('entry_reason'):compare.append("- 個人進場理由："+_peer_v2_md(context['entry_reason'])+"；本機報告不會把這個理由當成已驗證的行情證據。")
        compare.append("- 目前未取得雙方一致的盤中行情與停損計畫，不能排名誰的進場更好或直接評定紀律優劣。")
    else:compare.append("- 尚未提供可比較的個人成交；以下只做他人成交事實與風控檢討，不虛構個人差異。")
    summary=["### 彙總與限制",f"- 保留 {len(rows)} 列；{sum(bool(r['待確認原因']) for r in rows)} 列待確認；完成基本檢查且平倉的群組 {paired} 組。",f"- 僅就可配對群組計算：毛損益 {gross:+,} 元；淨損益暫估 {net:+,} 元。未配對、待確認與跨日列沒有納入。","- 費用沿用原程式：現股當沖、手續費六折、彙總買賣兩側各套最低20元、賣方稅率0.15%。未依每張委託／每筆券商帳單重算。","- 不輸出無依據的勝率、策略合格分數或最佳進出時間。","- 補充說明："+_peer_v2_md(peer_note),"- 執行狀態："+_peer_v2_md(reason)]
    tasks=["### 下次可執行的覆盤步驟","1. 先逐列核對股票、買賣方向、股數、價格與時間；有疑義的列先修正，不拿來計算。","2. 每一回合補上事前進場條件、失效價位、最大股數與出場計畫，再比對實際執行。","3. 附上同日分時走勢與進出標記，才進一步驗證戰法訊號；不要由損益倒推不存在的型態。"]
    parts=["## 成交辨識與證據式初步覆盤","這是依辨識候選資料產生的初步報告，尚未由人工逐筆確認；不是交易所或券商帳務驗證。","### 逐筆成交核對","\n".join(table),"\n\n".join(sections),"\n".join(compare),"\n".join(tasks),"\n".join(summary)]
    if cloud_comment:parts.extend(["### 雲端補充分析（仍須核對證據）",cloud_comment])
    return "\n\n".join(parts), ("雲端辨識＋本機證據覆盤（待人工核對）" if cloud_comment else "未完成截圖辨識｜本機證據式初步覆盤（待人工核對）")


def _peer_v2_cell(cell, numeric=False):
    if cell is None or not cell.size:return "",[]
    g=cv2.cvtColor(cell,cv2.COLOR_BGR2GRAY) if len(cell.shape)==3 else cell
    g=cv2.resize(g,None,fx=4,fy=4,interpolation=cv2.INTER_CUBIC)
    g=cv2.copyMakeBorder(g,12,12,12,12,cv2.BORDER_CONSTANT,value=255)
    variants=[cv2.threshold(g,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1],cv2.adaptiveThreshold(g,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,31,9)]
    votes=[]
    config="--psm 7"+(" -c tessedit_char_whitelist=0123456789./:,-" if numeric else "")
    for variant in variants:
        if time.monotonic()>st.session_state.get("peer_ocr_deadline_v2",float("inf")):raise TimeoutError("本機OCR已達30秒上限；保留已完成欄位並進入人工核對")
        try:
            text=pytesseract.image_to_string(variant,lang="eng" if numeric else "chi_tra+eng",config=config,timeout=2)
            votes.append(re.sub(r"\s+","",text))
        except RuntimeError as exc:
            _peer_v2_log("文字辨識逾時或引擎錯誤","本機OCR","本機",exc)
            votes.append("")
    nonempty=[v for v in votes if v]
    return (max(nonempty,key=len) if nonempty else ""),votes


def _peer_v2_models(client, keys):
    explicit=os.environ.get("PEER_GEMINI_MODEL","").strip()
    try:explicit=str(st.secrets.get("PEER_GEMINI_MODEL",explicit)).strip()
    except Exception:pass
    if explicit:return [explicit.removeprefix("models/")]
    names=[]
    try:
        for model in client.models.list():
            name=str(getattr(model,"name","") or "").removeprefix("models/")
            actions=[str(a).lower().replace("_","") for a in (getattr(model,"supported_actions",[]) or [])]
            if name and "gemini" in name.lower() and "generatecontent" in actions:
                names.append(name)
    except Exception as exc:
        _peer_v2_log("查詢可用模型","未選定","Gemini API",exc,keys)
        return []
    return sorted(set(names),key=lambda n:("preview" in n.lower(),"flash" not in n.lower(),n))[:2]


def _peer_v2_number(value):
    try:
        f=float(value)
        return f if math.isfinite(f) and f>=0 else 0.0
    except (ValueError,TypeError):return 0.0


def _peer_v2_verification_ui():
    rows=st.session_state.get("peer_review_rows_v2",[])
    if not rows:
        diagnostics=st.session_state.get("peer_analysis_diagnostics_v2",[])
        if diagnostics:
            with st.expander("分析連線診斷（已遮蔽金鑰）",expanded=False):
                for item in diagnostics:st.write(item)
        return
    revision=int(st.session_state.get("peer_review_revision_v2",0))
    with st.expander("逐筆人工核對與重算（不再次呼叫雲端）",expanded=False):
        st.caption("依原圖逐列修正並勾選確認；不確定就留待確認。這裡只更新報告，不會下單。人工重算後不會自動覆寫原歷史報告。")
        edited=[]
        with st.form(key=f"peer_manual_v2_{revision}"):
            for i,row in enumerate(rows):
                st.markdown(f"#### 原圖第 {row.get('原圖列次',i+1)} 列")
                prefix=f"pv2_{revision}_{i}"
                cols=st.columns(2)
                with cols[0]:code=st.text_input("股票代號（原圖未列可留空）",value=str(row.get("股票代號","")),key=prefix+"code")
                with cols[1]:name=st.text_input("股票名稱",value=str(row.get("原始股票文字",row.get("股票",""))),key=prefix+"name")
                cols=st.columns(3)
                with cols[0]:side=st.selectbox("買賣",["待確認","買進","賣出"],index=["待確認","買進","賣出"].index(row.get("買賣")) if row.get("買賣") in ("買進","賣出") else 0,key=prefix+"side")
                with cols[1]:qty=st.number_input("成交股數",min_value=0,step=1,value=int(_peer_v2_number(row.get("股數"))),key=prefix+"qty")
                with cols[2]:price=st.number_input("成交價",min_value=0.0,value=_peer_v2_number(row.get("價格")),format="%.4f",key=prefix+"price")
                cols=st.columns(2)
                with cols[0]:day=st.text_input("成交日期（年/月/日）",value=str(row.get("日期","")),key=prefix+"day")
                with cols[1]:tm=st.text_input("成交時間（時:分:秒）",value=str(row.get("時間","")),key=prefix+"time")
                confirmed=st.checkbox("我已對照原圖確認這一列",key=prefix+"confirmed",value=bool(row.get("人工確認",False)))
                identity=_peer_v2_identity(name,code,globals().get("all_stock_catalog",{}),row.get("原圖列次",i+1))
                if confirmed and str(name).strip():
                    identity={"股票代號":str(code).strip(),"股票":(str(code).strip()+" "+str(name).strip()).strip(),"身分鍵":str(code).strip() or "人工名稱:"+str(name).strip(),"身分可信":True,"身分說明":"使用者逐列核對"}
                edited.append({"原圖列次":row.get("原圖列次",i+1),"原始股票文字":name,"買賣":side,"股數":qty,"價格":price,"日期":day,"時間":tm,"人工確認":confirmed,"待確認原因":[] if confirmed else ["尚未人工確認此列"],**identity})
            submit=st.form_submit_button("依核對內容重算初步覆盤",type="primary")
        if submit:
            context=st.session_state.get("peer_user_context_v2",{})
            report,engine=_peer_v2_report(edited,st.session_state.get("peer_note_v2",""),"人工修改後重算；不代表券商帳務核驗",context)
            st.session_state["peer_ai_report"]=report
            st.session_state["peer_ai_engine"]="人工核對＋本機證據式覆盤"
            st.session_state["peer_review_revision_v2"]=revision+1
            st.rerun(scope="fragment")
    diagnostics=st.session_state.get("peer_analysis_diagnostics_v2",[])
    if diagnostics:
        with st.expander("分析連線診斷（已遮蔽金鑰）",expanded=False):
            for item in diagnostics:
                st.write(item)


def _crop_trade_table_v3(image_bytes: bytes) -> tuple:
    """從完整手機截圖找出成交表格，回傳裁切後PNG；偵測失敗才使用原圖。"""
    if not image_bytes:
        return image_bytes, "未提供圖片"
    img=cv2.imdecode(np.frombuffer(image_bytes,np.uint8),cv2.IMREAD_COLOR)
    if img is None:
        return image_bytes, "圖片解碼失敗，使用原圖"
    gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    inv=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_MEAN_C,cv2.THRESH_BINARY_INV,31,9)
    horizontal=cv2.morphologyEx(inv,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(max(45,img.shape[1]//12),1)))
    vertical=cv2.morphologyEx(inv,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(1,max(18,img.shape[0]//65))))
    grid=cv2.bitwise_or(horizontal,vertical)
    contours,_=cv2.findContours(grid,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    candidates=[]
    for c in contours:
        x,y,w,h=cv2.boundingRect(c)
        if w>=img.shape[1]*.70 and h>=img.shape[0]*.15:
            candidates.append((w*h,x,y,w,h))
    if not candidates:
        return image_bytes, "未偵測到完整表格，使用原圖"
    _,x,y,w,h=max(candidates)
    pad=6
    crop=img[max(0,y-pad):min(img.shape[0],y+h+pad),max(0,x-pad):min(img.shape[1],x+w+pad)]
    ok,encoded=cv2.imencode('.png',crop)
    if not ok:
        return image_bytes, "表格裁切編碼失敗，使用原圖"
    return encoded.tobytes(), f"已裁切表格：{crop.shape[1]}×{crop.shape[0]}像素"

def extract_trade_rows_local(image_bytes: bytes) -> tuple:
    if not image_bytes:return [],"未上傳截圖"
    if not HAS_LOCAL_OCR:return [],"缺少本機繁體中文辨識套件；未以其他資料補齊"
    try:
        if len(image_bytes)>8*1024*1024:raise ValueError("圖片超過8MB，請先裁切")
        from PIL import Image as PILImage
        with PILImage.open(io.BytesIO(image_bytes)) as check:
            if check.width*check.height>12_000_000:raise ValueError("圖片像素超過1200萬，請先縮圖")
            check.verify()
        st.session_state["peer_ocr_deadline_v2"]=time.monotonic()+30
        img=cv2.imdecode(np.frombuffer(image_bytes,np.uint8),cv2.IMREAD_COLOR)
        if img is None:raise ValueError("圖片無法解碼")
        gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
        bw=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_MEAN_C,cv2.THRESH_BINARY_INV,31,9)
        hk=cv2.getStructuringElement(cv2.MORPH_RECT,(max(35,img.shape[1]//18),1))
        vk=cv2.getStructuringElement(cv2.MORPH_RECT,(1,max(15,img.shape[0]//70)))
        grid=cv2.bitwise_or(cv2.morphologyEx(bw,cv2.MORPH_OPEN,hk),cv2.morphologyEx(bw,cv2.MORPH_OPEN,vk))
        contours,_=cv2.findContours(grid,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        boxes=[]
        for contour in contours:
            x,y,w,h=cv2.boundingRect(contour)
            if w>img.shape[1]*.65 and h>img.shape[0]*.12:boxes.append((w*h,x,y,w,h))
        if not boxes:return [],"找不到完整成交表格；未猜測列數"
        _,x,y,w,h=max(boxes);table=img[y:y+h,x:x+w]
        tg=cv2.cvtColor(table,cv2.COLOR_BGR2GRAY)
        ti=cv2.adaptiveThreshold(tg,255,cv2.ADAPTIVE_THRESH_MEAN_C,cv2.THRESH_BINARY_INV,25,8)
        hm=cv2.morphologyEx(ti,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(max(35,w//9),1)))
        vm=cv2.morphologyEx(ti,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(1,max(15,h//3))))
        def centers(indices):
            groups=[]
            for n in indices:
                if not groups or n-groups[-1][-1]>2:groups.append([int(n)])
                else:groups[-1].append(int(n))
            return [int(sum(g)/len(g)) for g in groups]
        ys=centers(np.where((hm>0).sum(axis=1)>w*.5)[0])
        xs=centers(np.where((vm>0).sum(axis=0)>h*.5)[0])
        if len(ys)<4:return [],"表格列線不足，請提供完整清晰表格"
        if len(ys)>32:return [],"超過30列，請分圖辨識，不截斷或補滿"
        if len(xs)!=10:return [],f"偵測到{len(xs)}條欄位邊界，無法確認九欄版型；請裁切完整表格，不再用固定比例猜欄位"
        catalog=globals().get("all_stock_catalog",{})
        rows=[]
        for row_id in range(1,len(ys)-1):
            top,bottom=ys[row_id]+2,ys[row_id+1]-2
            if bottom-top<6:continue
            cells=[table[top:bottom,xs[i]+2:xs[i+1]-2] for i in range(9)]
            values=[];all_votes=[]
            for i,cell in enumerate(cells):
                value,votes=_peer_v2_cell(cell,numeric=i in (4,5,6,7))
                values.append(value);all_votes.append(votes)
            if not any(values[1:8]):continue
            issues=[]
            name_votes=[_peer_v2_clean_name(v) for v in all_votes[1] if _peer_v2_clean_name(v)]
            normalized=values[1]
            # If two passes independently match different catalog names, leave this row unresolved.
            matching=[]
            for candidate in set(name_votes):
                identity=_peer_v2_identity(candidate,catalog=catalog,row_id=row_id)
                if identity["身分可信"]:matching.append((candidate,identity))
            if len({m[1]["身分鍵"] for m in matching})>1:
                identity=_peer_v2_identity("",row_id=row_id);issues.append("同列兩次名稱辨識指向不同股票")
            elif matching:identity=matching[0][1]
            else:identity=_peer_v2_identity(normalized,catalog=catalog,row_id=row_id,agreed=len(name_votes)==2 and name_votes[0]==name_votes[1])
            side="買進" if "買" in values[3] and "賣" not in values[3] else "賣出" if "賣" in values[3] and "買" not in values[3] else "待確認"
            if side=="待確認":issues.append("買賣文字辨識不清；未單憑底色判定")
            qty_raw=values[4].replace(",","")
            qty=int(qty_raw) if re.fullmatch(r"\d+",qty_raw or "") else 0
            price_raw=values[5].replace(",","")
            price=float(price_raw) if re.fullmatch(r"\d+(?:\.\d+)?",price_raw or "") else 0
            # Do not turn 1495 into 149.5 by guessing the decimal point.
            row={"原圖列次":row_id,"原始股票文字":values[1],"原始價格文字":values[5],"原始買賣文字":values[3],"買賣":side,"股數":qty,"價格":price,"日期":_normalize_date_v7(values[6]),"時間":_normalize_time_v7(values[7]),"待確認原因":issues,**identity}
            rows.append(row)
        rows=_peer_v2_validate(rows)
        count=len({r['身分鍵'] for r in rows if r['身分可信']})
        return rows,f"逐列保留{len(rows)}筆候選；名稱候選{count}組，未複製補列、未依價格合併，仍須人工核對"
    except Exception as exc:
        _peer_v2_log("本機表格辨識","本機OCR","本機",exc)
        return [],"本機表格辨識未完成；請查看分析診斷並裁切清晰的完整表格"

def _wp7(rows):
    q=sum(r['股數'] for r in rows);return (sum(r['股數']*r['價格'] for r in rows)/q if q else 0),q

def build_ocr_trade_report(rows, peer_note, reason, user_context=None):
    return _peer_v2_report(rows, peer_note, reason, user_context)

def build_peer_local_fallback(peer_note: str, user_context: dict, reason: str) -> tuple:
    return local_professional_review(peer_note, user_context, reason)


def run_peer_comparison_analysis(image_bytes: bytes, image_mime: str, peer_note: str, user_context: dict) -> tuple:
    st.session_state["peer_user_context_v2"]=dict(user_context or {})
    st.session_state["peer_note_v2"]=peer_note
    st.session_state["peer_review_revision_v2"]=int(st.session_state.get("peer_review_revision_v2",0))+1
    st.session_state["peer_analysis_diagnostics_v2"]=[]
    st.session_state["peer_review_rows_v2"]=[]
    keys=get_gemini_api_keys()
    errors=[]
    if HAS_GENAI and keys:
        try:
            from google.genai import types
            mode=os.environ.get("PEER_GEMINI_MODE","gemini").lower()
            try:mode=str(st.secrets.get("PEER_GEMINI_MODE",mode)).lower()
            except Exception:pass
            if mode not in ("gemini","vertex"):
                raise ValueError("PEER_GEMINI_MODE僅可為gemini或vertex，未依金鑰前綴猜測模式")
            options={"api_key":keys[0],"http_options":{"timeout":20000}}
            if mode=="vertex":options["vertexai"]=True
            client=genai.Client(**options)
            models=_peer_v2_models(client,keys)
            if not models:errors.append("未取得已宣告支援內容生成的模型，未盲試舊模型名稱")
            prompt="""你是繁體中文券商成交表格OCR。只逐列抄錄圖片，不做解盤、損益、策略、做多做空或個人比較。
只輸出JSON：{"rows":[{"row_id":1,"stock_name":"","stock_code":"","side":"買進或賣出或待確認","shares":1000,"price":51.5,"date":"2026/11/20","time":"13:30:00","uncertain":false}],"reported_count":10}。
原圖沒有代號就留空；看不清楚就留空並設uncertain=true；禁止複製、補造、依價格分組或輸出commentary。
"""
            contents=[prompt]
            cloud_ocr_bytes, crop_note = _crop_trade_table_v3(image_bytes)
            if cloud_ocr_bytes:
                if len(cloud_ocr_bytes)>8*1024*1024:raise ValueError("圖片超過8MB")
                contents.append(types.Part.from_bytes(data=cloud_ocr_bytes,mime_type="image/png"))
                st.session_state["peer_analysis_diagnostics_v2"].append({"階段":"OCR圖片前處理","連線模式":"本機","摘要":crop_note,"中文說明":"只將成交表格區域送往OCR，降低逾時風險。"})
            deadline=time.monotonic()+15
            for model in models[:1]:
                if time.monotonic()>deadline:break
                try:
                    response=client.models.generate_content(model=model,contents=contents,config={"response_mime_type":"application/json"})
                    raw=str(response.text or "").strip()
                    raw=re.sub(r"^```(?:json)?\s*|\s*```$","",raw)
                    parsed=json.loads(raw)
                    if not isinstance(parsed,dict) or not isinstance(parsed.get("rows"),list):raise ValueError("雲端回應缺少逐筆rows清單")
                    if len(parsed["rows"])>100:raise ValueError("回應列數異常，停止解析")
                    rows=[];seen_ids=set()
                    for i,row in enumerate(parsed["rows"],1):
                        if not isinstance(row,dict):raise ValueError("逐筆成交不是物件")
                        rid=int(row.get("row_id",i))
                        if rid<=0 or rid in seen_ids:raise ValueError("原圖列次重複或不合法；未補滿")
                        seen_ids.add(rid)
                        identity=_peer_v2_identity(row.get("stock_name",""),row.get("stock_code",""),globals().get("all_stock_catalog",{}),rid)
                        rows.append({"原圖列次":rid,"原始股票文字":str(row.get("stock_name","")),"買賣":row.get("side","待確認"),"股數":row.get("shares",0),"價格":row.get("price",0),"日期":row.get("date","待確認"),"時間":row.get("time","待確認"),"待確認原因":["雲端標記此列待確認"] if row.get("uncertain",True) else [],**identity})
                    count=parsed.get("reported_count")
                    count_note=f"原圖宣告筆數{count}，實際回傳{len(rows)}列；不補滿" if count is not None else f"回傳{len(rows)}列，未猜測原圖總筆數"
                    comment=""
                    if not rows:
                        if image_bytes:raise ValueError("圖片回應未含任何成交列，未視為辨識成功")
                        report,engine=build_peer_local_fallback(peer_note,user_context,"本次為文字分析，無成交圖片")
                        return report+("\n\n### 雲端文字補充\n"+comment if comment else ""),"文字覆盤（未辨識圖片）"
                    report,engine=_peer_v2_report(rows,peer_note,count_note,user_context,comment)
                    st.session_state["peer_analysis_diagnostics_v2"].append({"階段":"雲端回應已解析","模型":model,"連線模式":mode,"回傳列數":len(rows),"宣告筆數":count})
                    return report,engine if comment else "雲端辨識＋本機初步覆盤（待人工核對）"
                except Exception as exc:
                    detail=_peer_v2_log("生成／解析回應",model,mode,exc,keys)
                    errors.append(detail["摘要"])
                    text=str(exc).lower()
                    if any(code in text for code in ("429","resource_exhausted","403","permission_denied","401","unauthenticated","500","502","503","504","deadline_exceeded")):break
                    # A 404 may try only the next model actually returned by this endpoint, never a guessed name.
        except Exception as exc:
            detail=_peer_v2_log("初始化分析","未選定","未完成",exc,keys)
            errors.append(detail["摘要"])
    else:
        errors.append("未設定可用雲端模型套件或金鑰，改用本機初步覆盤")
    if not image_bytes:
        return build_peer_local_fallback(peer_note,user_context,"雲端未完成；僅根據使用者文字分析，不虛構圖片內容")
    local_ocr_bytes, crop_note = _crop_trade_table_v3(image_bytes)
    st.session_state["peer_ocr_deadline_v2"] = time.monotonic() + 30
    rows,status=extract_trade_rows_local(local_ocr_bytes)
    st.session_state["peer_analysis_diagnostics_v2"].append({"階段":"本機OCR圖片前處理","連線模式":"本機","摘要":crop_note,"中文說明":"雲端OCR未完成後，重新給本機OCR獨立30秒預算。"})
    reason=("雲端OCR未完成；"+_friendly_ai_error(errors) if errors else "本機OCR")+"；"+status
    return build_ocr_trade_report(rows,peer_note,reason,user_context)

from ai_model_guard import install_ai_model_guard
install_ai_model_guard(globals())

with tab_review:
    @st.fragment
    def render_review_fragment():
        st.markdown("""
        <div style="background:rgba(245,158,11,0.10);border:1px solid rgba(245,158,11,0.38);border-left:4px solid #F59E0B;border-radius:10px;padding:12px 16px;margin-bottom:14px;">
            <div style="color:#FBBF24;font-size:14.5px;font-weight:900;margin-bottom:3px;">📝 當日個人操作覆盤紀錄｜時間點位與紀律檢核</div>
            <div style="color:#E2E8F0;font-size:13px;line-height:1.55;">
                請先選擇今日實際操作的股票代號與名稱（已自動排除 ETF），再填寫<b>實際進／出場時間、成交價格與當下進出理由</b>。填寫過程中畫面完全流暢不閃爍、不反黑，填畢按下「送出覆盤」即可獲得老帥 AI 診斷。
            </div>
        </div>
        """, unsafe_allow_html=True)

        if "diag_form_ver" not in st.session_state:
            st.session_state["diag_form_ver"] = 0
        if "diag_last_stock" not in st.session_state:
            st.session_state["diag_last_stock"] = None
        if "personal_review_html" not in st.session_state:
            st.session_state["personal_review_html"] = ""

        watchlist_labels = [
            f"{r['code']} {r['name']}"
            for _, r in live_df.iterrows()
            if not str(r["code"]).startswith("0") and "ETF" not in str(r["name"]).upper()
        ] if not live_df.empty else []
        other_labels = sorted([
            k for k in all_stock_catalog.keys()
            if k not in watchlist_labels and not k.startswith("0") and "ETF" not in k.upper()
        ])
        stock_search_options = watchlist_labels + other_labels

        if "diag_stock_ver" not in st.session_state:
            st.session_state["diag_stock_ver"] = 0

        def _reset_diag_all():
            st.session_state["diag_stock_ver"] += 1
            st.session_state["diag_last_stock"] = None
            st.session_state["diag_form_ver"] += 1
            st.session_state["personal_review_html"] = ""

        sv = st.session_state["diag_stock_ver"]
        top_bar_c1, top_bar_c2 = st.columns([3.2, 0.8])
        with top_bar_c1:
            in_stock = st.selectbox(
                "📌 操作標的代號與名稱（已排除 ETF，輸入部分代號或名稱即跳出選項，切換標的時自動清空下方數值）",
                options=stock_search_options,
                index=None,
                placeholder="請點選並輸入部分代號或部分名稱（例如：4916 或 事欣科）...",
                key=f"diag_stock_{sv}"
            )
        with top_bar_c2:
            st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
            st.button("🧹 一鍵清空", width="stretch", key=f"btn_clear_diag_top_{sv}", on_click=_reset_diag_all)

        if in_stock != st.session_state["diag_last_stock"]:
            st.session_state["diag_last_stock"] = in_stock
            st.session_state["diag_form_ver"] += 1
            st.session_state["personal_review_html"] = ""

        v = st.session_state["diag_form_ver"]

        with st.form(key=f"diag_trade_form_{v}", clear_on_submit=False):
            r1_c1, r1_c2 = st.columns([1.1, 2.9])
            with r1_c1:
                in_date = st.date_input("交易日期", value=now_tw.date(), key=f"diag_date_{v}")
            with r1_c2:
                st.markdown(
                    f'<div style="background:#090D16;border:1px solid #334155;border-radius:10px;padding:10px 14px;margin-top:26px;font-size:13.5px;color:#E2E8F0;">'
                    f'當前選定標的：<b style="color:#FBBF24;">{in_stock if in_stock else "尚未選擇（請於上方下拉選單挑選個股）"}</b></div>',
                    unsafe_allow_html=True
                )

            direction_c1, direction_c2 = st.columns([1.1, 2.9])
            with direction_c1:
                in_direction_mode = st.selectbox("↕️ 交易方向", ["自動判斷", "做多", "做空"], key=f"diag_direction_{v}")
            with direction_c2:
                st.caption("自動判斷會讀取進出理由與行為。做空交易建議直接指定『做空』，避免文字不完整造成誤判。")

            fee_c1, fee_c2, fee_c3, fee_c4, fee_c5 = st.columns([1.2, 1.0, 1.0, 1.0, 1.0])
            with fee_c1:
                in_trade_type = st.selectbox("交易類型", ["現股當沖", "一般現股／資券交易"], key=f"diag_trade_type_{v}")
            with fee_c2:
                in_shares = st.number_input("成交股數", min_value=1, value=1000, step=100, key=f"diag_shares_{v}")
            with fee_c3:
                in_fee_discount = st.number_input("手續費折數", min_value=0.0, max_value=1.0, value=0.6, step=0.1, format="%.2f", help="6 折請輸入 0.6；2.8 折請輸入 0.28", key=f"diag_fee_discount_{v}")
            with fee_c4:
                in_minimum_fee = st.number_input("單筆最低手續費", min_value=0, value=20, step=1, key=f"diag_min_fee_{v}")
            with fee_c5:
                in_extra_fee = st.number_input("其他費用（元）", min_value=0, value=0, step=1, help="可填借券費、融資利息或券商對帳單上的其他費用", key=f"diag_extra_fee_{v}")
            st.caption("費用會納入買進手續費、賣出手續費及賣出證交稅。現股當沖稅率 0.15%；一般現股或資券交易 0.3%。")

            r2_c1, r2_c1s, r2_c2, r2_c3 = st.columns([0.85, 0.65, 0.95, 2.05])
            with r2_c1:
                in_entry_hm = st.time_input("🟢 實際進場（時:分）", value=dt_time(9, 0), step=60, key=f"diag_entry_hm_{v}")
            with r2_c1s:
                in_entry_sec = st.number_input("🟢 秒（0~59）", min_value=0, max_value=59, value=0, step=1, format="%d", key=f"diag_entry_sec_{v}")
            with r2_c2:
                in_entry_price = st.number_input("🟢 實際進場成交價（元）", min_value=0.0, value=0.0, step=0.05, format="%.2f", key=f"diag_entry_price_{v}")
            with r2_c3:
                in_entry_reason = st.text_input("🟢 進場理由（請誠實填寫當時依據訊號或盤感）", value="", placeholder="請輸入進場依據...", key=f"diag_entry_reason_{v}")

            r3_c1, r3_c1s, r3_c2, r3_c3 = st.columns([0.85, 0.65, 0.95, 2.05])
            with r3_c1:
                in_exit_hm = st.time_input("🔴 實際出場（時:分）", value=dt_time(9, 15), step=60, key=f"diag_exit_hm_{v}")
            with r3_c1s:
                in_exit_sec = st.number_input("🔴 秒（0~59）", min_value=0, max_value=59, value=0, step=1, format="%d", key=f"diag_exit_sec_{v}")
            with r3_c2:
                in_exit_price = st.number_input("🔴 實際出場成交價（元）", min_value=0.0, value=0.0, step=0.05, format="%.2f", key=f"diag_exit_price_{v}")
            with r3_c3:
                in_exit_reason = st.text_input("🔴 出場理由（停利目標達標／停損／感覺漲不動）", value="", placeholder="請輸入出場依據...", key=f"diag_exit_reason_{v}")

            behaviors = st.multiselect(
                "盤中操作行為自檢（可複選）：",
                [
                    "由下向上站回-6%（首次觸發進場）",
                    "黃金20秒內依情境A/B/C決斷",
                    "耐心等拉回變綠・二次止跌進場",
                    "賺1%～1.5%安全快打落袋",
                    "嚴守-5%/-7%紀律停損",
                    "第二次站回-6%仍進場",
                    "跌破-6%仍攤平加碼",
                    "開盤超過1分鐘追高開盤單",
                    "逆勢放空"
                ],
                default=[],
                placeholder="請選擇盤中實際執行之行為...",
                key=f"diag_behaviors_{v}"
            )

            st.markdown("#### 🧾 同一股票分批成交明細（可新增／刪除多筆）")
            st.caption("同一股票可輸入多次買進與賣出；系統依日期、時間及第一筆有效成交自動判斷做多或做空。未填寫時仍沿用上方單筆進出場資料。")
            in_entry_time = dt_time(in_entry_hm.hour, in_entry_hm.minute, int(in_entry_sec))
            in_exit_time = dt_time(in_exit_hm.hour, in_exit_hm.minute, int(in_exit_sec))

            default_fill_df = pd.DataFrame([
                {"股票代號": (in_stock.split()[0] if in_stock else ""), "股票名稱": (in_stock.split(" ",1)[1] if in_stock and " " in in_stock else ""), "日期": str(in_date), "時間": in_entry_time.strftime("%H:%M:%S"), "買賣": "買進", "股數": int(in_shares), "成交價": float(in_entry_price or 0), "理由": in_entry_reason},
                {"股票代號": (in_stock.split()[0] if in_stock else ""), "股票名稱": (in_stock.split(" ",1)[1] if in_stock and " " in in_stock else ""), "日期": str(in_date), "時間": in_exit_time.strftime("%H:%M:%S"), "買賣": "賣出", "股數": int(in_shares), "成交價": float(in_exit_price or 0), "理由": in_exit_reason},
            ])
            personal_fills_df = st.data_editor(default_fill_df, num_rows="dynamic", hide_index=True, width="stretch", key=f"personal_fills_{v}", column_config={
                "買賣": st.column_config.SelectboxColumn("買賣", options=["買進","賣出"], required=True),
                "股數": st.column_config.NumberColumn("股數", min_value=1, step=100),
                "成交價": st.column_config.NumberColumn("成交價", min_value=0.0, format="%.2f"),
            })
            use_gemini_polish = st.checkbox(
                "使用 Gemini 補充白話說明（選用）", value=False,
                help="老師戰法規則引擎會先完成正式覆盤；Gemini 失敗不影響結果。",
                key=f"use_gemini_polish_{v}",
            )
            btn_submit = st.form_submit_button("🩺 開始老師戰法覆盤（並自動存檔）", type="primary", width="stretch")

        if btn_submit:
            selected_code = in_stock.split()[0] if in_stock else ""
            selected_name = in_stock.split(" ", 1)[1] if in_stock and " " in in_stock else ""
            normalized_personal_fills = normalize_fills(personal_fills_df, selected_code, selected_name)
            personal_trade_result = split_trade_rounds(
                normalized_personal_fills, trade_type=in_trade_type,
                fee_discount=in_fee_discount, minimum_fee=in_minimum_fee,
                extra_fee=in_extra_fee,
            )
            if not in_stock:
                st.warning("⚠️ 請先選擇操作標的代號與名稱。")
            elif not personal_trade_result.get("ok"):
                st.warning("⚠️ " + personal_trade_result.get("錯誤", "分批成交資料尚未完成核對"))
                if personal_trade_result.get("待確認列"):
                    st.dataframe(pd.DataFrame(personal_trade_result["待確認列"]), width="stretch", hide_index=True)
            else:
                first_fill = normalized_personal_fills[0]
                last_fill = normalized_personal_fills[-1]
                first_round = personal_trade_result["回合"][0]
                entry_t_str = first_round["開始時間"]
                exit_t_str = first_round["結束時間"]
                factual_entry_price = first_fill["價格"]
                factual_exit_price = last_fill["價格"]
                with st.spinner("正在核對操作日行情與老師戰法規則..."):
                    fact_check = fetch_intraday_fact_check(in_stock, in_date, entry_t_str, factual_entry_price, all_stock_catalog)

                in_ref = fact_check["prev_close"] if fact_check["prev_close"] > 0 else get_exact_prev_close(in_stock, in_date, live_df, all_stock_catalog)
                fact_check["prev_close"] = in_ref
                if in_ref > 0 and fact_check["line_m6"] <= 0:
                    fact_check["line_m6"] = round_to_tick(in_ref * 0.940, "down")
                    fact_check["ideal_reclaim_p"] = round_to_tick(in_ref * 0.9415, "up")

                entry_pct = round(((factual_entry_price - in_ref) / in_ref) * 100, 2) if in_ref > 0 else 0.0
                exit_pct = round(((factual_exit_price - in_ref) / in_ref) * 100, 2) if in_ref > 0 else 0.0
                trade_direction = personal_trade_result["主要方向"]
                direction_basis = "依分批成交的日期、時間與庫存路徑判斷"
                closed_rounds = [r for r in personal_trade_result["回合"] if not r.get("未平倉股數")]
                first_closed = closed_rounds[0] if closed_rounds else personal_trade_result["回合"][0]
                trade_costs = {
                    "buy_fee": sum(r.get("買進手續費", 0) for r in closed_rounds),
                    "sell_fee": sum(r.get("賣出手續費", 0) for r in closed_rounds),
                    "transaction_tax": sum(r.get("證券交易稅", 0) for r in closed_rounds),
                    "extra_fee": sum(r.get("其他費用", 0) for r in closed_rounds),
                    "total_cost": personal_trade_result["總交易成本"],
                    "gross_pnl": personal_trade_result["總毛損益"],
                    "net_pnl": personal_trade_result["總淨損益"],
                    "gross_pnl_pct": first_closed.get("毛報酬率", 0),
                    "net_pnl_pct": first_closed.get("淨報酬率", 0),
                }
                gross_pnl_pct = trade_costs["gross_pnl_pct"]
                pnl_pct = trade_costs["net_pnl_pct"]

                payload = {
                    "trade_date": in_date.strftime("%Y-%m-%d"),
                    "stock": in_stock,
                    "ref_price": in_ref,
                    "strategy_mode": strategy["title"],
                    "trade_direction": trade_direction,
                    "direction_basis": direction_basis,
                    "trade_type": in_trade_type,
                    "shares": sum(r["股數"] for r in normalized_personal_fills),
                    "buy_fee": trade_costs["buy_fee"],
                    "sell_fee": trade_costs["sell_fee"],
                    "transaction_tax": trade_costs["transaction_tax"],
                    "extra_fee": trade_costs["extra_fee"],
                    "total_cost": trade_costs["total_cost"],
                    "gross_pnl": trade_costs["gross_pnl"],
                    "net_pnl": trade_costs["net_pnl"],
                    "gross_pnl_pct": gross_pnl_pct,
                    "entry_time": entry_t_str,
                    "entry_price": factual_entry_price,
                    "entry_pct": entry_pct,
                    "entry_reason": in_entry_reason if in_entry_reason.strip() else "未填寫",
                    "exit_time": exit_t_str,
                    "exit_price": factual_exit_price,
                    "exit_pct": exit_pct,
                    "exit_reason": in_exit_reason if in_exit_reason.strip() else "未填寫",
                    "pnl_pct": pnl_pct,
                    "behaviors": behaviors,
                    "fact_check": fact_check,
                    "fills": normalized_personal_fills,
                    "trade_rounds": personal_trade_result["回合"],
                }
                rule_result = evaluate_teacher_rules(payload, personal_trade_result)
                review_md = render_rule_report(in_stock, personal_trade_result, rule_result)
                score = None
                sugg_time = "請依四態規則證據執行"
                sugg_price = factual_entry_price
                engine_name = RULE_ENGINE_VERSION
                if use_gemini_polish:
                    with st.spinner("規則覆盤已完成，Gemini 正在補充白話說明..."):
                        _, _, _, ai_review_md, ai_engine_name = run_laoshuai_ai_review(payload)
                    if ai_review_md:
                        review_md += "\n\n## Gemini 白話補充（不覆蓋規則判定）\n" + ai_review_md
                        engine_name += "＋" + ai_engine_name

                new_rec = {
                    "交易日期": payload["trade_date"],
                    "當日美股連動戰法判讀": strategy["title"],
                    "股票代號名稱": in_stock,
                    "交易方向": trade_direction,
                    "方向判斷依據": direction_basis,
                    "交易類型": in_trade_type,
                    "成交股數": sum(r["股數"] for r in normalized_personal_fills),
                    "買進手續費": trade_costs["buy_fee"],
                    "賣出手續費": trade_costs["sell_fee"],
                    "證券交易稅": trade_costs["transaction_tax"],
                    "其他費用": trade_costs["extra_fee"],
                    "總交易成本": trade_costs["total_cost"],
                    "毛損益(元)": trade_costs["gross_pnl"],
                    "稅費後淨損益(元)": trade_costs["net_pnl"],
                    "昨漲停參考價": in_ref if in_ref > 0 else "-",
                    "實際進場時間": entry_t_str,
                    "實際進場價": factual_entry_price,
                    "進場跌幅(%)": entry_pct if in_ref > 0 else "-",
                    "老師建議進場時間": sugg_time,
                    "老師建議進場價": sugg_price,
                    "進場理由": payload["entry_reason"],
                    "實際出場時間": exit_t_str,
                    "實際出場價": factual_exit_price,
                    "出場跌幅(%)": exit_pct if in_ref > 0 else "-",
                    "出場理由": payload["exit_reason"],
                    "稅費後單筆報酬率(%)": pnl_pct,
                    "老帥紀律評分": score,
                    "分批成交明細": json.dumps(normalized_personal_fills, ensure_ascii=False, default=str),
                    "交易回合明細": json.dumps(personal_trade_result["回合"], ensure_ascii=False, default=str),
                    "規則四態統計": json.dumps(rule_result["統計"], ensure_ascii=False),
                    "規則版本": RULE_ENGINE_VERSION,
                    "老帥AI覆盤總評": review_md
                }
                append_history_record(new_rec)

                clean_sugg_time = str(sugg_time).replace("`", "")
                clean_review_md = re.sub(r"<[^>]+>", "", str(review_md)).replace("`", "")
                pct_badge = f"（{entry_pct:+.2f}%）" if in_ref > 0 else ""
                pnl_color = "#FF4D4F" if pnl_pct > 0 else ("#22C55E" if pnl_pct < 0 else "#F8FAFC")
                first_brk_val = fact_check.get("first_break_m6_time", "未知")
                if not fact_check.get("ever_below_m6"):
                    first_brk_display = "未跌破 -6%"
                    brk_status_badge = "<span style='color:#F87171;font-weight:800;'>❌ 未跌破 -6% 線</span>"
                else:
                    first_brk_display = first_brk_val if first_brk_val != "未知" else "盤中曾跌破"
                    brk_status_badge = "<span style='color:#34D399;font-weight:800;'>✅ 確實跌破 -6% 線</span>"

                day_low_disp = f"{fact_check['day_low']} 元（{fact_check['day_low_pct']:+.2f}%）" if fact_check.get("day_low", 0) > 0 else "載入中"
                day_low_t_disp = f"出現於 {fact_check['low_time']}" if fact_check.get("low_time", "未知") != "未知" else ""

                # 將分點覆盤內容轉為高可讀性的獨立結構化卡片
                diag_cards_html = []
                border_colors = ["#EF4444", "#38BDF8", "#F59E0B"]
                for idx_p, para in enumerate([p.strip() for p in clean_review_md.split("\n\n") if p.strip()]):
                    para_html = re.sub(r"^###\s+(.+)$", r"<div style='color:#38BDF8;font-size:16px;font-weight:900;margin-bottom:8px;'>\1</div>", para, flags=re.M)
                    para_html = re.sub(r"\*\*(.+?)\*\*", r"<b style='color:#FBBF24;'>\1</b>", para)
                    para_html = re.sub(r"(?m)^-\s+", "• ", para_html)
                    para_html = re.sub(r"(?m)^(\d+)\.\s+", r"<b style='color:#38BDF8;'>\1.</b> ", para_html)
                    para_html = para_html.replace("\n", "<br>")
                    b_col = border_colors[idx_p % len(border_colors)]
                    diag_cards_html.append(f'<div class="review-diag-card" style="border-left-color:{b_col};">{para_html}</div>')

                st.session_state["personal_review_html"] = f"""
                <div class="ai-report-box">
                    <div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px;border-bottom:1px solid #1E293B;padding-bottom:12px;margin-bottom:14px;">
                        <div>
                            <div style="color:#FBBF24;font-size:17.5px;font-weight:900;">🩺 老帥實戰覆盤報告</div>
                            <div style="color:#94A3B8;font-size:12px;margin-top:2px;">驗證引擎：{engine_name} ｜ 數據源：{fact_check.get('data_sources', '')}</div>
                        </div>
                        <div style="display:flex;gap:10px;align-items:center;">
                            <span style="background:rgba(56,189,248,0.14);border:1px solid rgba(56,189,248,0.4);color:#38BDF8;font-size:14px;font-weight:800;padding:5px 12px;border-radius:8px;">紀律評分：{score} / 100 分</span>
                            <span style="background:rgba(15,23,42,0.9);border:1px solid #334155;color:{pnl_color};font-size:14px;font-weight:900;padding:5px 12px;border-radius:8px;">稅費後淨損益：{trade_costs['net_pnl']:+,} 元（{pnl_pct:+.3f}%）</span>
                        </div>
                    </div>
                    <div class="review-fact-grid">
                        <div class="review-fact-item">
                            <div class="review-fact-label">昨收基準價</div>
                            <div class="review-fact-val">{in_ref} 元</div>
                        </div>
                        <div class="review-fact-item">
                            <div class="review-fact-label">戰法 -6% 生死線</div>
                            <div class="review-fact-val" style="color:#FBBF24 !important;">{fact_check.get('line_m6', 0)} 元</div>
                        </div>
                        <div class="review-fact-item">
                            <div class="review-fact-label">首次跌破 -6% 時間</div>
                            <div class="review-fact-val">{first_brk_display}</div>
                            <div style="font-size:11.5px;margin-top:2px;">{brk_status_badge}</div>
                        </div>
                        <div class="review-fact-item">
                            <div class="review-fact-label">當日最低價與時間</div>
                            <div class="review-fact-val" style="color:#22C55E !important;">{day_low_disp}</div>
                            <div style="font-size:11.5px;color:#94A3B8;margin-top:2px;">{day_low_t_disp}</div>
                        </div>
                    </div>
                    <div class="review-fact-grid">
                        <div class="review-fact-item"><div class="review-fact-label">毛損益</div><div class="review-fact-val">{trade_costs['gross_pnl']:+,} 元</div></div>
                        <div class="review-fact-item"><div class="review-fact-label">買進／賣出手續費</div><div class="review-fact-val">{trade_costs['buy_fee']}／{trade_costs['sell_fee']} 元</div></div>
                        <div class="review-fact-item"><div class="review-fact-label">證券交易稅</div><div class="review-fact-val">{trade_costs['transaction_tax']} 元</div></div>
                        <div class="review-fact-item"><div class="review-fact-label">總交易成本</div><div class="review-fact-val" style="color:#F87171 !important;">{trade_costs['total_cost']} 元</div></div>
                    </div>
                    <div class="review-compare-grid">
                        <div class="review-compare-card" style="border-left:4px solid #38BDF8;">
                            <div style="font-size:12px;color:#94A3B8;font-weight:700;">⏱️ 學員實際進場點位</div>
                            <div style="font-size:15px;color:#F8FAFC;font-weight:800;margin-top:3px;">
                                時間 <span style="color:#38BDF8;">{entry_t_str}</span> ｜ 價格 <span style="color:#38BDF8;">{factual_entry_price} 元</span> {pct_badge}
                            </div>
                        </div>
                        <div class="review-compare-card" style="border-left:4px solid #10B981;">
                            <div style="font-size:12px;color:#94A3B8;font-weight:700;">🎯 老師建議最佳進場</div>
                            <div style="font-size:15px;color:#34D399;font-weight:800;margin-top:3px;">
                                {clean_sugg_time}（參考價 {sugg_price} 元）
                            </div>
                        </div>
                    </div>
                    {"".join(diag_cards_html)}
                </div>
                """

        if st.session_state.get("personal_review_html"):
            st.markdown(st.session_state["personal_review_html"], unsafe_allow_html=True)

        _pers_hist_df = load_history_df()
        if not _pers_hist_df.empty:
            if "當日美股連動戰法判讀" not in _pers_hist_df.columns:
                _pers_hist_df.insert(1, "當日美股連動戰法判讀", _pers_hist_df.get("戰法判讀", strategy["title"]))
            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
            dl_p1, dl_p2 = st.columns(2)
            with dl_p1:
                st.download_button(
                    label=f"📥 下載個人操作覆盤歷史 CSV（共 {len(_pers_hist_df)} 筆・含當日戰法）",
                    data=_pers_hist_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                    file_name=f"老帥個人操作覆盤歷史_{now_tw.strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    width="stretch",
                    key="dl_pers_csv_tab1"
                )
            with dl_p2:
                _p_xlsx = io.BytesIO()
                with pd.ExcelWriter(_p_xlsx, engine="openpyxl") as writer:
                    _pers_hist_df.to_excel(writer, index=False, sheet_name="個人操作覆盤歷史")
                st.download_button(
                    label=f"📊 下載個人操作覆盤歷史 Excel（共 {len(_pers_hist_df)} 筆・含當日戰法）",
                    data=_p_xlsx.getvalue(),
                    file_name=f"老帥個人操作覆盤歷史_{now_tw.strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                    key="dl_pers_xlsx_tab1"
                )

        # ------------------------------------------
        # 他人實戰操作／對帳單截圖解析與個人操作差異比對（同樣採用 st.form 防反黑）
        # ------------------------------------------
        st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)
        st.markdown("""
        <div style="background:rgba(56,189,248,0.10);border:1px solid rgba(56,189,248,0.38);border-left:4px solid #38BDF8;border-radius:10px;padding:12px 16px;margin-bottom:12px;">
            <div style="color:#38BDF8;font-size:14.5px;font-weight:900;margin-bottom:3px;">🔍 他人實戰操作／對帳單截圖解析 ＆ 與個人操作差異對照</div>
            <div style="color:#E2E8F0;font-size:13px;line-height:1.55;">
                上傳戰友或高手的<b>當日對帳單／分時走勢進出點位截圖</b>（或輸入文字描述），先逐列辨識成交表格並建立人工核對表；核對完成後，再由本機交易引擎分析回合、損益與老師戰法。圖片OCR與後續覆盤分開執行，點出雙方在切入點、風控與停利節奏上的關鍵差異！
            </div>
        </div>
        """, unsafe_allow_html=True)

        OCR_BUILD_VERSION = "peer-ocr-crop-fast-v4"
        if st.session_state.get("peer_ocr_build") != OCR_BUILD_VERSION:
            st.session_state["peer_ocr_build"] = OCR_BUILD_VERSION
            st.session_state["peer_ai_report"] = ""
            st.session_state["peer_ai_engine"] = ""
        st.caption(f"OCR 解盤版本：{OCR_BUILD_VERSION}")
        if "peer_form_ver" not in st.session_state:
            st.session_state["peer_form_ver"] = 0
        if "peer_ai_report" not in st.session_state:
            st.session_state["peer_ai_report"] = ""
        if "peer_ai_engine" not in st.session_state:
            st.session_state["peer_ai_engine"] = ""

        pv = st.session_state["peer_form_ver"]
        with st.form(key=f"peer_compare_form_{pv}", clear_on_submit=False):
            p_c1, p_c2 = st.columns([1.4, 2.6])
            with p_c1:
                peer_img_file = st.file_uploader(
                    "📸 上傳他人操作截圖（支援 PNG / JPG / WEBP）",
                    type=["png", "jpg", "jpeg", "webp"],
                    key=f"peer_img_uploader_{pv}"
                )
            with p_c2:
                peer_note = st.text_area(
                    "✍️ 補充說明他人當日操作細節（選填，例如：標的代號、進出場時間與價格、對方說的操作理由）",
                    value="",
                    placeholder="例如：戰友今天 09:05 在 4916 事欣科 51.2 元進場、09:22 在 53.5 元出場，說看到突破均價線跟大單敲進...",
                    height=135,
                    key=f"peer_note_input_{pv}"
                )
            btn_peer_submit = st.form_submit_button("🔍 第一步：辨識成交表格", type="primary", width="stretch")

        if peer_img_file is not None:
            safe_peer_name = str(peer_img_file.name).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            st.markdown(f"""
            <div style="background:#0F2133;border:1px solid #38BDF8;border-left:5px solid #22C55E;border-radius:10px;padding:13px 16px;margin:8px 0 12px;color:#F8FAFC !important;font-size:14px;font-weight:750;line-height:1.65;opacity:1;">
                <span style="color:#4ADE80 !important;font-size:17px;font-weight:900;">✅ 已接收截圖</span><br>
                <span style="color:#F8FAFC !important;">檔案：<b style="color:#FFFFFF !important;">{safe_peer_name}</b></span><br>
                <span style="color:#E2E8F0 !important;">目前只完成檔案載入，尚未開始辨識。按下「第一步：辨識成交表格」後，系統只會逐列辨識成交資料並建立人工核對表；確認資料後，才會另行計算損益與執行老師戰法覆盤。</span>
            </div>
            """, unsafe_allow_html=True)
        elif peer_note.strip():
            st.markdown("""
            <div style="background:#0F2133;border:1px solid #38BDF8;border-left:5px solid #22C55E;border-radius:10px;padding:13px 16px;margin:8px 0 12px;color:#F8FAFC !important;font-size:14px;font-weight:750;line-height:1.65;opacity:1;">
                <span style="color:#4ADE80 !important;font-size:17px;font-weight:900;">✅ 已接收文字說明</span><br>
                <span style="color:#E2E8F0 !important;">按下分析後才會呼叫 AI。若 AI 不可用，系統會依《美股大跌法》本機知識庫進行規則解盤；未辨識的截圖內容不會被猜測。</span>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.caption("尚未送出分析。上傳檔案本身不會呼叫 AI，也不會消耗生成額度。")

        if st.button("🧹 清空他人分析", key="btn_clear_peer_frag"):
            st.session_state["peer_form_ver"] += 1
            st.session_state["peer_ai_report"] = ""
            st.session_state["peer_ai_engine"] = ""
            st.rerun(scope="fragment")

        if btn_peer_submit:
            if peer_img_file is None and not peer_note.strip():
                st.warning("⚠️ 請至少「上傳一張他人操作截圖」或「輸入他人操作文字說明」再送出分析！")
            else:
                if peer_img_file is not None:
                    st.image(peer_img_file, caption="已載入他人操作截圖", width=360)
                img_bytes = peer_img_file.getvalue() if peer_img_file is not None else None
                img_mime = peer_img_file.type if peer_img_file is not None else None
                personal_batch = _personal_fills_summary_v8(personal_fills_df)
                if personal_batch["fills"]:
                    u_direction, u_direction_basis = personal_batch["direction"], personal_batch.get("direction_basis", "依逐筆成交判斷")
                else:
                    u_direction, u_direction_basis = detect_trade_direction(in_entry_reason, in_exit_reason, behaviors, in_direction_mode)
                u_costs = calc_trade_costs(in_entry_price, in_exit_price, in_shares, u_direction, in_trade_type, in_fee_discount, in_minimum_fee, in_extra_fee) if (in_entry_price > 0 and in_exit_price > 0) else {"net_pnl_pct": 0.0, "net_pnl": 0, "total_cost": 0}
                u_pnl = u_costs["net_pnl_pct"]
                user_ctx = {
                    "strategy_mode": strategy["title"],
                    "trade_direction": u_direction,
                    "direction_basis": u_direction_basis,
                    "trade_type": in_trade_type,
                    "shares": int(in_shares),
                    "total_cost": u_costs["total_cost"],
                    "net_pnl": u_costs["net_pnl"],
                    "stock": in_stock if in_stock else "",
                    "entry_time": in_entry_time.strftime("%H:%M:%S"),
                    "entry_price": in_entry_price,
                    "entry_reason": in_entry_reason if in_entry_reason.strip() else "未填寫",
                    "exit_time": in_exit_time.strftime("%H:%M:%S"),
                    "exit_price": in_exit_price,
                    "exit_reason": in_exit_reason if in_exit_reason.strip() else "未填寫",
                    "pnl_pct": u_pnl,
                    "fills": personal_batch["fills"],
                    "fills_summary": personal_batch["summary"],
                }
                with st.status("🔄 正在上傳截圖並進行 AI 視覺辨識，請勿重複點擊...", expanded=True) as peer_status:
                    st.write("步驟 1/3：讀取截圖與補充文字")
                    st.write("步驟 2/3：逐列辨識股票、買賣、股數、價格、日期與時間（不解盤）")
                    rep_md, eng_used = run_peer_comparison_analysis(img_bytes, img_mime, peer_note, user_ctx)
                    st.write("步驟 3/3：建立人工核對表；確認後才重算成交與覆盤")
                    if "未完成截圖辨識" in eng_used or "本機文字規則" in eng_used:
                        peer_status.update(label="雲端分析未完成，已產生本機初步覆盤；請先逐筆核對", state="error", expanded=True)
                    else:
                        peer_status.update(label="已產生初步報告，請先核對辨識與證據", state="complete", expanded=False)
                    st.session_state["peer_ai_report"] = rep_md
                    st.session_state["peer_ai_engine"] = eng_used
                    if not rep_md.startswith("❌") and not rep_md.startswith("⚠️"):
                        peer_rec = {
                            "分析時間": datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M:%S"),
                            "交易日期": in_date.strftime("%Y-%m-%d"),
                            "當日美股連動戰法判讀": strategy["title"],
                            "個人對照標的": in_stock if in_stock else "未填寫",
                            "個人進出場與報酬": f"{in_entry_time.strftime('%H:%M')}@{in_entry_price} -> {in_exit_time.strftime('%H:%M')}@{in_exit_price} ({u_pnl:+.2f}%)" if (in_entry_price > 0 and in_exit_price > 0) else "未填寫",
                            "他人操作補充說明": peer_note.strip() if peer_note.strip() else "（截圖純視覺解析）",
                            "分析狀態": "初步報告，辨識與帳務未經人工核對",
                            "分析引擎": eng_used,
                            "老帥戰法拆解與差異對照報告": rep_md
                        }
                        append_peer_history_record(peer_rec)

        if st.session_state.get("peer_ai_report"):
            st.markdown(f"""
            <div class="ai-report-box" style="border-color:rgba(56,189,248,0.5);">
                <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #1E293B;padding-bottom:10px;margin-bottom:12px;">
                    <span style="color:#38BDF8;font-size:17px;font-weight:900;">🔍 老帥戰法拆解：他人操作解析 ＆ 個人差異對照報告</span>
                    <span style="color:#94A3B8;font-size:13px;font-weight:700;">引擎：{st.session_state.get('peer_ai_engine', '')}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            st.markdown(st.session_state["peer_ai_report"])
            _peer_v2_verification_ui()

        _peer_hist_df = load_peer_history_df()
        if not _peer_hist_df.empty:
            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
            dl_o1, dl_o2 = st.columns(2)
            with dl_o1:
                st.download_button(
                    label=f"📥 下載他人操作差異分析歷史 CSV（共 {len(_peer_hist_df)} 筆・含當日戰法）",
                    data=_peer_hist_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                    file_name=f"老帥他人操作差異分析歷史_{now_tw.strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    width="stretch",
                    key="dl_peer_csv_tab1"
                )
            with dl_o2:
                _o_xlsx = io.BytesIO()
                with pd.ExcelWriter(_o_xlsx, engine="openpyxl") as writer:
                    _peer_hist_df.to_excel(writer, index=False, sheet_name="他人操作差異分析歷史")
                st.download_button(
                    label=f"📊 下載他人操作差異分析歷史 Excel（共 {len(_peer_hist_df)} 筆・含當日戰法）",
                    data=_o_xlsx.getvalue(),
                    file_name=f"老帥他人操作差異分析歷史_{now_tw.strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                    key="dl_peer_xlsx_tab1"
                )

    render_review_fragment()

with tab_history:
    today_tw_date = now_tw.date()
    st.markdown("""
    <div style="background:rgba(245,158,11,0.10);border:1px solid rgba(245,158,11,0.38);border-left:4px solid #F59E0B;border-radius:10px;padding:12px 16px;margin-bottom:14px;">
        <div style="color:#FBBF24;font-size:14.5px;font-weight:900;margin-bottom:3px;">📅 歷史實戰資料庫查詢與區段匯出（溫故知新・知己知彼百戰百勝）</div>
        <div style="color:#E2E8F0;font-size:13px;line-height:1.55;">
            預設查詢與匯出區間為<b>今日（今天開始 ～ 今天結束）</b>，您可自由調整起訖日期檢視歷史紀錄，並分別下載<b>【個人操作覆盤】</b>與<b>【他人操作戰法差異對照】</b>完整報表（每筆皆自動載入當日美股連動戰法）。
        </div>
    </div>
    """, unsafe_allow_html=True)

    hist_df = load_history_df()
    if not hist_df.empty and "當日美股連動戰法判讀" not in hist_df.columns:
        hist_df.insert(1, "當日美股連動戰法判讀", hist_df.get("戰法判讀", strategy["title"]))

    peer_df_all = load_peer_history_df()

    # 統一日期區間選擇器：預設今天開始、今天結束
    q1, q2, q3 = st.columns([1.2, 1.2, 1.6])
    with q1:
        start_d = st.date_input("📅 查詢／匯出起始日期（預設今日）", value=today_tw_date, key="hist_start")
    with q2:
        end_d = st.date_input("📅 查詢／匯出結束日期（預設今日）", value=today_tw_date, key="hist_end")
    with q3:
        all_stock_names = sorted(hist_df["股票代號名稱"].dropna().unique().tolist()) if not hist_df.empty else []
        stock_opts = ["全部標的"] + all_stock_names
        sel_stock = st.selectbox("篩選個人操作特定股票", options=stock_opts, key="hist_stock_filter")

    # ------------------------------------------
    # 子區塊 A：個人操作覆盤歷史查詢與區段匯出
    # ------------------------------------------
    st.markdown('<div style="font-size:15.5px;font-weight:900;color:#FBBF24;margin:14px 0 8px 0;">🩺 一、個人操作覆盤歷史紀錄（含當日戰法與紀律評分）</div>', unsafe_allow_html=True)

    if hist_df.empty:
        filtered_df = pd.DataFrame(columns=[
            "交易日期", "當日美股連動戰法判讀", "股票代號名稱", "昨漲停參考價",
            "實際進場時間", "實際進場價", "進場跌幅(%)",
            "老師建議進場時間", "老師建議進場價", "進場理由",
            "實際出場時間", "實際出場價", "出場跌幅(%)", "出場理由",
            "稅費後單筆報酬率(%)", "老帥紀律評分", "老帥AI覆盤總評"
        ])
    else:
        hist_df["交易日期_dt"] = pd.to_datetime(hist_df["交易日期"], errors="coerce").dt.date
        mask = (hist_df["交易日期_dt"] >= start_d) & (hist_df["交易日期_dt"] <= end_d)
        if sel_stock != "全部標的":
            mask = mask & (hist_df["股票代號名稱"] == sel_stock)
        filtered_df = hist_df[mask].drop(columns=["交易日期_dt"]).copy()

    s1, s2, s3, s4 = st.columns(4)
    total_trades = len(filtered_df)
    pnl_series = pd.to_numeric(filtered_df["稅費後單筆報酬率(%)"], errors="coerce").fillna(0.0) if total_trades > 0 else pd.Series(dtype=float)
    score_series = pd.to_numeric(filtered_df["老帥紀律評分"], errors="coerce").fillna(0.0) if total_trades > 0 else pd.Series(dtype=float)
    win_rate = round((len(pnl_series[pnl_series > 0]) / total_trades) * 100, 1) if total_trades > 0 else 0.0
    avg_pnl = round(float(pnl_series.mean()), 2) if total_trades > 0 else 0.0
    avg_score = round(float(score_series.mean()), 1) if total_trades > 0 else 0.0

    s1.metric("區段個人操作筆數", f"{total_trades} 筆")
    s2.metric("區段實戰勝率", f"{win_rate}%")
    s3.metric("平均稅費後單筆報酬", f"{avg_pnl:+.2f}%")
    s4.metric("老帥平均紀律分", f"{avg_score} 分")

    if filtered_df.empty:
        st.markdown(f"""
        <div style="background:#111726;border:1px solid #334155;border-left:4px solid #FBBF24;border-radius:10px;padding:14px 18px;margin:10px 0;color:#F8FAFC;font-size:13.5px;">
            📭 <b>選定區間（{start_d} ～ {end_d}）尚無個人操作覆盤紀錄</b>（資料庫累計共 {len(hist_df)} 筆歷史紀錄，可調整上方起訖日期查詢過往操作，或於左側頁籤送出今日覆盤）。
        </div>
        """, unsafe_allow_html=True)
    else:
        h_rows_html = []
        h_mobile_html = []
        for _, hr in filtered_df.iterrows():
            pnl_v = float(hr["稅費後單筆報酬率(%)"])
            pnl_c = "#FF4D4F" if pnl_v > 0 else ("#22C55E" if pnl_v < 0 else "#F8FAFC")
            tactic_txt = hr.get("當日美股連動戰法判讀", "-")
            h_rows_html.append(
                f'<tr style="border-bottom:1px solid #1E293B;">'
                f'<td style="padding:10px 8px;white-space:nowrap;color:#CBD5E1;">{hr["交易日期"]}</td>'
                f'<td style="padding:10px 8px;color:#FBBF24;font-size:12.5px;min-width:190px;">{tactic_txt}</td>'
                f'<td style="padding:10px 8px;white-space:nowrap;font-weight:800;color:#FFFFFF;">{hr["股票代號名稱"]}</td>'
                f'<td style="padding:10px 8px;white-space:nowrap;color:#38BDF8;">{hr["實際進場時間"]} / {hr["實際進場價"]}</td>'
                f'<td style="padding:10px 8px;white-space:nowrap;color:#FBBF24;">{hr["老師建議進場時間"]} / {hr["老師建議進場價"]}</td>'
                f'<td style="padding:10px 8px;white-space:nowrap;color:#CBD5E1;">{hr["實際出場時間"]} / {hr["實際出場價"]}</td>'
                f'<td style="padding:10px 8px;text-align:right;white-space:nowrap;font-weight:900;color:{pnl_c};">{pnl_v:+.2f}%</td>'
                f'<td style="padding:10px 8px;text-align:right;white-space:nowrap;font-weight:800;color:#34D399;">{hr["老帥紀律評分"]}分</td>'
                f'<td style="padding:10px 10px;color:#F1F5F9;font-size:13px;line-height:1.5;white-space:normal;word-break:break-word;min-width:260px;">{hr["老帥AI覆盤總評"]}</td>'
                f'</tr>'
            )
            h_mobile_html.append(
                f'<div class="m-stock-card">'
                f'<div class="m-card-top">'
                f'<div><div style="font-size:16px;font-weight:900;color:#FFFFFF;">{hr["股票代號名稱"]}</div>'
                f'<div style="font-size:11.5px;color:#94A3B8;">{hr["交易日期"]} ｜ 紀律評分 {hr["老帥紀律評分"]} 分</div></div>'
                f'<div style="font-size:17px;font-weight:900;color:{pnl_c};">{pnl_v:+.2f}%</div>'
                f'</div>'
                f'<div class="m-tactic-badge">🎯 {tactic_txt}</div>'
                f'<div style="font-size:12.5px;color:#CBD5E1;margin-bottom:6px;">'
                f'🟢 實際進：{hr["實際進場時間"]}（<b>{hr["實際進場價"]}</b>）<br>'
                f'🎯 老師建議：{hr["老師建議進場時間"]}（<b>{hr["老師建議進場價"]}</b>）<br>'
                f'🔴 實際出：{hr["實際出場時間"]}（<b>{hr["實際出場價"]}</b>）'
                f'</div>'
                f'<div class="m-advice-box">{hr["老帥AI覆盤總評"]}</div>'
                f'</div>'
            )

        h_desk_cls = "mobile-only-view" if is_mobile_ua else "desktop-only-view"
        h_mob_cls = "desktop-only-view" if is_mobile_ua else "mobile-only-view"
        hist_html = (
            f'<div class="{h_desk_cls}" style="width:100%;overflow-x:auto;background:#111726;border:1px solid #334155;border-radius:12px;margin-bottom:12px;">'
            f'<table style="width:100%;border-collapse:collapse;font-size:13px;text-align:left;">'
            f'<thead><tr style="background:#0D1322;border-bottom:1px solid #334155;color:#FBBF24;font-weight:800;">'
            f'<th style="padding:10px 8px;white-space:nowrap;">交易日期</th>'
            f'<th style="padding:10px 8px;min-width:190px;">當日美股連動戰法</th>'
            f'<th style="padding:10px 8px;white-space:nowrap;">股票代號名稱</th>'
            f'<th style="padding:10px 8px;white-space:nowrap;">實際進場(時/價)</th>'
            f'<th style="padding:10px 8px;white-space:nowrap;">老師建議進場(時/價)</th>'
            f'<th style="padding:10px 8px;white-space:nowrap;">實際出場(時/價)</th>'
            f'<th style="padding:10px 8px;text-align:right;white-space:nowrap;">報酬率</th>'
            f'<th style="padding:10px 8px;text-align:right;white-space:nowrap;">紀律分</th>'
            f'<th style="padding:10px 10px;min-width:260px;">老帥AI覆盤總評</th>'
            f'</tr></thead>'
            f'<tbody>{"".join(h_rows_html)}</tbody>'
            f'</table></div>'
            f'<div class="{h_mob_cls}">{"".join(h_mobile_html)}</div>'
        )
        st.markdown(hist_html, unsafe_allow_html=True)

    # 個人操作區段 CSV 與 Excel 匯出按鈕
    exp_c1, exp_c2 = st.columns(2)
    with exp_c1:
        csv_bytes = filtered_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            label=f"📥 匯出個人操作 CSV（{start_d} ~ {end_d}・共 {len(filtered_df)} 筆）",
            data=csv_bytes,
            file_name=f"老帥個人操作覆盤_{start_d}_至_{end_d}.csv",
            mime="text/csv",
            width="stretch",
            key="dl_pers_range_csv"
        )
    with exp_c2:
        excel_buf = io.BytesIO()
        with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
            filtered_df.to_excel(writer, index=False, sheet_name="個人實戰覆盤紀錄")
        st.download_button(
            label=f"📊 匯出個人操作 Excel（{start_d} ~ {end_d}・共 {len(filtered_df)} 筆）",
            data=excel_buf.getvalue(),
            file_name=f"老帥個人操作覆盤_{start_d}_至_{end_d}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
            key="dl_pers_range_xlsx"
        )

    # ------------------------------------------
    # 子區塊 B：他人操作解析與差異對照歷史查詢與區段匯出（知己知彼百戰百勝）
    # ------------------------------------------
    st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
    st.markdown('<div style="font-size:15.5px;font-weight:900;color:#38BDF8;margin:10px 0 8px 0;">🔍 二、他人操作戰法解析與差異對照歷史紀錄（知己知彼百戰百勝）</div>', unsafe_allow_html=True)

    if peer_df_all.empty:
        filtered_peer_df = pd.DataFrame(columns=[
            "分析時間", "交易日期", "當日美股連動戰法判讀",
            "個人對照標的", "個人進出場與報酬", "他人操作補充說明",
            "分析引擎", "老帥戰法拆解與差異對照報告"
        ])
    else:
        peer_df_all["交易日期_dt"] = pd.to_datetime(peer_df_all["交易日期"], errors="coerce").dt.date
        p_mask = (peer_df_all["交易日期_dt"] >= start_d) & (peer_df_all["交易日期_dt"] <= end_d)
        filtered_peer_df = peer_df_all[p_mask].drop(columns=["交易日期_dt"]).copy()

    if filtered_peer_df.empty:
        st.markdown(f"""
        <div style="background:#111726;border:1px solid #334155;border-left:4px solid #38BDF8;border-radius:10px;padding:14px 18px;margin:10px 0;color:#F8FAFC;font-size:13.5px;">
            📭 <b>選定區間（{start_d} ～ {end_d}）尚無他人操作差異分析紀錄</b>（資料庫累計共 {len(peer_df_all)} 筆他人分析紀錄，可調整上方起訖日期查詢，或於左側頁籤上傳他人對帳單／走勢截圖解析）。
        </div>
        """, unsafe_allow_html=True)
    else:
        p_rows_html = []
        p_mobile_html = []
        for _, pr in filtered_peer_df.iterrows():
            p_rows_html.append(
                f'<tr style="border-bottom:1px solid #1E293B;">'
                f'<td style="padding:10px 8px;white-space:nowrap;color:#CBD5E1;">{pr["交易日期"]}<br><span style="font-size:11px;color:#94A3B8;">{pr["分析時間"]}</span></td>'
                f'<td style="padding:10px 8px;color:#FBBF24;font-size:12.5px;min-width:190px;">{pr["當日美股連動戰法判讀"]}</td>'
                f'<td style="padding:10px 8px;white-space:nowrap;color:#38BDF8;font-weight:700;">{pr["個人對照標的"]}<br><span style="font-size:11.5px;color:#CBD5E1;">{pr["個人進出場與報酬"]}</span></td>'
                f'<td style="padding:10px 8px;color:#E2E8F0;font-size:12.5px;min-width:180px;">{pr["他人操作補充說明"]}</td>'
                f'<td style="padding:10px 10px;color:#F1F5F9;font-size:13px;line-height:1.5;white-space:normal;word-break:break-word;min-width:300px;">{pr["老帥戰法拆解與差異對照報告"]}</td>'
                f'</tr>'
            )
            p_mobile_html.append(
                f'<div class="m-stock-card" style="border-color:rgba(56,189,248,0.4);">'
                f'<div class="m-card-top">'
                f'<div><div style="font-size:15.5px;font-weight:900;color:#38BDF8;">他人操作解析（{pr["交易日期"]}）</div>'
                f'<div style="font-size:11.5px;color:#94A3B8;">個人對照：{pr["個人對照標的"]} ｜ {pr["個人進出場與報酬"]}</div></div>'
                f'</div>'
                f'<div class="m-tactic-badge">🎯 {pr["當日美股連動戰法判讀"]}</div>'
                f'<div style="font-size:12.5px;color:#CBD5E1;margin-bottom:6px;">📝 說明：{pr["他人操作補充說明"]}</div>'
                f'<div class="m-advice-box" style="border-left-color:#38BDF8;">{pr["老帥戰法拆解與差異對照報告"]}</div>'
                f'</div>'
            )

        p_desk_cls = "mobile-only-view" if is_mobile_ua else "desktop-only-view"
        p_mob_cls = "desktop-only-view" if is_mobile_ua else "mobile-only-view"
        peer_hist_html = (
            f'<div class="{p_desk_cls}" style="width:100%;overflow-x:auto;background:#111726;border:1px solid #334155;border-radius:12px;margin-bottom:12px;">'
            f'<table style="width:100%;border-collapse:collapse;font-size:13px;text-align:left;">'
            f'<thead><tr style="background:#0D1322;border-bottom:1px solid #334155;color:#38BDF8;font-weight:800;">'
            f'<th style="padding:10px 8px;white-space:nowrap;">交易日期 / 時間</th>'
            f'<th style="padding:10px 8px;min-width:190px;">當日美股連動戰法</th>'
            f'<th style="padding:10px 8px;white-space:nowrap;">個人對照標的與報酬</th>'
            f'<th style="padding:10px 8px;min-width:180px;">他人操作補充說明</th>'
            f'<th style="padding:10px 10px;min-width:300px;">老帥戰法拆解與差異對照報告</th>'
            f'</tr></thead>'
            f'<tbody>{"".join(p_rows_html)}</tbody>'
            f'</table></div>'
            f'<div class="{p_mob_cls}">{"".join(p_mobile_html)}</div>'
        )
        st.markdown(peer_hist_html, unsafe_allow_html=True)

    # 他人操作區段 CSV 與 Excel 匯出按鈕
    p_exp_c1, p_exp_c2 = st.columns(2)
    with p_exp_c1:
        p_csv_bytes = filtered_peer_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            label=f"📥 匯出他人操作差異分析 CSV（{start_d} ~ {end_d}・共 {len(filtered_peer_df)} 筆）",
            data=p_csv_bytes,
            file_name=f"老帥他人操作差異分析_{start_d}_至_{end_d}.csv",
            mime="text/csv",
            width="stretch",
            key="dl_peer_range_csv"
        )
    with p_exp_c2:
        p_excel_buf = io.BytesIO()
        with pd.ExcelWriter(p_excel_buf, engine="openpyxl") as writer:
            filtered_peer_df.to_excel(writer, index=False, sheet_name="他人操作差異對照紀錄")
        st.download_button(
            label=f"📊 匯出他人操作差異分析 Excel（{start_d} ~ {end_d}・共 {len(filtered_peer_df)} 筆）",
            data=p_excel_buf.getvalue(),
            file_name=f"老帥他人操作差異分析_{start_d}_至_{end_d}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
            key="dl_peer_range_xlsx"
        )

# 已改用 @st.fragment 局部輪詢，避免全頁重整中斷操作
