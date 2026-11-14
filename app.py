import os, io, csv, json, time, re, math
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta
import numpy as np, pandas as pd, pytz, requests, yfinance as yf
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="破產後重生之我要靠量化交易發財", page_icon="📈", layout="wide",
                   initial_sidebar_state="collapsed")
TZ = pytz.timezone("Asia/Taipei")
UP, DN = "#ff4d5a", "#22c55e"                   # 台股慣例：紅漲綠跌

# ───────────────────────── 系統設定與新聞白名單 / 黑名單 ─────────────────────────
DEFAULT_OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1")
INDEX_TICKER = "^TWII"
ETF_TICKER = "00631L.TW"
SYM = ETF_TICKER

NEWS_DAYS = 3
NEWS_PER_SOURCE = 3
NEWS_WHITELIST = [
    {"name": "中央社",       "domain": "cna.com.tw",     "lang": "zh"},
    {"name": "經濟日報",     "domain": "money.udn.com",  "lang": "zh"},
    {"name": "工商時報",     "domain": "ctee.com.tw",    "lang": "zh"},
    {"name": "鉅亨網",       "domain": "cnyes.com",      "lang": "zh"},
    {"name": "自由時報財經", "domain": "ec.ltn.com.tw",  "lang": "zh"},
    {"name": "財訊",         "domain": "wealth.com.tw",  "lang": "zh"},
    {"name": "Reuters",      "domain": "reuters.com",    "lang": "en"},
    {"name": "Bloomberg",    "domain": "bloomberg.com",  "lang": "en"},
    {"name": "CNBC",         "domain": "cnbc.com",       "lang": "en"},
]
NEWS_BLACKLIST = [
    "ptt.cc", "dcard.tw", "kknews.cc", "mobile01.com", "facebook.com",
    "youtube.com", "threads.net", "cmoney.tw", "medium.com"
]

FOUR_STATES = ["開高走高", "開高走低", "開低走高", "開低走低"]
MIN_TRAIN = 150
MAX_TRAIN = 500
GRID = [(lam, hl) for lam in (5.0, 20.0, 80.0) for hl in (80.0, 250.0)]

STATE_META = {
    "開高走高": {"col": "#ff4d5a", "bg": "rgba(255,77,90,.20)", "icon": "🔴", "desc": "開盤 > 昨收 且 收盤 ≥ 開盤（跳空續攻紅K）"},
    "開高走低": {"col": "#f59e0b", "bg": "rgba(245,158,11,.20)", "icon": "🟠", "desc": "開盤 > 昨收 但 收盤 < 開盤（開高出貨黑K）"},
    "開低走高": {"col": "#38bdf8", "bg": "rgba(56,189,248,.20)", "icon": "🔵", "desc": "開盤 ≤ 昨收 但 收盤 ≥ 開盤（低接承接紅K）"},
    "開低走低": {"col": "#22c55e", "bg": "rgba(34,197,94,.20)", "icon": "🟢", "desc": "開盤 ≤ 昨收 且 收盤 < 開盤（跳空殺低黑K）"},
}

AI_AGENTS = [
    {"id": "technical", "name": "技術面分析師", "model_id": DEFAULT_OPENAI_MODEL, "secret_key": "OPENAI_API_KEY", "short": "技", "color": "#10a37f", "role": "只根據「事實卡」與「條件式價位」判斷趨勢、動能、關鍵價位。不談新聞。"},
    {"id": "news",      "name": "消息面分析師", "model_id": DEFAULT_OPENAI_MODEL, "secret_key": "OPENAI_API_KEY", "short": "消", "color": "#3b82f6", "role": "只根據「新聞標題」判斷資金面、總經、國際股市（美股/半導體/Fed）對台股的影響。標題不足時要明說資訊不足。"},
    {"id": "risk",      "name": "風險控管官",   "model_id": DEFAULT_OPENAI_MODEL, "secret_key": "OPENAI_API_KEY", "short": "風", "color": "#8b5cf6", "role": "站在最壞情境。重點是波動、乖離過大、停損位置，以及 00631L 兩倍槓桿的每日再平衡耗損。"},
    {"id": "devil",     "name": "反方辯士",     "model_id": DEFAULT_OPENAI_MODEL, "secret_key": "OPENAI_API_KEY", "short": "反", "color": "#d97706", "role": "刻意找出其他人可能忽略的反面論點，專挑「現在進場最可能出錯的理由」。"},
]

FEATURE_COLS = [
    "tsm_pct", "sox_pct", "nvda_pct", "sp_pct", "vix_pct", "fx_pct",
    "tw_prev_pct", "prev_intra", "prev_clv", "wick_diff", "prev_hl_pct",
    "bias5", "bias10", "bias20", "ma5_slope", "rsi5_z",
    "lead_lag", "tsm_x_bias5", "sox_x_clv", "gap_reversal_risk", "adr_prem"
]

FEAT_NAMES = {
    "tsm_pct": "台積電ADR漲跌", "sox_pct": "費城半導體漲跌", "nvda_pct": "NVIDIA漲跌",
    "sp_pct": "標普500漲跌", "vix_pct": "VIX恐慌變動", "fx_pct": "台幣匯率變動",
    "tw_prev_pct": "前日台股漲跌", "prev_intra": "前日台股實體K", "prev_clv": "前日收盤強弱CLV",
    "wick_diff": "前日上下影線差", "prev_hl_pct": "前日高低振幅", "bias5": "5MA乖離率",
    "bias10": "10MA乖離率", "bias20": "20MA乖離率", "ma5_slope": "5MA斜率", "rsi5_z": "5日RSI位階",
    "lead_lag": "台美跨日基差", "tsm_x_bias5": "ADR×5MA乖離交互項", "sox_x_clv": "費半×CLV交互項",
    "gap_reversal_risk": "高檔跳空反轉風險", "adr_prem": "台積電ADR溢價率",
}

AGENT_SUBSPACES = {
    "technical": ["bias5", "bias10", "bias20", "ma5_slope", "rsi5_z", "prev_clv", "wick_diff", "prev_hl_pct"],
    "news":      ["tsm_pct", "sox_pct", "nvda_pct", "sp_pct", "fx_pct", "lead_lag", "adr_prem"],
    "risk":      ["vix_pct", "bias5", "bias20", "gap_reversal_risk", "prev_hl_pct", "tsm_x_bias5"],
    "devil":     ["lead_lag", "gap_reversal_risk", "sox_x_clv", "vix_pct", "bias20", "rsi5_z"],
}

# ───────────────────────── 全域樣式 ─────────────────────────
st.markdown("""<style>
header[data-testid=stHeader],footer,#MainMenu{display:none}
.stApp{background:linear-gradient(135deg,#f8c8e6 0%,#dcb8fb 52%,#b9a6f7 100%);background-attachment:fixed}
.block-container{padding:0!important;max-width:100%!important;overflow-x:hidden}
.st-key-nav{background:#0b0b0e;padding:0 1.5rem!important;min-height:64px;display:flex;flex-direction:column;justify-content:center;
  border-bottom:1px solid #26262d;box-shadow:0 4px 24px rgba(60,20,100,.35)}
.st-key-nav [data-testid=stHorizontalBlock]{align-items:center!important;gap:1rem}
.st-key-nav [data-testid=stColumn]{display:flex;align-items:center;min-height:64px}
.st-key-nav [data-testid=stColumn]:last-child{justify-content:flex-end}
.st-key-nav [data-testid=stColumn]>div{width:100%}
.st-key-nav [data-testid=stElementContainer],.st-key-nav [data-testid=stMarkdownContainer]{margin:0!important;padding:0!important}
.st-key-nav [data-testid=stMarkdownContainer]{display:flex;align-items:center}
.st-key-nav h1{color:#FFC83D;font-size:1.35rem;font-weight:800;letter-spacing:.05em;margin:0!important;padding:0!important;line-height:1.4!important}
.st-key-body{padding:.8rem 1.2rem 1.2rem}
.st-key-chart_card,.st-key-chart_card_s{background:#000;border-radius:18px;padding:.8rem 1rem .6rem;box-shadow:0 10px 30px rgba(70,30,120,.3)}
.st-key-flow_card,.st-key-strat_card,.st-key-trade_card,.st-key-vote_card{background:#15111c;border-radius:18px;padding:.9rem 1.2rem;color:#e8e6ee;box-shadow:0 10px 30px rgba(70,30,120,.25)}
.st-key-chart_card iframe,.st-key-chart_card_s iframe,.st-key-flow_card iframe,.st-key-vote_card iframe{border-radius:12px;display:block}
.ttl{color:#fff;font-size:1.05rem;font-weight:700}.ttl span{color:#8d8d99;font-size:.8rem;margin-left:.4rem;font-weight:500}
.fl-h{color:#fff;font-size:1.1rem;font-weight:700;margin-bottom:.4rem}.fl-h small{color:#8d8d99;font-weight:400;margin-left:.5rem;font-size:.85rem}
div[data-testid=stMetric]{background:#1e1927;border-radius:12px;padding:.5rem .8rem}
div[data-testid=stMetric] label p{color:#a9a6b5!important}div[data-testid=stMetricValue]{color:#fff}
</style>""", unsafe_allow_html=True)

# ───────────────────────── 無洩漏 Walk-Forward 量化引擎函式 ─────────────────────────
def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))

def _logit_fit(Z, y, w, lam, iters=8):
    n, d = Z.shape
    X = np.hstack([np.ones((n, 1)), Z])
    b = np.zeros(d + 1)
    R = np.eye(d + 1) * lam
    R[0, 0] = 1e-4
    for _ in range(iters):
        p = _sigmoid(X @ b)
        s = np.clip(p * (1 - p), 1e-4, None) * w
        g = X.T @ (w * (p - y)) + R @ b
        H = X.T @ (s[:, None] * X) + R
        b = b - np.linalg.solve(H, g)
    return b

def _pred(b, z):
    return float(_sigmoid(b[0] + z @ b[1:]))

def prep(df, feature_cols):
    X = np.nan_to_num(df[feature_cols].values.astype(float), nan=0.0, posinf=0.0, neginf=0.0)
    gap = (df["Open"].values.astype(float) > df["PrevClose"].values.astype(float)).astype(float)
    intra = (df["Close"].values.astype(float) >= df["Open"].values.astype(float)).astype(float)
    sidx = np.where(gap == 1, np.where(intra == 1, 0, 1), np.where(intra == 1, 2, 3))
    return X, gap, intra, sidx

def _train_slice(t):
    return max(0, t - MAX_TRAIN), t

def state_probs(pg, pu, pd_):
    p = np.array([pg * pu, pg * (1 - pu), (1 - pg) * pd_, (1 - pg) * (1 - pd_)])
    return p / p.sum()

def fit_predict(X, gap, intra, t, cols, lam, hl):
    lo, hi = _train_slice(t)
    Xtr = X[lo:hi][:, cols]
    mu = Xtr.mean(0)
    sd = Xtr.std(0)
    sd[sd < 1e-6] = 1.0
    Z = np.clip((Xtr - mu) / sd, -4, 4)
    z = np.clip((X[t, cols] - mu) / sd, -4, 4)
    n = len(Z)
    w = np.exp((np.arange(n) - n) / hl)
    w = w / w.mean()
    g, it = gap[lo:hi], intra[lo:hi]

    pg = _pred(_logit_fit(Z, g, w, lam), z)
    def sub(mask):
        if mask.sum() >= 40 and 0 < it[mask].mean() < 1:
            ws = w[mask] / w[mask].mean()
            return _pred(_logit_fit(Z[mask], it[mask], ws, lam * 3), z)
        return _pred(_logit_fit(Z, it, w, lam * 3), z)
    pu, pd_ = sub(g == 1), sub(g == 0)
    c = lambda v: float(min(0.97, max(0.03, v)))
    return c(pg), c(pu), c(pd_), mu, sd

def fit_predict_detail(X, gap, intra, t, cols, lam, hl):
    lo, hi = _train_slice(t)
    Xtr = X[lo:hi][:, cols]
    mu = Xtr.mean(0)
    sd = Xtr.std(0)
    sd[sd < 1e-6] = 1.0
    Z = np.clip((Xtr - mu) / sd, -4, 4)
    z = np.clip((X[t, cols] - mu) / sd, -4, 4)
    n = len(Z)
    w = np.exp((np.arange(n) - n) / hl)
    w = w / w.mean()
    g, it = gap[lo:hi], intra[lo:hi]

    bg = _logit_fit(Z, g, w, lam)
    pg = _pred(bg, z)

    def sub_fit(mask):
        if mask.sum() >= 40 and 0 < it[mask].mean() < 1:
            ws = w[mask] / w[mask].mean()
            b_sub = _logit_fit(Z[mask], it[mask], ws, lam * 3)
            return _pred(b_sub, z), b_sub
        b_all = _logit_fit(Z, it, w, lam * 3)
        return _pred(b_all, z), b_all

    pu, bu = sub_fit(g == 1)
    pd_, bd = sub_fit(g == 0)
    c = lambda v: float(min(0.97, max(0.03, v)))
    pg_c, pu_c, pd_c = c(pg), c(pu), c(pd_)
    return state_probs(pg_c, pu_c, pd_c), (pg_c, pu_c, pd_c), z, (bg, bu, bd)

def predict_state(X, gap, intra, t, cols, lam, hl):
    pg, pu, pd_, mu, sd = fit_predict(X, gap, intra, t, cols, lam, hl)
    return state_probs(pg, pu, pd_), (pg, pu, pd_), (mu, sd)

def baseline_state(sidx, t):
    lo, hi = _train_slice(t)
    return int(np.bincount(sidx[lo:hi], minlength=4).argmax())

def tune(X, gap, intra, sidx, end, cols, span=60):
    idxs = [t for t in range(max(MIN_TRAIN, end - span), end)]
    if not idxs: return GRID[2]
    best, best_ll = GRID[2], -1e9
    for lam, hl in GRID:
        ll = 0.0
        for t in idxs:
            p, _, _ = predict_state(X, gap, intra, t, cols, lam, hl)
            ll += math.log(max(p[sidx[t]], 1e-6))
        ll /= len(idxs)
        if ll > best_ll:
            best, best_ll = (lam, hl), ll
    return best

def binom_p(hits, n, p0):
    p0 = min(max(p0, 0.05), 0.95)
    return float(sum(math.comb(n, k) * p0 ** k * (1 - p0) ** (n - k) for k in range(hits, n + 1)))

def evaluate(X, gap, intra, sidx, idxs, cols, lam, hl):
    idxs = [t for t in idxs if t >= MIN_TRAIN]
    n = len(idxs)
    if n == 0:
        return dict(n=0, hit=0, base=0, gap=0, intra=0, p=1.0, rows=[])
    hit = base = gh = ih = 0
    rows = []
    for t in idxs:
        p, (pg, pu, pd_), _ = predict_state(X, gap, intra, t, cols, lam, hl)
        top = int(p.argmax())
        b = baseline_state(sidx, t)
        hit += top == sidx[t]
        base += b == sidx[t]
        gh += (pg >= 0.5) == (gap[t] == 1)
        pi = pu if pg >= 0.5 else pd_
        ih += (pi >= 0.5) == (intra[t] == 1)
        rows.append(dict(t=t, top=top, probs=p, pg=pg, pu=pu, pd=pd_, base_st=b, actual=int(sidx[t])))
    return dict(n=n, hit=int(hit), base=int(base), gap=int(gh), intra=int(ih),
                p=binom_p(int(hit), n, max(base / n, 0.25)), rows=rows)

def _top_feature_drivers(z, b, sub_cols, top_k=2):
    contribs = z * b[1:]
    pairs = [(FEAT_NAMES.get(FEATURE_COLS[sub_cols[i]], FEATURE_COLS[sub_cols[i]]), float(contribs[i]), float(z[i])) for i in range(len(sub_cols))]
    pos = sorted([p for p in pairs if p[1] > 0], key=lambda x: x[1], reverse=True)[:top_k]
    neg = sorted([p for p in pairs if p[1] < 0], key=lambda x: x[1])[:top_k]
    return pos, neg

# ───────────────────────── 基礎資料與休市日模組 ─────────────────────────
def _clean(d):
    if d is None or d.empty: return pd.DataFrame()
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    d = d[~d.index.duplicated()]
    return d.dropna(subset=["Close"])

def _parse_num(val):
    if val is None: return None
    s = str(val).strip().replace(",", "").replace("%", "").replace("+", "")
    if not s or s in ("-", "--", "N/A", "None"): return None
    try: return float(s)
    except Exception: return None

@st.cache_data(ttl=300, show_spinner=False)
def load_daily(sym, period="3y"):
    return _clean(yf.download(sym, period=period, interval="1d", auto_adjust=False, progress=False))

@st.cache_data(ttl=60, show_spinner=False)
def load_intraday():
    d = _clean(yf.download(INDEX_TICKER, period="5d", interval="1m", progress=False))
    if d.empty: return d
    d.index = d.index.tz_convert(TZ)
    return d[d.index.date == d.index[-1].date()]

@st.cache_data(ttl=60, show_spinner=False)
def load_5m_all(sym):
    d = _clean(yf.download(sym, period="60d", interval="5m", progress=False))
    if d.empty: return d
    d.index = d.index.tz_convert(TZ)
    return d

def load_5m_today(sym):
    d = load_5m_all(sym)
    if d.empty: return d
    return d[d.index.date == d.index[-1].date()]

@st.cache_data(ttl=900, show_spinner=False)
def twse_day(ymd):
    try:
        r = requests.get("https://www.twse.com.tw/rwd/zh/fund/BFI82U", timeout=8,
                         params={"dayDate": ymd, "type": "day", "response": "json"},
                         headers={"User-Agent": "Mozilla/5.0"}).json()
        time.sleep(0.25)
        if r.get("stat") != "OK": return None
        t = {row[0]: int(row[3].replace(",", "")) for row in r["data"]}
        f = lambda k: sum(v for n, v in t.items() if n.startswith(k))
        return {"外資": f("外資"), "投信": f("投信"), "自營": f("自營商"), "ymd": ymd}
    except Exception:
        return None

@st.cache_data(ttl=900, show_spinner=False)
def last_15_flows():
    out, d = [], datetime.now(TZ)
    for _ in range(38):
        if len(out) == 15: break
        if d.weekday() < 5:
            x = twse_day(d.strftime("%Y%m%d"))
            if x:
                x["d"] = d.strftime("%m/%d")
                x["dt"] = d.date()
                out.append(x)
        d = d - pd.Timedelta(days=1)
    return out[::-1]

def last_10_flows():
    return last_15_flows()[-10:]

@st.cache_data(ttl=86400, show_spinner=False)
def tw_holidays():
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule", timeout=8)
        if r.status_code != 200: raise ValueError("API Error")
        out = {}
        for row in r.json():
            name = str(row.get("Name", ""))
            desc = str(row.get("Description", ""))
            if "開始交易" in name or "最後交易" in name or "開始交易" in desc or "最後交易" in desc: continue
            d_str = str(row.get("Date", "")).strip().replace("-", "").replace("/", "")
            if len(d_str) == 8 and d_str.isdigit():
                y, m, d = int(d_str[:4]), int(d_str[4:6]), int(d_str[6:8])
                out[date(y, m, d)] = name or desc or "國定休市日"
        return out
    except Exception:
        raise ValueError("Fetch failed")

def is_tw_trading_day(d):
    if d.weekday() >= 5: return False, "週末休市"
    try:
        hol = tw_holidays()
        if d in hol: return False, f"國定休市（{hol[d]}）"
    except Exception:
        pass
    return True, "正常交易日"

def future_trading_days(after, k):
    hol, ok = {}, True
    try: hol = tw_holidays()
    except Exception: ok = False
    days, skipped, d = [], {}, after
    while len(days) < k:
        d += timedelta(days=1)
        if d.weekday() >= 5: continue
        if d in hol:
            skipped[d] = hol[d]
            continue
        days.append(d)
    return days, skipped, ok

WD = "一二三四五六日"
def fmt_d(d): return f"{d:%m/%d}（週{WD[d.weekday()]}）"

# ───────────────────────── 圖表與 UI 切換模組 (TradingView) ─────────────────────────
LW = '<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>'
BASE = LW + (
    '<style>html,body{margin:0;background:#000;font-family:-apple-system,"Noto Sans TC","Microsoft JhengHei",sans-serif}'
    '#w{position:relative}#cv{position:absolute;left:0;top:0;pointer-events:none}'
    '#lg{position:absolute;left:12px;top:8px;z-index:5;font-size:12px;line-height:1.6;color:#cfcfd8;pointer-events:none;text-shadow:0 0 5px #000}'
    '</style><div id="w"><div id="c"></div><canvas id="cv"></canvas><div id="lg"></div></div><script>'
    'const UP="#ff4d5a",DN="#22c55e",H=__H__,el=document.getElementById("c"),lg=document.getElementById("lg"),D=__DATA__;'
    'const pad=n=>String(n).padStart(2,"0"),f2=x=>x.toLocaleString("en",{minimumFractionDigits:2,maximumFractionDigits:2});'
    'const big=v=>v>=1e8?(v/1e8).toFixed(1)+"億":v>=1e4?(v/1e4).toFixed(0)+"萬":v;'
    'const mk=o=>LightweightCharts.createChart(el,Object.assign({width:el.clientWidth,height:H,'
    'layout:{background:{color:"#000"},textColor:"#9a9aa6",fontSize:11},'
    'localization:{dateFormat:"yyyy/MM/dd"},'
    'grid:{vertLines:{color:"rgba(255,255,255,.04)"},horzLines:{color:"rgba(255,255,255,.04)"}},'
    'crosshair:{mode:0,vertLine:{style:2,width:1,color:"rgba(255,255,255,.4)",labelBackgroundColor:"#3b3b46"},'
    'horzLine:{style:2,width:1,color:"rgba(255,255,255,.4)",labelBackgroundColor:"#3b3b46"}},'
    'rightPriceScale:{borderColor:"#1f1f26"}},o));'
    'const tkey=t=>typeof t==="string"?t:(t&&t.year?t.year+"-"+pad(t.month)+"-"+pad(t.day):t);'
    'let chart;addEventListener("resize",()=>{chart.applyOptions({width:el.clientWidth});window.redraw&&redraw()});'
)

DAILY_JS = (
    'chart=mk({timeScale:{borderColor:"#1f1f26",rightOffset:3}});const n=D.k.length;'
    'const cs=chart.addCandlestickSeries({upColor:UP,downColor:DN,borderUpColor:UP,borderDownColor:DN,wickUpColor:UP,wickDownColor:DN});'
    'cs.setData(D.k);cs.priceScale().applyOptions({scaleMargins:{top:.1,bottom:.22}});'
    'const vs=chart.addHistogramSeries({priceFormat:{type:"volume"},priceScaleId:"v",lastValueVisible:false,priceLineVisible:false});'
    'vs.setData(D.k.map((b,i)=>({time:b.time,value:D.v[i],color:b.close>=b.open?"rgba(255,77,90,.55)":"rgba(34,197,94,.55)"})));'
    'chart.priceScale("v").applyOptions({scaleMargins:{top:.82,bottom:0}});'
    'const C={5:"#fbbf24",10:"#60a5fa",20:"#c084fc",60:"#34d399",240:"#f472b6"};'
    'for(const p in C){const s=chart.addLineSeries({color:C[p],lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});'
    's.setData(D.k.map((b,i)=>({time:b.time,value:D.m[p][i]})).filter(x=>x.value!=null))}'
    'chart.timeScale().setVisibleLogicalRange({from:n-35,to:n+2});'
    'const idx={};D.k.forEach((b,i)=>idx[b.time]=i);'
    'function show(t){const i=(t in idx)?idx[t]:n-1,b=D.k[i],p=i?D.k[i-1].close:b.open,ch=b.close-p,pc=ch/p*100,c=ch>=0?UP:DN,s=ch>=0?"+":"";'
    'lg.innerHTML=`<b style="color:#fff">${b.time.replace(/-/g,"/")}</b> 開 ${f2(b.open)} 高 ${f2(b.high)} 低 ${f2(b.low)} 收 <b style="color:${c}">${f2(b.close)}</b> <span style="color:${c}">${s}${f2(ch)} (${s}${pc.toFixed(2)}%)</span> 量 ${big(D.v[i])}<br>`+'
    'Object.keys(C).map(k=>`<span style="color:${C[k]}">MA${k} ${D.m[k][i]==null?"--":f2(D.m[k][i])}</span>`).join(" ")}'
    'chart.subscribeCrosshairMove(q=>show(tkey(q.time)));show();</script>'
)

INTRA_JS = (
    'chart=mk({handleScroll:false,handleScale:false,timeScale:{visible:false,fixLeftEdge:true,fixRightEdge:true},'
    'rightPriceScale:{borderColor:"#1f1f26",scaleMargins:{top:.1,bottom:.12}}});'
    'const s=chart.addBaselineSeries({baseValue:{type:"price",price:0},topLineColor:UP,topFillColor1:"rgba(255,77,90,.38)",topFillColor2:"rgba(255,77,90,.03)",'
    'bottomLineColor:DN,bottomFillColor1:"rgba(34,197,94,.03)",bottomFillColor2:"rgba(34,197,94,.38)",lineWidth:2,priceLineVisible:false,'
    'priceFormat:{type:"custom",minMove:__MM__,formatter:v=>(v>0?"+":"")+v.toFixed(__DEC__)},'
    'autoscaleInfoProvider:o=>{const r=o(),m=r?Math.max(Math.abs(r.priceRange.minValue),Math.abs(r.priceRange.maxValue),__FLOOR__):__FLOOR__*2.5;return{priceRange:{minValue:-m,maxValue:m}}}});'
    'const have={};D.pts.forEach(p=>have[p[0]]=p);'
    's.setData(D.all.map(t=>have[t]?{time:t,value:have[t][1]}:{time:t}));'
    's.createPriceLine({price:0,color:"rgba(255,255,255,.6)",lineWidth:1,lineStyle:2,axisLabelVisible:true,title:"昨收 "+f2(D.prev)});'
    'chart.timeScale().fitContent();'
    'const cv=document.getElementById("cv"),dpr=window.devicePixelRatio||1;'
    'function redraw(){const w=el.clientWidth;cv.width=w*dpr;cv.height=H*dpr;cv.style.width=w+"px";cv.style.height=H+"px";'
    'const g=cv.getContext("2d");g.scale(dpr,dpr);g.font="11px sans-serif";g.textAlign="center";'
    'D.grid.forEach(t=>{const x=chart.timeScale().timeToCoordinate(t);if(x==null)return;const hr=t%3600===0,d=new Date(t*1000);'
    'g.strokeStyle=hr?"rgba(255,255,255,.30)":"rgba(255,255,255,.10)";g.lineWidth=hr?1.8:.8;g.beginPath();g.moveTo(x,0);g.lineTo(x,H-20);g.stroke();'
    'g.fillStyle=hr?"#cfcfd8":"#7d7d8a";g.fillText(pad(d.getUTCHours())+":"+pad(d.getUTCMinutes()),x,H-5)})}'
    'chart.timeScale().subscribeVisibleLogicalRangeChange(redraw);setTimeout(redraw,80);setTimeout(redraw,400);'
    'function show(t){const p=have[t]||D.pts[D.pts.length-1];if(!p){lg.textContent="尚無資料";return}'
    'const ch=p[1],pc=ch/D.prev*100,c=ch>=0?UP:DN,s=ch>=0?"+":"",d=new Date(p[0]*1000);'
    'lg.innerHTML=`<b style="color:#fff">${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}</b> 價格 <b style="color:${c}">${f2(p[2])}</b> <span style="color:${c}">${s}${f2(ch)} (${s}${pc.toFixed(2)}%)</span> 昨收 ${f2(D.prev)}`}'
    'chart.subscribeCrosshairMove(q=>show(q.time));show();</script>'
)

def daily_html(df, h=390, n=130):
    d = df.copy()
    if "Volume" not in d: d["Volume"] = 0
    for p in (5, 10, 20, 60, 240): d[f"MA{p}"] = d.Close.rolling(p).mean()
    d = d.tail(n)
    k = [dict(time=i.strftime("%Y-%m-%d"), open=round(float(r.Open), 2), high=round(float(r.High), 2),
              low=round(float(r.Low), 2), close=round(float(r.Close), 2)) for i, r in d.iterrows()]
    m = {p: [None if pd.isna(x) else round(float(x), 2) for x in d[f"MA{p}"]] for p in (5, 10, 20, 60, 240)}
    data = dict(k=k, v=[int(x) if pd.notna(x) else 0 for x in d.Volume], m=m)
    return (BASE + DAILY_JS).replace("__H__", str(h)).replace("__DATA__", json.dumps(data))

def intraday_html(d, prev, h=390, step=60, floor=20, dec=0, mm=1):
    off = 8 * 3600
    base = int(d.index[-1].normalize().timestamp()) + off
    pts = [[int(t.timestamp()) + off, round(float(c) - prev, 4), round(float(c), 2)] for t, c in d.Close.items()]
    allt = [base + 9 * 3600 + k * step for k in range(270 * 60 // step + 1)]
    data = dict(pts=pts, prev=float(prev), all=allt, grid=[t for t in allt if (t - base) % 1800 == 0])
    js = INTRA_JS.replace("__FLOOR__", str(floor)).replace("__DEC__", str(dec)).replace("__MM__", str(mm))
    return (BASE + js).replace("__H__", str(h)).replace("__DATA__", json.dumps(data))

def pick(label, opts, key):
    return st.segmented_control(label, opts, default=opts[0], key=key, label_visibility="collapsed") or opts[0]

def prev_close(daily, d):
    dts = pd.DatetimeIndex(daily.index).tz_localize(None).date
    sub = daily.Close[dts < d.index[-1].date()]
    return float(sub.iloc[-1]) if not sub.empty else float(daily.Close.iloc[-1])

# ───────────────────────── 頁面一：大盤 (三大法人互動式方框) ─────────────────────────
def _bar(a, mx, up):
    ok = (a >= 0) == up
    return f"<i style='height:{abs(a) / mx * 100:.0f}%;background:{UP if up else DN}'></i>" if ok else ""

def _col(a):
    return UP if a >= 0 else DN

FL_HEAD = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{margin:0;background:transparent;color:#e8e6ee;font-family:-apple-system,"Noto Sans TC","Microsoft JhengHei",sans-serif;overflow:hidden}
.fl-h{color:#fff;font-size:.95rem;font-weight:700;margin-bottom:.3rem}
.fl-h small{color:#8d8d99;font-weight:400;margin-left:.5rem}
.fl{display:grid;grid-template-columns:50px 130px 1fr 240px;gap:20px;align-items:center;padding:6px 0;border-top:1px solid #2a2433}
.fl .nm{font-weight:700;color:#fff}
.fl .lt{font-size:1.15rem;font-weight:800}
.fl .sm{font-size:1rem;color:#a9a6b5}
.fl .sm .row{display:flex;gap:25px;white-space:nowrap}
.fl .sm b{font-weight:700;font-size:1.05rem}
.bars{display:grid;grid-template-columns:repeat(10,1fr);gap:5px;height:42px}
.bars>div{display:flex;flex-direction:column;cursor:pointer;border-radius:3px}
.bars>div.hi{background:rgba(255,255,255,.10)}
.bars .u,.bars .d{flex:1;display:flex}
.bars .u{align-items:flex-end}.bars .d{align-items:flex-start}
.bars i{display:block;width:100%;border-radius:2px}
.dates{display:grid;grid-template-columns:repeat(10,1fr);gap:5px;color:#7d7a8a;font-size:.68rem;text-align:center}
.dates div{cursor:pointer;border-radius:3px}.dates div.hi{color:#fff;background:rgba(255,255,255,.10)}
</style></head><body>
<div class="fl-h">近 10 日三大法人買賣超<small>上市 · 億元 · 紅＝買超 綠＝賣超（游標移到長條或日期上，左側數值會顯示該日資料）</small></div>
<div class="fl" style="border:0;padding-bottom:2px">
  <div></div>
  <div class="lt" id="dlab" style="font-size:.8rem;color:#9a97a8">最新 當日買賣超</div>
  <div></div>
  <div class="sm"><div class="row" style="font-size:.75rem;color:#7d7a8a"><div style="width:95px">近 5 日累積</div><div style="width:95px">近 10 日累積</div></div></div>
</div>
"""

FL_JS = """
<script>
const flowData=__DATA__, lastIdx=flowData.length-1;
function updateFlow(i,hl){
  const d=flowData[i]; if(!d) return;
  ['外資','投信','自營'].forEach(k=>{
    const e=document.getElementById('val_'+k);
    if(e){e.innerText=d[k];e.style.color=d[k+'c'];}
  });
  document.getElementById('dlab').innerText=(hl?d.d:'最新 '+d.d)+' 當日買賣超';
  document.querySelectorAll('[data-i]').forEach(e=>e.classList.toggle('hi',hl&&Number(e.dataset.i)===i));
}
function resetFlow(){updateFlow(lastIdx,false);}
document.querySelectorAll('[data-i]').forEach(e=>{
  e.addEventListener('mouseenter',()=>updateFlow(Number(e.dataset.i),true));
});
document.querySelectorAll('.bars,.dates').forEach(e=>e.addEventListener('mouseleave',resetFlow));
resetFlow();
</script></body></html>
"""

def flows_html(days):
    raw = []
    for x in days:
        f, t, z = x["外資"] / 1e8, x["投信"] / 1e8, x["自營"] / 1e8
        raw.append({"d": x["d"],
                    "外資": f"{f:+,.1f}億", "外資c": _col(f),
                    "投信": f"{t:+,.1f}億", "投信c": _col(t),
                    "自營": f"{z:+,.1f}億", "自營c": _col(z)})
    rows = ""
    for k in ("外資", "投信", "自營"):
        v = [x[k] / 1e8 for x in days]
        mx = max(abs(a) for a in v) or 1
        bars = "".join(f"<div data-i='{i}'><div class='u'>{_bar(a, mx, True)}</div><div class='d'>{_bar(a, mx, False)}</div></div>"
                       for i, a in enumerate(v))
        s5, s10 = sum(v[-5:]), sum(v)
        rows += (f"<div class='fl'><div class='nm'>{k}</div>"
                 f"<div class='lt' id='val_{k}' style='color:{_col(v[-1])}'>{v[-1]:+,.1f}億</div>"
                 f"<div class='bars'>{bars}</div>"
                 f"<div class='sm'><div class='row'><div style='width:95px'><b style='color:{_col(s5)}'>{s5:+,.1f}億</b></div>"
                 f"<div style='width:95px'><b style='color:{_col(s10)}'>{s10:+,.1f}億</b></div></div></div></div>")
    dates = "".join(f"<div data-i='{i}'>{x['d']}</div>" for i, x in enumerate(days))
    rows += f"<div class='fl' style='border:0;padding-top:0'><div></div><div></div><div class='dates'>{dates}</div><div></div></div>"
    return FL_HEAD + rows + FL_JS.replace("__DATA__", json.dumps(raw))

def market_page():
    daily = load_daily(INDEX_TICKER)
    with st.container(key="chart_card"):
        l, r = st.columns([5, 2], vertical_alignment="center")
        l.markdown(f"<div class='ttl'>加權指數<span>{INDEX_TICKER}</span></div>", unsafe_allow_html=True)
        with r:
            tf = pick("週期", ["分時圖", "日線圖"], "tf")
        if tf == "分時圖":
            d = load_intraday()
            if d.empty or daily.empty:
                st.warning("目前抓不到分時資料(可能休市或 Yahoo 暫時無回應)。")
            else:
                components.html(intraday_html(d, prev_close(daily, d), h=390), height=400)
        elif daily.empty:
            st.warning("日線資料載入失敗。")
        else:
            components.html(daily_html(daily, h=390), height=400)

    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
    with st.container(key="flow_card"):
        with st.spinner("讀取證交所三大法人…"):
            days = last_10_flows()
        if days:
            components.html(flows_html(days), height=215, scrolling=False)
        else:
            st.warning("目前無法取得證交所三大法人資料。")

# ───────────────────────── 頁面二：策略 B (00631L.TW) ─────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def strategy_data():
    df = load_daily(SYM, "3y").copy()
    df5 = load_5m_all(SYM)
    intra = {}
    if not df5.empty:
        for dt, g in df5.groupby(df5.index.date):
            intra[dt] = [(float(o), float(h), float(l), float(c)) for o, h, l, c in zip(g.Open, g.High, g.Low, g.Close)]
        if not df.empty:
            last_idx = df.index[-1]
            g = df5[df5.index.date == last_idx.date()]
            if not g.empty:
                df.loc[last_idx, "High"] = max(df.loc[last_idx, "Open"], df.loc[last_idx, "Close"], g["High"].max())
                df.loc[last_idx, "Low"] = min(df.loc[last_idx, "Open"], df.loc[last_idx, "Close"], g["Low"].min())
                df.loc[last_idx, "Close"] = g["Close"].iloc[-1]
                df.loc[last_idx, "Volume"] = max(df.loc[last_idx, "Volume"], g["Volume"].sum())
    return df, intra

def simulate(df, intra, em, xm, sl, tp1, sl1, cool):
    d = df.copy()
    for p in (5, 10, 240): d[f"m{p}"] = d.Close.rolling(p).mean()
    O, Hh, L, C = d["Open"].values, d["High"].values, d["Low"].values, d["Close"].values
    M5, M10, M240 = d["m5"].values, d["m10"].values, d["m240"].values
    dates = [x.date() for x in d.index]
    pos, ep, reg, ei, last, tr = 0, 0., 0, 0, -9999, []

    def lines(ep, reg, m5):
        return (ep * (1 - sl1), ep * (1 + tp1)) if reg == 1 else (max(ep * (1 - sl), m5 * xm), None)

    def close(i, xp, why):
        nonlocal pos, last
        tr.append(dict(進場日=d.index[ei].date(), 進場價=round(ep, 2), 出場日=d.index[i].date(), 出場價=round(xp, 2),
                       報酬率=f"{(xp / ep - 1) * 100 - 0.4:+.2f}%", 原因=why, K棒="5分K" if dates[i] in intra else "日K"))
        pos, last = 0, i

    for i in range(241, len(d)):
        m5, m10, m240 = M5[i-1], M10[i-1], M240[i-1]
        m5b, m10b = M5[i-2], M10[i-2]
        bars = intra.get(dates[i]) or [(O[i], Hh[i], L[i], C[i])]
        for j, (bo, bh, bl, bc) in enumerate(bars):
            if pos:
                ln, tp = lines(ep, reg, m5)
                if bo <= ln or (tp and bo >= tp): close(i, bo, "跳空出場")
                elif bl <= ln: close(i, ln, "弱勢停損" if reg == 1 else "停損" if ep * (1 - sl) >= m5 * xm else "跌破均線")
                elif tp and bh >= tp: close(i, tp, "弱勢停利")
            elif i - last > cool:
                ent, r = None, 0
                if m5 < m240:
                    if j == 0 and m5 > m10 and m5b <= m10b: ent, r = bo, 1
                else:
                    lv = m5 * em
                    if bo >= lv: ent, r = bo, 2
                    elif bh >= lv: ent, r = lv, 2
                if ent:
                    pos, ep, reg, ei = 1, ent, r, i
                    ln, tp = lines(ep, reg, m5)
                    if (bl <= ln) if ent == bo else (bc <= ln): close(i, ln, "當日停損")
    N = len(d)
    return dict(pos=pos, ep=ep, reg=reg, since=d.index[ei].date() if pos else None,
                cd=max(0, cool + 1 - (N - last)) if last > 0 else 0,
                m5=M5[-1], m10=M10[-1], m240=M240[-1], m5b=M5[-2], m10b=M10[-2], trades=tr)

def entry_plan(df, s, em, xm, sl, tp1, sl1):
    c = df.Close.values
    last = float(c[-1])
    if s["m5"] < s["m240"]:
        hit = s["m5"] > s["m10"] and s["m5b"] <= s["m10b"]
        if hit:
            ent, how = last, f"5MA 已上穿 10MA，明日開盤進場（以最新價 {last:,.2f} 估算）"
        elif s["m5b"] > s["m10b"]:
            return None, None, None, "5MA 已在 10MA 之上，需先回落到 10MA 下方、再重新上穿才會有進場訊號"
        else:
            trig = float(c[-10:-1].sum() - 2 * c[-5:-1].sum())
            ent, how = trig, f"收盤價需站上 {trig:,.2f}，5MA 才會上穿 10MA，隔日開盤進場（此價為估算進場價）"
        return ent, ent * (1 - sl1), ent * (1 + tp1), how
    ent = s["m5"] * em
    return ent, max(ent * (1 - sl), s["m5"] * xm), None, f"盤中價 ≥ {ent:,.2f}（5MA {s['m5']:,.2f} × {em}）即進場"

def strategy_page():
    with st.container(key="strat_card"):
        st.markdown("<div class='fl-h'>策略 B：狀態與訊號<small>00631L · 進出場以 5 分 K 時序精準判定（避免開高走低／開低走高的假訊號）</small></div>",
                    unsafe_allow_html=True)
        with st.spinner("同步歷史資料…"): df, intra = strategy_data()
        if len(df) < 245: st.error("歷史資料不足 245 根，無法計算 240MA。"); return
        if not intra: st.warning("抓不到 5 分 K，回測退回日 K 判斷。")
        with st.expander("策略參數"):
            c = st.columns(6)
            em = c[0].number_input("強勢進場乘數", value=1.04, step=0.01)
            xm = c[1].number_input("強勢出場乘數", value=0.98, step=0.01)
            sl = c[2].number_input("強勢停損 %", value=3.0, step=0.5) / 100
            tp1 = c[3].number_input("弱勢停利 %", value=20.0, step=1.0) / 100
            sl1 = c[4].number_input("弱勢停損 %", value=3.0, step=0.5) / 100
            cool = int(c[5].number_input("冷卻交易日", value=5, step=1))
        s = simulate(df, intra, em, xm, sl, tp1, sl1, cool)
        weak = s["m5"] < s["m240"]
        last = float(df.Close.iloc[-1])
        m = st.columns(4)
        m[0].metric("最新價", f"{last:,.2f}", f"{(last / df.Close.iloc[-2] - 1) * 100:+.2f}%")
        m[1].metric("區間", "弱勢 (5MA<240MA)" if weak else "強勢 (5MA≥240MA)")
        m[2].metric("5MA / 10MA", f"{s['m5']:,.1f} / {s['m10']:,.1f}")
        m[3].metric("240MA", f"{s['m240']:,.1f}")

        if s["pos"]:
            ln, tp = (s["ep"] * (1 - sl1), s["ep"] * (1 + tp1)) if s["reg"] == 1 else (max(s["ep"] * (1 - sl), s["m5"] * xm), None)
            st.info(f"🟢 模擬持有中（{'弱勢' if s['reg'] == 1 else '強勢'}單，{s['since']} 進場）")
            k = st.columns(3)
            k[0].metric("持有成本", f"{s['ep']:,.2f}", f"{(last / s['ep'] - 1) * 100:+.2f}%")
            k[1].metric("出場線（停損）", f"{ln:,.2f}", f"{(ln / s['ep'] - 1) * 100:+.2f}%")
            k[2].metric("停利價", f"{tp:,.2f}" if tp else "—", f"{(tp / s['ep'] - 1) * 100:+.2f}%" if tp else None)
        else:
            ent, stop, tp, how = entry_plan(df, s, em, xm, sl, tp1, sl1)
            if s["cd"]:
                days, skipped, ok = future_trading_days(df.index[-1].date(), s["cd"] + 1)
                msg = (f"⏳ 冷卻中，還需 {s['cd']} 個交易日｜冷卻結束：{fmt_d(days[s['cd'] - 1])} "
                       f"最早可再進場：{fmt_d(days[s['cd']])}（冷卻結束後參考下列價位）")
                if skipped: msg += "\n\n已排除休市日：" + "、".join(f"{fmt_d(k)} {v}" for k, v in skipped.items())
                if not ok: msg += "\n\n⚠️ 無法連接證交所 OpenAPI 獲取休假資料，目前只排除週末，遇到國定假日請自行順延。"
                st.info(msg)
            else: st.info(f"⚪ 空手：{how}")
            if ent:
                if s["cd"]: st.caption(how)
                k = st.columns(3)
                k[0].metric("合理進場價", f"{ent:,.2f}", f"{(ent / last - 1) * 100:+.2f}% vs 現價", delta_color="off")
                k[1].metric("停損／出場價", f"{stop:,.2f}", f"{(stop / ent - 1) * 100:+.2f}%", delta_color="off")
                k[2].metric("停利價", f"{tp:,.2f}" if tp else "—（強勢單無固定停利，跌破出場線即出）",
                            f"{(tp / ent - 1) * 100:+.2f}%" if tp else None, delta_color="off")

    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
    with st.container(key="chart_card_s"):
        l, r = st.columns([5, 2], vertical_alignment="center")
        l.markdown(f"<div class='ttl'>00631L<span>{SYM}</span></div>", unsafe_allow_html=True)
        with r:
            tf = pick("週期", ["分時圖", "日線圖"], "tf2")
        if tf == "分時圖":
            d = load_5m_today(SYM)
            if d.empty: st.warning("目前抓不到 5 分 K 分時資料(可能休市或 Yahoo 暫時無回應)。")
            else: components.html(intraday_html(d, prev_close(df, d), h=390, step=300, floor=0.5, dec=2, mm=0.01), height=400)
        else:
            components.html(daily_html(df, h=390), height=400)
    if s["trades"]:
        st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
        with st.container(key="trade_card"):
            st.markdown("<div class='fl-h'>最近 5 筆模擬交易</div>", unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(s["trades"][-5:][::-1]), hide_index=True, use_container_width=True)

# ───────────────────────── 頁面三：5 大盤前資料源與委員會早會系統 ─────────────────────────
def _gnews_url(query):
    return f"https://www.google.com/search?q={urllib.parse.quote(query)}&tbm=nws"

@st.cache_data(ttl=180, show_spinner=False)
def fetch_taifex_night_session():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Content-Type": "application/json;charset=UTF-8",
        "Referer": "https://mis.taifex.com.tw/futures/AfterHoursSession/IndexFutures/"
    }
    try:
        payload = {"MarketType": "1", "SymbolType": "F", "KindID": "1", "CID": "TXF", "ExpireMonth": "", "RowSize": "全部", "PageNo": "", "SortColumn": "", "AscDesc": "A"}
        r = requests.post("https://mis.taifex.com.tw/futures/api/getQuoteList", json=payload, headers=headers, timeout=6)
        if r.status_code == 200:
            quotes = r.json().get("RtData", {}).get("QuoteList", [])
            for q in quotes:
                sid, cname = str(q.get("SymbolID", "")), str(q.get("DispCName", ""))
                if "/" in sid or "總計" in cname: continue
                last_p, diff_p, diff_r, vol = _parse_num(q.get("CLastPrice")), _parse_num(q.get("CDiff")), _parse_num(q.get("CDiffRate")), _parse_num(q.get("CTotalVolume"))
                if last_p is not None and last_p > 0:
                    return {
                        "ok": True, "source": "期交所 MIS", "contract": cname or sid,
                        "close": last_p, "diff": diff_p or 0.0, "pct": diff_r or 0.0,
                        "high": _parse_num(q.get("CHighPrice")) or last_p,
                        "low": _parse_num(q.get("CLowPrice")) or last_p,
                        "vol": int(vol) if vol else 0, "time": str(q.get("CTime", "")),
                        "label": f"{last_p:,.0f} 點 ({diff_p or 0:+.0f} / {diff_r or 0:+.2f}%)"
                    }
    except Exception:
        pass
    try:
        r2 = requests.get("https://openapi.taifex.com.tw/v1/DailyMarketReportFut", headers={"User-Agent": "Mozilla/5.0"}, timeout=7)
        if r2.status_code == 200:
            tx_after = [
                x for x in r2.json()
                if str(x.get("Contract", "")).strip() == "TX"
                and ("盤後" in str(x.get("TradingSession", "")) or "After" in str(x.get("TradingSession", "")))
                and "/" not in str(x.get("ContractMonth(Week)", ""))
            ]
            if tx_after:
                q = tx_after[0]
                last_p, diff_p, vol = _parse_num(q.get("Last")), _parse_num(q.get("Change")), _parse_num(q.get("Volume"))
                if last_p is not None and last_p > 0:
                    pct = (diff_p / (last_p - diff_p) * 100.0) if diff_p is not None and (last_p - diff_p) != 0 else 0.0
                    return {
                        "ok": True, "source": "期交所 OpenAPI",
                        "contract": f"臺指期 {q.get('ContractMonth(Week)', '')}",
                        "close": last_p, "diff": diff_p or 0.0, "pct": pct,
                        "high": _parse_num(q.get("High")) or last_p,
                        "low": _parse_num(q.get("Low")) or last_p,
                        "vol": int(vol) if vol else 0, "time": str(q.get("Date", "05:00 收盤")),
                        "label": f"{last_p:,.0f} 點 ({diff_p or 0:+.0f} / {pct:+.2f}%)"
                    }
    except Exception:
        pass
    return {"ok": False, "source": "未取得", "label": "未取得"}

@st.cache_data(ttl=600, show_spinner=False)
def fetch_taifex_oi_and_pcr():
    res = {
        "fx_oi_ok": False, "fx_net_oi": None, "fx_net_chg": None, "fx_date": "", "fx_label": "未取得",
        "pcr_ok": False, "pcr_oi_ratio": None, "pcr_vol_ratio": None, "pcr_date": "", "pcr_label": "未取得"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r_pcr = requests.get("https://openapi.taifex.com.tw/v1/PutCallRatio", headers=headers, timeout=7)
        if r_pcr.status_code == 200 and isinstance(r_pcr.json(), list) and len(r_pcr.json()) > 0:
            last_row = r_pcr.json()[-1]
            oi_r = _parse_num(last_row.get("PutCallOpenInterestRatio") or last_row.get("PutCallRatio"))
            vol_r = _parse_num(last_row.get("PutCallVolumeRatio"))
            if oi_r is not None:
                res.update({
                    "pcr_ok": True, "pcr_oi_ratio": oi_r, "pcr_vol_ratio": vol_r,
                    "pcr_date": str(last_row.get("Date", "")),
                    "pcr_label": f"{oi_r:.2f}%" + (f" (量比 {vol_r:.2f}%)" if vol_r else "")
                })
    except Exception:
        pass
    if not res["pcr_ok"]:
        try:
            r_csv = requests.get("https://www.taifex.com.tw/cht/3/pcRatioDown", headers=headers, timeout=7)
            if r_csv.status_code == 200:
                lines = [ln.strip() for ln in r_csv.content.decode("cp950", errors="ignore").splitlines() if ln.strip() and ln[0].isdigit()]
                if lines and len(lines[0].split(",")) >= 7:
                    cols = lines[0].split(",")
                    oi_r, vol_r = _parse_num(cols[6]), _parse_num(cols[3])
                    if oi_r is not None:
                        res.update({"pcr_ok": True, "pcr_oi_ratio": oi_r, "pcr_vol_ratio": vol_r, "pcr_date": cols[0], "pcr_label": f"{oi_r:.2f}% (量比 {vol_r:.2f}%)"})
        except Exception:
            pass
    try:
        r_oi = requests.get("https://openapi.taifex.com.tw/v1/MarketDataOfMajorInstitutionalTradersFuturesBytheDate", headers=headers, timeout=7)
        if r_oi.status_code == 200 and isinstance(r_oi.json(), list):
            for row in reversed(r_oi.json()):
                c_name = str(row.get("ContractCode", "") or row.get("商品名稱", "") or row.get("契約名稱", "")).strip()
                t_type = str(row.get("IdentityType", "") or row.get("身份別", "")).strip()
                if ("臺股期貨" in c_name or c_name == "TX") and "外資" in t_type:
                    net_oi = _parse_num(row.get("NetOpenInterestVolume") or row.get("OpenInterestNetVolume") or row.get("多空未平倉口數淨額"))
                    net_trd = _parse_num(row.get("NetTradingVolume") or row.get("DifferenceInOpenInterestVolume") or row.get("多空交易口數淨額"))
                    if net_oi is not None:
                        res.update({
                            "fx_oi_ok": True, "fx_net_oi": int(net_oi),
                            "fx_net_chg": int(net_trd) if net_trd is not None else None,
                            "fx_date": str(row.get("Date", "")),
                            "fx_label": f"{int(net_oi):+,d} 口" + (f" (變動 {int(net_trd):+,d} 口)" if net_trd is not None else "")
                        })
                        break
    except Exception:
        pass
    if not res["fx_oi_ok"]:
        try:
            r_fcsv = requests.get("https://www.taifex.com.tw/cht/3/futContractsDateDown", headers=headers, timeout=7)
            if r_fcsv.status_code == 200:
                txt = r_fcsv.content.decode("cp950", errors="ignore")
                for cols in csv.reader(io.StringIO(txt)):
                    if len(cols) >= 14 and "臺股期貨" in cols[1] and "外資" in cols[2]:
                        net_trd, net_oi = _parse_num(cols[7]), _parse_num(cols[13])
                        if net_oi is not None:
                            res.update({
                                "fx_oi_ok": True, "fx_net_oi": int(net_oi),
                                "fx_net_chg": int(net_trd) if net_trd is not None else None,
                                "fx_date": cols[0],
                                "fx_label": f"{int(net_oi):+,d} 口" + (f" (變動 {int(net_trd):+,d} 口)" if net_trd is not None else "")
                            })
                            break
        except Exception:
            pass
    return res

@st.cache_data(ttl=300, show_spinner=False)
def fetch_00631l_nav_premium():
    try:
        r = requests.get("https://mis.twse.com.tw/stock/data/all_etf.txt", headers={"User-Agent": "Mozilla/5.0"}, timeout=7)
        if r.status_code == 200:
            for group in r.json().get("a1", []):
                for msg in group.get("msgArray", []):
                    if str(msg.get("a", "")).strip() == "00631L":
                        mkt_p, nav_p, prem_pct, prev_nav = _parse_num(msg.get("e")), _parse_num(msg.get("f")), _parse_num(msg.get("g")), _parse_num(msg.get("h"))
                        if nav_p is not None and nav_p > 0:
                            if prem_pct is None and mkt_p is not None: prem_pct = (mkt_p / nav_p - 1.0) * 100.0
                            return {
                                "ok": True, "source": "證交所 MIS", "price": mkt_p, "nav": nav_p,
                                "prev_nav": prev_nav, "prem_pct": prem_pct or 0.0,
                                "time": f"{msg.get('i', '')} {msg.get('j', '')}".strip(),
                                "label": f"淨值 {nav_p:,.2f} 元｜折溢價 {prem_pct or 0.0:+.2f}%"
                            }
    except Exception:
        pass
    return {"ok": False, "source": "未取得", "label": "未取得"}

@st.cache_data(ttl=900, show_spinner=False)
def fetch_whitelist_news():
    def _is_blacklisted(u, t, s): return any(b in f"{u} {t} {s}".lower() for b in NEWS_BLACKLIST)
    collected, seen = [], set()
    for src in NEWS_WHITELIST:
        dom, lang = src["domain"], src["lang"]
        q_str = f"site:{dom} (台股 OR 台積電 OR 費半 OR 輝達 OR 聯準會 OR 外資) when:{NEWS_DAYS}d" if lang == "zh" else f"site:{dom} (TSMC OR NVIDIA OR semiconductor OR Fed OR Taiwan) when:{NEWS_DAYS}d"
        rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q_str)}&hl={'zh-TW' if lang=='zh' else 'en-US'}&gl={'TW' if lang=='zh' else 'US'}"
        try:
            r = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            if r.status_code != 200: continue
            root = ET.fromstring(r.content)
            cnt = 0
            for item in root.findall(".//item"):
                if cnt >= NEWS_PER_SOURCE: break
                raw_t, link, desc, pub, src_el = item.find("title"), item.find("link"), item.find("description"), item.find("pubDate"), item.find("source")
                title = re.sub(r"\s*-\s*[^-]+$", "", raw_t.text if raw_t is not None else "").strip()
                if not title or len(title) < 8 or title in seen or _is_blacklisted(link.text if link is not None else "", title, src_el.attrib.get("url", "") if src_el is not None else ""): continue
                clean_desc = re.sub(r"\s+", " ", re.sub(r"&[a-zA-Z0-9#]+;", " ", re.sub(r"<[^>]+>", " ", desc.text if desc is not None and desc.text else ""))).strip()
                rem_txt = clean_desc.replace(title, "").replace(src["name"], "").strip()
                has_body = len(rem_txt) > 25
                seen.add(title)
                cnt += 1
                collected.append({
                    "source": src["name"], "domain": dom, "title": title,
                    "url": link.text if link is not None else "",
                    "pub": (pub.text if pub is not None else "")[:16],
                    "has_body": has_body,
                    "snippet": rem_txt[:140] if has_body else "（此來源僅提供標題，無內文摘要）"
                })
        except Exception:
            continue
    return collected

@st.cache_data(ttl=1200, show_spinner=False)
def build_master_feature_table():
    tw = load_daily(INDEX_TICKER, "3y").copy()
    sox = load_daily("^SOX", "3y").copy()
    tsm = load_daily("TSM", "3y").copy()
    nvda = load_daily("NVDA", "3y").copy()
    sp = load_daily("^GSPC", "3y").copy()
    vix = load_daily("^VIX", "3y").copy()
    tnx = load_daily("^TNX", "3y").copy()
    fx = load_daily("USDTWD=X", "3y").copy()
    s2330 = load_daily("2330.TW", "3y").copy()

    if tw.empty or len(tw) < 200: return pd.DataFrame()

    tw["date"] = pd.DatetimeIndex(tw.index).tz_localize(None).date
    tw["PrevClose"] = tw["Close"].shift(1)
    tw["PrevOpen"] = tw["Open"].shift(1)
    tw["PrevHigh"] = tw["High"].shift(1)
    tw["PrevLow"] = tw["Low"].shift(1)
    tw["PrevHL"] = (tw["PrevHigh"] - tw["PrevLow"]).fillna(0.0)

    tw["tw_prev_pct"] = (tw["PrevClose"] / tw["Close"].shift(2) - 1.0) * 100.0
    tw["prev_intra"] = (tw["PrevClose"] / tw["PrevOpen"] - 1.0) * 100.0
    hl_range = (tw["PrevHigh"] - tw["PrevLow"]).replace(0, np.nan)
    tw["prev_clv"] = (((tw["PrevClose"] - tw["PrevLow"]) / hl_range - 0.5) * 2.0).fillna(0.0)
    tw["prev_hl_pct"] = (hl_range / tw["PrevClose"] * 100.0).fillna(1.0)

    body_top = np.maximum(tw["PrevOpen"], tw["PrevClose"])
    body_bot = np.minimum(tw["PrevOpen"], tw["PrevClose"])
    tw["wick_diff"] = ((tw["PrevHigh"] - body_top) - (body_bot - tw["PrevLow"])) / tw["PrevClose"] * 100.0

    for p in (5, 10, 20):
        ma_prev = tw["Close"].rolling(p).mean().shift(1)
        tw[f"ma{p}_prev"] = ma_prev
        tw[f"bias{p}"] = (tw["PrevClose"] / ma_prev - 1.0) * 100.0

    tw["ma5_slope"] = (tw["ma5_prev"] / tw["Close"].rolling(5).mean().shift(2) - 1.0) * 100.0
    delta_c = tw["Close"].shift(1).diff()
    gain = delta_c.clip(lower=0).rolling(5).mean()
    loss = (-delta_c.clip(upper=0)).rolling(5).mean().replace(0, 1e-4)
    tw["rsi5_z"] = (((100.0 - 100.0 / (1.0 + gain / loss)) - 50.0) / 25.0).fillna(0.0)

    def _align_us_series(us_df, mode="pct"):
        if us_df is None or us_df.empty: return pd.Series(0.0, index=tw.index)
        idx_dates = pd.DatetimeIndex(us_df.index).tz_localize(None).date
        s_raw = pd.Series(us_df["Close"].pct_change().values * 100.0, index=idx_dates) if mode == "pct" else pd.Series(us_df["Close"].values, index=idx_dates)
        s_raw = s_raw[~s_raw.index.duplicated(keep="last")]
        mapped = []
        for d_tw in tw["date"]:
            val = 0.0
            for offset in range(1, 6):
                d_us = d_tw - timedelta(days=offset)
                if d_us in s_raw and pd.notna(s_raw[d_us]):
                    val = float(s_raw[d_us])
                    break
            mapped.append(val)
        return pd.Series(mapped, index=tw.index)

    tw["sox_pct"] = _align_us_series(sox, "pct")
    tw["tsm_pct"] = _align_us_series(tsm, "pct")
    tw["nvda_pct"] = _align_us_series(nvda, "pct")
    tw["sp_pct"] = _align_us_series(sp, "pct")
    tw["vix_pct"] = _align_us_series(vix, "pct")
    tw["vix_close"] = _align_us_series(vix, "close")
    tw["tnx_close"] = _align_us_series(tnx, "close")
    tw["tnx_pct"] = _align_us_series(tnx, "pct")
    tw["fx_close"] = _align_us_series(fx, "close")
    tw["fx_pct"] = _align_us_series(fx, "pct")
    tw["tsm_close"] = _align_us_series(tsm, "close")

    if not s2330.empty:
        s2330_d = pd.Series(s2330["Close"].values, index=pd.DatetimeIndex(s2330.index).tz_localize(None).date)
        s2330_d = s2330_d[~s2330_d.index.duplicated(keep="last")]
        c2330_prev = []
        for d_tw in tw["date"]:
            v2330 = np.nan
            for off in range(1, 6):
                d_p = d_tw - timedelta(days=off)
                if d_p in s2330_d and pd.notna(s2330_d[d_p]):
                    v2330 = float(s2330_d[d_p])
                    break
            c2330_prev.append(v2330)
        tw["c2330_prev"] = c2330_prev
        tw["adr_prem"] = (((tw["tsm_close"] * tw["fx_close"] / 5.0) / tw["c2330_prev"] - 1.0) * 100.0).fillna(15.0)
    else:
        tw["adr_prem"] = 15.0

    tw["us_tech_avg"] = 0.5 * tw["tsm_pct"] + 0.5 * tw["sox_pct"]
    tw["lead_lag"] = tw["us_tech_avg"] - 0.65 * tw["tw_prev_pct"]
    tw["tsm_x_bias5"] = tw["tsm_pct"] * tw["bias5"]
    tw["sox_x_clv"] = tw["sox_pct"] * tw["prev_clv"]
    tw["gap_reversal_risk"] = tw["us_tech_avg"] * np.maximum(0.0, tw["bias5"])

    tw["ActualGapPct"] = (tw["Open"] / tw["PrevClose"] - 1.0) * 100.0
    tw["ActualIntraPct"] = (tw["Close"] / tw["Open"] - 1.0) * 100.0
    tw["ActualDayPct"] = (tw["Close"] / tw["PrevClose"] - 1.0) * 100.0

    return tw.dropna(subset=["PrevClose", "ma20_prev", "Open", "Close"]).copy().reset_index(drop=True)

@st.cache_data(ttl=1200, show_spinner=False)
def run_walk_forward_system():
    df = build_master_feature_table()
    if df.empty or len(df) <= MIN_TRAIN + 15: return None
    X, gap, intra, sidx = prep(df, FEATURE_COLS)
    df["ActualState"] = [FOUR_STATES[i] for i in sidx]
    N = len(df)
    w2_mask = (df["date"] >= date(2026, 11, 9)) & (df["date"] <= date(2026, 11, 13))
    w1_mask = (df["date"] >= date(2026, 11, 2)) & (df["date"] <= date(2026, 11, 6))
    w2_indices = [int(i) for i in np.where(w2_mask)[0] if i >= MIN_TRAIN]
    w1_indices = [int(i) for i in np.where(w1_mask)[0] if i >= MIN_TRAIN]
    if len(w2_indices) < 3: w2_indices = list(range(max(MIN_TRAIN, N - 5), N))
    if len(w1_indices) < 3:
        end_w1 = w2_indices[0] if w2_indices else N - 5
        w1_indices = list(range(max(MIN_TRAIN, end_w1 - 5), end_w1))
    tune_end = min(w1_indices[0] if w1_indices else N - 10, N - 10)
    cols_all = list(range(len(FEATURE_COLS)))
    master_lam, master_hl = tune(X, gap, intra, sidx, tune_end, cols_all, span=60)
    agent_params = {}
    for ag in AI_AGENTS:
        aid = ag["id"]
        sub_cols = [FEATURE_COLS.index(c) for c in AGENT_SUBSPACES[aid]]
        ag_lam, ag_hl = tune(X, gap, intra, sidx, tune_end, sub_cols, span=60)
        agent_params[aid] = {"cols": sub_cols, "lam": ag_lam, "hl": ag_hl}
    oos60_start = max(MIN_TRAIN, N - 60)
    oos60_idxs = list(range(oos60_start, N))
    lam60, hl60 = tune(X, gap, intra, sidx, oos60_start, cols_all, span=50)
    eval_60 = evaluate(X, gap, intra, sidx, oos60_idxs, cols_all, lam60, hl60)
    eval_w1 = evaluate(X, gap, intra, sidx, w1_indices, cols_all, master_lam, master_hl)
    eval_w2 = evaluate(X, gap, intra, sidx, w2_indices, cols_all, master_lam, master_hl)
    return {
        "df": df, "X": X, "gap": gap, "intra": intra, "sidx": sidx,
        "cols_all": cols_all, "master_lam": master_lam, "master_hl": master_hl,
        "agent_params": agent_params, "w1_indices": w1_indices, "w2_indices": w2_indices,
        "eval_60": eval_60, "eval_w1": eval_w1, "eval_w2": eval_w2
    }

def _try_call_openai_committee(agent, prompt):
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        try: api_key = str(st.secrets.get("OPENAI_API_KEY", "")).strip()
        except Exception: api_key = ""
    if not api_key: return None, None
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": agent["model_id"], "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3},
            timeout=16
        )
        if resp.status_code == 200:
            r = resp.json()
            return json.loads(r["choices"][0]["message"]["content"]), r.get("model", agent["model_id"])
    except Exception:
        pass
    return None, None

def build_committee_speeches(wf_sys, t_idx, flow_info, headlines, night_info, oi_pcr_info, nav_info):
    df, X, gap, intra = wf_sys["df"], wf_sys["X"], wf_sys["gap"], wf_sys["intra"]
    row = df.iloc[t_idx]
    lo, hi = _train_slice(t_idx)
    tw_close, tw_pct = float(row["PrevClose"]), float(row["tw_prev_pct"])
    tw_ma5, tw_ma10, tw_ma20 = float(row["ma5_prev"]), float(row["ma10_prev"]), float(row["ma20_prev"])
    bias_5ma, bias_20ma = float(row["bias5"]), float(row["bias20"])
    sox_pct, tsm_pct, nvda_pct, sp_pct = float(row["sox_pct"]), float(row["tsm_pct"]), float(row["nvda_pct"]), float(row["sp_pct"])
    fx_close, tnx_close, adr_prem = float(row["fx_close"]), float(row["tnx_close"]), float(row["adr_prem"])
    f_net, t_net, z_net = flow_info["f1"], flow_info["t1"], flow_info["z1"]
    n_total_news = len(headlines)
    n_body_news = sum(1 for h in headlines if h.get("has_body"))
    n_title_only = n_total_news - n_body_news

    speeches = []
    for idx, ag in enumerate(AI_AGENTS):
        aid = ag["id"]
        cfg = wf_sys["agent_params"][aid]
        sub_cols, lam, hl = cfg["cols"], cfg["lam"], cfg["hl"]
        p_arr, (pg, pu, pd_), z_t, (bg, bu, bd) = fit_predict_detail(X, gap, intra, t_idx, sub_cols, lam, hl)
        probs = {FOUR_STATES[i]: round(float(p_arr[i]) * 100.0, 1) for i in range(4)}
        top_idx = int(p_arr.argmax())
        v_state = FOUR_STATES[top_idx]
        conf = int(min(95, max(52, round(probs[v_state] * 1.4 + 15))))
        pos_g, neg_g = _top_feature_drivers(z_t, bg, sub_cols, top_k=2)
        b_intra = bu if pg >= 0.5 else bd
        pos_i, neg_i = _top_feature_drivers(z_t, b_intra, sub_cols, top_k=2)
        pos_str = "、".join(f"{n}(貢獻{cv:+.2f})" for n, cv, _ in pos_g + pos_i) or "常數基準項"
        neg_str = "、".join(f"{n}(貢獻{cv:+.2f})" for n, cv, _ in neg_g + neg_i) or "無顯著壓抑"

        if aid == "technical":
            evs = [
                {"title": f"【技術面事實卡】昨收 {tw_close:,.2f} ({tw_pct:+.2f}%)｜5MA {tw_ma5:,.2f} (乖離 {bias_5ma:+.2f}%)｜20MA {tw_ma20:,.2f}", "url": _gnews_url("台股 加權指數 均線 技術分析"), "dev": f"不談新聞，僅看價格結構：前日收盤強弱指標 CLV 為 {float(row['prev_clv']):+.2f}，前日高低振幅 {float(row['prev_hl_pct']):.2f}%，5MA 斜率 {float(row['ma5_slope']):+.2f}%。", "imp": f"條件式關鍵價位：上方短壓/多空分水嶺看 5MA ({tw_ma5:,.0f})，波段支撐看 10MA ({tw_ma10:,.0f})。台指期夜盤狀態：{night_info['label']}。"},
                {"title": f"【純技術 Walk-Forward 機率】P(跳空開高)={pg*100:.1f}% ｜ P(收≥開|高)={pu*100:.1f}% ｜ P(收≥開|低)={pd_*100:.1f}%", "url": _gnews_url("00631L 均線 突破 策略"), "dev": f"僅使用 [{lo}, {hi}) 歷史價格與均線特徵訓練（λ={lam:g}, hl={hl:g}），正向技術動能：{pos_str}；負向技術阻力：{neg_str}。", "imp": f"00631L 進出場條件嚴格綁定 5 分 K 站穩 5MA×1.04 強勢線或跌破 5MA×0.98 出場線，技術面四態最高機率為「{v_state}（{probs[v_state]:.1f}%）」。"}
            ]
            news_v = f"【純技術趨勢與價位（不談新聞）】指數與 5MA 乖離 {bias_5ma:+.2f}%、與 20MA 乖離 {bias_20ma:+.2f}%，5 日標準化 RSI 位階為 {float(row['rsi5_z']):+.2f}。"
            chip_v = f"【期貨與價差事實卡】台指期夜盤：{night_info['label']}｜外資台指期未平倉：{oi_pcr_info['fx_label']}｜選擇權 P/C Ratio：{oi_pcr_info['pcr_label']}。"
            reason_txt = f"不引用任何新聞，純依均線位階、前日 CLV ({float(row['prev_clv']):+.2f}) 與三階段條件機率分解，判定今日最可能走勢為【{v_state}】（機率 {probs[v_state]:.1f}%）。"
        elif aid == "news":
            top_news = headlines[:2]
            evs = []
            for h in top_news:
                evs.append({"title": f"【白名單：{h['source']}】{h['title']}", "url": h["url"], "dev": f"來源網域：{h['domain']}（{h['pub']}）｜內文狀態：{h['snippet']}", "imp": f"配合隔夜費半 {sox_pct:+.2f}%、TSM ADR {tsm_pct:+.2f}%（溢價 {adr_prem:+.2f}%）、S&P 500 {sp_pct:+.2f}%，傳導至今日開盤跳空機率 P(開高)={pg*100:.1f}%。"})
            if not evs:
                evs.append({"title": "【資訊不足聲明】目前白名單新聞源未抓到足夠標題", "url": _gnews_url("台股 美股 費城半導體"), "dev": "白名單過濾器目前無符合條件之新聞，嚴格遵守委員會規範明說「新聞標題資訊不足」，僅依隔夜美股收盤數字定價。", "imp": f"隔夜費半 {sox_pct:+.2f}%、TSM {tsm_pct:+.2f}%、10Y美債 {tnx_close:.2f}%、台幣 {fx_close:.2f}。"})
            limit_note = f"（⚠️ 誠實聲明：本次白名單共抓到 {n_total_news} 則新聞，其中 {n_title_only} 則因轉址或付費牆僅有標題無本文，資訊深度受限，不宜過度延伸）" if n_title_only > 0 or n_total_news < 3 else f"（本次白名單共檢索 {n_total_news} 則新聞，已排除 PTT/Dcard 等黑名單農場）"
            news_v = f"【白名單新聞與國際總經】{limit_note} 隔夜費半 {sox_pct:+.2f}%、TSM {tsm_pct:+.2f}%、NVDA {nvda_pct:+.2f}%、S&P {sp_pct:+.2f}%。"
            chip_v = f"【跨國資金面】外資現貨昨 {f_net:+.1f} 億（5日 {flow_info['f5']:+.1f} 億）、投信昨 {t_net:+.1f} 億（5日 {flow_info['t5']:+.1f} 億），台幣匯率 {fx_close:.2f}。"
            reason_txt = f"綜合白名單新聞標題與隔夜美股資金面傳導（{limit_note}），消息面模型評估今日以【{v_state}】（{probs[v_state]:.1f}%）機率最高。"
        elif aid == "risk":
            evs = [
                {"title": f"【00631L 槓桿耗損與折溢價檢核】{nav_info['label']}｜VIX 恐慌指數 {float(row['vix_close']):.2f} ({float(row['vix_pct']):+.2f}%)", "url": _gnews_url("00631L 折溢價 淨值 槓桿耗損"), "dev": f"00631L 最新淨值狀態：{nav_info['label']}。兩倍槓桿 ETF 具有每日重設特性，在反覆震盪盤中會產生波動率耗損（Volatility Drag）。", "imp": f"若 00631L 溢價過大（>0.5%）時於早盤追高，一旦盤中轉為走低，將同時承受「指數回檔 × 2 倍槓桿 + 溢價收斂」雙重傷害。"},
                {"title": f"【最壞情境與停損防線】5MA 乖離 {bias_5ma:+.2f}%｜20MA 乖離 {bias_20ma:+.2f}%｜高檔反轉風險 {float(row['gap_reversal_risk']):+.2f}", "url": _gnews_url("台股 乖離過大 停損 風險控管"), "dev": f"站在最壞情境檢視：今日出現「開高走低」機率為 {probs['開高走低']:.1f}%、「開低走低」機率為 {probs['開低走低']:.1f}%（合計收黑K風險達 {probs['開高走低']+probs['開低走低']:.1f}%）。", "imp": f"負向壓抑因子：{neg_str}。進場前必須先確認第二頁「策略 B」之 3% 硬停損與 5MA×0.98 出場線位置。"}
            ]
            news_v = f"【最壞情境波動檢核】VIX 位於 {float(row['vix_close']):.2f}，前日台股高低振幅 {float(row['prev_hl_pct']):.2f}%，5MA 乖離 {bias_5ma:+.2f}%。"
            chip_v = f"【00631L 再平衡耗損與避險】00631L 狀態：{nav_info['label']}｜外資期貨OI：{oi_pcr_info['fx_label']}｜自營商 5 日累積 {flow_info['z5']:+.1f} 億。"
            reason_txt = f"站在最壞情境，考量 00631L 兩倍槓桿震盪耗損、折溢價（{nav_info['label']}）與均線乖離風險，風控模型指向【{v_state}】（{probs[v_state]:.1f}%）。"
        else:
            evs = [
                {"title": f"【反方挑刺一：跨日基差與假突破陷阱】昨台股 {tw_pct:+.2f}% vs 隔夜費半 {sox_pct:+.2f}%、TSM {tsm_pct:+.2f}%", "url": _gnews_url("台股 利多出盡 開高走低 外資提款"), "dev": f"台美跨日領先落後基差為 {float(row['lead_lag']):+.2f}%。市場看到隔夜美股收紅就一面倒看多時，往往忽略台股前一日可能已經提前反應。", "imp": f"若現在貿然在 09:00 追價進場，最可能出錯的理由就是遭遇「開高走低（機率 {probs['開高走低']:.1f}%）」或假突破洗盤。"},
                {"title": f"【反方挑刺二：籌碼背離盲點】外資現貨昨 {f_net:+.1f} 億 vs 外資台指期未平倉 {oi_pcr_info['fx_label']}", "url": _gnews_url("外資 期貨空單 現貨買超 背離"), "dev": f"外資單日現貨買賣超 {f_net:+.1f} 億（10日累積 {flow_info['f10']:+.1f} 億），但期貨未平倉為 {oi_pcr_info['fx_label']}，選擇權 P/C Ratio 為 {oi_pcr_info['pcr_label']}。", "imp": f"反向檢核模型（λ={lam:g}, hl={hl:g}）顯示，扣除多頭同溫層偏誤後，最需防範的真實狀態為「{v_state}（{probs[v_state]:.1f}%）」。"}
            ]
            news_v = f"【現在進場最可能出錯的理由】隔夜美股漲跌在 09:00 開盤跳空瞬間就已定價完畢（P(開高)={pg*100:.1f}%），開盤後追價等於承擔別人隔夜獲利的風險。"
            chip_v = f"【籌碼背離盲點】外資 5 日現貨 {flow_info['f5']:+.1f} 億 vs 期貨未平倉 {oi_pcr_info['fx_label']}，前日上下影線差 {float(row['wick_diff']):+.2f}%。"
            reason_txt = f"專挑主流共識盲點：為避免在早盤情緒高點買單，反方模型經跨日基差與影線賣壓校準後，判定今日最可能出現的反轉或震盪狀態為【{v_state}】。"

        llm_prompt = (
            f"你是台股投研委員會的「{ag['name']}」，職責：{ag['role']}\n"
            f"無洩漏 Walk-Forward 模型算出：P(跳空開高)={pg*100:.1f}%，P(收>=開|高)={pu*100:.1f}%，P(收>=開|低)={pd_*100:.1f}%，四態機率：{json.dumps(probs, ensure_ascii=False)}，最高為「{v_state}」。\n"
            f"盤前事實：昨台股 {tw_pct:+.2f}% (5MA乖離 {bias_5ma:+.2f}%)，隔夜費半 {sox_pct:+.2f}%、TSM {tsm_pct:+.2f}%；夜盤：{night_info['label']}；外資期貨OI：{oi_pcr_info['fx_label']}；P/C比：{oi_pcr_info['pcr_label']}；00631L：{nav_info['label']}。\n"
            "請嚴格依你的角色職責回傳 JSON：{\"news_view\": \"60字內角色專屬視角分析\", \"chip_view\": \"60字內角色專屬籌碼/風控檢核\", \"reason\": \"80字內說明為何表態該四態與對00631L的具體建議\"}"
        )
        llm_json, actual_mod = _try_call_openai_committee(ag, llm_prompt)
        if llm_json and isinstance(llm_json.get("reason"), str) and len(llm_json["reason"]) > 10:
            news_v = llm_json.get("news_view") or news_v
            chip_v = llm_json.get("chip_view") or chip_v
            reason_txt = llm_json["reason"]
            engine_badge = f"🟢 OpenAI ({actual_mod}) + Walk-Forward"
        else:
            engine_badge = f"📐 Walk-Forward 脊邏輯斯 (λ={lam:g}, hl={hl:g})"

        speeches.append({**ag, "engine_badge": engine_badge, "events": evs, "news_view": news_v, "chip_view": chip_v, "reason": reason_txt, "vote": v_state, "probs": probs, "pg": pg, "pu": pu, "pd": pd_, "confidence": conf, "time": f"08:30:{12 + idx * 9:02d}"})
    return speeches

def build_chatroom_html(target_d, prev_d, trading_status_str, row, flow_info, night_info, oi_pcr_info, nav_info, headlines, speeches, master_probs, master_decomp, master_top, base_st_name, eval_60):
    tw_close = float(row["PrevClose"])
    tw_pct = float(row["tw_prev_pct"])
    tw_hl = float(row["PrevHL"])
    tw_ma5 = float(row["ma5_prev"])
    bias5 = float(row["bias5"])
    sox_pct = float(row["sox_pct"])
    tsm_pct = float(row["tsm_pct"])
    nvda_pct = float(row["nvda_pct"])
    sp_pct = float(row["sp_pct"])
    vix_close = float(row["vix_close"])
    fx_close = float(row["fx_close"])
    adr_prem = float(row["adr_prem"])
    f_net, t_net, z_net = flow_info["f1"], flow_info["t1"], flow_info["z1"]
    pg_m, pu_m, pd_m = master_decomp

    us_summary = (
        f"S&P 500 <b style='color:{_col(sp_pct)}'>{sp_pct:+.2f}%</b> ｜ "
        f"費城半導體 <b style='color:{_col(sox_pct)}'>{sox_pct:+.2f}%</b> ｜ "
        f"台積電 ADR <b style='color:{_col(tsm_pct)}'>{tsm_pct:+.2f}%</b>（換算溢價 <b>{adr_prem:+.2f}%</b>）｜ "
        f"NVIDIA <b style='color:{_col(nvda_pct)}'>{nvda_pct:+.2f}%</b> ｜ "
        f"VIX <b>{vix_close:.2f}</b> ｜ 台幣 <b>{fx_close:.2f}</b>"
    )

    cards_html = ""
    for ag in speeches:
        v_st = ag["vote"]
        s_meta = STATE_META[v_st]
        p = ag["probs"]
        p_bar = "".join(f"<div style='width:{max(p[k], 2)}%;background:{STATE_META[k]['col']}' title='{k}: {p[k]}%'></div>" for k in FOUR_STATES)
        p_labels = " ｜ ".join(f"<span style='color:{STATE_META[k]['col']}'><b>{k} {p[k]}%</b></span>" for k in FOUR_STATES)

        ev_items = ""
        for idx_e, e in enumerate(ag["events"][:2], 1):
            ev_items += (
                f"<div class='ev-card'>"
                f"<div class='ev-head'>"
                f"<span class='ev-num'>{idx_e}</span>"
                f"<a class='ev-link' href='{e['url']}' target='_blank' rel='noopener noreferrer'>{e['title']}<span class='ext-ico'>↗ 點擊檢視</span></a>"
                f"</div>"
                f"<div class='ev-detail'>"
                f"<div class='ev-row'><span class='tag-dev'>🔹 事實與數據</span><span>{e['dev']}</span></div>"
                f"<div class='ev-row'><span class='tag-imp'>🔸 傳導與影響</span><span>{e['imp']}</span></div>"
                f"</div></div>"
            )

        cards_html += (
            f"<div class='msg-row'>"
            f"<div class='avatar' style='background:{ag['color']}'>{ag['short']}</div>"
            f"<div class='bubble'>"
            f"<div class='b-head'>"
            f"<span class='b-name'>{ag['name']}</span>"
            f"<span class='b-role'>{ag['role']}</span>"
            f"<span class='eng-tag'>{ag['engine_badge']}</span>"
            f"<span class='v-badge' style='background:{s_meta['bg']};color:{s_meta['col']};border:1px solid {s_meta['col']}'>"
            f"{s_meta['icon']} 表態：{v_st} ({p[v_st]}%)</span>"
            f"<span class='b-time'>{target_d:%m/%d} {ag['time']}</span>"
            f"</div>"
            f"<div class='prob-box'>"
            f"🧩 <b>三階段分解：</b>P(跳空開高)=<b>{ag['pg']*100:.1f}%</b> ｜ P(收≥開|開高)=<b>{ag['pu']*100:.1f}%</b> ｜ P(收≥開|開低)=<b>{ag['pd']*100:.1f}%</b><br>"
            f"📊 <b>四態合成機率：</b>{p_labels}"
            f"<div class='mini-bar'>{p_bar}</div>"
            f"</div>"
            f"<div class='sec-title'>📌 委員專屬維度實證與傳導解析：</div>"
            f"<div class='ev-wrap'>{ev_items}</div>"
            f"<div class='think-grid'>"
            f"<div class='think-box'><b>🌍 角色視角定調：</b><br>{ag['news_view']}</div>"
            f"<div class='think-box'><b>💰 籌碼 / 風控檢核：</b><br>{ag['chip_view']}</div>"
            f"</div>"
            f"<div class='reason-box'><b>🎯 委員最終表態與操作建議：</b>{ag['reason']}</div>"
            f"</div></div>"
        )

    vote_counts = {k: sum(1 for a in speeches if a["vote"] == k) for k in FOUR_STATES}
    tally_str = " ｜ ".join(f"<b style='color:{STATE_META[k]['col']}'>{STATE_META[k]['icon']} {k} {vote_counts[k]} 票 (主模型 {master_probs[k]}%)</b>" for k in FOUR_STATES)
    tally_bar = "".join(f"<div style='width:{max(master_probs[k], 2)}%;background:{STATE_META[k]['col']}'></div>" for k in FOUR_STATES)
    win_meta = STATE_META[master_top]

    if master_top == "開高走高": action_guide = "早盤開高且盤中續攻機率高，00631L 可依策略 B 突破 5MA 乘數順勢做多。"
    elif master_top == "開高走低": action_guide = "⚠️ 提防「早盤開高後逢高出貨（收黑K）」！09:00~09:15 切勿盲目追高 00631L。"
    elif master_top == "開低走高": action_guide = "早盤開低但低接承接力道強（拉紅K下影線），切勿在開盤恐慌砍在低點。"
    else: action_guide = "⚠️ 容易出現開低走低黑K，請嚴格執行策略 B 停損紀律，空手建議觀望。"

    actual_st = row["ActualState"]
    act_gap = float(row["ActualGapPct"])
    act_intra = float(row["ActualIntraPct"])
    act_day = float(row["ActualDayPct"])
    is_hit = (actual_st == master_top)
    hit_badge = (
        "<span style='background:rgba(34,197,94,.22);color:#4ade80;border:1px solid #4ade80;padding:2px 10px;border-radius:99px;font-weight:800'>✅ 委員會共識命中實際狀態</span>"
        if is_hit else f"<span style='background:rgba(245,158,11,.22);color:#fbbf24;border:1px solid #fbbf24;padding:2px 10px;border-radius:99px;font-weight:800'>🔸 實際狀態為「{actual_st}」</span>"
    )

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{{margin:0;background:transparent;color:#e8e6ee;font-family:-apple-system,"Noto Sans TC","Microsoft JhengHei",sans-serif}}
.chat-room{{display:flex;flex-direction:column;gap:20px;padding:6px 6px 18px 6px}}
.msg-row{{display:flex;gap:14px;align-items:flex-start}}
.msg-row.host{{background:linear-gradient(90deg,rgba(255,200,61,.14),rgba(30,25,39,.95));border:1px solid rgba(255,200,61,.4);border-radius:16px;padding:16px 20px}}
.avatar{{width:48px;height:48px;border-radius:13px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:1.15rem;flex-shrink:0;color:#fff;box-shadow:0 4px 12px rgba(0,0,0,.35)}}
.bubble{{background:#1e1927;border:1px solid #322a44;border-radius:0 16px 16px 16px;padding:16px 20px;flex:1;line-height:1.7;font-size:1rem}}
.b-head{{display:flex;align-items:center;gap:12px;margin-bottom:10px;flex-wrap:wrap}}
.b-name{{font-weight:800;color:#fff;font-size:1.16rem}}
.b-role{{font-size:.84rem;color:#b0adc0;background:#2a2436;padding:3px 10px;border-radius:6px}}
.eng-tag{{font-size:.8rem;color:#c4b5fd;background:rgba(139,92,246,.16);border:1px solid rgba(139,92,246,.4);padding:2px 9px;border-radius:6px}}
.b-time{{font-size:.84rem;color:#8a8699;margin-left:auto}}
.v-badge{{padding:4px 13px;border-radius:99px;font-weight:800;font-size:.92rem;letter-spacing:.03em}}
.prob-box{{background:rgba(0,0,0,.28);border:1px solid #312942;border-radius:10px;padding:10px 14px;margin-bottom:12px;font-size:.92rem;line-height:1.65}}
.mini-bar{{display:flex;height:10px;border-radius:5px;overflow:hidden;background:#2a2433;margin-top:6px}}
.sec-title{{font-size:.98rem;color:#d0cce0;font-weight:700;margin:6px 0 10px 0}}
.ev-wrap{{display:flex;flex-direction:column;gap:10px;margin-bottom:14px}}
.ev-card{{background:rgba(0,0,0,.26);border:1px solid #312942;border-radius:11px;padding:11px 14px}}
.ev-head{{display:flex;align-items:baseline;gap:9px;margin-bottom:7px}}
.ev-num{{background:#3b3154;color:#ffc83d;font-weight:800;font-size:.85rem;padding:1px 8px;border-radius:6px;flex-shrink:0}}
.ev-link{{color:#fff;font-weight:700;font-size:1.04rem;text-decoration:none;border-bottom:1px dashed rgba(255,200,61,.55);padding-bottom:1px;transition:all .18s ease}}
.ev-link:hover{{color:#FFC83D;border-bottom:1px solid #FFC83D}}
.ext-ico{{font-size:.8rem;color:#a78bfa;margin-left:8px;font-weight:500}}
.ev-link:hover .ext-ico{{color:#FFC83D}}
.ev-detail{{display:flex;flex-direction:column;gap:5px;padding-left:4px;font-size:.96rem;color:#ddd9e8;line-height:1.65}}
.ev-row{{display:flex;align-items:flex-start;gap:8px}}
.tag-dev{{background:rgba(59,130,246,.18);color:#93c5fd;border:1px solid rgba(59,130,246,.4);font-size:.8rem;font-weight:700;padding:1px 7px;border-radius:5px;white-space:nowrap;margin-top:3px}}
.tag-imp{{background:rgba(244,114,182,.18);color:#f9a8d4;border:1px solid rgba(244,114,182,.4);font-size:.8rem;font-weight:700;padding:1px 7px;border-radius:5px;white-space:nowrap;margin-top:3px}}
.think-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}}
@media(max-width:768px){{.think-grid{{grid-template-columns:1fr}}}}
.think-box{{background:rgba(255,255,255,.045);border:1px solid #352e47;border-radius:10px;padding:11px 14px;font-size:.96rem;color:#ddd9e8;line-height:1.65}}
.think-box b{{color:#fff;font-size:.98rem}}
.reason-box{{background:rgba(124,92,255,.15);border-left:4px solid #8b5cf6;padding:12px 16px;border-radius:8px;font-size:1.03rem;color:#fff;line-height:1.68}}
.tally-bar{{display:flex;height:16px;border-radius:8px;overflow:hidden;background:#2a2433;margin:10px 0}}
</style></head><body>
<div class="chat-room">
  <div class="msg-row host">
    <div class="avatar" style="background:linear-gradient(135deg,#FFC83D,#d97706);color:#000">主</div>
    <div style="flex:1">
      <div class="b-head">
        <span class="b-name" style="color:#FFC83D">網站主持人（委員會盤前事實卡中控台）</span>
        <span class="b-role">{trading_status_str}</span>
        <span class="b-time">{target_d:%m/%d} 08:30:00</span>
      </div>
      <div style="font-size:1rem;line-height:1.75">
        各位委員會成員早安，現在是台北時間 <b>{target_d:%m/%d} 08:30</b>，開始今日台股（基準 <code>{INDEX_TICKER}</code>／操作標的 <code>{ETF_TICKER}</code>）盤前決策會議。<br>
        📊 <b>前日台股事實卡（{prev_d:%m/%d}）</b>：加權指數收 <b>{tw_close:,.2f}</b> 點（<b style="color:{_col(tw_pct)}">{tw_pct:+.2f}%</b>，振幅 {tw_hl:,.0f} 點），5MA 位於 <b>{tw_ma5:,.2f}</b>（乖離 <b>{bias5:+.2f}%</b>）。<br>
        🌙 <b>期交所夜盤 ＆ 期權籌碼</b>：台指期夜盤 <b>{night_info['label']}</b> ｜ 外資台指期未平倉 <b>{oi_pcr_info['fx_label']}</b> ｜ 選擇權 Put/Call 比 <b>{oi_pcr_info['pcr_label']}</b>。<br>
        🏷️ <b>00631L 淨值與折溢價</b>：<b>{nav_info['label']}</b> ｜ <b>白名單新聞檢索</b>：共 <b>{len(headlines)}</b> 則（已濾除論壇與內容農場黑名單）。<br>
        💰 <b>三大法人現貨（昨 / 5日 / 10日）</b>：外資 <b style="color:{_col(f_net)}">{f_net:+,.1f}億</b> ({flow_info['f5']:+.0f}億 / {flow_info['f10']:+.0f}億) ｜
        投信 <b style="color:{_col(t_net)}">{t_net:+,.1f}億</b> ({flow_info['t5']:+.0f}億 / {flow_info['t10']:+.0f}億) ｜ 自營商 <b style="color:{_col(z_net)}">{z_net:+,.1f}億</b>。<br>
        🌎 <b>隔夜美股關鍵指標</b>：{us_summary}。<br>
        請「技術面分析師」、「消息面分析師」、「風險控管官」與「反方辯士」依序獨立表態，最後由主持人整合！
      </div>
    </div>
  </div>
  {cards_html}
  <div class="msg-row host">
    <div class="avatar" style="background:linear-gradient(135deg,#FFC83D,#d97706);color:#000">結</div>
    <div style="flex:1">
      <div class="b-head">
        <span class="b-name" style="color:#FFC83D">網站主持人（委員會整合與 Walk-Forward 統計檢定）</span>
        <span class="b-role">近 60 日樣本外命中 {eval_60['hit']}/{eval_60['n']} vs 基準 {eval_60['base']}/{eval_60['n']} (二項檢定 p={eval_60['p']:.3f})</span>
        <span class="b-time">{target_d:%m/%d} 08:31:00</span>
      </div>
      <div style="font-size:1.02rem;line-height:1.75">
        感謝各位委員表態！今日（{fmt_d(target_d)}）委員會共識與三階段模型機率：<br>
        🧩 <b>主模型分解：P(跳空向上) = {pg_m*100:.1f}% ｜ P(收≥開|高) = {pu_m*100:.1f}% ｜ P(收≥開|低) = {pd_m*100:.1f}%</b><br>
        {tally_str}
        <div class="tally-bar">{tally_bar}</div>
        📢 <b>委員會最終整合決議：<span style="color:{win_meta['col']}">{win_meta['icon']} {master_top}（模型機率 {master_probs[master_top]}% ｜ 訓練期常態基準：{base_st_name}）</span></b><br>
        🎯 <b>00631L 槓桿操作指引</b>：{action_guide}
        <div style="margin-top:10px;padding:10px 14px;background:rgba(0,0,0,.35);border:1px solid #453a5c;border-radius:10px;font-size:.95rem">
          🏁 <b>【{target_d:%m/%d} 13:30 收盤真實結果對帳】</b> {hit_badge}<br>
          ‧ 實際開盤跳空：<b>{act_gap:+.2f}%</b> ｜ 實際盤中實體 (收vs開)：<b>{act_intra:+.2f}%</b> ｜ 全天漲跌：<b>{act_day:+.2f}%</b> ｜ 實際狀態：<b style="color:{STATE_META[actual_st]['col']}">{actual_st}</b>
        </div>
      </div>
    </div>
  </div>
</div>
</body></html>"""

def _eval_to_df(df, eval_res):
    rows = []
    for r in eval_res["rows"]:
        t = r["t"]
        row = df.iloc[t]
        p_top = FOUR_STATES[r["top"]]
        act_st = FOUR_STATES[r["actual"]]
        base_st = FOUR_STATES[r["base_st"]]
        rows.append({
            "日期": fmt_d(row["date"]),
            "隔夜費半/TSM": f"{row['sox_pct']:+.2f}% / {row['tsm_pct']:+.2f}%",
            "P(跳空向上)": f"{r['pg']*100:.1f}%",
            "P(收≥開|開高)": f"{r['pu']*100:.1f}%",
            "P(收≥開|開低)": f"{r['pd']*100:.1f}%",
            "Walk-Forward預測": f"{p_top} ({r['probs'][r['top']]*100:.1f}%)",
            "訓練期最常見基準": base_st,
            "實際跳空/盤中": f"{row['ActualGapPct']:+.2f}% / {row['ActualIntraPct']:+.2f}%",
            "實際四態": act_st,
            "命中": "✅" if r["top"] == r["actual"] else "❌"
        })
    return pd.DataFrame(rows)

def vote_page():
    today_d = datetime.now(TZ).date()
    is_open_today, hol_reason = is_tw_trading_day(today_d)

    with st.spinner("同步期交所夜盤、外資未平倉/PCR、00631L 淨值折溢價、白名單新聞與無洩漏 Walk-Forward 引擎…"):
        wf_sys = run_walk_forward_system()
        days_flow = last_15_flows()
        night_info = fetch_taifex_night_session()
        oi_pcr_info = fetch_taifex_oi_and_pcr()
        nav_info = fetch_00631l_nav_premium()
        headlines = fetch_whitelist_news()

    if not wf_sys:
        st.error("歷史樣本不足 150 筆，無法啟動無洩漏 Walk-Forward 引擎。")
        return

    df = wf_sys["df"]
    X, gap, intra, sidx = wf_sys["X"], wf_sys["gap"], wf_sys["intra"], wf_sys["sidx"]
    cols_all = wf_sys["cols_all"]
    lam, hl = wf_sys["master_lam"], wf_sys["master_hl"]
    w1_indices, w2_indices = wf_sys["w1_indices"], wf_sys["w2_indices"]
    eval_60, eval_w1, eval_w2 = wf_sys["eval_60"], wf_sys["eval_w1"], wf_sys["eval_w2"]

    sched_msg = (
        f"🟢 今日（{fmt_d(today_d)}）為正常交易日"
        if is_open_today else
        f"⏸️ 今日（{fmt_d(today_d)}）為【{hol_reason}】— 排程自動攔截休市日，目前顯示最近一交易日紀錄"
    )

    with st.container(key="vote_card"):
        st.markdown(
            f"<div class='fl-h'>🤖 盤前投研委員會早會聊天室 ＆ 無洩漏（Walk-Forward）四態中心"
            f"<small>{sched_msg} · 預設模型：{DEFAULT_OPENAI_MODEL}</small></div>",
            unsafe_allow_html=True
        )

        p_cols = st.columns(5)
        p_cols[0].metric("🌙 期交所台指期夜盤",
                         f"{night_info['close']:,.0f} 點" if night_info["ok"] else "未取得",
                         f"{night_info['diff']:+.0f} 點 ({night_info['pct']:+.2f}%)" if night_info["ok"] else night_info["source"])
        p_cols[1].metric("🏦 外資台指期淨未平倉",
                         f"{oi_pcr_info['fx_net_oi']:+,d} 口" if oi_pcr_info["fx_oi_ok"] else "未取得",
                         f"日變動 {oi_pcr_info['fx_net_chg']:+,d} 口" if (oi_pcr_info["fx_oi_ok"] and oi_pcr_info["fx_net_chg"] is not None) else oi_pcr_info["fx_date"] or "期交所 OpenAPI")
        p_cols[2].metric("⚖️ 臺指選擇權 Put/Call 比",
                         f"{oi_pcr_info['pcr_oi_ratio']:.2f}%" if oi_pcr_info["pcr_ok"] else "未取得",
                         f"成交量比 {oi_pcr_info['pcr_vol_ratio']:.2f}%" if (oi_pcr_info["pcr_ok"] and oi_pcr_info["pcr_vol_ratio"]) else oi_pcr_info["pcr_date"] or "期交所 OpenAPI")
        p_cols[3].metric("🏷️ 00631L 預估淨值 / 折溢價",
                         f"{nav_info['nav']:,.2f} 元" if nav_info["ok"] else "未取得",
                         f"折溢價 {nav_info['prem_pct']:+.2f}% (市價 {nav_info['price'] or '--'})" if nav_info["ok"] else "證交所 MIS")
        p_cols[4].metric("📰 白名單新聞過濾器",
                         f"{len(headlines)} 則合格",
                         f"含摘要 {sum(1 for h in headlines if h.get('has_body'))} 則 / 已濾黑名單")

        all_eval_indices = (w1_indices + w2_indices)[::-1]
        if not all_eval_indices:
            all_eval_indices = [len(df) - 1]
        opt_map = {f"{fmt_d(df.iloc[idx]['date'])} 08:30 早會場次": idx for idx in all_eval_indices}
        chosen_label = st.selectbox("📅 切換檢視早會場次（預設為最新交易日，可回放 11/02～11/13 任一日委員會決策與對帳）", list(opt_map.keys()), index=0)
        sel_idx = opt_map[chosen_label]

        sel_row = df.iloc[sel_idx]
        target_d = sel_row["date"]
        prev_d = df.iloc[sel_idx - 1]["date"] if sel_idx > 0 else (target_d - timedelta(days=1))

        p_arr, (pg_m, pu_m, pd_m), _ = predict_state(X, gap, intra, sel_idx, cols_all, lam, hl)
        master_probs = {FOUR_STATES[i]: round(float(p_arr[i]) * 100.0, 1) for i in range(4)}
        master_top = FOUR_STATES[int(p_arr.argmax())]
        base_st_name = FOUR_STATES[baseline_state(sidx, sel_idx)]

        sub_flows = [x for x in days_flow if x.get("dt") and x["dt"] < target_d] or days_flow
        if sub_flows:
            f_list = [x["外資"] / 1e8 for x in sub_flows]
            t_list = [x["投信"] / 1e8 for x in sub_flows]
            z_list = [x["自營"] / 1e8 for x in sub_flows]
            flow_info = {
                "f1": f_list[-1], "f5": sum(f_list[-5:]), "f10": sum(f_list[-10:]),
                "t1": t_list[-1], "t5": sum(t_list[-5:]), "t10": sum(t_list[-10:]),
                "z1": z_list[-1], "z5": sum(z_list[-5:]), "z10": sum(z_list[-10:]),
            }
        else:
            flow_info = {k: 0.0 for k in ("f1", "f5", "f10", "t1", "t5", "t10", "z1", "z5", "z10")}

        m = st.columns(6)
        m[0].metric("🔴 開高走高", f"{master_probs['開高走高']:.1f}%", f"P(開高)={pg_m*100:.0f}%×P(走高|高)={pu_m*100:.0f}%")
        m[1].metric("🟠 開高走低", f"{master_probs['開高走低']:.1f}%", f"P(開高)={pg_m*100:.0f}%×P(走低|高)={(1-pu_m)*100:.0f}%", delta_color="inverse")
        m[2].metric("🔵 開低走高", f"{master_probs['開低走高']:.1f}%", f"P(開低)={(1-pg_m)*100:.0f}%×P(走高|低)={pd_m*100:.0f}%")
        m[3].metric("🟢 開低走低", f"{master_probs['開低走低']:.1f}%", f"P(開低)={(1-pg_m)*100:.0f}%×P(走低|低)={(1-pd_m)*100:.0f}%", delta_color="inverse")
        m[4].metric("📐 近60日樣本外命中", f"{eval_60['hit']}/{eval_60['n']} ({eval_60['hit']/max(1,eval_60['n'])*100:.1f}%)", f"基準 {eval_60['base']}/{eval_60['n']} ｜ p={eval_60['p']:.3f}")
        m[5].metric("🎯 跳空 / 盤中方向準確率", f"{eval_60['gap']/max(1,eval_60['n'])*100:.0f}% / {eval_60['intra']/max(1,eval_60['n'])*100:.0f}%", f"11/9~13: {eval_w2['hit']}/{eval_w2['n']} ｜ 11/2~6: {eval_w1['hit']}/{eval_w1['n']}")

        with st.expander("📰 展開檢視：白名單新聞清單（已自動剔除 PTT / Dcard / CMoney / 內容農場等黑名單）", expanded=False):
            if headlines:
                st.dataframe(pd.DataFrame([
                    {"媒體": h["source"], "網域": h["domain"], "標題": h["title"], "摘要狀態": "✅ 含內文摘要" if h["has_body"] else "⚠️ 僅有標題", "連結": h["url"]}
                    for h in headlines
                ]), hide_index=True, use_container_width=True)
            else:
                st.info("目前白名單新聞暫無符合條件之項目。")

        with st.expander("📊 展開檢視：無洩漏 Walk-Forward 雙週（11/02~11/06 ＆ 11/09~11/13）與基準比較驗證表", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**🔹 11/09～11/13 成績：命中 `{eval_w2['hit']}/{eval_w2['n']}` ｜ 基準 `{eval_w2['base']}/{eval_w2['n']}` ｜ 二項檢定 `p={eval_w2['p']:.3f}`**")
                st.dataframe(_eval_to_df(df, eval_w2), hide_index=True, use_container_width=True)
            with c2:
                st.markdown(f"**🔸 11/02～11/06 成績：命中 `{eval_w1['hit']}/{eval_w1['n']}` ｜ 基準 `{eval_w1['base']}/{eval_w1['n']}` ｜ 二項檢定 `p={eval_w1['p']:.3f}`**")
                st.dataframe(_eval_to_df(df, eval_w1), hide_index=True, use_container_width=True)

        speeches = build_committee_speeches(wf_sys, sel_idx, flow_info, headlines, night_info, oi_pcr_info, nav_info)
        html_doc = build_chatroom_html(
            target_d, prev_d, sched_msg, sel_row, flow_info, night_info, oi_pcr_info, nav_info,
            headlines, speeches, master_probs, (pg_m, pu_m, pd_m), master_top, base_st_name, eval_60
        )
        components.html(html_doc, height=1550, scrolling=True)

# ───────────────────────── 導覽列與三頁整合組版 ─────────────────────────
with st.container(key="nav"):
    a, b = st.columns([5, 2], vertical_alignment="center")
    a.markdown("<h1>破產後重生之我要靠量化交易發財</h1>", unsafe_allow_html=True)
    with b:
        view = pick("頁面", ["大盤", "策略", "投票"], "view")
with st.container(key="body"):
    if view == "大盤":
        market_page()
    elif view == "策略":
        strategy_page()
    else:
        vote_page()
