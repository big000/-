import os, io, csv, json, time, re, math
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, date, time as dtime, timedelta
import numpy as np, pandas as pd, pytz, requests, yfinance as yf
import streamlit as st
import streamlit.components.v1 as components
import concurrent.futures

# ── 正文提取核心庫 ──
try:
    import trafilatura
    _TRAFILATURA_OK = True
except ImportError:
    _TRAFILATURA_OK = False

try:
    from bs4 import BeautifulSoup
    _BS4_OK = True
except ImportError:
    _BS4_OK = False

# ── OpenAI 客戶端 ──
try:
    from openai import OpenAI
    _OPENAI_OK = True
except ImportError:
    _OPENAI_OK = False

st.set_page_config(page_title="破產後重生之我要靠量化交易發財", page_icon="📈", layout="wide",
                   initial_sidebar_state="collapsed")
TZ = pytz.timezone("Asia/Taipei")
UP, DN = "#ff4d5a", "#22c55e"                   # 台股慣例：紅漲綠跌

# ───────────────────────── 系統設定與白名單設定 ─────────────────────────
DEFAULT_OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1")
INDEX_TICKER = "^TWII"
ETF_TICKER = "00631L.TW"
SYM = ETF_TICKER
ARCHIVE_FILE = "review_archive_6d.json"
MAX_ARCHIVE_DAYS = 6

# ── OpenAI API Key 讀取（env > st.secrets） ──
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    try:
        OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        pass


@st.cache_resource(show_spinner=False)
def _get_openai_client():
    if not _OPENAI_OK or not OPENAI_API_KEY:
        return None
    try:
        return OpenAI(api_key=OPENAI_API_KEY, timeout=90)
    except Exception:
        return None


def _ai_enabled():
    return _get_openai_client() is not None


NEWS_WHITELIST = [
    {"name": "中央社",    "domain": "cna.com.tw",       "lang": "zh", "paywall": False},
    {"name": "經濟日報",  "domain": "money.udn.com",    "lang": "zh", "paywall": False},
    {"name": "工商時報",  "domain": "ctee.com.tw",      "lang": "zh", "paywall": False},
    {"name": "鉅亨網",    "domain": "cnyes.com",        "lang": "zh", "paywall": False},
    {"name": "Reuters",   "domain": "reuters.com",      "lang": "en", "paywall": False},
    {"name": "CNBC",      "domain": "cnbc.com",         "lang": "en", "paywall": False},
    {"name": "Bloomberg", "domain": "bloomberg.com",    "lang": "en", "paywall": True},
    {"name": "WSJ",       "domain": "wsj.com",          "lang": "en", "paywall": True},
    {"name": "FT",        "domain": "ft.com",           "lang": "en", "paywall": True},
]
NEWS_BLACKLIST = [
    "ptt.cc", "dcard.tw", "kknews.cc", "mobile01.com", "facebook.com",
    "youtube.com", "threads.net", "cmoney.tw", "medium.com"
]

COMMITTEE_ROLES = [
    {"id": "fundamental", "name": "基本面委員", "short": "基", "color": "#10a37f", "role": "資金面與總經（利率、匯率、風險偏好、估值、政策與財報季事件）"},
    {"id": "industry",    "name": "產業面委員", "short": "產", "color": "#3b82f6", "role": "AI 供應鏈、半導體景氣、台積電營收與法說、美科技股財報、關稅與出口管制"},
    {"id": "technical",   "name": "技術面委員", "short": "技", "color": "#8b5cf6", "role": "讀取加權指數與 00631L 技術面事實卡，判讀均線、量價、缺口與條件式價位"},
    {"id": "chip",        "name": "籌碼面委員", "short": "籌", "color": "#d97706", "role": "外資現貨與期貨部位、投信、融資融券、選擇權 P/C 比、00631L 折溢價"},
]
_ROLE_MAP = {r["id"]: r for r in COMMITTEE_ROLES}

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

# ───────────────────────── 基礎資料與交易日曆模組 ─────────────────────────
def _clean(d):
    if d is None or d.empty:
        return pd.DataFrame()
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    d = d[~d.index.duplicated()]
    return d.dropna(subset=["Close"])

def _parse_num(val):
    if val is None:
        return None
    s = str(val).strip().replace(",", "").replace("%", "").replace("+", "")
    if not s or s in ("-", "--", "N/A", "None"):
        return None
    try:
        return float(s)
    except Exception:
        return None

@st.cache_data(ttl=300, show_spinner=False)
def load_daily(sym, period="3y"):
    return _clean(yf.download(sym, period=period, interval="1d", auto_adjust=False, progress=False))

@st.cache_data(ttl=60, show_spinner=False)
def load_intraday():
    d = _clean(yf.download(INDEX_TICKER, period="5d", interval="1m", progress=False))
    if d.empty:
        return d
    d.index = d.index.tz_convert(TZ)
    return d[d.index.date == d.index[-1].date()]

@st.cache_data(ttl=60, show_spinner=False)
def load_5m_all(sym):
    d = _clean(yf.download(sym, period="60d", interval="5m", progress=False))
    if d.empty:
        return d
    d.index = d.index.tz_convert(TZ)
    return d

def load_5m_today(sym):
    d = load_5m_all(sym)
    if d.empty:
        return d
    return d[d.index.date == d.index[-1].date()]

@st.cache_data(ttl=900, show_spinner=False)
def twse_day(ymd):
    try:
        r = requests.get("https://www.twse.com.tw/rwd/zh/fund/BFI82U", timeout=8,
                         params={"dayDate": ymd, "type": "day", "response": "json"},
                         headers={"User-Agent": "Mozilla/5.0"}).json()
        time.sleep(0.2)
        if r.get("stat") != "OK":
            return None
        t = {row[0]: int(row[3].replace(",", "")) for row in r["data"]}
        f = lambda k: sum(v for n, v in t.items() if n.startswith(k))
        return {"外資": f("外資"), "投信": f("投信"), "自營": f("自營商"), "ymd": ymd}
    except Exception:
        return None

@st.cache_data(ttl=900, show_spinner=False)
def twse_margin_day(ymd):
    try:
        r = requests.get("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN", timeout=8,
                         params={"date": ymd, "selectType": "MS", "response": "json"},
                         headers={"User-Agent": "Mozilla/5.0"}).json()
        if r.get("stat") != "OK":
            return None
        tables = r.get("tables", [])
        if not tables:
            return None
        rows = tables[0].get("data", [])
        margin_bal = margin_chg = None
        short_bal = short_chg = None
        for row in rows:
            item_name = str(row[0])
            if "融資金額" in item_name:
                prev_v = _parse_num(row[4])
                curr_v = _parse_num(row[5])
                if curr_v is not None:
                    margin_bal = curr_v / 1e5
                    margin_chg = (curr_v - prev_v) / 1e5 if prev_v is not None else 0.0
            elif "融券" in item_name and "交易單位" in item_name:
                prev_s = _parse_num(row[4])
                curr_s = _parse_num(row[5])
                if curr_s is not None:
                    short_bal = int(curr_s)
                    short_chg = int(curr_s - prev_s) if prev_s is not None else 0
        if margin_bal is not None:
            return {
                "ok": True,
                "margin_yi": round(margin_bal, 2),
                "margin_chg_yi": round(margin_chg, 2),
                "short_lots": short_bal or 0,
                "short_chg_lots": short_chg or 0,
                "label": f"融資餘額 {margin_bal:,.1f} 億（日增減 {margin_chg:+.2f} 億）｜融券 {short_bal or 0:,d} 張（{short_chg or 0:+,d} 張）"
            }
    except Exception:
        pass
    return {"ok": False, "label": "未取得"}

@st.cache_data(ttl=900, show_spinner=False)
def last_15_flows():
    out, d = [], datetime.now(TZ)
    for _ in range(38):
        if len(out) == 15:
            break
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
        if r.status_code != 200:
            raise ValueError("API Error")
        out = {}
        for row in r.json():
            name = str(row.get("Name", ""))
            desc = str(row.get("Description", ""))
            if "開始交易" in name or "最後交易" in name or "開始交易" in desc or "最後交易" in desc:
                continue
            d_str = str(row.get("Date", "")).strip().replace("-", "").replace("/", "")
            if len(d_str) == 8 and d_str.isdigit():
                y, m, d = int(d_str[:4]), int(d_str[4:6]), int(d_str[6:8])
                out[date(y, m, d)] = name or desc or "國定休市日"
        return out
    except Exception:
        raise ValueError("Fetch failed")

def is_tw_trading_day(d):
    if d.weekday() >= 5:
        return False, "週末休市"
    try:
        hol = tw_holidays()
        if d in hol:
            return False, f"國定休市（{hol[d]}）"
    except Exception:
        pass
    return True, "正常交易日"

def future_trading_days(after, k):
    hol, ok = {}, True
    try:
        hol = tw_holidays()
    except Exception:
        ok = False
    days, skipped, d = [], {}, after
    while len(days) < k:
        d += timedelta(days=1)
        if d.weekday() >= 5:
            continue
        if d in hol:
            skipped[d] = hol[d]
            continue
        days.append(d)
    return days, skipped, ok

WD = "一二三四五六日"
def fmt_d(d):
    return f"{d:%m/%d}（週{WD[d.weekday()]}）"

# ───────────────────────── 圖表與切換模組 (TradingView) ─────────────────────────
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
    if "Volume" not in d:
        d["Volume"] = 0
    for p in (5, 10, 20, 60, 240):
        d[f"MA{p}"] = d.Close.rolling(p).mean()
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

# ───────────────────────── 頁面一：大盤 ─────────────────────────
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
    for p in (5, 10, 240):
        d[f"m{p}"] = d.Close.rolling(p).mean()
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
                if bo <= ln or (tp and bo >= tp):
                    close(i, bo, "跳空出場")
                elif bl <= ln:
                    close(i, ln, "弱勢停損" if reg == 1 else "停損" if ep * (1 - sl) >= m5 * xm else "跌破均線")
                elif tp and bh >= tp:
                    close(i, tp, "弱勢停利")
            elif i - last > cool:
                ent, r = None, 0
                if m5 < m240:
                    if j == 0 and m5 > m10 and m5b <= m10b:
                        ent, r = bo, 1
                else:
                    lv = m5 * em
                    if bo >= lv:
                        ent, r = bo, 2
                    elif bh >= lv:
                        ent, r = lv, 2
                if ent:
                    pos, ep, reg, ei = 1, ent, r, i
                    ln, tp = lines(ep, reg, m5)
                    if (bl <= ln) if ent == bo else (bc <= ln):
                        close(i, ln, "當日停損")
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
        with st.spinner("同步歷史資料…"):
            df, intra = strategy_data()
        if len(df) < 245:
            st.error("歷史資料不足 245 根，無法計算 240MA。")
            return
        if not intra:
            st.warning("抓不到 5 分 K，回測退回日 K 判斷。")
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
                if skipped:
                    msg += "\n\n已排除休市日：" + "、".join(f"{fmt_d(k)} {v}" for k, v in skipped.items())
                if not ok:
                    msg += "\n\n⚠️ 無法連接證交所 OpenAPI 獲取休假資料，目前只排除週末，遇到國定假日請自行順延。"
                st.info(msg)
            else:
                st.info(f"⚪ 空手：{how}")
            if ent:
                if s["cd"]:
                    st.caption(how)
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
            if d.empty:
                st.warning("目前抓不到 5 分 K 分時資料(可能休市或 Yahoo 暫時無回應)。")
            else:
                components.html(intraday_html(d, prev_close(df, d), h=390, step=300, floor=0.5, dec=2, mm=0.01), height=400)
        else:
            components.html(daily_html(df, h=390), height=400)
    if s["trades"]:
        st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
        with st.container(key="trade_card"):
            st.markdown("<div class='fl-h'>最近 5 筆模擬交易</div>", unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(s["trades"][-5:][::-1]), hide_index=True, use_container_width=True)

# ───────────────────────── 頁面三：早會與 17:00 復盤系統 ─────────────────────────
def load_rolling_archive():
    if os.path.exists(ARCHIVE_FILE):
        try:
            with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_rolling_archive(store, valid_6_date_strs):
    pruned = {k: store[k] for k in valid_6_date_strs if k in store}
    try:
        with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
            json.dump(pruned, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return pruned

@st.cache_data(ttl=900, show_spinner=False)
def fetch_taifex_oi_and_pcr_for_date(ymd):
    return {"fx_oi_ok": False, "fx_label": "未取得", "pcr_ok": False, "pcr_label": "未取得"}

@st.cache_data(ttl=300, show_spinner=False)
def fetch_00631l_nav_info():
    return {"ok": False, "label": "未取得"}

def get_schedule_state(tw_df):
    now = datetime.now(TZ)
    cur_d = now.date()
    dts = []
    for i in tw_df.index:
        if hasattr(i, 'date'):
            dts.append(i.date())
        else:
            dts.append(i)
    unique_dates = sorted(list(set(dts)), reverse=True)
    is_trading, _ = is_tw_trading_day(cur_d)

    if is_trading and cur_d not in unique_dates:
        unique_dates.insert(0, cur_d)

    archive_dates = unique_dates[:MAX_ARCHIVE_DAYS]
    has_live_meeting = cur_d in archive_dates

    banner_state = "live"
    banner_msg = ""

    if is_trading:
        if now.time() < dtime(8, 30):
            banner_state = "waiting"
            banner_msg = f"⏳ 今日（{cur_d:%Y/%m/%d}）早會將於 08:30 準時開始。目前時間：{now.strftime('%H:%M')}。"
        elif now.time() < dtime(17, 0):
            banner_state = "live"
            banner_msg = f"🟢 今日（{cur_d:%Y/%m/%d}）08:30 盤前早會已上線！17:00 將自動更新盤後復盤紀錄。"
        else:
            banner_state = "live"
            banner_msg = f"🟢 今日（{cur_d:%Y/%m/%d}）早會與 17:00 復盤紀錄已完整更新。"
    else:
        banner_state = "closed"
        banner_msg = f"🔴 今日（{cur_d:%Y/%m/%d}）非台股交易日。顯示最近交易日（{archive_dates[0]:%Y/%m/%d}）的早會與復盤紀錄。"

    return {
        "archive_dates": archive_dates,
        "now": now,
        "cur_d": cur_d,
        "has_live_meeting": has_live_meeting,
        "banner_state": banner_state,
        "banner_msg": banner_msg
    }

def compute_tech_fact_card(df_full, upto_date, label_name, is_etf=False):
    dts = pd.DatetimeIndex(df_full.index).tz_localize(None).date
    d = df_full[dts <= upto_date].copy()
    if len(d) < 30:
        return None

    for p in (5, 20, 60, 240):
        d[f"MA{p}"] = d["Close"].rolling(p).mean()
    d["VolMA5"] = d["Volume"].rolling(5).mean()
    d["Ret"] = d["Close"].pct_change() * 100.0

    r_last = d.iloc[-1]
    r_prev = d.iloc[-2] if len(d) >= 2 else r_last
    c = float(r_last["Close"])
    o = float(r_last["Open"])
    h = float(r_last["High"])
    l = float(r_last["Low"])
    prev_c = float(r_prev["Close"])
    chg = c - prev_c
    pct = (c / prev_c - 1.0) * 100.0 if prev_c else 0.0

    ma5 = float(r_last["MA5"])
    ma20 = float(r_last["MA20"])
    ma60 = float(r_last["MA60"]) if pd.notna(r_last["MA60"]) else ma20
    ma240 = float(r_last["MA240"]) if pd.notna(r_last["MA240"]) else ma60

    def _pos_str(p_val, m_val, m_name):
        diff_pct = (p_val / m_val - 1.0) * 100.0
        rel = "上方" if p_val >= m_val else "下方"
        return f"{m_name} {m_val:,.2f}（位於{rel} {diff_pct:+.2f}%）"

    if ma5 > ma20 > ma60:
        ma_align = "5MA > 20MA > 60MA（短中長期均線呈正向排列）"
    elif ma5 < ma20 < ma60:
        ma_align = "5MA < 20MA < 60MA（短中長期均線呈反向排列）"
    else:
        ma_align = f"5MA({ma5:,.1f})、20MA({ma20:,.1f})、60MA({ma60:,.1f}) 交錯排列"

    trend_fact = (
        f"收盤 {c:,.2f}（{chg:+.2f} / {pct:+.2f}%）｜"
        f"{_pos_str(c, ma5, '5MA')}、{_pos_str(c, ma20, '20MA')}、"
        f"{_pos_str(c, ma60, '60MA')}、{_pos_str(c, ma240, '240MA')}｜排列狀態：{ma_align}。"
    )

    vol_cur = float(r_last["Volume"]) if pd.notna(r_last["Volume"]) else 0.0
    vol_ma5 = float(r_last["VolMA5"]) if (pd.notna(r_last["VolMA5"]) and r_last["VolMA5"] > 0) else 1.0
    vol_ratio = vol_cur / vol_ma5
    vol_fact = f"前一交易日成交量為 5 日均量的 {vol_ratio:.2f} 倍（當日量 {vol_cur:,.0f} vs 5日均量 {vol_ma5:,.0f}）。"

    body = abs(c - o)
    body_pct = body / prev_c * 100.0 if prev_c else 0.0
    body_color = "紅K（收高於開）" if c > o else ("黑K（收低於開）" if c < o else "十字線（收等於開）")
    u_wick = h - max(o, c)
    l_wick = min(o, c) - l
    kbar_fact = (
        f"開 {o:,.2f} / 高 {h:,.2f} / 低 {l:,.2f} / 收 {c:,.2f}｜"
        f"型態為{body_color}，實體長度 {body:,.2f}（{body_pct:.2f}%），"
        f"上影線長 {u_wick:,.2f}，下影線長 {l_wick:,.2f}（全天高低振幅 {h - l:,.2f}）。"
    )

    d20 = d.tail(20)
    h20 = float(d20["High"].max())
    l20 = float(d20["Low"].min())

    d60 = d.tail(60)
    unfilled_up_gaps, unfilled_dn_gaps = [], []
    highs_60 = d60["High"].values
    lows_60 = d60["Low"].values
    dates_60 = [x.strftime("%m/%d") for x in d60.index]
    for i in range(1, len(d60)):
        if lows_60[i] > highs_60[i - 1]:
            subsequent_min_low = float(np.min(lows_60[i:]))
            if subsequent_min_low > highs_60[i - 1]:
                unfilled_up_gaps.append(f"{dates_60[i]} 上跳缺口 [{highs_60[i-1]:,.1f} ~ {subsequent_min_low:,.1f}]")
        if highs_60[i] < lows_60[i - 1]:
            subsequent_max_high = float(np.max(highs_60[i:]))
            if subsequent_max_high < lows_60[i - 1]:
                unfilled_dn_gaps.append(f"{dates_60[i]} 下跳缺口 [{subsequent_max_high:,.1f} ~ {lows_60[i-1]:,.1f}]")

    gap_str = "、".join((unfilled_up_gaps[-1:] + unfilled_dn_gaps[-1:])) or "近60日無明顯未回補日K缺口"
    step_round = 10.0 if is_etf else 500.0
    upper_round = math.ceil(c / step_round) * step_round
    lower_round = math.floor(c / step_round) * step_round
    if upper_round == c: upper_round += step_round
    if lower_round == c: lower_round -= step_round

    levels_fact = (
        f"前日高點 {h:,.2f}、前日低點 {l:,.2f}｜"
        f"近 20 日高點 {h20:,.2f}、近 20 日低點 {l20:,.2f}｜"
        f"未回補缺口：{gap_str}｜鄰近整數關卡：{lower_round:,.0f} 與 {upper_round:,.0f}。"
    )

    pivot_up = max(h, ma5)
    res_1 = min(h20, upper_round) if min(h20, upper_round) > pivot_up else max(h20, upper_round)
    res_2 = max(h20, upper_round) if max(h20, upper_round) > res_1 else res_1 + step_round
    pivot_dn = min(l, ma5)
    sup_1 = max(l20, ma20, lower_round) if max(l20, ma20, lower_round) < pivot_dn else min(ma20, lower_round)
    sup_2 = min(l20, ma60, lower_round)

    cond_fact = (
        f"若開盤站上 {pivot_up:,.2f}（前日高點/5MA 上沿）以上，上方第一觀察位在 {res_1:,.2f}，次一壓力位在 {res_2:,.2f}；"
        f"若開盤落於 {pivot_dn:,.2f}（前日低點/5MA 下沿）以下，下方第一支撐位在 {sup_1:,.2f}，次一支撐位在 {sup_2:,.2f}。"
    )

    etf_extra = ""
    if is_etf:
        rets_5 = d["Ret"].tail(5).dropna().values
        std_5d = float(np.std(rets_5, ddof=1)) if len(rets_5) >= 2 else 0.0
        abs_mean_5d = float(np.mean(np.abs(rets_5))) if len(rets_5) >= 1 else 0.0
        strat_entry = round(ma5 * 1.04, 2)
        strat_exit = round(ma5 * 0.98, 2)
        etf_extra = (
            f"近 5 日單日報酬標準差為 {std_5d:.2f}%（平均單日絕對波動 {abs_mean_5d:.2f}%），"
            f"2 倍槓桿每日再平衡於雙向震盪盤會產生波動率累積耗損｜"
            f"策略 B 參考價位：5MA 強勢觸價線 {strat_entry:,.2f}（5MA×1.04）、5MA 出場保護線 {strat_exit:,.2f}（5MA×0.98）。"
        )

    return {
        "name": label_name, "date_str": r_last.name.strftime("%Y/%m/%d"),
        "close": c, "open": o, "high": h, "low": l, "prev_close": prev_c,
        "chg": chg, "pct": pct, "ma5": ma5, "ma20": ma20, "ma60": ma60, "ma240": ma240,
        "vol_ratio": round(vol_ratio, 2), "h20": h20, "l20": l20,
        "upper_round": upper_round, "lower_round": lower_round,
        "pivot_up": round(pivot_up, 2), "res_1": round(res_1, 2), "res_2": round(res_2, 2),
        "pivot_dn": round(pivot_dn, 2), "sup_1": round(sup_1, 2), "sup_2": round(sup_2, 2),
        "trend_fact": trend_fact, "vol_fact": vol_fact, "kbar_fact": kbar_fact,
        "levels_fact": levels_fact, "cond_fact": cond_fact, "etf_extra": etf_extra,
    }

TOPIC_CLUSTERS = [
    {"id": "tsmc_semi", "name": "台積電 / 晶圓代工 / 先進封裝", "kw": ["台積", "TSM", "2330", "CoWoS", "晶圓", "2奈米", "先進製程", "費半", "semiconductor", "foundry"]},
    {"id": "nvda_ai",   "name": "輝達 NVIDIA / AI 伺服器供應鏈", "kw": ["輝達", "NVIDIA", "NVDA", "Blackwell", "GB200", "GB300", "AI伺服器", "鴻海", "廣達", "緯穎", "CSP"]},
    {"id": "fed_macro", "name": "聯準會利率 / 通膨數據 / 美債匯率", "kw": ["聯準會", "Fed", "降息", "利率", "CPI", "PPI", "非農", "鮑爾", "Powell", "美債", "殖利率", "通膨", "inflation", "匯率", "台幣"]},
    {"id": "tariff_geo","name": "關稅貿易政策 / 出口管制 / 地緣", "kw": ["關稅", "川普", "Trump", "tariff", "出口管制", "禁令", "晶片法", "制裁", "貿易"]},
    {"id": "tw_flow",   "name": "台股外資期現貨 / 投信 ETF 籌碼", "kw": ["外資", "投信", "三大法人", "台指期", "融資", "ETF", "0050", "00631L", "權值股", "加權指數"]},
]

def _assign_topic_cluster(title_txt):
    t_up = title_txt.upper()
    for cl in TOPIC_CLUSTERS:
        if any(k.upper() in t_up for k in cl["kw"]):
            return cl["id"], cl["name"]
    return "general_mkt", "國際財經與市場焦點"

# ── 方案 B：用 Jina AI Reader 抓正文，繞反爬 ──
def _strip_jina_wrapper(text):
    """剝掉 r.jina.ai 回傳的 Title/URL Source 標頭，只留正文"""
    lines = text.splitlines()
    skip_until = -1
    for i, ln in enumerate(lines[:12]):
        if ln.strip().lower().startswith(("markdown content:", "markdown content：")):
            skip_until = i
            break
    if skip_until >= 0:
        text = "\n".join(lines[skip_until + 1:])
    return text.strip()


def _try_extract_article_snippet(url, title_str, src_name, is_paywall):
    """改用 r.jina.ai 代理抓正文（免費、繞 Cloudflare）"""
    if is_paywall:
        return False, "僅憑標題判斷（該外媒屬付費牆來源，無法取得全文）"

    try:
        jina_url = f"https://r.jina.ai/{url}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/plain, text/markdown",
        }
        resp = requests.get(jina_url, headers=headers, timeout=28)
        if resp.status_code != 200:
            return False, f"僅憑標題判斷（Jina Reader 回應 HTTP {resp.status_code}）"

        text = resp.text or ""
        if len(text) < 60:
            return False, "僅憑標題判斷（Jina 回傳內容過短）"

        text = _strip_jina_wrapper(text)
        text = re.sub(r"\s+", " ", text).strip()
        if title_str and title_str in text:
            text = text.replace(title_str, "", 1).strip(" -｜|—：:")
        if len(text) < 50:
            return False, "僅憑標題判斷（正文過短，可能為純圖片頁）"

        return True, text[:2400]
    except requests.exceptions.Timeout:
        return False, "僅憑標題判斷（Jina Reader 連線超時）"
    except Exception as e:
        return False, f"僅憑標題判斷（Jina 異常：{str(e)[:30]}）"


def _judge_priced_in(cluster_id, title_txt, sox_pct, tsm_pct, sp_pct):
    t = title_txt
    bull_words = ["大漲", "創高", "優於預期", "買超", "利多", "上調", "強勁", "成長", "rally", "surge", "beat", "gain"]
    bear_words = ["大跌", "重挫", "低於預期", "賣超", "利空", "下修", "管制", "關稅", "通膨升溫", "drop", "fall", "miss", "tariff", "curb"]
    is_bull = any(w in t.lower() for w in bull_words)
    is_bear = any(w in t.lower() for w in bear_words)
    ref_move = 0.5 * sox_pct + 0.5 * tsm_pct if cluster_id in ("tsmc_semi", "nvda_ai") else sp_pct
    if is_bull and ref_move >= 0.6:
        return "📌 已反映", f"隔夜費半 ({sox_pct:+.2f}%) 與 TSM ({tsm_pct:+.2f}%) 已先行上漲吸收此利多，開盤跳空即反映，不宜追高。"
    if is_bear and ref_move <= -0.6:
        return "📌 已反映", f"隔夜費半 ({sox_pct:+.2f}%) 與 TSM ({tsm_pct:+.2f}%) 已先行下跌反應此利空，直接體現於開盤跳空。"
    if abs(ref_move) >= 1.2:
        return "📌 大部分已反映", f"隔夜美股指標波動達 {ref_move:+.2f}%，價格已高度吸收，早盤重點在於現貨開盤承接力道。"
    return "🔥 尚未完全反映", f"隔夜美股指標變動僅 {ref_move:+.2f}%，需觀察今日開盤後外資與投信現貨實際交投反應。"


@st.cache_data(ttl=900, show_spinner=False)
def fetch_and_select_top5_news(window_hours, sox_pct, tsm_pct, nvda_pct, sp_pct):
    days_param = max(2, math.ceil(window_hours / 24.0) + 1)
    raw_candidates = []
    seen_titles = set()
    headers = {"User-Agent": "Mozilla/5.0"}

    # 1. 快速收集 RSS 標題與連結
    for src in NEWS_WHITELIST:
        dom, lang = src["domain"], src["lang"]
        q_str = f"site:{dom} (台股 OR 台積電 OR 費半 OR 輝達 OR 聯準會 OR 外資 OR 半導體) when:{days_param}d" if lang == "zh" else f"site:{dom} (TSMC OR NVIDIA OR semiconductor OR Fed OR Taiwan) when:{days_param}d"
        rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q_str)}&hl={'zh-TW' if lang=='zh' else 'en-US'}&gl={'TW' if lang=='zh' else 'US'}"
        try:
            r = requests.get(rss_url, headers=headers, timeout=5)
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            cnt = 0
            for item in root.findall(".//item"):
                if cnt >= 3:
                    break
                raw_t = item.find("title")
                link_el = item.find("link")
                pub_el = item.find("pubDate")
                title = re.sub(r"\s*-\s*[^-]+$", "", raw_t.text if raw_t is not None else "").strip()
                link = (link_el.text if link_el is not None else "").strip()
                if not title or len(title) < 8 or not link or title in seen_titles:
                    continue
                if any(b in f"{link} {title}".lower() for b in NEWS_BLACKLIST):
                    continue

                cid, cname = _assign_topic_cluster(title)
                seen_titles.add(title)
                cnt += 1
                raw_candidates.append({
                    "source": src["name"], "domain": dom, "title": title, "url": link,
                    "pub": (pub_el.text if pub_el is not None else "")[:16],
                    "cluster_id": cid, "cluster_name": cname,
                    "is_paywall": src["paywall"],
                    "has_body": False, "snippet": ""
                })
        except Exception:
            continue

    # 2. 先分群，每個 cluster 只取前 3 條送 Jina 抓正文（省時省頻寬）
    clusters_pre = {}
    for c in raw_candidates:
        clusters_pre.setdefault(c["cluster_id"], []).append(c)
    to_fetch = []
    for cid, items in clusters_pre.items():
        # 免費來源優先
        items_sorted = sorted(items, key=lambda x: x["is_paywall"])
        to_fetch.extend(items_sorted[:3])

    if to_fetch:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            future_to_candidate = {
                executor.submit(_try_extract_article_snippet, c["url"], c["title"], c["source"], c["is_paywall"]): c
                for c in to_fetch
            }
            for future in concurrent.futures.as_completed(future_to_candidate):
                c = future_to_candidate[future]
                try:
                    has_body, snip = future.result()
                    c["has_body"] = has_body
                    c["snippet"] = snip
                except Exception:
                    c["has_body"] = False
                    c["snippet"] = "僅憑標題判斷（正文提取失敗）"

    # 3. 分群挑代表（同群內已含正文者優先）
    clusters = {}
    for c in raw_candidates:
        clusters.setdefault(c["cluster_id"], []).append(c)

    sorted_cids = sorted(clusters.keys(), key=lambda k: (len(clusters[k]), k != "general_mkt"), reverse=True)
    selected, used_urls = [], set()
    for cid in sorted_cids:
        group = sorted(clusters[cid], key=lambda x: x["has_body"], reverse=True)
        rep = group[0]
        other_sources = sorted(list({x["source"] for x in group}))
        priced_tag, priced_reason = _judge_priced_in(cid, rep["title"], sox_pct, tsm_pct, sp_pct)
        selected.append({
            **rep, "source_count": len(other_sources), "all_sources": ", ".join(other_sources),
            "priced_tag": priced_tag,
            "dev": f"【{rep['cluster_name']}｜共 {len(other_sources)} 家白名單報導（{', '.join(other_sources)}）】{rep['snippet']}",
            "imp": f"{priced_reason} 對 00631L 而言，臺灣 50 權值股將直接受此事件與隔夜 ADR ({tsm_pct:+.2f}%) 連動。",
        })
        used_urls.add(rep["url"])
        if len(selected) >= 5:
            break

    for c in raw_candidates:
        if len(selected) >= 5:
            break
        if c["url"] not in used_urls:
            priced_tag, priced_reason = _judge_priced_in(c["cluster_id"], c["title"], sox_pct, tsm_pct, sp_pct)
            selected.append({
                **c, "source_count": 1, "all_sources": c["source"], "priced_tag": priced_tag,
                "dev": f"【{c['source']}（{c['domain']}）】{c['snippet']}", "imp": f"{priced_reason}",
            })
            used_urls.add(c["url"])

    return selected[:5]


# ═══════════════════════════════════════════════════════════════
#                 AI 委員會：真串 OpenAI
# ═══════════════════════════════════════════════════════════════

def _build_facts_block(briefing):
    tw_c, etf_c = briefing["tw_card"], briefing["etf_card"]
    fl, mg, op, nv, us = briefing["flow"], briefing["margin"], briefing["oi_pcr"], briefing["nav"], briefing["us"]
    return f"""【市場事實摘要（{briefing['target_d']}）】
台灣加權指數 前一日收盤：{tw_c['close']:,.2f}（{tw_c['pct']:+.2f}%），5MA={tw_c['ma5']:,.2f}，20MA={tw_c['ma20']:,.2f}，60MA={tw_c['ma60']:,.2f}，240MA={tw_c['ma240']:,.2f}，量比={tw_c['vol_ratio']:.2f}倍
加權 前日K棒：{tw_c['kbar_fact']}
加權 20日高={tw_c['h20']:,.2f}，20日低={tw_c['l20']:,.2f}；上沿={tw_c['pivot_up']:,.2f}，下沿={tw_c['pivot_dn']:,.2f}，支撐1={tw_c['sup_1']:,.2f}，壓力1={tw_c['res_1']:,.2f}

00631L 前一日收盤：{etf_c['close']:,.2f}（{etf_c['pct']:+.2f}%），5MA={etf_c['ma5']:,.2f}，20MA={etf_c['ma20']:,.2f}，240MA={etf_c['ma240']:,.2f}，量比={etf_c['vol_ratio']:.2f}倍
00631L 前日K棒：{etf_c['kbar_fact']}
00631L 20日高={etf_c['h20']:,.2f}，20日低={etf_c['l20']:,.2f}；上沿={etf_c['pivot_up']:,.2f}，下沿={etf_c['pivot_dn']:,.2f}，支撐1={etf_c['sup_1']:,.2f}，壓力1={etf_c['res_1']:,.2f}
策略B參考：強勢觸價線=5MA×1.04={etf_c['ma5']*1.04:,.2f}，出場線=5MA×0.98={etf_c['ma5']*0.98:,.2f}；{etf_c['etf_extra']}

三大法人（{fl['date_label']}）：外資 {fl['f1']:+.1f} 億（5日 {fl['f5']:+.1f} 億，10日 {fl['f10']:+.1f} 億）；投信 {fl['t1']:+.1f} 億（5日 {fl['t5']:+.1f} 億）；自營商 {fl['z1']:+.1f} 億
融資融券：{mg['label']}
外資台指期淨部位：{op['fx_label']}；選擇權 P/C 比：{op['pcr_label']}
00631L 折溢價與量能：{nv['label']}

美股（{us['date_str']} 收盤）：
費半 {us['sox_pct']:+.2f}%（收 {us['sox_close']:.2f}）
台積電 ADR {us['tsm_pct']:+.2f}%（收 {us['tsm_close']:.2f}，換算台股溢價率 {us['adr_prem']:+.2f}%）
NVDA {us['nvda_pct']:+.2f}%（收 {us['nvda_close']:.2f}）
S&P 500 {us['sp_pct']:+.2f}%
VIX {us['vix_close']:.2f}（{us['vix_pct']:+.2f}%）
10Y 美債殖利率 {us['tnx_close']:.2f}%
美元兌台幣 {us['fx_close']:.2f}（{us['fx_pct']:+.2f}%）
"""


def _build_news_block(briefing, max_chars_per_news=1400):
    lines = []
    for i, n in enumerate(briefing["news_list"], 1):
        body = n["snippet"] if n.get("has_body") else "（僅標題，無正文）"
        body = body[:max_chars_per_news]
        lines.append(
            f"--- 新聞 {i}｜{n['source']}（{n.get('cluster_name', n.get('cluster_id', ''))}）｜{n['priced_tag']} ---\n"
            f"標題：{n['title']}\n內文：{body}\n"
        )
    return "\n".join(lines) if lines else "（無可用新聞）"


def _call_llm_json(client, prompt, model, temperature=0.4, max_tokens=4000):
    """呼叫 LLM 並強制解析 JSON；失敗回傳 None"""
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是嚴謹的台灣股市盤前分析主持人，所有輸出必須符合要求的 JSON schema，不得附加任何多餘文字。"},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception:
        return None


def _ai_generate_committee(briefing):
    """用 LLM 生成 3 輪討論；失敗則回傳 None"""
    client = _get_openai_client()
    if client is None:
        return None

    model = DEFAULT_OPENAI_MODEL
    facts = _build_facts_block(briefing)
    news_block = _build_news_block(briefing)

    # ---------- Round 1 ----------
    prompt_r1 = f"""你是一場盤前投資委員會的主持人，需要模擬 4 位委員的第一輪獨立發言。

{facts}

{news_block}

4 位委員角色：
1. fundamental：基本面委員 — 資金面與總經（利率、匯率、風險偏好、估值、政策與財報季事件）
2. industry：產業面委員 — AI 供應鏈、半導體景氣、台積電營收與法說、美科技股財報、關稅與出口管制
3. technical：技術面委員 — 讀取加權指數與 00631L 技術面事實卡，判讀均線、量價、缺口與條件式價位
4. chip：籌碼面委員 — 外資現貨與期貨部位、投信、融資融券、選擇權 P/C 比、00631L 折溢價

分析原則：
- 必須引用具體數字（如「費半 +1.23%」「外資 -35.4 億」「5MA 234.56 元」），禁止空泛評論
- 最終操作標的是 00631L（2 倍槓桿追蹤臺灣50），所有結論都要推導到 00631L 的具體價位
- 因果鏈必須是「A → B → 對 00631L 影響 C」三段式
- 立場只能是「偏多」「偏空」「觀望」三選一
- 建議空手/持有者時要給具體價位（可用事實中的 5MA、上沿、下沿、支撐、壓力、策略B線）

請嚴格輸出以下 JSON（不得加任何說明文字）：
{{
  "committees": [
    {{
      "id": "fundamental",
      "stance": "偏多|偏空|觀望",
      "confidence": "20~40字，需引用具體數字",
      "thesis": "60~100字，必須引用具體數字",
      "causal_chain": "A → B → 對 00631L 影響 C（60~120字）",
      "evidence": "30~60字，只能引用上面事實摘要中的數據",
      "advice_flat": "對 00631L 空手者建議（40~70字，含具體價位）",
      "advice_hold": "對 00631L 持有者建議含止損（40~70字，含具體價位）"
    }},
    {{"id": "industry", "...": "同上"}},
    {{"id": "technical", "...": "同上"}},
    {{"id": "chip", "...": "同上"}}
  ]
}}"""

    r1 = _call_llm_json(client, prompt_r1, model, temperature=0.45, max_tokens=3500)
    if not r1 or "committees" not in r1 or len(r1["committees"]) < 4:
        return None

    round1 = []
    for item in r1["committees"]:
        rid = item.get("id", "")
        base = _ROLE_MAP.get(rid)
        if not base:
            continue
        merged = {**base, **{k: v for k, v in item.items() if k != "id"}}
        # 强制立场一致性
        if merged.get("stance") not in ("偏多", "偏空", "觀望"):
            merged["stance"] = "觀望"
        for k in ("confidence", "thesis", "causal_chain", "evidence", "advice_flat", "advice_hold"):
            merged[k] = str(merged.get(k, "")).strip() or "（AI 未提供）"
        round1.append(merged)

    if len(round1) < 4:
        return None

    # ---------- Round 2 ----------
    r1_summary = "\n".join(
        f"- {m['name']}（{m['stance']}）：{m['thesis']}" for m in round1
    )
    prompt_r2 = f"""基於以下第一輪發言，請模擬「第二輪交叉質疑」。

第一輪摘要：
{r1_summary}

{facts}

規則：
- 每位委員質疑另一位委員（不可質疑自己）
- 反駁必須基於具體數字與事實，不可只是立場對立
- 立場改變時需給出合理理由，否則維持
- 輸出必須是嚴格 JSON

請嚴格輸出以下 JSON（不得加任何說明文字）：
{{
  "committees": [
    {{
      "id": "fundamental",
      "target": "產業面委員|技術面委員|籌碼面委員|基本面委員",
      "rebuttal": "60~100字，基於數字反駁",
      "stance_change": "維持【X】：理由（40~80字），或修正為【Y】：理由"
    }},
    {{"id": "industry", "...": "同上"}},
    {{"id": "technical", "...": "同上"}},
    {{"id": "chip", "...": "同上"}}
  ]
}}"""

    r2 = _call_llm_json(client, prompt_r2, model, temperature=0.5, max_tokens=2500)
    if not r2 or "committees" not in r2 or len(r2["committees"]) < 4:
        return None

    round2 = []
    for item in r2["committees"]:
        rid = item.get("id", "")
        base = _ROLE_MAP.get(rid)
        if not base:
            continue
        merged = {**base, **{k: v for k, v in item.items() if k != "id"}}
        merged["target"] = str(merged.get("target", "")).strip() or "其他委員"
        merged["rebuttal"] = str(merged.get("rebuttal", "")).strip() or "（AI 未提供）"
        merged["stance_change"] = str(merged.get("stance_change", "")).strip() or "維持原立場"
        round2.append(merged)

    if len(round2) < 4:
        return None

    # ---------- Host Conclusion ----------
    prompt_host = f"""作為主持人，整合以下資訊並給出最終結論。

{facts}

第一輪立場：
{r1_summary}

第二輪重點：
{chr(10).join(f"- {m['name']} 質疑 {m['target']}：{m['rebuttal']}" for m in round2)}

請嚴格輸出以下 JSON（不得加任何說明文字）：
{{
  "consensus": "80~150字，說明今日委員會共識（含具體數字）",
  "divergence": "60~120字，說明分歧的核心因果環節",
  "key_variables": [
    "變數1：具體觀察指標與價位（30~60字）",
    "變數2：...",
    "變數3：..."
  ],
  "decision_tree": [
    "🟢 【情境一：順勢偏多】明確條件與 00631L 具體動作（60~100字）",
    "🟠 【情境二：開高走低】明確條件與 00631L 具體動作",
    "🔵 【情境三：開低走高】明確條件與 00631L 具體動作",
    "🔴 【情境四：開低走低】明確條件與 00631L 具體動作"
  ]
}}"""

    host = _call_llm_json(client, prompt_host, model, temperature=0.35, max_tokens=2000)
    if not host:
        return None

    if not isinstance(host.get("key_variables"), list) or not host["key_variables"]:
        host["key_variables"] = ["（AI 未提供關鍵變數）"]
    if not isinstance(host.get("decision_tree"), list) or not host["decision_tree"]:
        host["decision_tree"] = ["（AI 未提供決策樹）"]
    host["consensus"] = str(host.get("consensus", "")).strip() or "（AI 未提供共識）"
    host["divergence"] = str(host.get("divergence", "")).strip() or "（AI 未提供分歧）"

    return round1, round2, host


# ── 保底：規則引擎（原版本） ──
def _rule_based_committee(briefing):
    us, flow, margin, oi_pcr, nav = briefing["us"], briefing["flow"], briefing["margin"], briefing["oi_pcr"], briefing["nav"]
    tw_card, etf_card, news_list = briefing["tw_card"], briefing["etf_card"], briefing["news_list"]

    sp_pct, sox_pct, tsm_pct, nvda_pct = us["sp_pct"], us["sox_pct"], us["tsm_pct"], us["nvda_pct"]
    vix_close, vix_pct, tnx_close, fx_close, fx_pct, adr_prem = us["vix_close"], us["vix_pct"], us["tnx_close"], us["fx_close"], us["fx_pct"], us["adr_prem"]
    f1, f5, t1, t5, z1 = flow["f1"], flow["f5"], flow["t1"], flow["t5"], flow["z1"]

    n1_ref = f"新聞 #1（{news_list[0]['source']}：{news_list[0]['title'][:22]}…）" if len(news_list) >= 1 else "簡報項目"

    f_stance = "偏多" if (sp_pct > 0.3 and vix_pct <= 0) else ("偏空" if (sp_pct < -0.4 or vix_pct > 5.0) else "觀望")
    r1_fundamental = {
        **COMMITTEE_ROLES[0], "stance": f_stance, "confidence": "中（總經利率與匯率為跨國資金背景）",
        "thesis": f"隔夜 S&P 500 變動 {sp_pct:+.2f}%、VIX 收 {vix_close:.2f}、10Y 美債 {tnx_close:.2f}%、台幣 {fx_close:.2f}，總經環境呈現{f_stance}。",
        "causal_chain": f"美債 10Y 報 {tnx_close:.2f}% 且台幣 {fx_close:.2f} → 影響跨國機構風險偏好 → 決定外資於權值股方向，連動 00631L 波動。",
        "evidence": f"引自簡報之 S&P 500 ({sp_pct:+.2f}%)、VIX ({vix_close:.2f})、10Y 殖利率 ({tnx_close:.2f}%)、美元兌台幣 ({fx_close:.2f})。",
        "advice_flat": f"空手者：觀察台幣匯率穩定度，待 00631L 站穩 {etf_card['pivot_up']:,.2f} 元再評估。",
        "advice_hold": f"持有者：若跌破事實卡支撐 {etf_card['sup_1']:,.2f} 元或策略B出場線 {etf_card['ma5']*0.98:,.2f} 元應止損。",
    }

    semi_avg = 0.5 * sox_pct + 0.5 * tsm_pct
    i_stance = "偏多" if semi_avg > 0.4 else ("偏空" if semi_avg < -0.4 else "觀望")
    r1_industry = {
        **COMMITTEE_ROLES[1], "stance": i_stance, "confidence": f"高（費半 {sox_pct:+.2f}% 與 TSM ADR {tsm_pct:+.2f}% 主導定價）",
        "thesis": f"隔夜費半 {sox_pct:+.2f}%、台積電 ADR {tsm_pct:+.2f}%（溢價 {adr_prem:+.2f}%）、NVDA {nvda_pct:+.2f}%。",
        "causal_chain": f"ADR {tsm_pct:+.2f}% 且 NVDA {nvda_pct:+.2f}% → 傳導至權值股跳空 → 透過 2 倍槓桿放大為 00631L 波動。",
        "evidence": f"引自簡報之費半 ({sox_pct:+.2f}%)、TSM ({tsm_pct:+.2f}%)、NVDA ({nvda_pct:+.2f}%) 與 {n1_ref}。",
        "advice_flat": f"空手者：若新聞標註『已反映』，09:00~09:15 切勿追價，待 00631L 守穩 {etf_card['pivot_up']:,.2f} 元再考慮。",
        "advice_hold": f"持有者：以 {etf_card['pivot_dn']:,.2f} 元為防線，跌破 {etf_card['sup_1']:,.2f} 元嚴格止損。",
    }

    tw_above_5 = tw_card["close"] >= tw_card["ma5"]
    t_stance = "偏多" if tw_above_5 else "偏空"
    r1_technical = {
        **COMMITTEE_ROLES[2], "stance": t_stance, "confidence": f"中（加權 {tw_card['close']:,.2f} vs 5MA {tw_card['ma5']:,.2f}）",
        "thesis": f"加權昨收 {tw_card['close']:,.2f}（5MA {tw_card['ma5']:,.2f}），00631L 昨收 {etf_card['close']:,.2f}（5MA {etf_card['ma5']:,.2f}）。",
        "causal_chain": f"加權前日高低 {tw_card['high']:,.2f}/{tw_card['low']:,.2f} → 決定早盤在 5MA 換手成敗 → 影響 00631L 日內回撤。",
        "evidence": "引自技術面事實卡之均線位階、前日 K 棒結構與條件式價位。",
        "advice_flat": f"空手者：開盤站上 {etf_card['pivot_up']:,.2f} 元看 {etf_card['res_1']:,.2f} 元；低於 {etf_card['pivot_dn']:,.2f} 元觀望。",
        "advice_hold": f"持有者：止損設在 {etf_card['pivot_dn']:,.2f} 元（策略B出場線 {etf_card['ma5']*0.98:,.2f} 元）。",
    }

    c_stance = "偏多" if f1 > 30 else ("偏空" if f1 < -30 else "觀望")
    r1_chip = {
        **COMMITTEE_ROLES[3], "stance": c_stance, "confidence": f"中（外資 {f1:+.1f} 億、P/C {oi_pcr['pcr_label']}）",
        "thesis": f"外資 {f1:+.1f} 億（5日 {f5:+.1f} 億）、投信 {t1:+.1f} 億、期貨 OI：{oi_pcr['fx_label']}、折溢價：{nav['label']}。",
        "causal_chain": f"外資現貨與期貨部位 → 決定開盤後避險單調節方向 → 影響 00631L 折溢價收斂風險。",
        "evidence": "引自簡報之三大法人買賣超、期交所外資未平倉、P/C 比與 00631L 折溢價。",
        "advice_flat": f"空手者：檢查折溢價（{nav['label']}），若溢價超過 +0.5% 絕不追高。",
        "advice_hold": f"持有者：若外資賣壓導致跌破 {etf_card['pivot_dn']:,.2f} 元立即止損。",
    }

    round1 = [r1_fundamental, r1_industry, r1_technical, r1_chip]
    round2 = [
        {**COMMITTEE_ROLES[0], "target": "產業面委員", "rebuttal": f"ADR（{tsm_pct:+.2f}%）於 09:00 已反映完畢，盤中走勢取決於匯率（{fx_close:.2f}）。", "stance_change": f"維持【{f_stance}】但收緊：若台幣轉貶且失守 {etf_card['pivot_up']:,.2f} 元則觀望。"},
        {**COMMITTEE_ROLES[1], "target": "技術面委員", "rebuttal": f"靜態均線（5MA {tw_card['ma5']:,.2f}）在跳空時前 15 分鐘易失真。", "stance_change": "修正為：觀察 09:15 後 00631L 是否守穩條件上沿再決定。"},
        {**COMMITTEE_ROLES[2], "target": "籌碼面委員", "rebuttal": f"昨日現貨買超（{f1:+.1f} 億）是落後指標，常遇開高走低反轉。", "stance_change": f"維持【{t_stance}】嚴守：00631L 守 {etf_card['pivot_up']:,.2f} 元才有效，跌破 {etf_card['pivot_dn']:,.2f} 元止損。"},
        {**COMMITTEE_ROLES[3], "target": "基本面委員", "rebuttal": f"宏觀利率是長週期變數，對 00631L 殺傷力不如外資期貨未平倉。", "stance_change": "維持【" + c_stance + "】並將期貨價差列為否決多單硬條件。"},
    ]

    host_conclusion = {
        "consensus": f"1. 隔夜美股 ADR 與費半（{sox_pct:+.2f}%）於 09:00 開盤跳空反應完畢，開盤第一刻不追價。\n2. 00631L 為 2 倍槓桿，務必嚴守事實卡止損線。",
        "divergence": "分歧在於 09:00 跳空後的日內延續性：產業面偏向半導體動能，技術與籌碼面警惕前日高低振幅與外資避險賣壓。",
        "key_variables": [
            f"變數 1（開盤定錨）：09:00~09:15 加權能否站穩 {tw_card['pivot_up']:,.0f} 點（00631L {etf_card['pivot_up']:,.2f} 元）。",
            f"變數 2（龍頭與匯率）：台積電 ADR 反應後之 5 分 K 走勢與美元兌台幣（{fx_close:.2f}）。",
            f"變數 3（折溢價）：00631L 折溢價率（{nav['label']}）是否過度溢價（> +0.5%）。",
        ],
        "decision_tree": [
            f"🟢 【情境一：順勢偏多】若 09:15 前加權守在 {tw_card['pivot_up']:,.0f} 點以上、00631L 守穩 {etf_card['pivot_up']:,.2f} 元（溢價 ≤ +0.5%），上方看 {etf_card['res_1']:,.2f} 元，突破策略 B 強勢線 {etf_card['ma5']*1.04:,.2f} 元可順勢做多。",
            f"🟠 【情境二：開高走低】若因 ADR 跳空開高但 09:15 後跌破開盤價，代表利多已反映且逢高調節，空手不買，持有者減碼。",
            f"🔵 【情境三：開低走高】若開在 {etf_card['pivot_dn']:,.2f} 元以下但在支撐 {etf_card['sup_1']:,.2f} 元出現長下影線，暫不砍在低點，等收復 5MA 再議。",
            f"🔴 【情境四：開低走低】若加權跌破 {tw_card['pivot_dn']:,.0f} 點且 00631L 跌破 {etf_card['pivot_dn']:,.2f} 元，無條件止損。",
        ],
    }
    return round1, round2, host_conclusion


def generate_two_round_meeting_and_tree(briefing):
    """AI 優先；失敗回退規則引擎。用 session_state 快取結果避免重複燒 token。"""
    cache_key = (
        f"ai_committee_{briefing['target_d']}_"
        f"{briefing['us']['sox_pct']:.2f}_{briefing['us']['tsm_pct']:.2f}_"
        f"{briefing['flow']['f1']:.1f}"
    )
    if "ai_committee_cache" not in st.session_state:
        st.session_state.ai_committee_cache = {}

    if cache_key in st.session_state.ai_committee_cache:
        return st.session_state.ai_committee_cache[cache_key]

    if _ai_enabled():
        try:
            result = _ai_generate_committee(briefing)
            if result is not None:
                st.session_state.ai_committee_cache[cache_key] = result
                st.session_state[f"ai_status_{briefing['target_d']}"] = "ai"
                return result
            st.session_state[f"ai_status_{briefing['target_d']}"] = "ai_fallback"
        except Exception:
            st.session_state[f"ai_status_{briefing['target_d']}"] = "ai_error"
    else:
        st.session_state[f"ai_status_{briefing['target_d']}"] = "no_key"

    fallback = _rule_based_committee(briefing)
    st.session_state.ai_committee_cache[cache_key] = fallback
    return fallback


def build_1700_review_record(target_d, now_dt, tw_df, etf_df, briefing, round1, host_conclusion):
    if target_d == now_dt.date() and now_dt.time() < dtime(17, 0):
        return {"ready": False, "msg": f"⏳ 復盤紀錄將於今日（{target_d:%Y/%m/%d}）下午 17:00 準時更新存檔。"}

    tw_dts = pd.DatetimeIndex(tw_df.index).tz_localize(None).date
    etf_dts = pd.DatetimeIndex(etf_df.index).tz_localize(None).date
    tw_sub = tw_df[tw_dts == target_d]
    etf_sub = etf_df[etf_dts == target_d]

    if tw_sub.empty or etf_sub.empty:
        return {"ready": False, "msg": "⏳ 尚待收盤完整資料同步後於 17:00 產生復盤紀錄。"}

    tw_r = tw_sub.iloc[-1]
    etf_r = etf_sub.iloc[-1]
    tw_prev_c = briefing["tw_card"]["close"]
    etf_prev_c = briefing["etf_card"]["close"]

    tw_o, tw_h, tw_l, tw_c = float(tw_r["Open"]), float(tw_r["High"]), float(tw_r["Low"]), float(tw_r["Close"])
    etf_o, etf_h, etf_l, etf_c = float(etf_r["Open"]), float(etf_r["High"]), float(etf_r["Low"]), float(etf_r["Close"])

    tw_gap = (tw_o / tw_prev_c - 1.0) * 100.0 if tw_prev_c else 0.0
    tw_intra = (tw_c / tw_o - 1.0) * 100.0 if tw_o else 0.0
    tw_day = (tw_c / tw_prev_c - 1.0) * 100.0 if tw_prev_c else 0.0

    etf_gap = (etf_o / etf_prev_c - 1.0) * 100.0 if etf_prev_c else 0.0
    etf_intra = (etf_c / etf_o - 1.0) * 100.0 if etf_o else 0.0
    etf_day = (etf_c / etf_prev_c - 1.0) * 100.0 if etf_prev_c else 0.0

    state_4 = (
        "開高走高（跳空續攻紅K）" if (tw_o > tw_prev_c and tw_c >= tw_o) else
        "開高走低（跳空拉回黑K）" if (tw_o > tw_prev_c and tw_c < tw_o) else
        "開低走高（開低承接紅K）" if (tw_o <= tw_prev_c and tw_c >= tw_o) else
        "開低走低（跳空殺低黑K）"
    )

    p_up = briefing["etf_card"]["pivot_up"]
    p_dn = briefing["etf_card"]["pivot_dn"]
    if etf_c >= p_up:
        tree_hit = f"觸發【情境一】：00631L 收盤 {etf_c:,.2f} 元站穩條件上沿 {p_up:,.2f} 元。"
    elif etf_o > etf_prev_c and etf_c < etf_o:
        tree_hit = f"觸發【情境二】：00631L 開高 {etf_gap:+.2f}% 但盤中拉回 {etf_intra:+.2f}% 收 {etf_c:,.2f} 元。"
    elif etf_c <= p_dn:
        tree_hit = f"觸發【情境四】：00631L 收盤 {etf_c:,.2f} 元落於下沿 {p_dn:,.2f} 元之下。"
    else:
        tree_hit = f"觸發【區間整理】：00631L 全天開 {etf_o:,.2f} / 收 {etf_c:,.2f}。"

    member_reviews = []
    for m in round1:
        st_m = m["stance"]
        verdict = "推理方向與當日盤勢相符" if ((st_m == "偏多" and etf_day > 0.2) or (st_m == "偏空" and etf_day < -0.2) or (st_m == "觀望" and abs(etf_intra) < 0.8)) else "因果鏈受盤中反向資金干擾，需依賴條件式價位止損保護"
        member_reviews.append(f"‧ <b>{m['name']}（結論：{st_m}）</b>：{verdict}")

    return {
        "ready": True, "updated_at": f"{target_d:%Y/%m/%d} 17:00:00",
        "tw_o": tw_o, "tw_h": tw_h, "tw_l": tw_l, "tw_c": tw_c,
        "tw_gap": tw_gap, "tw_intra": tw_intra, "tw_day": tw_day,
        "etf_o": etf_o, "etf_h": etf_h, "etf_l": etf_l, "etf_c": etf_c,
        "etf_gap": etf_gap, "etf_intra": etf_intra, "etf_day": etf_day,
        "state_4": state_4, "tree_hit": tree_hit, "member_reviews": member_reviews,
    }


def build_meeting_briefing_for_date(target_d, tw_df, etf_df, days_flow, is_latest_day):
    tw_dts = list(pd.DatetimeIndex(tw_df.index).tz_localize(None).date)
    idx_pos = tw_dts.index(target_d) if target_d in tw_dts else len(tw_dts) - 1
    prev_d = tw_dts[idx_pos - 1] if idx_pos > 0 else (target_d - timedelta(days=1))
    window_hours = max(24, int((datetime.combine(target_d, dtime(8, 30)) - datetime.combine(prev_d, dtime(8, 30))).total_seconds() // 3600))

    tw_card = compute_tech_fact_card(tw_df, prev_d, "加權指數 (^TWII)", is_etf=False)
    etf_card = compute_tech_fact_card(etf_df, prev_d, "元大台灣50正2 (00631L.TW)", is_etf=True)

    sub_flows = [x for x in days_flow if x.get("dt") and x["dt"] <= prev_d] or days_flow
    if sub_flows:
        f_list = [x["外資"] / 1e8 for x in sub_flows]
        t_list = [x["投信"] / 1e8 for x in sub_flows]
        z_list = [x["自營"] / 1e8 for x in sub_flows]
        flow_info = {
            "date_label": sub_flows[-1]["d"],
            "f1": f_list[-1], "f5": sum(f_list[-5:]), "f10": sum(f_list[-10:]),
            "t1": t_list[-1], "t5": sum(t_list[-5:]), "t10": sum(t_list[-10:]),
            "z1": z_list[-1], "z5": sum(z_list[-5:]), "z10": sum(z_list[-10:]),
        }
    else:
        flow_info = {"date_label": prev_d.strftime("%m/%d"), "f1": 0.0, "f5": 0.0, "f10": 0.0, "t1": 0.0, "t5": 0.0, "t10": 0.0, "z1": 0.0, "z5": 0.0, "z10": 0.0}

    margin_info = twse_margin_day(prev_d.strftime("%Y%m%d"))
    oi_pcr_info = fetch_taifex_oi_and_pcr_for_date(prev_d.strftime("%Y%m%d")) if is_latest_day else {"fx_oi_ok": False, "fx_label": "未取得", "pcr_ok": False, "pcr_label": "未取得"}
    nav_info = fetch_00631l_nav_info() if is_latest_day else {"ok": False, "label": "未取得"}

    def _us_val_before(sym):
        u_df = load_daily(sym, "6mo")
        if u_df.empty or len(u_df) < 2:
            return 0.0, 0.0, "--"
        u_dts = pd.DatetimeIndex(u_df.index).tz_localize(None).date
        sub = u_df[u_dts < target_d]
        if len(sub) < 2:
            sub = u_df
        c1, c0 = float(sub["Close"].iloc[-1]), float(sub["Close"].iloc[-2])
        return c1, (c1 / c0 - 1.0) * 100.0, pd.Timestamp(sub.index[-1]).strftime("%m/%d")

    sox_c, sox_pct, us_d_str = _us_val_before("^SOX")
    tsm_c, tsm_pct, _ = _us_val_before("TSM")
    nvda_c, nvda_pct, _ = _us_val_before("NVDA")
    sp_c, sp_pct, _ = _us_val_before("^GSPC")
    vix_c, vix_pct, _ = _us_val_before("^VIX")
    tnx_c, tnx_pct, _ = _us_val_before("^TNX")
    fx_c, fx_pct, _ = _us_val_before("USDTWD=X")
    c2330, _, _ = _us_val_before("2330.TW")
    adr_prem = ((tsm_c * fx_c / 5.0) / c2330 - 1.0) * 100.0 if (c2330 and c2330 > 0 and fx_c > 0) else 15.0

    us_info = {
        "date_str": us_d_str, "sox_close": sox_c, "sox_pct": sox_pct,
        "tsm_close": tsm_c, "tsm_pct": tsm_pct, "nvda_close": nvda_c, "nvda_pct": nvda_pct,
        "sp_close": sp_c, "sp_pct": sp_pct, "vix_close": vix_c, "vix_pct": vix_pct,
        "tnx_close": tnx_c, "tnx_pct": tnx_pct, "fx_close": fx_c, "fx_pct": fx_pct, "adr_prem": adr_prem,
    }
    news_list = fetch_and_select_top5_news(window_hours, sox_pct, tsm_pct, nvda_pct, sp_pct)

    return {
        "target_d": target_d, "prev_d": prev_d, "window_hours": window_hours,
        "tw_card": tw_card, "etf_card": etf_card, "flow": flow_info,
        "margin": margin_info, "oi_pcr": oi_pcr_info, "nav": nav_info,
        "us": us_info, "news_list": news_list,
    }


def render_morning_meeting_html(briefing, round1, round2, host_conclusion, review_rec):
    target_d = briefing["target_d"]
    prev_d = briefing["prev_d"]
    tw_c = briefing["tw_card"]
    etf_c = briefing["etf_card"]
    fl = briefing["flow"]
    mg = briefing["margin"]
    op = briefing["oi_pcr"]
    nv = briefing["nav"]
    us = briefing["us"]
    news_list = briefing["news_list"]

    news_cards_html = ""
    for idx, n in enumerate(news_list, 1):
        p_col = "#38bdf8" if "已反映" in n["priced_tag"] else "#f59e0b"
        b_tag = "✅ 含內文摘要" if n.get("has_body") else "⚠️ 僅憑標題判斷"
        news_cards_html += (
            f"<div class='ev-card'>"
            f"<div class='ev-head'>"
            f"<span class='ev-num'>新聞 #{idx}</span>"
            f"<a class='ev-link' href='{n['url']}' target='_blank' rel='noopener noreferrer'>{n['title']}<span class='ext-ico'>↗ 點擊核對原文 ({n['source']})</span></a>"
            f"<span class='p-tag' style='border-color:{p_col};color:{p_col}'>{n['priced_tag']}</span>"
            f"<span class='b-tag'>{b_tag}</span>"
            f"</div>"
            f"<div class='ev-detail'>"
            f"<div class='ev-row'><span class='tag-dev'>🔹 事情發展</span><span>{n['dev']}</span></div>"
            f"<div class='ev-row'><span class='tag-imp'>🔸 下個交易日影響</span><span>{n['imp']}</span></div>"
            f"</div></div>"
        )
    if not news_cards_html:
        news_cards_html = "<div class='ev-card'>目前白名單時間窗內未抓到可驗證連結之新聞，絕不自行編造標題。</div>"

    r1_html = ""
    for idx, m in enumerate(round1):
        st_col = UP if m["stance"] == "偏多" else (DN if m["stance"] == "偏空" else "#FFC83D")
        r1_html += (
            f"<div class='msg-row'>"
            f"<div class='avatar' style='background:{m['color']}'>{m['short']}</div>"
            f"<div class='bubble'>"
            f"<div class='b-head'>"
            f"<span class='b-name'>{m['name']}</span>"
            f"<span class='b-role'>{m['role']}</span>"
            f"<span class='v-badge' style='border:1px solid {st_col};color:{st_col};background:rgba(255,255,255,.05)'>第一輪結論：{m['stance']}</span>"
            f"<span class='b-time'>{target_d:%m/%d} 08:30:{15 + idx*8:02d}</span>"
            f"</div>"
            f"<div class='item-row'><b>1️⃣ 結論與信心程度：</b><span style='color:{st_col};font-weight:800'>{m['stance']}</span> ｜ 信心程度：{m['confidence']}</div>"
            f"<div class='item-row'><b>2️⃣ 核心論點：</b>{m['thesis']}</div>"
            f"<div class='item-row causal'><b>3️⃣ 因果鏈（A → B → 對 00631L 影響 C）：</b><br>{m['causal_chain']}</div>"
            f"<div class='item-row'><b>4️⃣ 證據來源（嚴格引用簡報）：</b>{m['evidence']}</div>"
            f"<div class='think-grid'>"
            f"<div class='think-box'><b>5️⃣-A 對 00631L 建議【空手者】：</b><br>{m['advice_flat']}</div>"
            f"<div class='think-box'><b>5️⃣-B 對 00631L 建議【持有者（含止損）】：</b><br>{m['advice_hold']}</div>"
            f"</div></div></div>"
        )

    r2_html = ""
    for idx, m in enumerate(round2):
        r2_html += (
            f"<div class='msg-row'>"
            f"<div class='avatar' style='background:{m['color']}'>{m['short']}</div>"
            f"<div class='bubble' style='border-color:#4b3f66'>"
            f"<div class='b-head'>"
            f"<span class='b-name'>{m['name']}（第二輪交叉質疑）</span>"
            f"<span class='eng-tag'>質疑對象：{m['target']}</span>"
            f"<span class='b-time'>{target_d:%m/%d} 08:31:{10 + idx*7:02d}</span>"
            f"</div>"
            f"<div class='item-row'><b>⚔️ 反駁與盲點指出：</b>{m['rebuttal']}</div>"
            f"<div class='reason-box'><b>🔄 立場是否修正與理由：</b>{m['stance_change']}</div>"
            f"</div></div>"
        )

    kv_li = "".join(f"<li>{x}</li>" for x in host_conclusion["key_variables"])
    dt_li = "".join(f"<div class='tree-item'>{x}</div>" for x in host_conclusion["decision_tree"])

    if review_rec["ready"]:
        mem_li = "<br>".join(review_rec["member_reviews"])
        review_html = (
            f"<div class='msg-row host' style='border-color:#38bdf8;background:linear-gradient(90deg,rgba(56,189,248,.14),rgba(30,25,39,.95))'>"
            f"<div class='avatar' style='background:#0284c7;color:#fff'>復</div>"
            f"<div style='flex:1'>"
            f"<div class='b-head'>"
            f"<span class='b-name' style='color:#38bdf8'>17:00 盤後復盤紀錄（僅檢視推理品質 · 絕不回頭調參或改權重）</span>"
            f"<span class='b-role'>滾動保存 6 個交易日</span>"
            f"<span class='b-time'>{review_rec['updated_at']}</span>"
            f"</div>"
            f"<div style='font-size:.96rem;line-height:1.72'>"
            f"📊 <b>當日實際收盤數據對帳（{target_d:%Y/%m/%d}）</b>：<br>"
            f"‧ <b>加權指數 (^TWII)</b>：開 <b>{review_rec['tw_o']:,.2f}</b>（跳空 {review_rec['tw_gap']:+.2f}%）／ 高 <b>{review_rec['tw_h']:,.2f}</b> ／ 低 <b>{review_rec['tw_l']:,.2f}</b> ／ 收 <b>{review_rec['tw_c']:,.2f}</b>（盤中實體 {review_rec['tw_intra']:+.2f}%，全天 <b style='color:{_col(review_rec['tw_day'])}'>{review_rec['tw_day']:+.2f}%</b>）｜型態：<b>{review_rec['state_4']}</b><br>"
            f"‧ <b>00631L (台灣50正2)</b>：開 <b>{review_rec['etf_o']:,.2f}</b>（跳空 {review_rec['etf_gap']:+.2f}%）／ 高 <b>{review_rec['etf_h']:,.2f}</b> ／ 低 <b>{review_rec['etf_l']:,.2f}</b> ／ 收 <b>{review_rec['etf_c']:,.2f}</b>（盤中實體 {review_rec['etf_intra']:+.2f}%，全天 <b style='color:{_col(review_rec['etf_day'])}'>{review_rec['etf_day']:+.2f}%</b>）<br>"
            f"🌲 <b>早會決策樹觸發檢視</b>：{review_rec['tree_hit']}<br>"
            f"🔍 <b>四位委員推理品質復盤</b>：<br>{mem_li}"
            f"</div></div></div>"
        )
    else:
        review_html = f"<div class='msg-row host' style='border-color:#64748b'><div class='avatar' style='background:#475569;color:#fff'>復</div><div style='flex:1'>{review_rec['msg']}</div></div>"

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{{margin:0;background:transparent;color:#e8e6ee;font-family:-apple-system,"Noto Sans TC","Microsoft JhengHei",sans-serif}}
.chat-room{{display:flex;flex-direction:column;gap:20px;padding:6px 6px 18px 6px}}
.sec-banner{{background:#282036;border-left:4px solid #FFC83D;padding:8px 14px;border-radius:8px;font-weight:800;color:#FFC83D;font-size:1.02rem}}
.msg-row{{display:flex;gap:14px;align-items:flex-start}}
.msg-row.host{{background:linear-gradient(90deg,rgba(255,200,61,.13),rgba(30,25,39,.96));border:1px solid rgba(255,200,61,.4);border-radius:16px;padding:16px 20px}}
.avatar{{width:48px;height:48px;border-radius:13px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:1.15rem;flex-shrink:0;color:#fff;box-shadow:0 4px 12px rgba(0,0,0,.35)}}
.bubble{{background:#1e1927;border:1px solid #322a44;border-radius:0 16px 16px 16px;padding:16px 20px;flex:1;line-height:1.7;font-size:.98rem}}
.b-head{{display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap}}
.b-name{{font-weight:800;color:#fff;font-size:1.14rem}}
.b-role{{font-size:.83rem;color:#b0adc0;background:#2a2436;padding:3px 10px;border-radius:6px}}
.b-time{{font-size:.83rem;color:#8a8699;margin-left:auto}}
.fact-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:10px 0}}
@media(max-width:800px){{.fact-grid{{grid-template-columns:1fr}}}}
.fact-card{{background:rgba(0,0,0,.3);border:1px solid #3b3154;border-radius:11px;padding:11px 14px;font-size:.92rem;line-height:1.65}}
.fact-card h4{{margin:0 0 6px 0;color:#FFC83D;font-size:.98rem}}
.ev-wrap{{display:flex;flex-direction:column;gap:10px;margin-top:8px}}
.ev-card{{background:rgba(0,0,0,.28);border:1px solid #312942;border-radius:11px;padding:11px 14px}}
.ev-head{{display:flex;align-items:center;gap:9px;margin-bottom:7px;flex-wrap:wrap}}
.ev-num{{background:#3b3154;color:#ffc83d;font-weight:800;font-size:.82rem;padding:2px 8px;border-radius:6px}}
.ev-link{{color:#fff;font-weight:700;font-size:1.01rem;text-decoration:none;border-bottom:1px dashed rgba(255,200,61,.55)}}
.ev-link:hover{{color:#FFC83D}}
.ext-ico{{font-size:.78rem;color:#a78bfa;margin-left:7px;font-weight:500}}
.p-tag{{border:1px solid;padding:1px 8px;border-radius:99px;font-size:.78rem;font-weight:700;margin-left:auto}}
.b-tag{{background:rgba(255,255,255,.07);color:#cfcfd8;padding:1px 8px;border-radius:6px;font-size:.76rem}}
.ev-detail{{display:flex;flex-direction:column;gap:5px;font-size:.93rem;color:#ddd9e8;line-height:1.62}}
.ev-row{{display:flex;align-items:flex-start;gap:8px}}
.tag-dev{{background:rgba(59,130,246,.18);color:#93c5fd;border:1px solid rgba(59,130,246,.4);font-size:.78rem;font-weight:700;padding:1px 7px;border-radius:5px;white-space:nowrap;margin-top:2px}}
.tag-imp{{background:rgba(244,114,182,.18);color:#f9a8d4;border:1px solid rgba(244,114,182,.4);font-size:.78rem;font-weight:700;padding:1px 7px;border-radius:5px;white-space:nowrap;margin-top:2px}}
.item-row{{margin-bottom:8px;font-size:.95rem}}
.item-row.causal{{background:rgba(59,130,246,.1);border-left:3px solid #3b82f6;padding:8px 12px;border-radius:6px}}
.think-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:8px}}
@media(max-width:768px){{.think-grid{{grid-template-columns:1fr}}}}
.think-box{{background:rgba(255,255,255,.045);border:1px solid #352e47;border-radius:10px;padding:10px 13px;font-size:.93rem;color:#ddd9e8;line-height:1.62}}
.reason-box{{background:rgba(124,92,255,.15);border-left:4px solid #8b5cf6;padding:10px 14px;border-radius:8px;font-size:.95rem;color:#fff}}
.tree-item{{background:rgba(0,0,0,.32);border:1px solid #453a5c;border-radius:9px;padding:9px 13px;margin-bottom:7px;font-size:.95rem;line-height:1.65}}
.eng-tag{{font-size:.83rem;color:#fbbf24;background:rgba(251,191,36,.15);padding:3px 10px;border-radius:6px}}
.v-badge{{font-size:.83rem;font-weight:800;padding:2px 10px;border-radius:6px}}
</style></head><body>
<div class="chat-room">

  <div class="sec-banner">步驟一 ＆ 二：08:30 主持人盤前客觀簡報（只陳述事實、不下結論）＋ 5 則最重要白名單新聞</div>

  <div class="msg-row host">
    <div class="avatar" style="background:linear-gradient(135deg,#FFC83D,#d97706);color:#000">主</div>
    <div style="flex:1">
      <div class="b-head">
        <span class="b-name" style="color:#FFC83D">網站主持人（08:30 盤前事實簡報）</span>
        <span class="b-role">新聞時間窗：{prev_d:%m/%d} 08:30 ～ {target_d:%m/%d} 08:30（共 {briefing['window_hours']} 小時）</span>
        <span class="b-time">{target_d:%Y/%m/%d} 08:30:00</span>
      </div>
      <div style="font-size:.95rem;line-height:1.72">
        ⚠️ <b>標的基準特別說明</b>：最終操作標的 <code>00631L</code> 追蹤的是<b>「臺灣 50 指數」單日正向 2 倍報酬（非加權指數）</b>，台指期夜盤或臺灣 50 成分股漲跌 1%，大約對應 <code>00631L</code> 漲跌 <b>2%</b> 左右。<br>
        💰 <b>籌碼事實（上一交易日 {fl['date_label']}）</b>：<br>
        ‧ <b>三大法人現貨買賣超</b>：外資 <b style="color:{_col(fl['f1'])}">{fl['f1']:+.1f} 億</b>（近5日 {fl['f5']:+.1f} 億）｜投信 <b style="color:{_col(fl['t1'])}">{fl['t1']:+.1f} 億</b>（近5日 {fl['t5']:+.1f} 億）｜自營商 <b style="color:{_col(fl['z1'])}">{fl['z1']:+.1f} 億</b>。<br>
        ‧ <b>大盤融資融券</b>：{mg['label']}<br>
        ‧ <b>外資台指期未平倉 ＆ 選擇權 P/C 比</b>：外資台指期淨部位 <b>{op['fx_label']}</b> ｜ 選擇權 Put/Call 比 <b>{op['pcr_label']}</b><br>
        ‧ <b>00631L 折溢價與量能</b>：{nv['label']}<br>
        🌎 <b>費半與美股事實（{us['date_str']} 收盤）</b>：費半 <b style="color:{_col(us['sox_pct'])}">{us['sox_pct']:+.2f}%</b> ｜ 台積電 ADR <b style="color:{_col(us['tsm_pct'])}">{us['tsm_pct']:+.2f}%</b>（換算台股溢價率 <b>{us['adr_prem']:+.2f}%</b>）｜ NVDA <b style="color:{_col(us['nvda_pct'])}">{us['nvda_pct']:+.2f}%</b> ｜ S&P 500 <b style="color:{_col(us['sp_pct'])}">{us['sp_pct']:+.2f}%</b> ｜ VIX <b>{us['vix_close']:.2f}</b>（{us['vix_pct']:+.2f}%）｜ 10Y 殖利率 <b>{us['tnx_close']:.2f}%</b> ｜ 美元兌台幣 <b>{us['fx_close']:.2f}</b>（{us['fx_pct']:+.2f}%）。

        <div class="fact-grid">
          <div class="fact-card">
            <h4>📐 技術面事實卡 A：加權指數 (^TWII)</h4>
            <b>‧ 趨勢：</b>{tw_c['trend_fact']}<br>
            <b>‧ 量價：</b>{tw_c['vol_fact']}<br>
            <b>‧ 前日 K 棒描述：</b>{tw_c['kbar_fact']}<br>
            <b>‧ 關鍵價位：</b>{tw_c['levels_fact']}<br>
            <b>‧ 條件式價位：</b><span style="color:#fde047">{tw_c['cond_fact']}</span>
          </div>
          <div class="fact-card">
            <h4>📐 技術面事實卡 B：元大台灣50正2 (00631L)</h4>
            <b>‧ 趨勢：</b>{etf_c['trend_fact']}<br>
            <b>‧ 量價：</b>{etf_c['vol_fact']}<br>
            <b>‧ 前日 K 棒描述：</b>{etf_c['kbar_fact']}<br>
            <b>‧ 關鍵價位：</b>{etf_c['levels_fact']}<br>
            <b>‧ 00631L 波動與耗損：</b>{etf_c['etf_extra']}<br>
            <b>‧ 條件式價位：</b><span style="color:#fde047">{etf_c['cond_fact']}</span>
          </div>
        </div>

        <div style="margin-top:10px;font-weight:800;color:#FFC83D">📰 主持人挑選 5 則對下一交易日台股與 00631L 最重要之白名單新聞（含已反映／尚未反映判定）：</div>
        <div class="ev-wrap">{news_cards_html}</div>
      </div>
    </div>
  </div>

  <div class="sec-banner">步驟三：四位委員第一輪獨立發言（基本面 · 產業面 · 技術面 · 籌碼面）</div>
  {r1_html}

  <div class="sec-banner">步驟四：第二輪互相質疑（每人反駁另一人論點，並說明是否修正立場與理由）</div>
  {r2_html}

  <div class="sec-banner">步驟五：主持人結論（不平均票數 — 列出共識、分歧環節、關鍵變數與「如果…就…」決策樹）</div>
  <div class="msg-row host">
    <div class="avatar" style="background:linear-gradient(135deg,#FFC83D,#d97706);color:#000">結</div>
    <div style="flex:1">
      <div class="b-head">
        <span class="b-name" style="color:#FFC83D">網站主持人（最終整合與條件式決策樹）</span>
        <span class="b-role">不做票數平均 · 以條件式行動劇本取代單一買賣標籤</span>
        <span class="b-time">{target_d:%Y/%m/%d} 08:32:00</span>
      </div>
      <div style="font-size:.96rem;line-height:1.72">
        🤝 <b>一、今日委員會共識</b>：<br>{host_conclusion['consensus'].replace(chr(10), '<br>')}<br><br>
        ⚡ <b>二、分歧在哪個因果環節</b>：<br>{host_conclusion['divergence'].replace(chr(10), '<br>')}<br><br>
        🔎 <b>三、今日盯盤的 3 個關鍵變數</b>：<ul style="margin:4px 0 12px 18px;padding:0">{kv_li}</ul>
        🧭 <b>四、「如果…就…」00631L 條件式決策樹</b>：
        <div style="margin-top:6px">{dt_li}</div>
      </div>
    </div>
  </div>

  <div class="sec-banner">步驟六：17:00 盤後復盤紀錄（滾動保存 6 個交易日 · 不回頭調整任何規則或權重）</div>
  {review_html}

</div>
</body></html>"""


def meeting_page():
    tw_df = load_daily(INDEX_TICKER, "3y")
    if tw_df.empty:
        st.error("無法取得加權指數歷史資料。")
        return

    sched = get_schedule_state(tw_df)
    archive_dates = sched["archive_dates"]
    valid_6_strs = [d.strftime("%Y-%m-%d") for d in archive_dates]
    store = load_rolling_archive()

    with st.spinner("載入早會簡報、白名單新聞與 6 日滾動存檔…"):
        etf_df = load_daily(ETF_TICKER, "3y")
        days_flow = last_15_flows()

    with st.container(key="vote_card"):
        st.markdown(
            "<div class='fl-h'>🤖 08:30 盤前結構化早會 ＆ 17:00 盤後復盤紀錄中心"
            "<small>AI 生成雙輪討論 · 條件式決策樹 · 6 日滾動存檔</small></div>",
            unsafe_allow_html=True
        )

        if sched["banner_state"] == "live":
            st.success(sched["banner_msg"])
        elif sched["banner_state"] == "waiting":
            st.warning(sched["banner_msg"])
        else:
            st.error(sched["banner_msg"])

        opt_map = {
            f"{'🟢 [今日早會]' if (sched['has_live_meeting'] and d == sched['cur_d']) else '📁 [歷史存檔]'} {fmt_d(d)} 08:30 早會與 17:00 復盤紀錄": d
            for d in archive_dates
        }
        chosen_label = st.selectbox(
            f"📅 選擇檢視紀錄（系統嚴格滾動保留最近 {MAX_ARCHIVE_DAYS} 個交易日，舊紀錄自動刪除）",
            list(opt_map.keys()),
            index=0
        )
        sel_d = opt_map[chosen_label]
        is_latest = (sel_d == archive_dates[0])

        briefing = build_meeting_briefing_for_date(sel_d, tw_df, etf_df, days_flow, is_latest)
        round1, round2, host_conclusion = generate_two_round_meeting_and_tree(briefing)
        review_rec = build_1700_review_record(sel_d, sched["now"], tw_df, etf_df, briefing, round1, host_conclusion)

        ai_status = st.session_state.get(f"ai_status_{sel_d}", "")
        if ai_status == "ai":
            st.caption(f"🤖 委員討論由 **AI 生成**（model: `{DEFAULT_OPENAI_MODEL}`）")
        elif ai_status == "ai_fallback":
            st.caption("⚠️ AI 回傳格式異常，本日已回退至內建規則引擎（不影響其他日期）")
        elif ai_status == "ai_error":
            st.caption("⚠️ AI 呼叫異常（網路／額度／key 問題），本日已回退至規則引擎")
        elif ai_status == "no_key":
            st.caption("🔑 未偵測到 `OPENAI_API_KEY`，使用內建規則引擎產出討論。設定環境變數後即可啟用 AI 生成。")

        d_key = sel_d.strftime("%Y-%m-%d")
        store[d_key] = {
            "date": d_key,
            "stances": {m["name"]: m["stance"] for m in round1},
            "review_ready": review_rec["ready"],
            "state_4": review_rec.get("state_4", "待 17:00 更新"),
            "tw_day_pct": f"{review_rec['tw_day']:+.2f}%" if review_rec["ready"] else "--",
            "etf_day_pct": f"{review_rec['etf_day']:+.2f}%" if review_rec["ready"] else "--",
            "tree_hit": review_rec.get("tree_hit", "待 17:00 更新"),
        }
        store = save_rolling_archive(store, valid_6_strs)

        with st.expander(f"🗂️ 展開檢視：最近 {MAX_ARCHIVE_DAYS} 個交易日早會立場與 17:00 復盤滾動存檔一覽表", expanded=False):
            summary_rows = []
            for d_item in archive_dates:
                dk = d_item.strftime("%Y-%m-%d")
                if dk not in store:
                    b_tmp = build_meeting_briefing_for_date(d_item, tw_df, etf_df, days_flow, False)
                    r1_tmp, _, hc_tmp = generate_two_round_meeting_and_tree(b_tmp)
                    rv_tmp = build_1700_review_record(d_item, sched["now"], tw_df, etf_df, b_tmp, r1_tmp, hc_tmp)
                    store[dk] = {
                        "date": dk,
                        "stances": {m["name"]: m["stance"] for m in r1_tmp},
                        "review_ready": rv_tmp["ready"],
                        "state_4": rv_tmp.get("state_4", "待 17:00 更新"),
                        "tw_day_pct": f"{rv_tmp['tw_day']:+.2f}%" if rv_tmp["ready"] else "--",
                        "etf_day_pct": f"{rv_tmp['etf_day']:+.2f}%" if rv_tmp["ready"] else "--",
                        "tree_hit": rv_tmp.get("tree_hit", "待 17:00 更新"),
                    }
                rec = store[dk]
                st_map = rec["stances"]
                summary_rows.append({
                    "交易日": fmt_d(d_item),
                    "基本面": st_map.get("基本面委員", "--"),
                    "產業面": st_map.get("產業面委員", "--"),
                    "技術面": st_map.get("技術面委員", "--"),
                    "籌碼面": st_map.get("籌碼面委員", "--"),
                    "17:00 實際走勢": rec["state_4"],
                    "加權指數": rec["tw_day_pct"],
                    "00631L": rec["etf_day_pct"],
                    "決策樹復盤": rec["tree_hit"],
                })
            store = save_rolling_archive(store, valid_6_strs)
            st.dataframe(pd.DataFrame(summary_rows), hide_index=True, use_container_width=True)

        html_doc = render_morning_meeting_html(briefing, round1, round2, host_conclusion, review_rec)
        components.html(html_doc, height=1850, scrolling=True)


# ───────────────────────── 導覽列與三頁整合組版 ─────────────────────────
with st.container(key="nav"):
    a, b = st.columns([5, 2], vertical_alignment="center")
    a.markdown("<h1>破產後重生之我要靠量化交易發財</h1>", unsafe_allow_html=True)
    with b:
        view = pick("頁面", ["早會", "大盤", "策略"], "view")
with st.container(key="body"):
    if view == "早會":
        meeting_page()
    elif view == "大盤":
        market_page()
    else:
        strategy_page()
