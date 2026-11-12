import json, time
from datetime import datetime
import numpy as np, pandas as pd, pytz, requests, yfinance as yf
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="破產後重生之我要靠量化交易發財", page_icon="📈", layout="wide",
                    initial_sidebar_state="collapsed")
TZ = pytz.timezone("Asia/Taipei")
UP, DN = "#ff4d5a", "#22c55e"                    # 台股慣例：紅漲綠跌

st.markdown("""<style>
header[data-testid=stHeader],footer,#MainMenu{display:none}
.stApp{background:linear-gradient(135deg,#f8c8e6 0%,#dcb8fb 52%,#b9a6f7 100%);background-attachment:fixed}
.block-container{padding:0!important;max-width:100%!important;overflow:hidden}

/* 標題垂直置中優化 */
.st-key-nav{background:#0b0b0e;padding:0.6rem 1.5rem;border-bottom:1px solid #26262d;box-shadow:0 4px 24px rgba(60,20,100,.35)}
.st-key-nav h1{color:#FFC83D;font-size:1.35rem;font-weight:800;letter-spacing:.05em;margin:0;padding:0;line-height:1}

.st-key-body{padding:.8rem 1.2rem 1.2rem}
.st-key-chart_card{background:#000;border-radius:18px;padding:.8rem 1rem .6rem;box-shadow:0 10px 30px rgba(70,30,120,.3)}
.st-key-flow_card,.st-key-strat_card{background:#15111c;border-radius:18px;padding:.9rem 1.2rem;color:#e8e6ee;box-shadow:0 10px 30px rgba(70,30,120,.25)}
.st-key-chart_card iframe, .st-key-flow_card iframe {border-radius:12px; display:block;}
.ttl{color:#fff;font-size:1.05rem;font-weight:700}.ttl span{color:#8d8d99;font-size:.8rem;margin-left:.4rem;font-weight:500}
div[data-testid=stMetric]{background:#1e1927;border-radius:12px;padding:.5rem .8rem}
div[data-testid=stMetric] label p{color:#a9a6b5!important}div[data-testid=stMetricValue]{color:#fff}
</style>""", unsafe_allow_html=True)

# ───────────────────────── 資料模組 (移除 Google Sheets，專注即時行情) ─────────────────────────
def _clean(d):
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    d = d[~d.index.duplicated()]
    return d.dropna(subset=["Close"])

@st.cache_data(ttl=300, show_spinner=False)
def load_daily(sym, period="3y"):
    return _clean(yf.download(sym, period=period, interval="1d", auto_adjust=False, progress=False))

@st.cache_data(ttl=60, show_spinner=False)
def load_intraday():
    d = _clean(yf.download("^TWII", period="5d", interval="1m", progress=False))
    if d.empty: return d
    d.index = d.index.tz_convert(TZ)
    return d[np.array([x.date() for x in d.index]) == d.
