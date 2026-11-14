import os, io, csv, json, time, re, math
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, date, time as dtime, timedelta
import numpy as np, pandas as pd, pytz, requests, yfinance as yf
import streamlit as st
import streamlit.components.v1 as components

# ── 新增：正文提取核心庫 ──
try:
    import trafilatura
    _TRAFILATURA_OK = True
except ImportError:
    _TRAFILATURA_OK = False

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

# ★★★ 新增：修復缺失的輔助函數 ★★★
@st.cache_data(ttl=900, show_spinner=False)
def fetch_taifex_oi_and_pcr_for_date(ymd):
    # 佔位函數，避免 NameError。若需實際抓取請在此加入爬蟲。
    return {"fx_oi_ok": False, "fx_label": "未取得", "pcr_ok": False, "pcr_label": "未取得"}

@st.cache_data(ttl=300, show_spinner=False)
def fetch_00631l_nav_info():
    # 佔位函數，避免 NameError。若需實際抓取折溢價請在此加入爬蟲。
    return {"ok": False, "label": "未取得"}

def get_schedule_state(tw_df):
    now = datetime.now(TZ)
    cur_d = now.date()
    
    # 提取 tw_df 的所有日期
    dts = []
    for i in tw_df.index:
        if hasattr(i, 'date'):
            dts.append(i.date())
        else:
            dts.append(i)
            
    unique_dates = sorted(list(set(dts)), reverse=True)
    is_trading, _ = is_tw_trading_day(cur_d)
    
    # 如果今天是交易日但 yfinance 尚未更新到今天的資料，手動加入以利排程顯示
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
# ★★★ 新增結束 ★★★

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

# ── ★★★ 改寫：真正的正文提取 ───
def _try_extract_article_snippet(url, title_str, src_name, is_paywall):
    """
    用 trafilatura 抓取並提取原文正文。
    回傳 (has_body: bool, snippet: str)。
    - 付費牆來源：直接回傳 False + 說明，不浪費請求。
    - 抓取/提取失敗：回傳 False + 說明，絕不編造。
    - 成功：回傳 True + 正文前 1500 字（供後續因果鏈分析引用）。
    """
    if is_paywall:
        return False, "僅憑標題判斷（該外媒屬付費牆來源，無法取得全文）"

    if not _TRAFILATURA_OK:
        return False, "僅憑標題判斷（環境未安裝 trafilatura，請執行 pip install trafilatura）"

    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return False, "僅憑標題判斷（無法連線或頁面禁止抓取）"

        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
            deduplicate=True,
        )
        if not text:
            return False, "僅憑標題判斷（頁面無可提取正文，可能為 JavaScript 渲染或純圖片頁）"

        text = re.sub(r"\s+", " ", text).strip()
        text = text.replace(title_str, "").strip(" -｜|—")
        if len(text) < 30:
            return False, "僅憑標題判斷（提取到的正文過短，不足以分析）"

        return True, text[:1500]
    except Exception:
        return False, "僅憑標題判斷（提取過程發生異常）"
# ── 改寫結束 ───

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
    candidates, seen_titles = [], set()
    headers = {"User-Agent": "Mozilla/5.0"}
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
                # ★ 改動：傳入 url，用 trafilatura 抓取正文
                has_body, snip = _try_extract_article_snippet(link, title, src["name"], src["paywall"])
                seen_titles.add(title)
                cnt += 1
                candidates.append({
                    "source": src["name"], "domain": dom, "title": title, "url": link,
                    "pub": (pub_el.text if pub_el is not None else "")[:16],
                    "cluster_id": cid, "cluster_name": cname, "has_body": has_body, "snippet": snip,
                })
        except Exception:
            continue

    clusters = {}
    for c in candidates:
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

    for c in candidates:
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
