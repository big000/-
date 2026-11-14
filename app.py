import json, time, re
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

# 四種日內狀態標準配色與定義
STATE_META = {
    "開高走高": {"col": "#ff4d5a", "bg": "rgba(255,77,90,.18)", "desc": "開盤 > 昨收 且 收盤 ≥ 開盤（跳空續攻紅K）"},
    "開高走低": {"col": "#f59e0b", "bg": "rgba(245,158,11,.18)", "desc": "開盤 > 昨收 但 收盤 < 開盤（開高出貨黑K）"},
    "開低走高": {"col": "#38bdf8", "bg": "rgba(56,189,248,.18)", "desc": "開盤 ≤ 昨收 但 收盤 ≥ 開盤（低接承接紅K）"},
    "開低走低": {"col": "#22c55e", "bg": "rgba(34,197,94,.18)", "desc": "開盤 ≤ 昨收 且 收盤 < 開盤（跳空殺低黑K）"},
}
 FOUR_STATES = ["開高走高", "開高走低", "開低走高", "開低走低"]

st.markdown("""<style>
header[data-testid=stHeader],footer,#MainMenu{display:none}
.stApp{background:linear-gradient(135deg,#f8c8e6 0%,#dcb8fb 52%,#b9a6f7 100%);background-attachment:fixed}
.block-container{padding:0!important;max-width:100%!important;overflow-x:hidden}

/* 標題列：整條黑底內，標題與右側按鈕都垂直置中 */
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

# ───────────────────────── 資料模組 ─────────────────────────
def _clean(d):
    if d is None or d.empty:
        return pd.DataFrame()
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
    return d[d.index.date == d.index[-1].date()]

@st.cache_data(ttl=60, show_spinner=False)
def load_5m_all(sym):
    """5 分 K（Yahoo 最多提供近 60 天），給策略模擬與分時圖使用"""
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
        time.sleep(0.3)
        if r.get("stat") != "OK": return None
        t = {row[0]: int(row[3].replace(",", "")) for row in r["data"]}
        f = lambda k: sum(v for n, v in t.items() if n.startswith(k))
        return {"外資": f("外資"), "投信": f("投信"), "自營": f("自營商"), "ymd": ymd}
    except Exception:
        return None

def last_10_flows():
    out, d = [], datetime.now(TZ)
    for _ in range(30):
        if len(out) == 10: break
        if d.weekday() < 5:
            x = twse_day(d.strftime("%Y%m%d"))
            if x:
                x["d"] = d.strftime("%m/%d")      # 固定 MM/DD，例如 01/02
                out.append(x)
        d = d - pd.Timedelta(days=1)
    return out[::-1]

# ───────────────────────── 交易日曆（證交所休市日） ─────────────────────────
@st.cache_data(ttl=86400, show_spinner=False)
def tw_holidays():
    """從證交所 OpenAPI 官方端點抓取休市日 {date: 名稱}"""
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule", timeout=8)
        if r.status_code != 200: raise ValueError("API Error")
        out = {}
        for row in r.json():
            name = str(row.get("Name", ""))
            desc = str(row.get("Description", ""))
            if "開始交易" in name or "最後交易" in name or "開始交易" in desc or "最後交易" in desc: 
                continue
            d_str = str(row.get("Date", "")).strip().replace("-", "").replace("/", "")
            if len(d_str) == 8 and d_str.isdigit():
                y, m, d = int(d_str[:4]), int(d_str[4:6]), int(d_str[6:8])
                out[date(y, m, d)] = name or desc or "休市"
        return out
    except Exception:
        raise ValueError("Fetch failed")

def future_trading_days(after, k):
    """after 之後的第 1~k 個交易日 → (日期清單, 期間遇到的平日假日 {date: 名稱}, 假日資料是否完整)"""
    hol, ok = {}, True
    try:
        hol = tw_holidays()
    except Exception:
        ok = False
        
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

# ───────────────────────── 圖表模組(TradingView) ─────────────────────────
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
    'let chart;'
    'addEventListener("resize",()=>{chart.applyOptions({width:el.clientWidth});window.redraw&&redraw()});'
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
    return daily.Close[dts < d.index[-1].date()].iloc[-1]

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
    daily = load_daily("^TWII")
    with st.container(key="chart_card"):
        l, r = st.columns([5, 2], vertical_alignment="center")
        l.markdown("<div class='ttl'>加權指數<span>^TWII</span></div>", unsafe_allow_html=True)
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

# ───────────────────────── 頁面二：策略 B ─────────────────────────
SYM = "00631L.TW"

@st.cache_data(ttl=300, show_spinner=False)
def strategy_data():
    """回傳 (日線 df, {日期: [(O,H,L,C), ...] 5 分 K})。今日日線用 5 分 K 校正高低收。"""
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

# ───────────────────────── 頁面三：AI 投研早會與四態量化分析 ─────────────────────────
# 修正模型名稱與實際呼叫的 Model ID 完全一致，杜絕標示不實
AI_AGENTS = [
    {"id": "chatgpt",  "name": "ChatGPT",  "model_id": "gpt-4o-mini",              "secret_key": "OPENAI_API_KEY",    "short": "GPT", "color": "#10a37f", "role": "國際總經、利率匯率與跨國資金流向"},
    {"id": "deepseek", "name": "DeepSeek", "model_id": "deepseek-chat",            "secret_key": "DEEPSEEK_API_KEY",  "short": "DS",  "color": "#3b82f6", "role": "歷史四態條件機率、波動率與動能微結構"},
    {"id": "gemini",   "name": "Gemini",   "model_id": "gemini-2.5-flash",         "secret_key": "GEMINI_API_KEY",    "short": "GEM", "color": "#8b5cf6", "role": "台灣 AI 供應鏈新聞實證與台積電 ADR 溢價套利"},
    {"id": "claude",   "name": "Claude",   "model_id": "claude-3-5-sonnet-latest", "secret_key": "ANTHROPIC_API_KEY", "short": "CLD", "color": "#d97706", "role": "反方論證（Devil's Advocate）、籌碼背離與開高走低風控"},
]

def get_meeting_session_info():
    """判斷當前最新的 08:30 盤前會議所屬交易日與前次會議時間"""
    now = datetime.now(TZ)
    hol = {}
    try:
        hol = tw_holidays()
    except Exception:
        pass

    def is_trading_day(d):
        return d.weekday() < 5 and d not in hol

    cur_d = now.date()
    if is_trading_day(cur_d) and (now.hour > 8 or (now.hour == 8 and now.minute >= 30)):
        target_d = cur_d
        status = "今日 08:30 盤前會議場次"
    else:
        if is_trading_day(cur_d) and (now.hour < 8 or (now.hour == 8 and now.minute < 30)):
            status = "今日 08:30 尚未開會（目前顯示前次交易日紀錄）"
        else:
            status = "休市期間（目前顯示最近一個交易日紀錄）"
        d = cur_d - timedelta(days=1)
        while not is_trading_day(d):
            d -= timedelta(days=1)
        target_d = d

    prev_d = target_d - timedelta(days=1)
    while not is_trading_day(prev_d):
        prev_d -= timedelta(days=1)

    return target_d, prev_d, status

def classify_4state(open_p, close_p, prev_c):
    """將單日 K 線嚴格分類為四種狀態"""
    is_gap_up = open_p > prev_c
    is_intra_up = close_p >= open_p
    if is_gap_up and is_intra_up:
        return "開高走高"
    elif is_gap_up and not is_intra_up:
        return "開高走低"
    elif not is_gap_up and is_intra_up:
        return "開低走高"
    else:
        return "開低走低"

@st.cache_data(ttl=900, show_spinner=False)
def fetch_expanded_global_context(session_key):
    """
    抓取完整總經、匯率、美債、VIX、美股科技指標與真實 Google News RSS（移除假新聞池）
    並回傳各資產最新收盤日期以供檢核時間對齊。
    """
    tickers = {
        "S&P 500": "^GSPC",
        "費城半導體": "^SOX",
        "台積電 ADR": "TSM",
        "NVIDIA": "NVDA",
        "美債10Y殖利率": "^TNX",
        "恐慌指數 VIX": "^VIX",
        "美元兌台幣": "USDTWD=X",
        "台積電(2330)": "2330.TW"
    }
    us_mkt = {}
    for name, sym in tickers.items():
        try:
            d = _clean(yf.download(sym, period="10d", interval="1d", progress=False))
            if len(d) >= 2:
                c1, c0 = float(d.Close.iloc[-1]), float(d.Close.iloc[-2])
                dt_str = pd.Timestamp(d.index[-1]).strftime("%m/%d")
                us_mkt[name] = {
                    "close": c1,
                    "prev": c0,
                    "pct": (c1 / c0 - 1) * 100,
                    "diff": c1 - c0,
                    "date": dt_str
                }
        except Exception:
            pass

    # 計算台積電 ADR 換算台股溢價率 (1 ADR = 5 股 2330.TW)
    tsm_adr = us_mkt.get("台積電 ADR", {}).get("close")
    fx_twd = us_mkt.get("美元兌台幣", {}).get("close")
    tsmc_tw = us_mkt.get("台積電(2330)", {}).get("close")
    adr_premium = None
    adr_implied_twd = None
    if tsm_adr and fx_twd and tsmc_tw and tsmc_tw > 0:
        adr_implied_twd = (tsm_adr * fx_twd) / 5.0
        adr_premium = (adr_implied_twd / tsmc_tw - 1.0) * 100.0

    # 抓取真實 Google News RSS（包含標題、真實連結、發布時間、內文摘要）
    headlines = []
    seen_titles = set()
    rss_urls = [
        "https://news.google.com/rss/search?q=%E5%8F%B0%E7%A9%8D%E9%9B%BB+OR+%E8%B2%BB%E5%8D%8A+OR+%E8%BC%9D%E9%81%94+OR+%E8%81%AF%E6%BA%96%E6%9C%83+OR+%E5%8F%B0%E8%82%A1+when:2d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
        "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    ]
    for url in rss_urls:
        try:
            r = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                for item in root.findall(".//item")[:15]:
                    raw_title = item.find("title").text if item.find("title") is not None else ""
                    link = item.find("link").text if item.find("link") is not None else ""
                    desc = item.find("description").text if item.find("description") is not None else ""
                    pub = item.find("pubDate").text if item.find("pubDate") is not None else ""
                    source_el = item.find("source")
                    src_name = source_el.text if source_el is not None else "新聞來源"
                    title = re.sub(r"\s*-\s*[^-]+$", "", raw_title).strip()
                    clean_desc = re.sub(r"<[^>]+>", " ", desc or "")
                    clean_desc = re.sub(r"&[a-zA-Z0-9#]+;", " ", clean_desc)
                    clean_desc = re.sub(r"\s+", " ", clean_desc).strip()
                    if title and title not in seen_titles and len(title) > 8 and link:
                        seen_titles.add(title)
                        headlines.append({
                            "title": title,
                            "url": link,
                            "source": src_name,
                            "pub": pub[:22] if pub else "近期發布",
                            "snippet": clean_desc[:160] if clean_desc and clean_desc != title else "（RSS 僅提供標題，請點擊連結閱讀原文）"
                        })
        except Exception:
            pass
        if len(headlines) >= 10:
            break

    return us_mkt, adr_premium, adr_implied_twd, headlines[:10]

@st.cache_data(ttl=1800, show_spinner=False)
def calc_historical_4state_probs(cur_us_tech_pct, cur_bias_5ma, cur_tw_prev_pct):
    """
    【量化客觀歷史條件機率引擎】
    使用過去 3 年 ^TWII、^SOX、TSM 的真實日 K 資料（以日期對齊），
    計算在當前市場環境下，「開高走高、開高走低、開低走高、開低走低」四種狀態的真實歷史條件機率。
    """
    tw = load_daily("^TWII", "3y").copy()
    sox = load_daily("^SOX", "3y").copy()
    tsm = load_daily("TSM", "3y").copy()

    if tw.empty or len(tw) < 60:
        return None

    tw["date"] = pd.DatetimeIndex(tw.index).tz_localize(None).date
    tw["PrevClose"] = tw["Close"].shift(1)
    tw["PrevPct"] = (tw["PrevClose"] / tw["Close"].shift(2) - 1) * 100
    tw["MA5_prev"] = tw["Close"].rolling(5).mean().shift(1)
    tw["Bias5_prev"] = (tw["PrevClose"] / tw["MA5_prev"] - 1) * 100
    tw["GapPct"] = (tw["Open"] / tw["PrevClose"] - 1) * 100
    tw["IntraPct"] = (tw["Close"] / tw["Open"] - 1) * 100
    tw["DayPct"] = (tw["Close"] / tw["PrevClose"] - 1) * 100

    # 對齊美股隔夜漲跌幅：台股 T 日開盤前對應的是美股 T-1 日收盤漲跌幅
    us_map = {}
    if not sox.empty and not tsm.empty:
        sox_d = pd.Series(sox["Close"].pct_change().values * 100, index=pd.DatetimeIndex(sox.index).tz_localize(None).date)
        tsm_d = pd.Series(tsm["Close"].pct_change().values * 100, index=pd.DatetimeIndex(tsm.index).tz_localize(None).date)
        for d_tw in tw["date"]:
            # 往前找最近一個美股交易日（最多往前找 4 天以跨過週末）
            for offset in range(1, 5):
                d_us = d_tw - timedelta(days=offset)
                if d_us in sox_d and pd.notna(sox_d[d_us]):
                    s_val = float(sox_d[d_us])
                    t_val = float(tsm_d.get(d_us, s_val))
                    us_map[d_tw] = 0.5 * s_val + 0.5 * t_val
                    break

    tw["US_Tech"] = tw["date"].map(us_map)
    df = tw.dropna(subset=["PrevClose", "MA5_prev", "US_Tech", "Open", "Close"]).copy()
    df["State"] = [classify_4state(o, c, p) for o, c, p in zip(df["Open"], df["Close"], df["PrevClose"])]

    # 定義當前三大環境條件（Regime Conditions）
    # 條件 1：隔夜美股半導體動能（強勢 > +0.5% / 弱勢 < -0.5% / 中性震盪）
    if cur_us_tech_pct > 0.5:
        c1_mask = df["US_Tech"] > 0.5
        c1_desc = f"隔夜費半/TSM 偏強 ({cur_us_tech_pct:+.2f}% > +0.5%)"
    elif cur_us_tech_pct < -0.5:
        c1_mask = df["US_Tech"] < -0.5
        c1_desc = f"隔夜費半/TSM 偏弱 ({cur_us_tech_pct:+.2f}% < -0.5%)"
    else:
        c1_mask = (df["US_Tech"] >= -0.5) & (df["US_Tech"] <= 0.5)
        c1_desc = f"隔夜費半/TSM 震盪 ({cur_us_tech_pct:+.2f}% 介於 ±0.5%)"

    # 條件 2：台股前日收盤與 5MA 正負乖離狀態
    if cur_bias_5ma >= 0:
        c2_mask = df["Bias5_prev"] >= 0
        c2_desc = f"台股位於 5MA 之上 (乖離 {cur_bias_5ma:+.2f}%)"
    else:
        c2_mask = df["Bias5_prev"] < 0
        c2_desc = f"台股位於 5MA 之下 (乖離 {cur_bias_5ma:+.2f}%)"

    # 條件 3：台股前一日自身漲跌方向
    if cur_tw_prev_pct >= 0:
        c3_mask = df["PrevPct"] >= 0
        c3_desc = f"前日台股收紅 ({cur_tw_prev_pct:+.2f}%)"
    else:
        c3_mask = df["PrevPct"] < 0
        c3_desc = f"前日台股收黑 ({cur_tw_prev_pct:+.2f}%)"

    # 優先使用「三條件完全吻合」樣本；若樣本數 < 20，退回「前兩條件吻合」確保統計顯著性
    sub = df[c1_mask & c2_mask & c3_mask]
    cond_label = f"{c1_desc} ＋ {c2_desc} ＋ {c3_desc}"
    if len(sub) < 20:
        sub = df[c1_mask & c2_mask]
        cond_label = f"{c1_desc} ＋ {c2_desc}"
    if len(sub) < 15:
        sub = df[c1_mask]
        cond_label = c1_desc

    n_sample = len(sub)
    n_total = len(df)

    probs = {}
    base_probs = {}
    stats_detail = {}
    for st_name in FOUR_STATES:
        g = sub[sub["State"] == st_name]
        cnt = len(g)
        probs[st_name] = round(cnt / n_sample * 100, 1) if n_sample > 0 else 25.0
        base_probs[st_name] = round(len(df[df["State"] == st_name]) / n_total * 100, 1)
        stats_detail[st_name] = {
            "count": cnt,
            "avg_gap": round(float(g["GapPct"].mean()), 2) if cnt > 0 else 0.0,
            "avg_intra": round(float(g["IntraPct"].mean()), 2) if cnt > 0 else 0.0,
            "avg_day": round(float(g["DayPct"].mean()), 2) if cnt > 0 else 0.0,
        }

    top_state = max(probs.items(), key=lambda x: x[1])[0]
    # 近期過去 5 個交易日實際發生的四態驗證紀錄
    recent_5 = []
    for _, r in df.tail(5).iterrows():
        recent_5.append({
            "日期": r["date"].strftime("%m/%d"),
            "隔夜費半/TSM均值": f"{r['US_Tech']:+.2f}%",
            "開盤跳空": f"{r['GapPct']:+.2f}%",
            "盤中實體(收vs開)": f"{r['IntraPct']:+.2f}%",
            "全天漲跌": f"{r['DayPct']:+.2f}%",
            "實際日內四態": r["State"]
        })

    return {
        "n_total": n_total,
        "n_sample": n_sample,
        "cond_label": cond_label,
        "probs": probs,
        "base_probs": base_probs,
        "detail": stats_detail,
        "top_state": top_state,
        "avg_gap_all": round(float(sub["GapPct"].mean()), 2),
        "avg_intra_all": round(float(sub["IntraPct"].mean()), 2),
        "win_intra_up": round(probs["開高走高"] + probs["開低走高"], 1),  # 盤中收紅K機率
        "recent_5": recent_5[::-1]
    }

def _call_llm_strict(agent, prompt):
    """
    嚴格呼叫真實 LLM API，絕不靜默切換至規則模板。
    回傳: (is_success: bool, actual_model_id: str, error_reason: str, parsed_json: dict | None)
    """
    sec = st.secrets if hasattr(st, "secrets") else {}
    k_name = agent["secret_key"]
    if k_name not in sec or not str(sec[k_name]).strip():
        return False, "未連線", f"未設定 st.secrets['{k_name}']，不參與投票", None

    api_key = str(sec[k_name]).strip()
    aid = agent["id"]
    try:
        if aid == "chatgpt":
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": agent["model_id"],
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3
                },
                timeout=20
            )
            if resp.status_code != 200:
                return False, agent["model_id"], f"HTTP {resp.status_code}", None
            r = resp.json()
            actual_model = r.get("model", agent["model_id"])
            data = json.loads(r["choices"][0]["message"]["content"])
            return True, actual_model, "API 正常回應", data

        if aid == "deepseek":
            resp = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": agent["model_id"],
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3
                },
                timeout=20
            )
            if resp.status_code != 200:
                return False, agent["model_id"], f"HTTP {resp.status_code}", None
            r = resp.json()
            actual_model = r.get("model", agent["model_id"])
            data = json.loads(r["choices"][0]["message"]["content"])
            return True, actual_model, "API 正常回應", data

        if aid == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{agent['model_id']}:generateContent?key={api_key}"
            resp = requests.post(
                url,
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3}
                },
                timeout=20
            )
            if resp.status_code != 200:
                return False, agent["model_id"], f"HTTP {resp.status_code}", None
            r = resp.json()
            actual_model = r.get("modelVersion", agent["model_id"])
            txt = r["candidates"][0]["content"]["parts"][0]["text"]
            return True, actual_model, "API 正常回應", json.loads(txt)

        if aid == "claude":
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={
                    "model": agent["model_id"],
                    "max_tokens": 1000,
                    "temperature": 0.3,
                    "messages": [{"role": "user", "content": prompt + "\n請只輸出純 JSON，不要加 Markdown 語法。"}]
                },
                timeout=20
            )
            if resp.status_code != 200:
                return False, agent["model_id"], f"HTTP {resp.status_code}", None
            r = resp.json()
            actual_model = r.get("model", agent["model_id"])
            return True, actual_model, "API 正常回應", json.loads(r["content"][0]["text"])

    except Exception as e:
        return False, agent["model_id"], f"呼叫例外：{type(e).__name__}", None

    return False, agent["model_id"], "未知原因", None

def _build_specialized_prompt(agent, target_date_str, tw_info, flow_info, us_mkt, adr_prem, headlines, quant_4state):
    """
    為四位 AI 委員分別注入「不同維度的專屬資料子集」與「必答核心問題」，
    降低模型間的共線性，並強制要求預測「開高走高、開高走低、開低走高、開低走低」四態機率。
    """
    aid = agent["id"]
    sp = us_mkt.get("S&P 500", {})
    sox = us_mkt.get("費城半導體", {})
    tsm = us_mkt.get("台積電 ADR", {})
    nvda = us_mkt.get("NVIDIA", {})
    tnx = us_mkt.get("美債10Y殖利率", {})
    vix = us_mkt.get("恐慌指數 VIX", {})
    fx = us_mkt.get("美元兌台幣", {})

    news_block = "\n".join(
        f"- [{h['source']} | {h['pub']}] {h['title']} (摘要：{h['snippet']}) URL:{h['url']}"
        for h in headlines[:6]
    ) or "（目前無 RSS 新聞）"

    if aid == "chatgpt":
        spec_context = (
            f"【你的專屬研究維度：國際總經、利率匯率與外資資金流向】\n"
            f"- 標普 500：{sp.get('pct', 0):+.2f}% | 美國 10 年期公債殖利率：{tnx.get('close', 0):.2f}% (變動 {tnx.get('pct', 0):+.2f}%)\n"
            f"- 美元兌新台幣匯率：{fx.get('close', 0):.2f} ({fx.get('pct', 0):+.2f}%)\n"
            f"- 外資現貨動向：昨買賣超 {flow_info['f1']:+.1f} 億｜近 5 日累積 {flow_info['f5']:+.1f} 億｜近 10 日累積 {flow_info['f10']:+.1f} 億\n"
            f"【你必須回答的核心問題】美債殖利率與匯率環境是否支持外資延續買盤？今日開盤後外資在權值股是順勢加碼（走高）還是趁跳空提款（走低）？"
        )
    elif aid == "deepseek":
        q_probs = quant_4state["probs"] if quant_4state else {}
        spec_context = (
            f"【你的專屬研究維度：量化動能、波動率微結構與歷史統計】\n"
            f"- 費城半導體：{sox.get('pct', 0):+.2f}% | NVIDIA：{nvda.get('pct', 0):+.2f}% | VIX 恐慌指數：{vix.get('close', 0):.2f} ({vix.get('pct', 0):+.2f}%)\n"
            f"- 台股昨收：{tw_info['close']:,.2f} ({tw_info['pct']:+.2f}%)，5MA 乖離率：{tw_info['bias5']:+.2f}%\n"
            f"- 系統過去3年同環境歷史樣本 ({quant_4state['n_sample'] if quant_4state else 0}日) 客觀統計分布：開高走高 {q_probs.get('開高走高',25)}%、開高走低 {q_probs.get('開高走低',25)}%、開低走高 {q_probs.get('開低走高',25)}%、開低走低 {q_probs.get('開低走低',25)}%\n"
            f"【你必須回答的核心問題】結合費半動能與 VIX 波動率，今日開盤跳空幅度是否已過度反應？統計上今日出現均值回歸（開高走低／開低走高）還是趨勢延續的機率較高？"
        )
    elif aid == "gemini":
        prem_str = f"{adr_prem:+.2f}%" if adr_prem is not None else "N/A"
        spec_context = (
            f"【你的專屬研究維度：台灣 AI 供應鏈新聞實證與台積電 ADR 折溢價】\n"
            f"- 台積電 ADR 隔夜漲跌：{tsm.get('pct', 0):+.2f}%（換算台股溢價率：{prem_str}）| NVIDIA：{nvda.get('pct', 0):+.2f}%\n"
            f"- 投信動向：昨買賣超 {flow_info['t1']:+.1f} 億｜近 5 日累積 {flow_info['t5']:+.1f} 億｜近 10 日累積 {flow_info['t10']:+.1f} 億\n"
            f"- 國際財經新聞與摘要：\n{news_block}\n"
            f"【你必須回答的核心問題】上述新聞對台積電與台灣 AI 伺服器鏈是實質利多還是已提前反應？台積電開盤反應 ADR 後，盤中內資投信能否承接推動走高？"
        )
    else:  # claude
        spec_context = (
            f"【你的專屬研究維度：反方論證（Devil's Advocate）、籌碼背離與風控】\n"
            f"- 台股前日漲跌 {tw_info['pct']:+.2f}% (5MA 乖離 {tw_info['bias5']:+.2f}%) vs 隔夜費半 {sox.get('pct', 0):+.2f}%、TSM {tsm.get('pct', 0):+.2f}%\n"
            f"- 三大法人籌碼結構：外資昨 {flow_info['f1']:+.1f} 億 (5日 {flow_info['f5']:+.1f} 億)｜投信昨 {flow_info['t1']:+.1f} 億 (5日 {flow_info['t5']:+.1f} 億)｜自營商昨 {flow_info['z1']:+.1f} 億 (5日 {flow_info['z5']:+.1f} 億)\n"
            f"- 新聞列表：\n{news_block}\n"
            f"【你必須回答的核心問題】請專門挑出市場過度樂觀或過度悲觀的盲點！昨日台股是否已「偷跑先反應」？今日早盤若跳空開高，是否面臨極高的「開高走低」出貨風險？"
        )

    schema_instruction = (
        f"你是 {agent['name']} ({agent['role']})。現在進行 {target_date_str} 08:30 台股加權指數 (^TWII) 盤前研究。\n"
        f"{spec_context}\n\n"
        "請針對今日台股「開盤跳空（Open vs 昨收）」與「盤中實體走勢（Close vs Open）」組合成的四種狀態進行機率評估：\n"
        "1. 開高走高（開盤>昨收，收盤>=開盤）\n"
        "2. 開高走低（開盤>昨收，收盤<開盤）\n"
        "3. 開低走高（開盤<=昨收，收盤>=開盤）\n"
        "4. 開低走低（開盤<=昨收，收盤<開盤）\n"
        "請嚴格輸出 JSON 格式（四種狀態機率加總必須等於 100）：\n"
        "{\n"
        '  "vote_state": "開高走高|開高走低|開低走高|開低走低 (選機率最高者)",\n'
        '  "probs": {"開高走高": 30, "開高走低": 35, "開低走高": 20, "開低走低": 15},\n'
        '  "confidence": 70,\n'
        '  "core_thesis": "回答你的專屬核心問題（80~120字，禁止空泛套話，需引用具體數字）",\n'
        '  "bull_evidence": ["多方/走高具體證據1", "多方/走高具體證據2"],\n'
        '  "bear_risk": ["空方/走低具體風險1", "空方/走低具體風險2"],\n'
        '  "action_advice": "針對日內走勢的操作建議（例如：提防開高走低勿在09:15前追高，或等拉回5MA承接）"\n'
        "}"
    )
    return schema_instruction

@st.cache_data(ttl=900, show_spinner=False)
def run_ai_panel(session_key, target_date_str, tw_info, flow_info, us_mkt, adr_prem, headlines, quant_4state):
    """執行四位 AI 委員獨立呼叫並記錄真實執行狀態"""
    panel_results = []
    for idx, ag in enumerate(AI_AGENTS):
        prompt = _build_specialized_prompt(ag, target_date_str, tw_info, flow_info, us_mkt, adr_prem, headlines, quant_4state)
        ok, actual_model, status_reason, data = _call_llm_strict(ag, prompt)

        if ok and isinstance(data, dict) and data.get("vote_state") in FOUR_STATES:
            raw_p = data.get("probs", {})
            p_clean = {k: max(0, int(float(raw_p.get(k, 25)))) for k in FOUR_STATES}
            tot_p = sum(p_clean.values()) or 100
            p_norm = {k: round(v / tot_p * 100, 1) for k in FOUR_STATES}
            best_st = max(p_norm.items(), key=lambda x: x[1])[0]

            panel_results.append({
                **ag,
                "api_ok": True,
                "actual_model": actual_model,
                "status_reason": status_reason,
                "vote_state": best_st,
                "probs": p_norm,
                "confidence": min(100, max(1, int(float(data.get("confidence", 65))))),
                "core_thesis": str(data.get("core_thesis", "")),
                "bull_evidence": [str(x) for x in (data.get("bull_evidence") or [])[:2]],
                "bear_risk": [str(x) for x in (data.get("bear_risk") or [])[:2]],
                "action_advice": str(data.get("action_advice", "")),
            })
        else:
            panel_results.append({
                **ag,
                "api_ok": False,
                "actual_model": actual_model,
                "status_reason": status_reason if not ok else "回傳 JSON 格式不符四態規範",
                "vote_state": None,
                "probs": None,
                "confidence": None,
            })
    return panel_results

def build_4state_dashboard_html(target_d, tw_info, flow_info, us_mkt, adr_prem, adr_imp_twd, headlines, quant_4state, ai_panel):
    """
    組裝誠實透明的「A. 量化歷史條件機率」與「B. AI 委員獨立研究（含真實連線狀態）」雙軌決策面板
    """
    # 1. API 執行狀態膠囊列
    status_cards = ""
    active_agents = [a for a in ai_panel if a["api_ok"]]
    for a in ai_panel:
        if a["api_ok"]:
            badge = "<span class='st-ok'>🟢 API 連線成功（參與投票）</span>"
            mod_txt = f"實際回傳模型：<code>{a['actual_model']}</code>"
        else:
            badge = "<span class='st-off'>⚪ 未連線 / 棄權（不計入選票）</span>"
            mod_txt = f"原因：{a['status_reason']}"
        status_cards += (
            f"<div class='st-card'>"
            f"<div class='st-top'><span class='st-dot' style='background:{a['color']}'>{a['short']}</span>"
            f"<b>{a['name']}</b>{badge}</div>"
            f"<div class='st-sub'>設定端點：<code>{a['model_id']}</code> ｜ {mod_txt}</div>"
            f"</div>"
        )

    # 2. 量化歷史四態機率橫條與卡片
    q_probs = quant_4state["probs"]
    q_base = quant_4state["base_probs"]
    q_det = quant_4state["detail"]
    q_bars_html = ""
    q_cards_html = ""
    for st_name in FOUR_STATES:
        meta = STATE_META[st_name]
        p = q_probs[st_name]
        b_p = q_base[st_name]
        diff_p = p - b_p
        det = q_det[st_name]
        q_bars_html += f"<div style='width:{max(p, 2)}%;background:{meta['col']}' title='{st_name}: {p}%'></div>"
        q_cards_html += (
            f"<div class='q-box' style='border-color:{meta['col']};background:{meta['bg']}'>"
            f"<div class='q-title' style='color:{meta['col']}'>{st_name}</div>"
            f"<div class='q-prob'>{p:.1f}% <small>(基準 {b_p:.1f}% / {diff_p:+.1f}%)</small></div>"
            f"<div class='q-desc'>{meta['desc']}</div>"
            f"<div class='q-stat'>歷史同情境發生 <b>{det['count']}</b> 次｜平均跳空 <b>{det['avg_gap']:+.2f}%</b>｜盤中實體 <b>{det['avg_intra']:+.2f}%</b></div>"
            f"</div>"
        )

    # 3. 真實 RSS 新聞清單（無假新聞）
    news_html = ""
    if headlines:
        for idx, h in enumerate(headlines[:6], 1):
            news_html += (
                f"<div class='n-item'>"
                f"<span class='n-num'>{idx}</span>"
                f"<div style='flex:1'>"
                f"<a class='n-link' href='{h['url']}' target='_blank' rel='noopener noreferrer'>{h['title']} <span>↗ 原始報導 ({h['source']} · {h['pub']})</span></a>"
                f"<div class='n-snip'>摘要：{h['snippet']}</div>"
                f"</div></div>"
            )
    else:
        news_html = "<div class='n-snip'>目前無法連線 Google News RSS，系統不產生任何人工假標題。</div>"

    # 4. 已連線 AI 委員研究報告（未連線者不偽造發言）
    ai_cards_html = ""
    if active_agents:
        for a in active_agents:
            v_st = a["vote_state"]
            v_col = STATE_META[v_st]["col"]
            p_str = " ｜ ".join(f"{k} <b>{a['probs'][k]}%</b>" for k in FOUR_STATES)
            bull_li = "".join(f"<li>{x}</li>" for x in a["bull_evidence"]) or "<li>無特別補充</li>"
            bear_li = "".join(f"<li>{x}</li>" for x in a["bear_risk"]) or "<li>無特別補充</li>"
            ai_cards_html += (
                f"<div class='msg-row'>"
                f"<div class='avatar' style='background:{a['color']}'>{a['short']}</div>"
                f"<div class='bubble'>"
                f"<div class='b-head'>"
                f"<span class='b-name'>{a['name']}</span>"
                f"<span class='b-role'>Model ID: {a['actual_model']} · {a['role']}</span>"
                f"<span class='v-badge' style='border:1px solid {v_col};color:{v_col};background:rgba(255,255,255,.06)'>預測：{v_st}（信心 {a['confidence']}/100）</span>"
                f"</div>"
                f"<div class='prob-strip'>📊 模型四態機率分佈：{p_str}</div>"
                f"<div class='thesis-box'><b>💡 獨立維度核心推論：</b>{a['core_thesis']}</div>"
                f"<div class='think-grid'>"
                f"<div class='think-box'><b>📈 支持走高之實證（Bull Case）：</b><ul>{bull_li}</ul></div>"
                f"<div class='think-box'><b>📉 提防走低之風險（Bear Case）：</b><ul>{bear_li}</ul></div>"
                f"</div>"
                f"<div class='reason-box'><b>🎯 日內操作與風控建議：</b>{a['action_advice']}</div>"
                f"</div></div>"
            )
    else:
        ai_cards_html = (
            "<div class='empty-ai'>"
            "<b>ℹ️ 目前尚未設定任何 LLM API 金鑰（或 API 請求未成功）</b><br>"
            "為確保研究誠實度，系統<b>已全面停用過去的「內建線性加權公式偽裝 AI 發言」機制</b>，未連線的模型一律棄權不投票。<br>"
            "請直接參考上方經過去 3 年真實歷史數據校準之<b>【量化歷史條件四態機率模型】</b>，或於 Streamlit Secrets 配置 API Key 以啟動 AI 主觀研究對比。"
            "</div>"
        )

    # 5. 主持人雙軌對比（A. 量化歷史統計 vs B. AI 主觀共識）
    q_top = quant_4state["top_state"]
    q_top_p = q_probs[q_top]
    if active_agents:
        avg_ai_probs = {
            k: round(sum(a["probs"][k] for a in active_agents) / len(active_agents), 1)
            for k in FOUR_STATES
        }
        ai_top = max(avg_ai_probs.items(), key=lambda x: x[1])[0]
        ai_top_p = avg_ai_probs[ai_top]
        if ai_top == q_top:
            comp_verdict = f"🟢 量化統計與 AI 研究【方向一致】：雙軌皆指向「{q_top}」（量化機率 {q_top_p}% vs AI 平均機率 {ai_top_p}%）"
        else:
            comp_verdict = (
                f"⚠️ 量化統計與 AI 研究【出現分歧】：歷史統計指向「{q_top} ({q_top_p}%)」，"
                f"但 {len(active_agents)} 位連線 AI 委員傾向「{ai_top} ({ai_top_p}%)」。"
                "請檢視新聞是否有量化尚未納入之突發政策，或提防 AI 過度解讀隔夜新聞！"
            )
    else:
        comp_verdict = f"📊 今日單軌由【量化歷史條件機率】主導：最高機率狀態為「{q_top}（{q_top_p}%）」，盤中收紅K（走高）總機率為 {quant_4state['win_intra_up']}%"

    prem_txt = f"{adr_prem:+.2f}% (折合台股 {adr_imp_twd:,.0f} 元)" if adr_prem is not None else "資料載入中"
    tnx_v = us_mkt.get("美債10Y殖利率", {})
    vix_v = us_mkt.get("恐慌指數 VIX", {})
    fx_v = us_mkt.get("美元兌台幣", {})

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{{margin:0;background:transparent;color:#e8e6ee;font-family:-apple-system,"Noto Sans TC","Microsoft JhengHei",sans-serif}}
.wrap{{display:flex;flex-direction:column;gap:16px;padding:4px 4px 16px 4px}}
.sec-card{{background:#1e1927;border:1px solid #322a44;border-radius:15px;padding:15px 18px}}
.sec-h{{font-size:1.05rem;font-weight:800;color:#FFC83D;margin-bottom:10px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px}}
.sec-h small{{color:#a9a6b5;font-weight:400;font-size:.84rem}}
.st-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}}
@media(max-width:768px){{.st-grid{{grid-template-columns:1fr}}}}
.st-card{{background:rgba(0,0,0,.28);border:1px solid #312942;border-radius:10px;padding:9px 13px;font-size:.88rem}}
.st-top{{display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap}}
.st-dot{{padding:2px 7px;border-radius:5px;color:#fff;font-weight:800;font-size:.78rem}}
.st-ok{{background:rgba(34,197,94,.18);color:#4ade80;border:1px solid rgba(34,197,94,.45);padding:1px 8px;border-radius:99px;font-size:.78rem;margin-left:auto}}
.st-off{{background:rgba(161,161,170,.15);color:#a1a1aa;border:1px solid rgba(161,161,170,.35);padding:1px 8px;border-radius:99px;font-size:.78rem;margin-left:auto}}
.st-sub{{color:#b0adc0;font-size:.82rem}}
code{{background:#2a2436;color:#f9a8d4;padding:1px 5px;border-radius:4px;font-size:.8rem}}
.macro-bar{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:8px}}
@media(max-width:768px){{.macro-bar{{grid-template-columns:repeat(2,1fr)}}}}
.m-cell{{background:rgba(255,255,255,.04);border:1px solid #312942;border-radius:10px;padding:8px 12px;font-size:.86rem}}
.m-cell b{{display:block;font-size:.98rem;color:#fff;margin-top:2px}}
.q-bar{{display:flex;height:14px;border-radius:7px;overflow:hidden;margin:10px 0 14px 0;background:#2a2433}}
.q-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
@media(max-width:900px){{.q-grid{{grid-template-columns:repeat(2,1fr)}}}}
.q-box{{border:1px solid;border-radius:12px;padding:11px 13px}}
.q-title{{font-weight:800;font-size:1.02rem}}
.q-prob{{font-size:1.35rem;font-weight:900;color:#fff;margin:3px 0}}
.q-prob small{{font-size:.76rem;color:#cfcfd8;font-weight:500}}
.q-desc{{font-size:.8rem;color:#ddd9e8;margin-bottom:6px}}
.q-stat{{font-size:.78rem;color:#b0adc0;border-top:1px solid rgba(255,255,255,.1);padding-top:5px}}
.n-item{{display:flex;gap:10px;align-items:flex-start;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.06)}}
.n-item:last-child{{border-bottom:0}}
.n-num{{background:#3b3154;color:#ffc83d;font-weight:800;font-size:.8rem;padding:1px 7px;border-radius:5px}}
.n-link{{color:#fff;font-weight:700;font-size:.94rem;text-decoration:none}}
.n-link:hover{{color:#FFC83D}}
.n-link span{{color:#a78bfa;font-size:.8rem;font-weight:500;margin-left:6px}}
.n-snip{{color:#b0adc0;font-size:.84rem;margin-top:3px;line-height:1.5}}
.msg-row{{display:flex;gap:13px;align-items:flex-start;margin-top:10px}}
.avatar{{width:44px;height:44px;border-radius:11px;display:flex;align-items:center;justify-content:center;font-weight:800;color:#fff;flex-shrink:0}}
.bubble{{background:rgba(0,0,0,.25);border:1px solid #352e47;border-radius:0 14px 14px 14px;padding:13px 16px;flex:1;font-size:.93rem;line-height:1.62}}
.b-head{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px}}
.b-name{{font-weight:800;color:#fff;font-size:1.05rem}}
.b-role{{font-size:.8rem;color:#b0adc0;background:#2a2436;padding:2px 8px;border-radius:5px}}
.v-badge{{padding:3px 11px;border-radius:99px;font-weight:800;font-size:.84rem;margin-left:auto}}
.prob-strip{{background:rgba(255,255,255,.04);padding:6px 11px;border-radius:7px;font-size:.85rem;margin-bottom:8px;color:#d0cce0}}
.thesis-box{{margin-bottom:8px;color:#fff}}
.think-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:8px}}
@media(max-width:768px){{.think-grid{{grid-template-columns:1fr}}}}
.think-box{{background:rgba(255,255,255,.035);border:1px solid #312942;border-radius:8px;padding:8px 12px;font-size:.86rem}}
.think-box ul{{margin:4px 0 0 16px;padding:0}}
.reason-box{{background:rgba(139,92,246,.14);border-left:3px solid #8b5cf6;padding:8px 12px;border-radius:6px;color:#fff;font-size:.9rem}}
.empty-ai{{background:rgba(255,200,61,.08);border:1px dashed rgba(255,200,61,.45);border-radius:11px;padding:14px 16px;color:#e8e6ee;font-size:.92rem;line-height:1.65}}
.verdict-banner{{background:linear-gradient(90deg,rgba(255,200,61,.16),rgba(30,25,39,.95));border:1px solid rgba(255,200,61,.5);border-radius:13px;padding:13px 16px;font-size:.96rem;line-height:1.65}}
</style></head><body>
<div class="wrap">

  <!-- 區塊 1：API 誠實狀態檢核 -->
  <div class="sec-card">
    <div class="sec-h">
      <span>🔍 一、AI 委員 API 真實執行狀態檢核（誠實標示 · 失敗或未設 Key 絕不偽造投票）</span>
      <small>目標交易日：{target_d:%Y/%m/%d} ｜ 已連線投票委員：{len(active_agents)} / 4 位</small>
    </div>
    <div class="st-grid">{status_cards}</div>
  </div>

  <!-- 區塊 2：擴充盤前總經、匯率、台積電 ADR 溢價與多日籌碼結構 -->
  <div class="sec-card">
    <div class="sec-h">
      <span>🌎 二、盤前關鍵總經、ADR 溢價與法人累積籌碼（解決單日籌碼盲點與跨日時間對齊）</span>
      <small>台股資料日：{tw_info['date_str']} ｜ 美股最新收盤日：{us_mkt.get('費城半導體', {{}}).get('date', '--')}</small>
    </div>
    <div class="macro-bar">
      <div class="m-cell">台積電 ADR 換算溢價<b>{prem_txt}</b></div>
      <div class="m-cell">美元兌台幣 / 美債10Y<b>{fx_v.get('close', 0):.2f} ({fx_v.get('pct', 0):+.2f}%) ｜ {tnx_v.get('close', 0):.2f}%</b></div>
      <div class="m-cell">恐慌指數 VIX / 費半<b>{vix_v.get('close', 0):.2f} ({vix_v.get('pct', 0):+.2f}%) ｜ 費半 {us_mkt.get('費城半導體', {{}}).get('pct', 0):+.2f}%</b></div>
      <div class="m-cell">外資現貨 (昨 / 5日 / 10日)<b>{flow_info['f1']:+.0f}億 / {flow_info['f5']:+.0f}億 / {flow_info['f10']:+.0f}億</b></div>
    </div>
  </div>

  <!-- 區塊 3：A 軌 — 量化客觀歷史條件四態機率模型 -->
  <div class="sec-card">
    <div class="sec-h">
      <span>📐 三、【A 軌：量化客觀判斷】過去 3 年歷史條件四態機率分佈（取代人工加權公式）</span>
      <small>篩選條件：{quant_4state['cond_label']}（符合樣本：{quant_4state['n_sample']} 日 / 總樣本 {quant_4state['n_total']} 日）</small>
    </div>
    <div class="q-bar">{q_bars_html}</div>
    <div class="q-grid">{q_cards_html}</div>
  </div>

  <!-- 區塊 4：真實國際財經新聞與摘要 -->
  <div class="sec-card">
    <div class="sec-h">
      <span>📰 四、真實 Google News 國際財經新聞與摘要（已移除人工假標題池）</span>
      <small>點擊標題可開啟原始媒體報導驗證</small>
    </div>
    {news_html}
  </div>

  <!-- 區塊 5：B 軌 — 四位 AI 獨立維度研究報告 -->
  <div class="sec-card">
    <div class="sec-h">
      <span>🤖 五、【B 軌：AI 主觀研究會議】獨立資料子集與反方論證</span>
      <small>僅顯示真實連線成功之模型報告</small>
    </div>
    {ai_cards_html}
  </div>

  <!-- 區塊 6：C 軌 — 主持人雙軌對帳總結 -->
  <div class="verdict-banner">
    <b>⚖️ 六、【C 軌：主持人雙軌比對結論（量化統計 vs AI 投研）】</b><br>
    {comp_verdict}<br>
    <span style="font-size:.86rem;color:#d0cce0">
      💡 <b>00631L 交易紀律提醒</b>：隔夜美股漲跌多數於 09:00 開盤跳空直接反映。若歷史四態中「開高走低」機率偏高，切勿在早盤跳空第一根 5 分 K 盲目追高，應嚴格以第二頁「策略 B」之 5 分 K 觸價與停損線為唯一交易依據。
    </span>
  </div>

</div>
</body></html>"""

def vote_page():
    target_d, prev_d, status_msg = get_meeting_session_info()

    with st.spinner("同步過去 3 年台美股日線、計算歷史四態條件機率與檢核 AI 連線狀態…"):
        daily = load_daily("^TWII", "1y")
        days_flow = last_10_flows()
        us_mkt, adr_prem, adr_imp_twd, headlines = fetch_expanded_global_context(target_d.strftime("%Y%m%d"))

    if daily.empty or len(daily) < 10:
        st.error("無法取得大盤歷史資料，會議暫停。")
        return

    tw_close = float(daily.Close.iloc[-1])
    tw_prev = float(daily.Close.iloc[-2])
    tw_pct = (tw_close / tw_prev - 1) * 100
    tw_ma5 = float(daily.Close.rolling(5).mean().iloc[-1])
    bias_5ma = (tw_close / tw_ma5 - 1) * 100
    tw_date_str = pd.Timestamp(daily.index[-1]).strftime("%m/%d")

    tw_info = {
        "close": tw_close,
        "pct": tw_pct,
        "ma5": tw_ma5,
        "bias5": bias_5ma,
        "date_str": tw_date_str
    }

    if days_flow:
        f_list = [x["外資"] / 1e8 for x in days_flow]
        t_list = [x["投信"] / 1e8 for x in days_flow]
        z_list = [x["自營"] / 1e8 for x in days_flow]
        flow_info = {
            "f1": f_list[-1], "f5": sum(f_list[-5:]), "f10": sum(f_list),
            "t1": t_list[-1], "t5": sum(t_list[-5:]), "t10": sum(t_list),
            "z1": z_list[-1], "z5": sum(z_list[-5:]), "z10": sum(z_list),
        }
    else:
        flow_info = {k: 0.0 for k in ("f1", "f5", "f10", "t1", "t5", "t10", "z1", "z5", "z10")}

    sox_pct = us_mkt.get("費城半導體", {}).get("pct", 0.0)
    tsm_pct = us_mkt.get("台積電 ADR", {}).get("pct", 0.0)
    cur_us_tech = 0.5 * sox_pct + 0.5 * tsm_pct

    quant_4state = calc_historical_4state_probs(cur_us_tech, bias_5ma, tw_pct)
    if not quant_4state:
        st.error("歷史統計計算失敗。")
        return

    ai_panel = run_ai_panel(
        target_d.strftime("%Y%m%d"),
        target_d.strftime("%Y/%m/%d"),
        tw_info, flow_info, us_mkt, adr_prem, headlines, quant_4state
    )

    with st.container(key="vote_card"):
        st.markdown(
            f"<div class='fl-h'>🤖 盤前四態量化統計與 AI 投研早會"
            f"<small>場次：{fmt_d(target_d)} · {status_msg}</small></div>",
            unsafe_allow_html=True
        )

        # 頂部四種日內狀態歷史條件機率一覽
        qp = quant_4state["probs"]
        m = st.columns(4)
        m[0].metric("🔴 開高走高 (歷史條件機率)", f"{qp['開高走高']:.1f}%", f"跳空 {quant_4state['detail']['開高走高']['avg_gap']:+.2f}% / 盤中 {quant_4state['detail']['開高走高']['avg_intra']:+.2f}%")
        m[1].metric("🟠 開高走低 (歷史條件機率)", f"{qp['開高走低']:.1f}%", f"跳空 {quant_4state['detail']['開高走低']['avg_gap']:+.2f}% / 盤中 {quant_4state['detail']['開高走低']['avg_intra']:+.2f}%", delta_color="inverse")
        m[2].metric("🔵 開低走高 (歷史條件機率)", f"{qp['開低走高']:.1f}%", f"跳空 {quant_4state['detail']['開低走高']['avg_gap']:+.2f}% / 盤中 {quant_4state['detail']['開低走高']['avg_intra']:+.2f}%")
        m[3].metric("🟢 開低走低 (歷史條件機率)", f"{qp['開低走低']:.1f}%", f"跳空 {quant_4state['detail']['開低走低']['avg_gap']:+.2f}% / 盤中 {quant_4state['detail']['開低走低']['avg_intra']:+.2f}%", delta_color="inverse")

        html_doc = build_4state_dashboard_html(
            target_d, tw_info, flow_info, us_mkt, adr_prem, adr_imp_twd,
            headlines, quant_4state, ai_panel
        )
        components.html(html_doc, height=1180, scrolling=True)

        with st.expander("📊 檢視最近 5 個交易日「隔夜美股 vs 台股日內四態」真實對帳紀錄"):
            st.dataframe(pd.DataFrame(quant_4state["recent_5"]), hide_index=True, use_container_width=True)

# ───────────────────────── 組版 ─────────────────────────
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
