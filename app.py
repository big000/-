import os, io, csv, json, time, re, math
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, date, time as dtime, timedelta
import numpy as np, pandas as pd, pytz, requests, yfinance as yf
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="破產後重生之我要靠量化交易發財", page_icon="📈", layout="wide",
                   initial_sidebar_state="collapsed")
TZ = pytz.timezone("Asia/Taipei")
UP, DN = "#ff4d5a", "#22c55e"                   # 台股慣例：紅漲綠跌

# ───────────────────────── 核心常數與白名單設定 ─────────────────────────
DEFAULT_OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1")
INDEX_TICKER = "^TWII"
ETF_TICKER = "00631L.TW"
SYM = ETF_TICKER
ARCHIVE_FILE = "review_archive_6d.json"
MAX_ARCHIVE_DAYS = 6

# 第五節：新聞來源白名單（國內 4 家 + 國外 5 家）與黑名單
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

# 第六節：四位委員的角色定義
COMMITTEE_ROLES = [
    {
        "id": "fundamental",
        "name": "基本面委員",
        "short": "基",
        "color": "#10a37f",
        "role": "資金面與總經（利率、匯率、風險偏好、估值、政策與財報季事件）"
    },
    {
        "id": "industry",
        "name": "產業面委員",
        "short": "產",
        "color": "#3b82f6",
        "role": "AI 供應鏈、半導體景氣、台積電營收與法說、美科技股財報、關稅與出口管制"
    },
    {
        "id": "technical",
        "name": "技術面委員",
        "short": "技",
        "color": "#8b5cf6",
        "role": "讀取加權指數與 00631L 技術面事實卡，判讀均線、量價、缺口與條件式價位"
    },
    {
        "id": "chip",
        "name": "籌碼面委員",
        "short": "籌",
        "color": "#d97706",
        "role": "外資現貨與期貨部位、投信、融資融券、選擇權 P/C 比、00631L 折溢價"
    },
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
    """從證交所 MI_MARGN 抓取上一交易日大盤融資餘額(億元)與融券餘額(張)"""
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
                    margin_bal = curr_v / 1e5  # 仟元 -> 億元
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

# ───────────────────────── 頁面三：早會簡報、兩輪委員會辯論與 17:00 復盤系統 ─────────────────────────
def get_schedule_state(tw_df):
    """
    嚴格檢查當前時間是否為「交易日 08:30 後」：
    - 只有交易日當天 >= 08:30 才會召開今日早會！
    - 週末、國定休市日或 08:30 前，嚴格標示「今日無早會」，僅開放調閱最近 6 個交易日存檔。
    - 每天 17:00 後才會解鎖當日收盤復盤紀錄，並維持最多 6 個交易日滾動保存。
    """
    now = datetime.now(TZ)
    cur_d = now.date()
    cur_t = now.time()
    is_trd, reason = is_tw_trading_day(cur_d)

    all_dates = list(pd.DatetimeIndex(tw_df.index).tz_localize(None).date)
    # 若今日是交易日且已過 08:30，但 yfinance 日線尚未出現今日列，把最近 6 個已完成交易日列出
    past_6_dates = [d for d in all_dates if d <= cur_d][-MAX_ARCHIVE_DAYS:]

    if is_trd and cur_t >= dtime(8, 30):
        has_live_meeting = True
        banner_state = "live"
        if cur_t >= dtime(17, 0):
            banner_msg = f"🟢 今日（{fmt_d(cur_d)}）08:30 早會已召開，且 17:00 收盤復盤紀錄已準時更新存檔。"
        else:
            banner_msg = f"🟢 今日（{fmt_d(cur_d)}）08:30 盤前早會已召開（17:00 將準時更新今日收盤復盤紀錄）。"
    elif is_trd and cur_t < dtime(8, 30):
        has_live_meeting = False
        banner_state = "waiting"
        banner_msg = f"⏳ 今日（{fmt_d(cur_d)}）為交易日，但尚未到 08:30 開會時間（目前 {now:%H:%M}），今日早會尚未召開！以下為最近 {MAX_ARCHIVE_DAYS} 個交易日之存檔紀錄。"
    else:
        has_live_meeting = False
        banner_state = "closed"
        banner_msg = f"⛔ 今日（{fmt_d(cur_d)}）為【{reason}】，非交易日不召開 08:30 早會！以下僅供檢視最近 {MAX_ARCHIVE_DAYS} 個交易日之早會與 17:00 復盤滾動存檔。"

    return {
        "now": now,
        "cur_d": cur_d,
        "has_live_meeting": has_live_meeting,
        "banner_state": banner_state,
        "banner_msg": banner_msg,
        "archive_dates": past_6_dates[::-1]  # 最新在最前，嚴格只保留 6 個交易日
    }

@st.cache_data(ttl=600, show_spinner=False)
def fetch_taifex_oi_and_pcr_for_date(ymd_str):
    """抓取期交所外資台指期未平倉淨口數與選擇權 Put/Call 比（查無該日或失敗標示未取得）"""
    res = {
        "fx_oi_ok": False, "fx_net_oi": None, "fx_net_chg": None, "fx_label": "未取得",
        "pcr_ok": False, "pcr_oi_ratio": None, "pcr_vol_ratio": None, "pcr_label": "未取得"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r_pcr = requests.get("https://openapi.taifex.com.tw/v1/PutCallRatio", headers=headers, timeout=6)
        if r_pcr.status_code == 200 and isinstance(r_pcr.json(), list) and len(r_pcr.json()) > 0:
            last_row = r_pcr.json()[-1]
            oi_r = _parse_num(last_row.get("PutCallOpenInterestRatio") or last_row.get("PutCallRatio"))
            vol_r = _parse_num(last_row.get("PutCallVolumeRatio"))
            if oi_r is not None:
                res.update({
                    "pcr_ok": True, "pcr_oi_ratio": oi_r, "pcr_vol_ratio": vol_r,
                    "pcr_label": f"{oi_r:.2f}%" + (f"（成交量比 {vol_r:.2f}%）" if vol_r else "")
                })
    except Exception:
        pass

    try:
        r_oi = requests.get("https://openapi.taifex.com.tw/v1/MarketDataOfMajorInstitutionalTradersFuturesBytheDate",
                            headers=headers, timeout=6)
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
                            "fx_label": f"{int(net_oi):+,d} 口" + (f"（單日增減 {int(net_trd):+,d} 口）" if net_trd is not None else "")
                        })
                        break
    except Exception:
        pass
    return res

@st.cache_data(ttl=300, show_spinner=False)
def fetch_00631l_nav_info():
    """從證交所/元大即時淨值端點抓取 00631L 折溢價率"""
    try:
        r = requests.get("https://mis.twse.com.tw/stock/data/all_etf.txt",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        if r.status_code == 200:
            for group in r.json().get("a1", []):
                for msg in group.get("msgArray", []):
                    if str(msg.get("a", "")).strip() == "00631L":
                        mkt_p = _parse_num(msg.get("e"))
                        nav_p = _parse_num(msg.get("f"))
                        prem_pct = _parse_num(msg.get("g"))
                        if nav_p is not None and nav_p > 0:
                            if prem_pct is None and mkt_p is not None:
                                prem_pct = (mkt_p / nav_p - 1.0) * 100.0
                            return {
                                "ok": True,
                                "price": mkt_p,
                                "nav": nav_p,
                                "prem_pct": prem_pct or 0.0,
                                "label": f"預估淨值 {nav_p:,.2f} 元｜折溢價率 {prem_pct or 0.0:+.2f}%"
                            }
    except Exception:
        pass
    return {"ok": False, "prem_pct": None, "label": "未取得（非盤中或元大/證交所端點無回應）"}

def compute_tech_fact_card(df_full, upto_date, label_name, is_etf=False):
    """
    【第四節：技術面事實卡（程式只算並陳述事實，不給多空結論）】
    嚴格只使用 `upto_date`（含）以前的日線資料（即早會前一日 T-1 收盤狀態）：
    1. 趨勢：收盤相對 5、20、60、240 日均線的位置與均線排列描述
    2. 量價：前日成交量相對 5 日均量
    3. 關鍵價位：前日高低點、近 20 日高低點、未回補缺口、整數關卡
    4. 前日 K 棒描述：實體大小、上下影線長度（只描述不判讀）
    5. 00631L 專屬：近 5 日實際波動率（提醒 2 倍槓桿震盪耗損）
    6. 條件式價位：「若開在 X 以上，上方壓力在 Y；若開在 Z 以下，支撐在 W」
    """
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

    # 量價事實
    vol_cur = float(r_last["Volume"]) if pd.notna(r_last["Volume"]) else 0.0
    vol_ma5 = float(r_last["VolMA5"]) if (pd.notna(r_last["VolMA5"]) and r_last["VolMA5"] > 0) else 1.0
    vol_ratio = vol_cur / vol_ma5
    vol_fact = f"前一交易日成交量為 5 日均量的 {vol_ratio:.2f} 倍（當日量 {vol_cur:,.0f} vs 5日均量 {vol_ma5:,.0f}）。"

    # 前日 K 棒純客觀描述
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

    # 關鍵價位：前日高低、近 20 日高低、近 60 日未回補缺口、整數關卡
    d20 = d.tail(20)
    h20 = float(d20["High"].max())
    l20 = float(d20["Low"].min())

    # 掃描近 60 日未回補缺口
    d60 = d.tail(60)
    unfilled_up_gaps = []
    unfilled_dn_gaps = []
    highs_60 = d60["High"].values
    lows_60 = d60["Low"].values
    dates_60 = [x.strftime("%m/%d") for x in d60.index]
    for i in range(1, len(d60)):
        # 向上跳空缺口：當日低點 > 前日高點，且後續所有交易日低點皆未跌破前日高點
        if lows_60[i] > highs_60[i - 1]:
            subsequent_min_low = float(np.min(lows_60[i:]))
            if subsequent_min_low > highs_60[i - 1]:
                unfilled_up_gaps.append(f"{dates_60[i]} 上跳缺口 [{highs_60[i-1]:,.1f} ~ {subsequent_min_low:,.1f}]")
        # 向下跳空缺口：當日高點 < 前日低點，且後續所有交易日高點皆未突破前日低點
        if highs_60[i] < lows_60[i - 1]:
            subsequent_max_high = float(np.max(highs_60[i:]))
            if subsequent_max_high < lows_60[i - 1]:
                unfilled_dn_gaps.append(f"{dates_60[i]} 下跳缺口 [{subsequent_max_high:,.1f} ~ {lows_60[i-1]:,.1f}]")

    gap_str = "、".join((unfilled_up_gaps[-1:] + unfilled_dn_gaps[-1:])) or "近60日無明顯未回補日K缺口"
    step_round = 10.0 if is_etf else 500.0
    upper_round = math.ceil(c / step_round) * step_round
    lower_round = math.floor(c / step_round) * step_round
    if upper_round == c:
        upper_round += step_round
    if lower_round == c:
        lower_round -= step_round

    levels_fact = (
        f"前日高點 {h:,.2f}、前日低點 {l:,.2f}｜"
        f"近 20 日高點 {h20:,.2f}、近 20 日低點 {l20:,.2f}｜"
        f"未回補缺口：{gap_str}｜鄰近整數關卡：{lower_round:,.0f} 與 {upper_round:,.0f}。"
    )

    # 條件式價位：「若開在 X 以上，上方壓力在 Y；若開在 Z 以下，支撐在 W」
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

    # 00631L 專屬：近 5 日實際波動與策略 B 條件價位
    etf_extra = ""
    if is_etf:
        rets_5 = d["Ret"].tail(5).dropna().values
        std_5d = float(np.std(rets_5, ddof=1)) if len(rets_5) >= 2 else 0.0
        abs_mean_5d = float(np.mean(np.abs(rets_5))) if len(rets_5) >= 1 else 0.0
        strat_entry = round(ma5 * 1.04, 2)
        strat_exit = round(ma5 * 0.98, 2)
        etf_extra = (
            f"近 5 日單日報酬標準差為 {std_5d:.2f}%（平均單日絕對波動 {abs_mean_5d:.2f}%），"
            f"2 倍槓桿每日再平衡（Daily Reset）於雙向震盪盤會產生波動率累積耗損｜"
            f"策略 B 參考價位：5MA 強勢觸價線 {strat_entry:,.2f}（5MA×1.04）、5MA 出場保護線 {strat_exit:,.2f}（5MA×0.98）。"
        )

    return {
        "name": label_name,
        "date_str": r_last.name.strftime("%Y/%m/%d"),
        "close": c, "open": o, "high": h, "low": l, "prev_close": prev_c,
        "chg": chg, "pct": pct,
        "ma5": ma5, "ma20": ma20, "ma60": ma60, "ma240": ma240,
        "vol_ratio": round(vol_ratio, 2),
        "h20": h20, "l20": l20,
        "upper_round": upper_round, "lower_round": lower_round,
        "pivot_up": round(pivot_up, 2), "res_1": round(res_1, 2), "res_2": round(res_2, 2),
        "pivot_dn": round(pivot_dn, 2), "sup_1": round(sup_1, 2), "sup_2": round(sup_2, 2),
        "trend_fact": trend_fact,
        "vol_fact": vol_fact,
        "kbar_fact": kbar_fact,
        "levels_fact": levels_fact,
        "cond_fact": cond_fact,
        "etf_extra": etf_extra,
    }

# ───────────────────────── 第五節：白名單新聞抓取、同事件歸群與「已反映/尚未反映」判定 ─────────────────────────
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

def _try_extract_article_snippet(url_str, rss_desc, title_str, src_name, is_paywall):
    """清理 RSS 摘要，若無內文且非付費牆則嘗試輕量抓取 meta og:description，誠實標示是否僅憑標題"""
    clean_d = re.sub(r"<[^>]+>", " ", rss_desc or "")
    clean_d = re.sub(r"&[a-zA-Z0-9#]+;", " ", clean_d)
    clean_d = re.sub(r"\s+", " ", clean_d).strip()
    rem = clean_d.replace(title_str, "").replace(src_name, "").strip(" -｜|—")
    if len(rem) > 28 and not is_paywall:
        return True, rem[:150]
    if is_paywall:
        return False, "僅憑標題判斷（該外媒屬付費牆來源，RSS 未開放全文）"
    return False, "僅憑標題判斷（Google News 轉址未附帶內文摘要）"

def _judge_priced_in(cluster_id, title_txt, sox_pct, tsm_pct, sp_pct):
    """對照隔夜費半、TSM ADR 與標普走勢，判斷該事件是否已反映於隔夜價格"""
    t = title_txt
    bull_words = ["大漲", "創高", "優於預期", "買超", "利多", "上調", "強勁", "成長", "rally", "surge", "beat", "gain"]
    bear_words = ["大跌", "重挫", "低於預期", "賣超", "利空", "下修", "管制", "關稅", "通膨升溫", "drop", "fall", "miss", "tariff", "curb"]
    is_bull_news = any(w in t.lower() for w in bull_words)
    is_bear_news = any(w in t.lower() for w in bear_words)

    ref_move = 0.5 * sox_pct + 0.5 * tsm_pct if cluster_id in ("tsmc_semi", "nvda_ai") else sp_pct
    if is_bull_news and ref_move >= 0.6:
        return "📌 已反映", f"隔夜費半 ({sox_pct:+.2f}%) 與 TSM ({tsm_pct:+.2f}%) 已先行上漲吸收此利多，台股開盤跳空即反映，盤中不宜重複追高。"
    if is_bear_news and ref_move <= -0.6:
        return "📌 已反映", f"隔夜費半 ({sox_pct:+.2f}%) 與 TSM ({tsm_pct:+.2f}%) 已先行下跌反應此消息，將直接體現於台股開盤跳空。"
    if abs(ref_move) >= 1.2:
        return "📌 大部分已反映", f"隔夜美股指標波動達 {ref_move:+.2f}%，價格已高度吸收美股盤中資訊，早盤重點在於開盤後現貨承接力道。"
    return "🔥 尚未完全反映", f"隔夜美股相關指標變動僅 {ref_move:+.2f}%（或消息發布於美股盤後/亞太時段），需觀察今日台股開盤後外資與投信現貨的實際反應。"

@st.cache_data(ttl=900, show_spinner=False)
def fetch_and_select_top5_news(window_hours, sox_pct, tsm_pct, nvda_pct, sp_pct):
    """
    第五節挑選步驟：
    1. 抓 RSS，只留白名單網域，排除黑名單與無效連結
    2. 把講同一件事的報導歸成一群，被多家來源報導的事件排前面
    3. 選出對下一個交易日台股與 00631L 最重要的 5 則新聞
    4. 每則標註「已反映」或「尚未反映」，並誠實標明「含摘要」或「僅憑標題判斷」
    """
    days_param = max(2, math.ceil(window_hours / 24.0) + 1)
    candidates = []
    seen_titles = set()
    headers = {"User-Agent": "Mozilla/5.0"}

    for src in NEWS_WHITELIST:
        dom = src["domain"]
        lang = src["lang"]
        if lang == "zh":
            q_str = f"site:{dom} (台股 OR 台積電 OR 費半 OR 輝達 OR 聯準會 OR 外資 OR 半導體) when:{days_param}d"
            rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q_str)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        else:
            q_str = f"site:{dom} (TSMC OR NVIDIA OR semiconductor OR Fed OR Taiwan) when:{days_param}d"
            rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q_str)}&hl=en-US&gl=US&ceid=US:en"

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
                desc_el = item.find("description")
                pub_el = item.find("pubDate")
                title = re.sub(r"\s*-\s*[^-]+$", "", raw_t.text if raw_t is not None else "").strip()
                link = (link_el.text if link_el is not None else "").strip()
                if not title or len(title) < 8 or not link or title in seen_titles:
                    continue
                if any(b in f"{link} {title}".lower() for b in NEWS_BLACKLIST):
                    continue

                cid, cname = _assign_topic_cluster(title)
                has_body, snip = _try_extract_article_snippet(
                    link, desc_el.text if desc_el is not None else "", title, src["name"], src["paywall"]
                )
                seen_titles.add(title)
                cnt += 1
                candidates.append({
                    "source": src["name"],
                    "domain": dom,
                    "title": title,
                    "url": link,
                    "pub": (pub_el.text if pub_el is not None else "")[:16],
                    "cluster_id": cid,
                    "cluster_name": cname,
                    "has_body": has_body,
                    "snippet": snip,
                })
        except Exception:
            continue

    # 依主題歸群（計算同一事件群被幾家白名單媒體報導）
    clusters = {}
    for c in candidates:
        cid = c["cluster_id"]
        clusters.setdefault(cid, []).append(c)

    # 先從報導家數最多的群各取代表性最高（優先有摘要者）的新聞，湊滿 5 則
    sorted_cids = sorted(clusters.keys(), key=lambda k: (len(clusters[k]), k != "general_mkt"), reverse=True)
    selected = []
    used_urls = set()

    for cid in sorted_cids:
        group = sorted(clusters[cid], key=lambda x: x["has_body"], reverse=True)
        rep = group[0]
        other_sources = sorted(list({x["source"] for x in group}))
        priced_tag, priced_reason = _judge_priced_in(cid, rep["title"], sox_pct, tsm_pct, sp_pct)
        dev_txt = (
            f"【{rep['cluster_name']}｜共 {len(other_sources)} 家白名單媒體報導（{', '.join(other_sources)}）】"
            f"{rep['snippet']}"
        )
        imp_txt = (
            f"{priced_reason} 對 00631L 而言，臺灣 50 權值股（台積電、鴻海、聯發科、廣達）將直接受此事件與隔夜 ADR ({tsm_pct:+.2f}%) 連動。"
        )
        selected.append({
            **rep,
            "source_count": len(other_sources),
            "all_sources": ", ".join(other_sources),
            "priced_tag": priced_tag,
            "dev": dev_txt,
            "imp": imp_txt,
        })
        used_urls.add(rep["url"])
        if len(selected) >= 5:
            break

    # 若主題群不足 5 個，從剩餘候選補齊至 5 則（若實際抓不到 5 則就誠實呈現抓到的數量，絕不偽造假新聞）
    for c in candidates:
        if len(selected) >= 5:
            break
        if c["url"] not in used_urls:
            cid = c["cluster_id"]
            priced_tag, priced_reason = _judge_priced_in(cid, c["title"], sox_pct, tsm_pct, sp_pct)
            selected.append({
                **c,
                "source_count": 1,
                "all_sources": c["source"],
                "priced_tag": priced_tag,
                "dev": f"【{c['source']}（{c['domain']}）】{c['snippet']}",
                "imp": f"{priced_reason}",
            })
            used_urls.add(c["url"])

    return selected[:5]

# ───────────────────────── 第六節 & 第二節：兩輪委員辯論與主持人決策樹生成 ─────────────────────────
def _call_openai_json(prompt):
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        try:
            api_key = str(st.secrets.get("OPENAI_API_KEY", "")).strip()
        except Exception:
            api_key = ""
    if not api_key:
        return None, None
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": DEFAULT_OPENAI_MODEL,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2
            },
            timeout=22
        )
        if resp.status_code == 200:
            r = resp.json()
            return json.loads(r["choices"][0]["message"]["content"]), r.get("model", DEFAULT_OPENAI_MODEL)
    except Exception:
        pass
    return None, None

def generate_two_round_meeting_and_tree(briefing):
    """
    嚴格依據簡報事實卡生成：
    - 第一輪：四位委員（基本面、產業面、技術面、籌碼面）依 5 點固定格式發言（無固定分數門檻，完全由因果鏈推導）
    - 第二輪：四位委員互相質疑（每人反駁另一人的一個因果環節，並說明是否修正立場）
    - 主持人結論：共識、分歧所在的因果環節、今日關鍵變數、「如果…就…」00631L 條件式決策樹
    """
    us = briefing["us"]
    flow = briefing["flow"]
    margin = briefing["margin"]
    oi_pcr = briefing["oi_pcr"]
    nav = briefing["nav"]
    tw_card = briefing["tw_card"]
    etf_card = briefing["etf_card"]
    news_list = briefing["news_list"]

    sp_pct = us["sp_pct"]
    sox_pct = us["sox_pct"]
    tsm_pct = us["tsm_pct"]
    nvda_pct = us["nvda_pct"]
    vix_close = us["vix_close"]
    vix_pct = us["vix_pct"]
    tnx_close = us["tnx_close"]
    fx_close = us["fx_close"]
    fx_pct = us["fx_pct"]
    adr_prem = us["adr_prem"]

    f1, f5 = flow["f1"], flow["f5"]
    t1, t5 = flow["t1"], flow["t5"]
    z1 = flow["z1"]

    n1_ref = f"新聞 #1（{news_list[0]['source']}：{news_list[0]['title'][:22]}…）" if len(news_list) >= 1 else "簡報國際盤勢項目"
    n2_ref = f"新聞 #2（{news_list[1]['source']}：{news_list[1]['title'][:22]}…）" if len(news_list) >= 2 else n1_ref

    # ─── 1. 基本面委員（第一輪） ───
    if sp_pct > 0.3 and vix_pct <= 0 and fx_pct <= 0.15:
        f_stance = "偏多"
        f_conf = "中（美股標普收紅且 VIX 回落，但總經利率與匯率對單日盤中走勢屬背景支撐而非絕對主導）"
    elif sp_pct < -0.4 or vix_pct > 5.0 or fx_pct > 0.25:
        f_stance = "偏空"
        f_conf = "中偏高（VIX 恐慌指數或匯率貶值壓力升溫，跨國資金風險偏好收縮）"
    else:
        f_stance = "觀望"
        f_conf = "中（總經指標多空交錯，美債殖利率與匯率未出現單邊極端變化）"

    r1_fundamental = {
        **COMMITTEE_ROLES[0],
        "stance": f_stance,
        "confidence": f_conf,
        "thesis": f"隔夜 S&P 500 變動 {sp_pct:+.2f}%、VIX 收 {vix_close:.2f}（{vix_pct:+.2f}%），搭配 10Y 美債殖利率 {tnx_close:.2f}% 與美元兌台幣 {fx_close:.2f}（{fx_pct:+.2f}%），總經資金環境呈現{f_stance}格局。",
        "causal_chain": (
            f"美債 10Y 殖利率報 {tnx_close:.2f}% 且 VIX 變動 {vix_pct:+.2f}% "
            f"→ 影響跨國機構對新興亞洲匯率（美元兌台幣 {fx_close:.2f}）與大型權值股的風險溢價要求 "
            f"→ 進而決定今日外資於臺灣 50 成分股是順勢配置或提款，使 00631L 開盤後承受對應的資金推力或壓力。"
        ),
        "evidence": f"引自【主持人簡報：費半與美股】之 S&P 500 ({sp_pct:+.2f}%)、VIX ({vix_close:.2f})、10Y 殖利率 ({tnx_close:.2f}%)、美元兌台幣 ({fx_close:.2f})，以及 {n1_ref}。",
        "advice_flat": f"空手者：觀察早盤台幣匯率是否維持於 {fx_close:.2f} 附近穩定，且 00631L 站穩條件價位 {etf_card['pivot_up']:,.2f} 元再行評估，不於開盤第一刻盲目進場。",
        "advice_hold": f"持有者：若盤中 00631L 跌破技術面事實卡之第一支撐位 {etf_card[' pivot_dn' if ' pivot_dn' in etf_card else 'pivot_dn']:,.2f} 元（或策略 B 出場線 {etf_card['ma5']*0.98:,.2f} 元）應執行止損減碼。"
    }

    # ─── 2. 產業面委員（第一輪） ───
    semi_avg = 0.5 * sox_pct + 0.5 * tsm_pct
    if semi_avg > 0.4:
        i_stance = "偏多"
        i_conf = f"高（費半 {sox_pct:+.2f}% 與台積電 ADR {tsm_pct:+.2f}% 方向明確，且台積電佔臺灣 50 指數權重逾 50%）" if (sox_pct > 0 and tsm_pct > 0) else "中（半導體指標偏多但內部仍有分歧）"
    elif semi_avg < -0.4:
        i_stance = "偏空"
        i_conf = f"高（費半 {sox_pct:+.2f}% 與台積電 ADR {tsm_pct:+.2f}% 同步回檔，直接壓抑臺灣 50 權值股開盤定價）" if (sox_pct < 0 and tsm_pct < 0) else "中（AI 晶片與晶圓代工走勢分歧）"
    else:
        i_stance = "觀望"
        i_conf = "低（隔夜費半與台積電 ADR 漲跌幅收斂，部分新聞受限付費牆僅憑標題判斷，缺乏強烈單邊產業催化劑）"

    r1_industry = {
        **COMMITTEE_ROLES[1],
        "stance": i_stance,
        "confidence": i_conf,
        "thesis": f"隔夜費城半導體變動 {sox_pct:+.2f}%、台積電 ADR 變動 {tsm_pct:+.2f}%（換算台股溢價率 {adr_prem:+.2f}%）、NVIDIA 變動 {nvda_pct:+.2f}%，直接牽動臺灣 50 電子權值股定價。",
        "causal_chain": (
            f"隔夜台積電 ADR 變動 {tsm_pct:+.2f}% 且 NVDA 變動 {nvda_pct:+.2f}% "
            f"→ 直接傳導至台股 2330（台積電）與 AI 伺服器權值股（鴻海、聯發科、廣達）的 09:00 開盤跳空幅度 "
            f"→ 因 00631L 追蹤臺灣 50 指數正向 2 倍，半導體權值股跳空 1% 將直接放大為 00631L 約 2% 的早盤波動。"
        ),
        "evidence": f"引自【主持人簡報：費半與美股】之費半 ({sox_pct:+.2f}%)、台積電 ADR ({tsm_pct:+.2f}%)、NVDA ({nvda_pct:+.2f}%)，以及 {n1_ref}、{n2_ref}。",
        "advice_flat": f"空手者：若隔夜新聞標註為「已反映」，代表開盤跳空即吸收 ADR ({tsm_pct:+.2f}%) 漲跌幅，空手切勿在 09:00~09:15 追價，應等 00631L 盤中突破 {etf_card['pivot_up']:,.2f} 元並守穩再考慮。",
        "advice_hold": f"持有者：以 00631L 前日低點與 5MA 下沿 {etf_card['pivot_dn']:,.2f} 元作為第一道防線，若跌破 {etf_card['sup_1']:,.2f} 元則嚴格止損出場。"
    }

    # ─── 3. 技術面委員（第一輪） ───
    tw_above_5 = tw_card["close"] >= tw_card["ma5"]
    tw_above_20 = tw_card["close"] >= tw_card["ma20"]
    if tw_above_5 and tw_above_20:
        t_stance = "偏多"
        t_conf = f"中偏高（加權指數收 {tw_card['close']:,.2f} 同時位於 5MA {tw_card['ma5']:,.2f} 與 20MA {tw_card['ma20']:,.2f} 之上，成交量為 5 日均量的 {tw_card['vol_ratio']:.2f} 倍）"
    elif (not tw_above_5) and (not tw_above_20):
        t_stance = "偏空"
        t_conf = f"中偏高（加權指數收 {tw_card['close']:,.2f} 同時落於 5MA {tw_card['ma5']:,.2f} 與 20MA {tw_card['ma20']:,.2f} 之下，短中期均線形成上檔反壓）"
    else:
        t_stance = "觀望"
        t_conf = f"中（指數夾在 5MA {tw_card['ma5']:,.2f} 與 20MA {tw_card['ma20']:,.2f} 之間震盪，且 00631L 在震盪區間存在 2 倍槓桿耗損）"

    r1_technical = {
        **COMMITTEE_ROLES[2],
        "stance": t_stance,
        "confidence": t_conf,
        "thesis": f"加權指數昨收 {tw_card['close']:,.2f}（5MA {tw_card['ma5']:,.2f} / 20MA {tw_card['ma20']:,.2f}），00631L 昨收 {etf_card['close']:,.2f}（5MA {etf_card['ma5']:,.2f} / 20MA {etf_card['ma20']:,.2f}），必須以條件式價位取代主觀猜測。",
        "causal_chain": (
            f"加權指數前日高低點為 {tw_card['high']:,.2f} / {tw_card['low']:,.2f}（量比 5 日均量 {tw_card['vol_ratio']:.2f} 倍） "
            f"→ 決定今日早盤開盤後買賣雙方在 5MA ({tw_card['ma5']:,.2f}) 與整數關卡 ({tw_card['upper_round']:,.0f} / {tw_card['lower_round']:,.0f}) 的換手成敗 "
            f"→ 若無法站穩條件上沿則易引發短線停利賣壓，放大 00631L 的日內回撤。"
        ),
        "evidence": f"引自【技術面事實卡：加權指數】與【技術面事實卡：00631L】之均線位階、前日 K 棒結構、5 日均量比（{tw_card['vol_ratio']:.2f} 倍）與條件式價位。",
        "advice_flat": f"空手者：若 00631L 開在 {etf_card['pivot_up']:,.2f} 元以上且 5 分 K 守穩，上方看壓力 {etf_card['res_1']:,.2f} 元（策略 B 強勢線為 {etf_card['ma5']*1.04:,.2f} 元）；若開在 {etf_card['pivot_dn']:,.2f} 元以下則觀望不接刀。",
        "advice_hold": f"持有者：嚴格設定止損位在 {etf_card['pivot_dn']:,.2f} 元（或策略 B 出場線 {etf_card['ma5']*0.98:,.2f} 元），跌破下方支撐 {etf_card['sup_1']:,.2f} 元無條件停損。"
    }

    # ─── 4. 籌碼面委員（第一輪） ───
    if f1 > 50 and t1 >= 0:
        c_stance = "偏多"
        c_conf = f"中偏高（外資昨日現貨買超 {f1:+.1f} 億、投信 {t1:+.1f} 億，土洋法人現貨同步站在買方）"
    elif f1 < -50:
        c_stance = "偏空"
        c_conf = f"高（外資昨日現貨賣超 {abs(f1):.1f} 億、近 5 日累積 {f5:+.1f} 億，大型權值股面臨外資調節壓力）"
    else:
        c_stance = "觀望"
        c_conf = f"中（外資昨 {f1:+.1f} 億、投信 {t1:+.1f} 億、自營商 {z1:+.1f} 億，法人籌碼力道分歧）"

    r1_chip = {
        **COMMITTEE_ROLES[3],
        "stance": c_stance,
        "confidence": c_conf,
        "thesis": f"上一交易日外資現貨 {f1:+.1f} 億（近5日 {f5:+.1f} 億）、投信 {t1:+.1f} 億（近5日 {t5:+.1f} 億）、自營商 {z1:+.1f} 億；外資台指期未平倉：{oi_pcr['fx_label']}，選擇權 P/C 比：{oi_pcr['pcr_label']}。",
        "causal_chain": (
            f"外資現貨買賣超 {f1:+.1f} 億搭配台指期未平倉（{oi_pcr['fx_label']}）與大盤融資（{margin['label']}） "
            f"→ 決定開盤跳空後外資在現貨權值股與期貨避險單的順勢或反向調節行為 "
            f"→ 同時影響 00631L 市價相對淨值的折溢價（{nav['label']}）收斂風險。"
        ),
        "evidence": f"引自【主持人簡報：籌碼面】之三大法人買賣超、融資融券（{margin['label']}）、期交所外資未平倉與 P/C 比（{oi_pcr['pcr_label']}）、00631L 折溢價（{nav['label']}）。",
        "advice_flat": f"空手者：進場前先檢查 00631L 即時折溢價（目前簡報為 {nav['label']}），若溢價超過 +0.5% 絕不追高；需待外資期現貨方向一致且站穩 {etf_card['pivot_up']:,.2f} 元再動作。",
        "advice_hold": f"持有者：若盤中外資賣壓湧現導致 00631L 跌破 {etf_card['pivot_dn']:,.2f} 元（或策略 B 出場線 {etf_card['ma5']*0.98:,.2f} 元），應立即執行止損。"
    }

    round1 = [r1_fundamental, r1_industry, r1_technical, r1_chip]

    # ─── 第二輪互相質疑（每人讀完其他三人論點，反駁其中一個，並說明是否修正立場） ───
    round2 = [
        {
            **COMMITTEE_ROLES[0],
            "target": "產業面委員",
            "rebuttal": (
                f"質疑【產業面委員】直接將隔夜費半（{sox_pct:+.2f}%）與台積電 ADR（{tsm_pct:+.2f}%）外推為今日台股全天走勢的因果鏈："
                f"隔夜 ADR 漲跌幅在早上 09:00 開盤跳空瞬間就會反應完畢（見新聞『已反映/尚未反映』標註），但 09:00 之後的盤中走勢取決於美元兌台幣（{fx_close:.2f}）與亞太盤中資金流向。"
            ),
            "stance_change": (
                f"維持【{f_stance}】但收緊進場條件：若早盤開高幅度已完全反映 ADR ({tsm_pct:+.2f}%)，但盤中台幣轉貶或失守 {etf_card['pivot_up']:,.2f} 元，則由偏多改為觀望。"
                if f_stance == "偏多" else
                f"維持【{f_stance}】：因為美債殖利率（{tnx_close:.2f}%）與 VIX（{vix_close:.2f}）顯示跨國資金仍具戒心，單憑產業消息不宜過度樂觀。"
            )
        },
        {
            **COMMITTEE_ROLES[1],
            "target": "技術面委員",
            "rebuttal": (
                f"質疑【技術面委員】過度依賴昨日靜態均線（加權 5MA {tw_card['ma5']:,.2f}、00631L 5MA {etf_card['ma5']:,.2f}）："
                f"當隔夜費半（{sox_pct:+.2f}%）與台積電 ADR（{tsm_pct:+.2f}%）出現跳空時，台股開盤往往直接越過前日高點（{tw_card['high']:,.2f}）或跌破前日低點（{tw_card['low']:,.2f}），靜態日均線在早盤前 15 分鐘容易失真。"
            ),
            "stance_change": (
                f"部分修正立場（加入技術防線）：同意若開盤跳空已反映隔夜利多，不能無腦追價；修正為「開盤後觀察 15 分鐘（09:15），確認 00631L 守穩 {etf_card['pivot_up']:,.2f} 元才維持【{i_stance}】，否則退回觀望」。"
            )
        },
        {
            **COMMITTEE_ROLES[2],
            "target": "籌碼面委員",
            "rebuttal": (
                f"質疑【籌碼面委員】以昨日三大法人買賣超（外資 {f1:+.1f} 億、投信 {t1:+.1f} 億）推論今日盤中買盤："
                f"法人單日現貨數字是『T-1 日的落後指標』。歷史上常見外資前一日大買、隔天趁美股跳空開高反手出貨（形成開高走低黑K，前日高低振幅已達 {tw_card['high']-tw_card['low']:,.0f} 點）。"
            ),
            "stance_change": (
                f"維持【{t_stance}】並強化價位紀律：昨日籌碼僅供參考，盤中一切以價格事實為準——00631L 守住 {etf_card['pivot_up']:,.2f} 元才算多方有效，跌破 {etf_card['pivot_dn']:,.2f} 元一律視為轉弱止損。"
            )
        },
        {
            **COMMITTEE_ROLES[3],
            "target": "基本面委員",
            "rebuttal": (
                f"質疑【基本面委員】用 S&P 500（{sp_pct:+.2f}%）與 10Y 殖利率（{tnx_close:.2f}%）推導 00631L 單日表現："
                f"宏觀利率是長週期變數，對 00631L 今日 2 倍槓桿的極短線殺傷力，遠不如外資台指期未平倉（{oi_pcr['fx_label']}）、融資變化（{margin['label']}）與 00631L 折溢價（{nav['label']}）的直接衝擊。"
            ),
            "stance_change": (
                f"維持【{c_stance}】並補充技術面委員的提醒：承認昨日外資現貨（{f1:+.1f} 億）可能隨隔夜盤勢翻臉，因此將「盤中期貨價差與 00631L 跌破 {etf_card['pivot_dn']:,.2f} 元」列為否決多單的硬性條件。"
            )
        },
    ]

    # ─── 主持人結論：不做票數平均，列出共識、分歧環節、關鍵變數與「如果…就…」決策樹 ───
    host_conclusion = {
        "consensus": (
            f"1. 隔夜美股（費半 {sox_pct:+.2f}%、台積電 ADR {tsm_pct:+.2f}%、NVDA {nvda_pct:+.2f}%）的漲跌力道會在 09:00 開盤跳空時第一時間反映完畢，四位委員一致同意「09:00 開盤第一刻不追價」。\n"
            f"2. 00631L 為臺灣 50 指數正向 2 倍槓桿（近 5 日實際波動與震盪耗損見技術面事實卡），持有部位必須嚴守明確止損線（{etf_card['pivot_dn']:,.2f} 元與策略 B 出場線 {etf_card['ma5']*0.98:,.2f} 元）。"
        ),
        "divergence": (
            f"核心分歧在於【09:00 開盤跳空後的日內延續性（開高走高 vs 開高走低／開低走高 vs 開低走低）】：\n"
            f"‧ 產業面委員（{i_stance}）認為半導體隔夜動能（費半 {sox_pct:+.2f}% / TSM {tsm_pct:+.2f}%）將主導權值股方向；\n"
            f"‧ 但技術面委員（{t_stance}）與籌碼面委員（{c_stance}）指出，昨日外資現貨（{f1:+.1f} 億，5日累積 {f5:+.1f} 億）與加權指數關鍵價位（{tw_card['pivot_up']:,.0f} / {tw_card['pivot_dn']:,.0f}）才是決定 09:15 後買盤是否承接或逢高倒貨的關鍵環節。"
        ),
        "key_variables": [
            f"變數 1（開盤價位定錨）：09:00~09:15 加權指數能否站穩 {tw_card['pivot_up']:,.0f} 點（對應 00631L {etf_card['pivot_up']:,.2f} 元），或跌破 {tw_card['pivot_dn']:,.0f} 點（對應 00631L {etf_card['pivot_dn']:,.2f} 元）。",
            f"變數 2（權值龍頭與匯率）：台積電現貨開盤反應 ADR（{tsm_pct:+.2f}%）後，第一根与第二根 5 分 K 是否守住開盤價，以及美元兌台幣是否維持於 {fx_close:.2f} 以下。",
            f"變數 3（ETF 折溢價與期貨）：00631L 盤中即時折溢價率（目前 {nav['label']}）是否過度溢價（> +0.5%），以及外資期貨未平倉（{oi_pcr['fx_label']}）在盤中正逆價差的變化。"
        ],
        "decision_tree": [
            f"🟢 【情境一：順勢偏多／續抱條件】如果今日開盤後 09:15 以前，加權指數守在 {tw_card['pivot_up']:,.0f} 點以上、00631L 5 分 K 守穩 {etf_card['pivot_up']:,.2f} 元（且即時溢價率 ≤ +0.5%），上方壓力看 {etf_card['res_1']:,.2f} 元與 {etf_card['res_2']:,.2f} 元；若進一步突破策略 B 強勢線 {etf_card['ma5']*1.04:,.2f} 元，可依策略 B 規則順勢進場或續抱。",
            f"🟠 【情境二：開高走低／誘多規避條件】如果早盤因 ADR（{tsm_pct:+.2f}%）跳空開高，但 09:15 後 00631L 跌破開盤第一根 5 分 K 低點或失守 {etf_card['pivot_up']:,.2f} 元，代表隔夜利多「已反映」且遭遇法人逢高調節，空手者一律不買，持有者逢高減碼。",
            f"🔵 【情境三：開低走高／低檔承接觀察】如果早盤開在 {etf_card['pivot_dn']:,.2f} 元以下，但下檔在第一支撐位 {etf_card['sup_1']:,.2f} 元（對應加權 {tw_card['sup_1']:,.0f} 點）出現長下影線且 09:30 後站回均價線，持有者暫不砍在最低點，空手者維持觀望等收復 5MA（{etf_card['ma5']:,.2f} 元）再議。",
            f"🔴 【情境四：開低走低／無條件止損條件】如果盤中加權指數跌破 {tw_card['pivot_dn']:,.0f} 點且 00631L 跌破 {etf_card['pivot_dn']:,.2f} 元（或觸及策略 B 出場線 {etf_card['ma5']*0.98:,.2f} 元 / 支撐位 {etf_card['sup_1']:,.2f} 元），空手者絕對不做，持有者無條件執行止損出場。"
        ]
    }

    return round1, round2, host_conclusion

# ───────────────────────── 第七節：17:00 復盤紀錄與 6 天滾動存檔管理 ─────────────────────────
def load_rolling_archive():
    if os.path.exists(ARCHIVE_FILE):
        try:
            with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_rolling_archive(store, valid_6_date_strs):
    """只保留最近 6 個交易日的紀錄，超過 6 天的舊紀錄自動滾動刪除"""
    pruned = {k: store[k] for k in valid_6_date_strs if k in store}
    try:
        with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
            json.dump(pruned, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return pruned

def build_1700_review_record(target_d, now_dt, tw_df, etf_df, briefing, round1, host_conclusion):
    """
    【第七節：復盤紀錄（每天下午 5 點準時更新）】
    檢查該交易日是否已過當日 17:00：
    - 若尚未到當日 17:00：顯示「今日 17:00 準時更新復盤紀錄」
    - 若已過當日 17:00（或為過去 6 天內已完成之交易日）：對照當天實際開盤與收盤，檢視早會推理與決策樹品質（絕不調參）。
    """
    if target_d == now_dt.date() and now_dt.time() < dtime(17, 0):
        return {
            "ready": False,
            "msg": f"⏳ 復盤紀錄將於今日（{target_d:%Y/%m/%d}）下午 17:00 準時更新存檔。"
        }

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
        tree_hit = f"觸發【情境一（順勢偏多分支）】：00631L 收盤 {etf_c:,.2f} 元站穩條件上沿 {p_up:,.2f} 元。"
    elif etf_o > etf_prev_c and etf_c < etf_o:
        tree_hit = f"觸發【情境二（開高走低規避分支）】：00631L 早盤開 {etf_o:,.2f} 元（{etf_gap:+.2f}%），但盤中實體拉回 {etf_intra:+.2f}% 收 {etf_c:,.2f} 元，驗證『09:00 不追高』紀律。"
    elif etf_c <= p_dn:
        tree_hit = f"觸發【情境四（風控止損/觀望分支）】：00631L 收盤 {etf_c:,.2f} 元落於條件下沿 {p_dn:,.2f} 元之下，空手觀望與停損紀律有效保護部位。"
    else:
        tree_hit = f"觸發【區間整理分支】：00631L 全天介於條件區間（開 {etf_o:,.2f} / 收 {etf_c:,.2f}），盤中實體變動 {etf_intra:+.2f}%。"

    member_reviews = []
    for m in round1:
        st_m = m["stance"]
        if (st_m == "偏多" and etf_day > 0.2 and etf_intra >= 0) or (st_m == "偏空" and etf_day < -0.2) or (st_m == "觀望" and abs(etf_intra) < 0.8):
            verdict = "推理方向與當日盤勢相符"
        elif st_m == "偏多" and etf_o > etf_prev_c and etf_c < etf_o:
            verdict = "跳空方向相符，但忽略開高後獲利了結賣壓（如第二輪質疑所指）"
        else:
            verdict = "因果鏈受盤中反向資金干擾，需依賴條件式價位止損保護"
        member_reviews.append(f"‧ <b>{m['name']}（早會結論：{st_m}）</b>：{verdict}")

    return {
        "ready": True,
        "updated_at": f"{target_d:%Y/%m/%d} 17:00:00",
        "tw_o": tw_o, "tw_h": tw_h, "tw_l": tw_l, "tw_c": tw_c,
        "tw_gap": tw_gap, "tw_intra": tw_intra, "tw_day": tw_day,
        "etf_o": etf_o, "etf_h": etf_h, "etf_l": etf_l, "etf_c": etf_c,
        "etf_gap": etf_gap, "etf_intra": etf_intra, "etf_day": etf_day,
        "state_4": state_4,
        "tree_hit": tree_hit,
        "member_reviews": member_reviews,
    }

# ───────────────────────── 組裝單日完整早會簡報與渲染 HTML ─────────────────────────
def build_meeting_briefing_for_date(target_d, tw_df, etf_df, days_flow, is_latest_day):
    """組裝指定交易日 target_d 08:30 盤前主持人簡報所需的所有客觀事實數據"""
    tw_dts = list(pd.DatetimeIndex(tw_df.index).tz_localize(None).date)
    idx_pos = tw_dts.index(target_d) if target_d in tw_dts else len(tw_dts) - 1
    prev_d = tw_dts[idx_pos - 1] if idx_pos > 0 else (target_d - timedelta(days=1))

    # 計算上次會議到本次會議的時間窗（週一早會包含整個週末 72 小時）
    window_hours = max(24, int((datetime.combine(target_d, dtime(8, 30)) - datetime.combine(prev_d, dtime(8, 30))).total_seconds() // 3600))

    # 技術面事實卡（嚴格只取 prev_d 收盤狀態，零未來資訊）
    tw_card = compute_tech_fact_card(tw_df, prev_d, "加權指數 (^TWII)", is_etf=False)
    etf_card = compute_tech_fact_card(etf_df, prev_d, "元大台灣50正2 (00631L.TW)", is_etf=True)

    # 對齊 prev_d 之三大法人現貨買賣超與融資融券
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
    oi_pcr_info = fetch_taifex_oi_and_pcr_for_date(prev_d.strftime("%Y%m%d")) if is_latest_day else {
        "fx_oi_ok": False, "fx_label": "未取得（歷史單日期貨OI未快取）",
        "pcr_ok": False, "pcr_label": "未取得（歷史單日P/C比未快取）"
    }
    nav_info = fetch_00631l_nav_info() if is_latest_day else {"ok": False, "label": "未取得（非當日即時盤前）"}
    # 第三節明確規定：期交所夜盤資料未確認穩定來源前，不假設它可用，誠實標示「未取得」
    night_info = {"ok": False, "label": "未取得（尚未確認穩定可抓之期交所夜盤歷史/即時源，不假設可用）"}

    # 對齊 target_d 08:30 前之隔夜美股 7 大指標
    def _us_val_before(sym):
        u_df = load_daily(sym, "6mo")
        if u_df.empty or len(u_df) < 2:
            return 0.0, 0.0, "--"
        u_dts = pd.DatetimeIndex(u_df.index).tz_localize(None).date
        # 美股隔夜收盤日期為 target_d 的前一日（或跨週末往前最近一日）
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
        "date_str": us_d_str,
        "sox_close": sox_c, "sox_pct": sox_pct,
        "tsm_close": tsm_c, "tsm_pct": tsm_pct,
        "nvda_close": nvda_c, "nvda_pct": nvda_pct,
        "sp_close": sp_c, "sp_pct": sp_pct,
        "vix_close": vix_c, "vix_pct": vix_pct,
        "tnx_close": tnx_c, "tnx_pct": tnx_pct,
        "fx_close": fx_c, "fx_pct": fx_pct,
        "adr_prem": adr_prem,
    }

    news_list = fetch_and_select_top5_news(window_hours, sox_pct, tsm_pct, nvda_pct, sp_pct)

    return {
        "target_d": target_d,
        "prev_d": prev_d,
        "window_hours": window_hours,
        "tw_card": tw_card,
        "etf_card": etf_card,
        "flow": flow_info,
        "margin": margin_info,
        "oi_pcr": oi_pcr_info,
        "nav": nav_info,
        "night": night_info,
        "us": us_info,
        "news_list": news_list,
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
    nt = briefing["night"]
    us = briefing["us"]
    news_list = briefing["news_list"]

    # 主持人挑選 5 則最重要新聞 HTML
    news_cards_html = ""
    for idx, n in enumerate(news_list, 1):
        p_col = "#38bdf8" if "已反映" in n["priced_tag"] else "#f59e0b"
        b_tag = "✅ 含內文摘要" if n["has_body"] else "⚠️ 僅憑標題判斷"
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

    # 第一輪：四位委員發言 HTML
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
            f"</div>"
            f"</div></div>"
        )

    # 第二輪：互相質疑 HTML
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

    # 主持人決策樹 HTML
    kv_li = "".join(f"<li>{x}</li>" for x in host_conclusion["key_variables"])
    dt_li = "".join(f"<div class='tree-item'>{x}</div>" for x in host_conclusion["decision_tree"])

    # 17:00 復盤紀錄 HTML
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
        review_html = (
            f"<div class='msg-row host' style='border-color:#64748b'>"
            f"<div class='avatar' style='background:#475569;color:#fff'>復</div>"
            f"<div style='flex:1'>{review_rec['msg']}</div></div>"
        )

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
.eng-tag{{font-size:.82rem;color:#fca5a5;background:rgba(239,68,68,.16);border:1px solid rgba(239,68,68,.4);padding:2px 9px;border-radius:6px;font-weight:700}}
.b-time{{font-size:.83rem;color:#8a8699;margin-left:auto}}
.v-badge{{padding:3px 12px;border-radius:99px;font-weight:800;font-size:.9rem}}
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
        ‧ <b>00631L 折溢價與量能</b>：{nv['label']} ｜ <b>昨晚台指期夜盤與日盤差距</b>：{nt['label']}<br>
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

def vote_page():
    with st.spinner("檢查交易日曆與 08:30 排程狀態，載入雙標的技術面事實卡、白名單新聞與 6 日滾動復盤存檔…"):
        tw_df = load_daily(INDEX_TICKER, "3y")
        etf_df = load_daily(ETF_TICKER, "3y")
        days_flow = last_15_flows()

    if tw_df.empty or etf_df.empty:
        st.error("無法取得加權指數或 00631L 日線資料。")
        return

    sched = get_schedule_state(tw_df)
    archive_dates = sched["archive_dates"]
    valid_6_strs = [d.strftime("%Y-%m-%d") for d in archive_dates]
    store = load_rolling_archive()

    with st.container(key="vote_card"):
        st.markdown(
            "<div class='fl-h'>🤖 08:30 盤前結構化早會 ＆ 17:00 盤後復盤紀錄中心"
            "<small>只陳述事實與因果鏈 · 兩輪交叉質疑 · 條件式決策樹 · 6 日滾動存檔</small></div>",
            unsafe_allow_html=True
        )

        # 醒目顯示今日是否召開早會（解決「今天週六休市怎麼會有會議」的問題）
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

        # 更新並滾動修剪 6 日存檔 JSON
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
                    "加權全天": rec["tw_day_pct"],
                    "00631L全天": rec["etf_day_pct"],
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
        view = pick("頁面", ["大盤", "策略", "投票"], "view")
with st.container(key="body"):
    if view == "大盤":
        market_page()
    elif view == "策略":
        strategy_page()
    else:
        vote_page()
