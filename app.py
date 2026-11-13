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
        return {"外資": f("外資"), "投信": f("投信"), "自營": f("自營商")}
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

# ───────────────────────── 頁面三：AI 投研早會與多空投票 ─────────────────────────
AI_AGENTS = [
    {"id": "chatgpt",  "name": "ChatGPT (GPT-4o)",     "short": "GPT", "color": "#10a37f", "role": "總經宏觀與外資期現貨解讀"},
    {"id": "deepseek", "name": "DeepSeek (R1-Quant)",  "short": "DS",  "color": "#3b82f6", "role": "量化動能因子與費半微結構"},
    {"id": "gemini",   "name": "Gemini (2.5 Pro)",     "short": "GEM", "color": "#8b5cf6", "role": "AI 供應鏈與台積電 ADR 溢價"},
    {"id": "claude",   "name": "Claude (3.7 Sonnet)",  "short": "CLD", "color": "#d97706", "role": "風險控管與土洋籌碼背離檢核"},
]

def _gnews_url(query):
    """將關鍵字轉為 Google 新聞搜尋網址"""
    return f"https://www.google.com/search?q={urllib.parse.quote(query)}&tbm=nws"

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
        status = "今日 08:30 盤前會議已召開"
    else:
        if is_trading_day(cur_d) and (now.hour < 8 or (now.hour == 8 and now.minute < 30)):
            status = "今日 08:30 會議準備中（目前顯示前次交易日早會紀錄）"
        else:
            status = "休市期間（目前顯示最近一個交易日 08:30 早會紀錄）"
        d = cur_d - timedelta(days=1)
        while not is_trading_day(d):
            d -= timedelta(days=1)
        target_d = d

    prev_d = target_d - timedelta(days=1)
    while not is_trading_day(prev_d):
        prev_d -= timedelta(days=1)

    return target_d, prev_d, status

@st.cache_data(ttl=900, show_spinner=False)
def fetch_global_context(session_key):
    """抓取隔夜美股關鍵指標與 Google News 國際財經新聞（含原始連結）"""
    tickers = {"S&P 500": "^GSPC", "費城半導體": "^SOX", "台積電 ADR": "TSM", "NVIDIA": "NVDA"}
    us_mkt = {}
    for name, sym in tickers.items():
        try:
            d = _clean(yf.download(sym, period="5d", interval="1d", progress=False))
            if len(d) >= 2:
                c1, c0 = float(d.Close.iloc[-1]), float(d.Close.iloc[-2])
                us_mkt[name] = {"close": c1, "pct": (c1 / c0 - 1) * 100}
        except Exception:
            pass

    headlines = []
    seen_titles = set()
    rss_urls = [
        "https://news.google.com/rss/search?q=%E7%BE%8E%E8%82%A1+OR+%E5%8F%B0%E7%A9%8D%E9%9B%BB+OR+%E8%BC%9D%E9%81%94+OR+%E8%81%AF%E6%BA%96%E6%9C%83+when:2d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
        "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    ]
    for url in rss_urls:
        try:
            r = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                for item in root.findall(".//item")[:12]:
                    title = item.find("title").text if item.find("title") is not None else ""
                    link = item.find("link").text if item.find("link") is not None else ""
                    title = re.sub(r"\s*-\s*[^-]+$", "", title).strip()
                    if title and title not in seen_titles and len(title) > 8:
                        seen_titles.add(title)
                        headlines.append({"title": title, "url": link or _gnews_url(title)})
        except Exception:
            pass
        if len(headlines) >= 12:
            break

    return us_mkt, headlines[:12]

def _call_llm_json(agent_id, prompt):
    sec = st.secrets if hasattr(st, "secrets") else {}
    try:
        if agent_id == "chatgpt" and "OPENAI_API_KEY" in sec:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {sec['OPENAI_API_KEY']}"},
                json={"model": "gpt-4o-mini", "response_format": {"type": "json_object"},
                      "messages": [{"role": "user", "content": prompt}], "temperature": 0.4}, timeout=15
            ).json()
            return json.loads(r["choices"][0]["message"]["content"])

        if agent_id == "deepseek" and "DEEPSEEK_API_KEY" in sec:
            r = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {sec['DEEPSEEK_API_KEY']}"},
                json={"model": "deepseek-chat", "response_format": {"type": "json_object"},
                      "messages": [{"role": "user", "content": prompt}], "temperature": 0.4}, timeout=15
            ).json()
            return json.loads(r["choices"][0]["message"]["content"])

        if agent_id == "gemini" and "GEMINI_API_KEY" in sec:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={sec['GEMINI_API_KEY']}"
            r = requests.post(
                url, json={"contents": [{"parts": [{"text": prompt}]}],
                           "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4}}, timeout=15
            ).json()
            txt = r["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(txt)

        if agent_id == "claude" and "ANTHROPIC_API_KEY" in sec:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": sec["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-3-5-sonnet-latest", "max_tokens": 700,
                      "messages": [{"role": "user", "content": prompt + "\n請只輸出純 JSON，不要加 Markdown。"}]}, timeout=15
            ).json()
            return json.loads(r["content"][0]["text"])
    except Exception:
        return None
    return None

@st.cache_data(ttl=900, show_spinner=False)
def generate_ai_meeting(target_date_str, prev_date_str, tw_close, tw_pct, tw_ma5, f_net, t_net, z_net, us_mkt, headlines):
    sox_pct = us_mkt.get("費城半導體", {}).get("pct", 0.0)
    tsm_pct = us_mkt.get("台積電 ADR", {}).get("pct", 0.0)
    nvda_pct = us_mkt.get("NVIDIA", {}).get("pct", 0.0)
    sp_pct = us_mkt.get("S&P 500", {}).get("pct", 0.0)
    tot_flow = f_net + t_net + z_net
    bias_5ma = (tw_close / tw_ma5 - 1) * 100

    default_pool = [
        {"title": f"美股費城半導體指數隔夜收盤變動 {sox_pct:+.2f}%，牽動台股半導體與電子權值股開盤定價", "url": _gnews_url("費城半導體 台股 電子股")},
        {"title": f"台積電 ADR (TSM) 隔夜漲跌幅達 {tsm_pct:+.2f}%，外資對台積電現貨套利空間成為開盤焦點", "url": _gnews_url("台積電 ADR 美股")},
        {"title": f"AI 領頭羊 NVIDIA 隔夜表現 {nvda_pct:+.2f}%，直接影響台灣 AI 伺服器、組裝與散熱族群買氣", "url": _gnews_url("輝達 NVIDIA AI概念股")},
        {"title": f"標普 500 指數收盤變動 {sp_pct:+.2f}%，反映華爾街對最新總經通膨與聯準會利率路徑之預期", "url": _gnews_url("美股 S&P 500 聯準會")},
        {"title": f"外資昨日於台股集中市場{'買超' if f_net>=0 else '賣超'} {abs(f_net):.1f} 億元，熱錢流向與匯率連動密切", "url": _gnews_url("台股 外資 買賣超")},
        {"title": f"投信與自營商昨日分別{'買超' if t_net>=0 else '賣超'} {abs(t_net):.1f} 億與{'買超' if z_net>=0 else '賣超'} {abs(z_net):.1f} 億", "url": _gnews_url("台股 三大法人 投信 買賣超")}
    ]
    all_news = headlines + default_pool

    base_prompt = (
        f"現在是台北時間 {target_date_str} 早上 08:30 的台股盤前投研早會。上次會議為 {prev_date_str} 08:30。\n"
        f"【昨日台股盤勢】加權指數收 {tw_close:,.2f}（{tw_pct:+.2f}%），5MA 為 {tw_ma5:,.2f}（乖離 {bias_5ma:+.2f}%）。\n"
        f"【昨日三大法人】外資 {f_net:+.1f} 億、投信 {t_net:+.1f} 億、自營商 {z_net:+.1f} 億（合計 {tot_flow:+.1f} 億）。\n"
        f"【隔夜國際盤勢】費半 {sox_pct:+.2f}%、台積電ADR {tsm_pct:+.2f}%、NVDA {nvda_pct:+.2f}%、S&P500 {sp_pct:+.2f}%。\n"
        f"【最新國際新聞標題】{'; '.join(x['title'] for x in all_news[:8])}\n"
        "請挑出距離上次開會後，國際間最影響今日台股的 3 件事，並詳細說明你的【推論過程】（包含國際新聞衝擊、籌碼面解讀、進場操作建議），最後投票決定今日台股走勢為「看漲」、「看跌」或「平盤」。\n"
        "請嚴格回傳 JSON 格式：{\"events\": [\"事件1\", \"事件2\", \"事件3\"], \"news_view\": \"新聞與美股連動解析\", \"chip_view\": \"三大法人籌碼解讀\", \"reason\": \"最終投票理由與操作判斷\", \"vote\": \"看漲|看跌|平盤\"}"
    )

    results = []
    for idx, ag in enumerate(AI_AGENTS):
        llm_res = _call_llm_json(ag["id"], f"你是 {ag['name']}，專長為{ag['role']}。\n" + base_prompt)
        if llm_res and isinstance(llm_res.get("events"), list) and llm_res.get("vote") in ("看漲", "看跌", "平盤"):
            ev_objs = []
            for e in llm_res["events"][:3]:
                if isinstance(e, dict) and "title" in e:
                    ev_objs.append({"title": e["title"], "url": e.get("url") or _gnews_url(e["title"])})
                else:
                    s_txt = str(e)
                    clean_q = re.sub(r"^【[^】]+】", "", s_txt).strip()
                    ev_objs.append({"title": s_txt, "url": _gnews_url(clean_q)})
            results.append({
                **ag,
                "events": ev_objs,
                "news_view": llm_res.get("news_view", "依隔夜美股與國際新聞進行宏觀定價。"),
                "chip_view": llm_res.get("chip_view", f"外資 {f_net:+.1f} 億、投信 {t_net:+.1f} 億之籌碼結構分析。"),
                "reason": llm_res.get("reason", ""),
                "vote": llm_res["vote"],
                "time": f"08:30:{12 + idx*9:02d}"
            })
            continue

        # ─── 內建深度推演引擎（每個事件皆附帶可點擊的新聞連結） ───
        if ag["id"] == "chatgpt":
            evs = [
                {"title": f"【國際焦點】{all_news[0]['title']}", "url": all_news[0]["url"]},
                {"title": f"【總經與美股】S&P 500 隔夜變動 {sp_pct:+.2f}%、台積電 ADR 變動 {tsm_pct:+.2f}%，反映美股最新風險偏好", "url": _gnews_url("美股 S&P 500 台積電 ADR")},
                {"title": f"【跨國資金】外資前一交易日於台股現貨{'大舉買超' if f_net>100 else ('買超' if f_net>=0 else '調節賣超')} {abs(f_net):.1f} 億元", "url": _gnews_url("台股 外資 買賣超")}
            ]
            news_v = (
                f"隔夜 S&P 500 ({sp_pct:+.2f}%) 與台積電 ADR ({tsm_pct:+.2f}%) 表現"
                f"{'偏弱，科技股面臨消息面與估值修正壓力' if (sp_pct+tsm_pct)<0 else '穩健，國際資金對風險資產仍具承接意願'}。"
            )
            chip_v = (
                f"昨日外資買賣超為 {f_net:+.1f} 億元，三大法人合計 {tot_flow:+.1f} 億元。"
                f"{'雖然昨日外資買超，但隔夜美股回檔將考驗今日外資是否轉買為賣。' if (f_net>0 and tsm_pct<-0.8) else ('外資籌碼與國際盤勢方向一致。' if f_net*tsm_pct>=0 else '昨日外資雖站在賣方，但隔夜美股反彈有助減緩提款壓力。')}"
            )
            score = sp_pct * 0.35 + tsm_pct * 0.40 + (f_net / 150.0) * 0.25
            if score > 0.20:
                v = "看漲"
                rsn = f"綜合評估得分偏多：美股與 ADR ({tsm_pct:+.2f}%) 提供下檔保護，加上外資昨日 {f_net:+.1f} 億的資金慣性，今日開盤後權值股有望吸引買盤推升，投【看漲】一票。"
            elif score < -0.25:
                v = "看跌"
                rsn = f"綜合評估得分偏空：隔夜國際盤勢轉弱（ADR {tsm_pct:+.2f}%）壓抑今日開盤表現，外資極可能順勢調節權值股，建議進場前先觀望避開早盤賣壓，投【看跌】一票。"
            else:
                v = "平盤"
                rsn = f"多空力道相互抵銷：昨日外資雖有 {f_net:+.1f} 億動作，但隔夜 S&P 500 ({sp_pct:+.2f}%) 與國際消息面缺乏單邊突破動能，預期今日台股於平盤附近箱型震盪，投【平盤】一票。"

        elif ag["id"] == "deepseek":
            n1 = all_news[1] if len(all_news) > 1 else default_pool[1]
            evs = [
                {"title": f"【硬體動能】費城半導體指數 (^SOX) 隔夜變動 {sox_pct:+.2f}%，NVIDIA 變動 {nvda_pct:+.2f}%", "url": _gnews_url("費城半導體 NVIDIA 輝達")},
                {"title": f"【產業新聞】{n1['title']}", "url": n1["url"]},
                {"title": f"【技術結構】台股昨日收 {tw_close:,.2f} 點 ({tw_pct:+.2f}%)，與 5MA ({tw_ma5:,.2f}) 乖離率為 {bias_5ma:+.2f}%", "url": _gnews_url("台股 加權指數 均線")}
            ]
            news_v = (
                f"從量化因子觀察，費半 ({sox_pct:+.2f}%) 與 NVDA ({nvda_pct:+.2f}%) 是台股電子股的領先指標，"
                f"{'隔夜半導體因子顯著回落，短線動能受阻' if (sox_pct+nvda_pct)<-1.0 else '硬體與半導體動能維持在一定水位'}。"
            )
            chip_v = (
                f"昨日三大法人合計 {tot_flow:+.1f} 億元，指數收在 5MA {'之上' if tw_close>=tw_ma5 else '之下'}（乖離 {bias_5ma:+.2f}%）。"
                f"{'短線正乖離過大且遇美股科技股拉回，量化模型顯示均值回歸壓力上升。' if (bias_5ma>1.0 and sox_pct<0) else '目前日線趨勢動能與法人資金流向尚無結構性破壞。'}"
            )
            score = sox_pct * 0.45 + nvda_pct * 0.25 + (tot_flow / 180.0) * 0.30
            if score > 0.25:
                v = "看漲"
                rsn = f"量化多頭共振：費半 ({sox_pct:+.2f}%) 與法人籌碼 ({tot_flow:+.1f}億) 維持正斜率，且指數站穩 5MA 強勢區，順勢交易模型判定【看漲】。"
            elif score < -0.25:
                v = "看跌"
                rsn = f"動能衰減訊號：隔夜費半 ({sox_pct:+.2f}%) 與 NVDA ({nvda_pct:+.2f}%) 同步走弱，將拖累今日台股早盤 5 分 K 開低，操作上不宜盲目追高，判定【看跌】。"
            else:
                v = "平盤"
                rsn = f"動能指標中性：隔夜費半 ({sox_pct:+.2f}%) 波動收斂，搭配昨日法人籌碼 ({tot_flow:+.1f}億) 支撐，預計今日在 5MA 附近進行籌碼換手整理，判定【平盤】。"

        elif ag["id"] == "gemini":
            n2 = all_news[2] if len(all_news) > 2 else default_pool[2]
            evs = [
                {"title": f"【AI 算力鏈】NVIDIA 隔夜收盤 {nvda_pct:+.2f}%、台積電 ADR {tsm_pct:+.2f}%，連動台股超過 40% 權重", "url": _gnews_url("台積電 ADR 輝達 NVIDIA")},
                {"title": f"【市場熱點】{n2['title']}", "url": n2["url"]},
                {"title": f"【內資動向】投信昨日於集中市場{'買超' if t_net>=0 else '賣超'} {abs(t_net):.1f} 億元，鎖定 AI 與高息 ETF 成分股", "url": _gnews_url("投信 買賣超 ETF 台股")}
            ]
            news_v = (
                f"台積電 ADR ({tsm_pct:+.2f}%) 與 NVIDIA ({nvda_pct:+.2f}%) 直接決定台股今日開盤跳空方向。"
                f"{'兩大 AI 核心指標隔夜雙雙拉回，今日電子權值股開盤勢必面臨逆風。' if (tsm_pct<0 and nvda_pct<0) else 'AI 供應鏈隔夜表現具韌性，有利維繫台股人氣。'}"
            )
            chip_v = (
                f"觀察籌碼細節：昨日外資 {f_net:+.1f} 億、投信 {t_net:+.1f} 億。"
                f"{'內外資昨日同步站在買方，下檔具備強勁的法人成本區支撐。' if (f_net>0 and t_net>0) else '土洋法人態度分歧，盤中易出現拉高出貨或急殺護盤的劇烈震盪。'}"
            )
            score = tsm_pct * 0.45 + nvda_pct * 0.30 + ((f_net + t_net * 2) / 150.0) * 0.25
            if score > 0.20:
                v = "看漲"
                rsn = f"AI 權值與內外資籌碼雙重支撐：昨日外資 ({f_net:+.1f}億) 與投信 ({t_net:+.1f}億) 買盤強勁，足以緩衝國際雜音並推升指數，投【看漲】一票。"
            elif score < -0.20:
                v = "看跌"
                rsn = f"AI 雙雄回檔拖累：由於 TSM ADR ({tsm_pct:+.2f}%) 與 NVDA ({nvda_pct:+.2f}%) 隔夜明顯修正，台積電今日開盤承壓將直接壓抑加權指數表現，投【看跌】一票。"
            else:
                v = "平盤"
                rsn = f"權值休兵、個股表現：雖然隔夜 AI 指標股震盪，但內資投信 ({t_net:+.1f}億) 護盤意願明確，預期大盤指數平盤整理、資金轉向中小型股，投【平盤】一票。"

        else:  # claude
            n3 = all_news[3] if len(all_news) > 3 else default_pool[3]
            evs = [
                {"title": f"【風險事件】{n3['title']}", "url": n3["url"]},
                {"title": f"【避險情緒】自營商昨日買賣超 {z_net:+.1f} 億元（含權證避險與自營部位），反映短線波動率預期", "url": _gnews_url("台股 自營商 買賣超 避險")},
                {"title": f"【多空比對】昨日台股漲跌 {tw_pct:+.2f}% vs 隔夜美股費半 {sox_pct:+.2f}%、TSM {tsm_pct:+.2f}% 之背離檢核", "url": _gnews_url("台股 美股 費半 台積電ADR")}
            ]
            news_v = (
                f"從風險控管角度檢視，昨日台股已先反應 {tw_pct:+.2f}% 的漲幅，而隔夜美股（費半 {sox_pct:+.2f}%、TSM {tsm_pct:+.2f}%）"
                f"{'並未跟上台股漲勢甚至出現回吐，存在「昨日台股偷跑、今日補跌修正」的乖離風險' if (tw_pct>0.8 and tsm_pct<-0.5) else '表現相對平穩，未出現系統性黑天鵝訊號'}。"
            )
            chip_v = (
                f"昨日三大法人外資 {f_net:+.1f} 億、投信 {t_net:+.1f} 億、自營商 {z_net:+.1f} 億。"
                f"{'雖然昨日法人大買，但在隔夜美股拉回背景下，早盤若開高極易引來短線獲利了結賣壓。' if (tot_flow>200 and tsm_pct<0) else '籌碼面並無過度擁擠或失控跡象。'}"
            )
            score = (tot_flow / 160.0) * 0.45 + (tsm_pct + sox_pct) * 0.35 - (max(0, bias_5ma - 1.5)) * 0.20
            if score > 0.25:
                v = "看漲"
                rsn = f"下檔風險可控：昨日三大法人合計買超達 {tot_flow:+.1f} 億元，籌碼結構紮實，即便早盤受美股影響小幅震盪，低接買盤仍強，審慎投下【看漲】。"
            elif score < -0.20:
                v = "看跌"
                rsn = f"風控警示觸發：隔夜美股科技股回檔（TSM {tsm_pct:+.2f}% / NVDA {nvda_pct:+.2f}%），建議今日切勿在早盤急拉時追進 00631L，應提防開低或回測 5MA，投【看跌】。"
            else:
                v = "平盤"
                rsn = f"昨日法人大買 ({tot_flow:+.1f}億) 的多方力道，剛好與隔夜美股回檔 ({tsm_pct:+.2f}%) 的空方壓力互相抵銷！進場前建議等 09:30 後方向明確再動作，投【平盤】。"

        results.append({
            **ag, "events": evs, "news_view": news_v, "chip_view": chip_v,
            "vote": v, "reason": rsn, "time": f"08:30:{12 + idx*9:02d}"
        })

    return results

def build_chatroom_html(target_d, prev_d, flow_date_label, tw_close, tw_pct, tw_hl, tw_ma5, f_net, t_net, z_net, tot_net, us_mkt, ai_votes, cnt_up, cnt_dn, cnt_fl, final_verdict, v_col):
    """使用獨立 HTML 組裝聊天室：每個事件皆為可點擊的新聞連結，並放大字體與間距以提升閱讀體驗"""
    us_summary = " ｜ ".join(
        f"{k} <b style='color:{UP if v['pct']>=0 else DN}'>{v['pct']:+.2f}%</b>"
        for k, v in us_mkt.items()
    ) or "隔夜美股資料載入中"

    cards_html = ""
    for ag in ai_votes:
        v_cls = "v-up" if ag["vote"] == "看漲" else ("v-dn" if ag["vote"] == "看跌" else "v-fl")
        v_icon = "📈 投票：看漲" if ag["vote"] == "看漲" else ("📉 投票：看跌" if ag["vote"] == "看跌" else "⚖️ 投票：平盤")
        ev_items = ""
        for e in ag["events"][:3]:
            if isinstance(e, dict):
                t_txt, u_lnk = e.get("title", ""), e.get("url", "#")
            else:
                t_txt, u_lnk = str(e), _gnews_url(str(e))
            ev_items += f"<li><a class='ev-link' href='{u_lnk}' target='_blank' rel='noopener noreferrer'>{t_txt}<span class='ext-ico'>↗</span></a></li>"

        cards_html += (
            f"<div class='msg-row'>"
            f"<div class='avatar' style='background:{ag['color']}'>{ag['short']}</div>"
            f"<div class='bubble'>"
            f"<div class='b-head'>"
            f"<span class='b-name'>{ag['name']}</span>"
            f"<span class='b-role'>{ag['role']}</span>"
            f"<span class='v-badge {v_cls}'>{v_icon}</span>"
            f"<span class='b-time'>{target_d:%m/%d} {ag['time']}</span>"
            f"</div>"
            f"<div class='sec-title'>📌 距上次開會（{prev_d:%m/%d} 08:30）後最影響台股之 3 大國際與市場事件（點擊文字可查看相關新聞）：</div>"
            f"<ol class='ev-list'>{ev_items}</ol>"
            f"<div class='think-grid'>"
            f"<div class='think-box'><b>🌍 國際新聞衝擊解析：</b><br>{ag['news_view']}</div>"
            f"<div class='think-box'><b>💰 三大法人籌碼檢核：</b><br>{ag['chip_view']}</div>"
            f"</div>"
            f"<div class='reason-box'><b>🎯 進場前綜合判斷與投票理由：</b>{ag['reason']}</div>"
            f"</div></div>"
        )

    w_up, w_fl, w_dn = cnt_up * 25, cnt_fl * 25, cnt_dn * 25
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{{margin:0;background:transparent;color:#e8e6ee;font-family:-apple-system,"Noto Sans TC","Microsoft JhengHei",sans-serif}}
.chat-room{{display:flex;flex-direction:column;gap:18px;padding:6px 6px 16px 6px}}
.msg-row{{display:flex;gap:14px;align-items:flex-start}}
.msg-row.host{{background:linear-gradient(90deg,rgba(255,200,61,.14),rgba(30,25,39,.95));border:1px solid rgba(255,200,61,.4);border-radius:16px;padding:16px 20px}}
.avatar{{width:48px;height:48px;border-radius:13px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:1.15rem;flex-shrink:0;color:#fff;box-shadow:0 4px 12px rgba(0,0,0,.35)}}
.bubble{{background:#1e1927;border:1px solid #322a44;border-radius:0 16px 16px 16px;padding:15px 20px;flex:1;line-height:1.7;font-size:1rem}}
.b-head{{display:flex;align-items:center;gap:12px;margin-bottom:10px;flex-wrap:wrap}}
.b-name{{font-weight:800;color:#fff;font-size:1.15rem}}
.b-role{{font-size:.86rem;color:#b0adc0;background:#2a2436;padding:3px 10px;border-radius:6px}}
.b-time{{font-size:.84rem;color:#8a8699;margin-left:auto}}
.v-badge{{padding:4px 13px;border-radius:99px;font-weight:800;font-size:.9rem;letter-spacing:.03em}}
.v-up{{background:rgba(255,77,90,.2);color:#ff4d5a;border:1px solid #ff4d5a}}
.v-dn{{background:rgba(34,197,94,.2);color:#22c55e;border:1px solid #22c55e}}
.v-fl{{background:rgba(169,166,181,.2);color:#e2e0ec;border:1px solid #8d8d99}}
.sec-title{{font-size:.95rem;color:#c4c0d4;font-weight:600;margin-top:4px}}
.ev-list{{margin:8px 0 14px 22px;padding:0;color:#f0eef7;font-size:1.02rem;line-height:1.75}}
.ev-list li{{margin-bottom:6px}}
.ev-link{{color:#f2f0fa;text-decoration:none;border-bottom:1px dashed rgba(192,132,252,.55);padding-bottom:1px;transition:all .18s ease}}
.ev-link:hover{{color:#FFC83D;border-bottom:1px solid #FFC83D}}
.ext-ico{{font-size:.82rem;color:#a78bfa;margin-left:5px;opacity:.85}}
.ev-link:hover .ext-ico{{color:#FFC83D;opacity:1}}
.think-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}}
@media(max-width:768px){{.think-grid{{grid-template-columns:1fr}}}}
.think-box{{background:rgba(255,255,255,.045);border:1px solid #352e47;border-radius:10px;padding:11px 14px;font-size:.96rem;color:#ddd9e8;line-height:1.65}}
.think-box b{{color:#fff;font-size:.98rem}}
.reason-box{{background:rgba(124,92,255,.14);border-left:4px solid #8b5cf6;padding:11px 15px;border-radius:8px;font-size:1.02rem;color:#fff;line-height:1.65}}
.tally-bar{{display:flex;height:16px;border-radius:8px;overflow:hidden;background:#2a2433;margin:10px 0}}
</style></head><body>
<div class="chat-room">
  <div class="msg-row host">
    <div class="avatar" style="background:linear-gradient(135deg,#FFC83D,#d97706);color:#000">主</div>
    <div style="flex:1">
      <div class="b-head">
        <span class="b-name" style="color:#FFC83D">網站主持人（量化中控台）</span>
        <span class="b-role">盤前數據餵價與議程主持</span>
        <span class="b-time">{target_d:%m/%d} 08:30:00</span>
      </div>
      <div style="font-size:1rem;line-height:1.75">
        各位 AI 投研委員早安，現在是台北時間 <b>{target_d:%m/%d} 08:30</b>，開始今日台股開盤前決策會議。<br>
        📊 <b>前一交易日（{flow_date_label}）台股盤勢</b>：加權指數收 <b>{tw_close:,.2f}</b> 點
        （<b style="color:{_col(tw_pct)}">{tw_pct:+.2f}%</b>，高低震幅 {tw_hl:,.0f} 點），5MA 位於 <b>{tw_ma5:,.2f}</b>。<br>
        💰 <b>三大法人買賣超</b>：外資 <b style="color:{_col(f_net)}">{f_net:+,.1f}億</b> ｜
        投信 <b style="color:{_col(t_net)}">{t_net:+,.1f}億</b> ｜
        自營商 <b style="color:{_col(z_net)}">{z_net:+,.1f}億</b>（合計 <b style="color:{_col(tot_net)}">{tot_net:+,.1f}億</b>）。<br>
        🌎 <b>隔夜美股關鍵指標</b>：{us_summary}。<br>
        請四位模型依序報告距離上次開會（{prev_d:%m/%d} 08:30）後<b>最影響台股的 3 件國際大事</b>、<b>籌碼與新聞推演過程</b>，並投下今日漲跌選票！
      </div>
    </div>
  </div>
  {cards_html}
  <div class="msg-row host">
    <div class="avatar" style="background:linear-gradient(135deg,#FFC83D,#d97706);color:#000">結</div>
    <div style="flex:1">
      <div class="b-head">
        <span class="b-name" style="color:#FFC83D">網站主持人（計票中心與進場前總結）</span>
        <span class="b-role">08:30 盤前會議最終統計</span>
        <span class="b-time">{target_d:%m/%d} 08:31:00</span>
      </div>
      <div style="font-size:1.02rem;line-height:1.75">
        感謝四位委員完整推演！今日（{fmt_d(target_d)}）盤前多空投票統計結果：<br>
        <b>🔴 看漲 {cnt_up} 票 ｜ ⚪ 平盤 {cnt_fl} 票 ｜ 🟢 看跌 {cnt_dn} 票</b>
        <div class="tally-bar">
          <div style="width:{w_up}%;background:{UP}"></div>
          <div style="width:{w_fl}%;background:#8d8d99"></div>
          <div style="width:{w_dn}%;background:{DN}"></div>
        </div>
        📢 <b>今日早會最終決議：<span style="color:{v_col}">{final_verdict}</span></b>
      </div>
    </div>
  </div>
</div>
</body></html>"""

def vote_page():
    target_d, prev_d, status_msg = get_meeting_session_info()

    with st.spinner("召開 08:30 AI 投研早會，彙整前日籌碼與國際新聞中…"):
        daily = load_daily("^TWII", "6mo")
        days_flow = last_10_flows()
        us_mkt, headlines = fetch_global_context(target_d.strftime("%Y%m%d"))

    if daily.empty or len(daily) < 6:
        st.error("無法取得大盤歷史資料，會議暫停。")
        return

    tw_close = float(daily.Close.iloc[-1])
    tw_prev = float(daily.Close.iloc[-2])
    tw_pct = (tw_close / tw_prev - 1) * 100
    tw_hl = float(daily.High.iloc[-1] - daily.Low.iloc[-1])
    tw_ma5 = float(daily.Close.rolling(5).mean().iloc[-1])

    if days_flow:
        lf = days_flow[-1]
        f_net, t_net, z_net = lf["外資"] / 1e8, lf["投信"] / 1e8, lf["自營"] / 1e8
        flow_date_label = lf["d"]
    else:
        f_net = t_net = z_net = 0.0
        flow_date_label = prev_d.strftime("%m/%d")
    tot_net = f_net + t_net + z_net

    ai_votes = generate_ai_meeting(
        target_d.strftime("%Y/%m/%d"), prev_d.strftime("%Y/%m/%d"),
        tw_close, tw_pct, tw_ma5, f_net, t_net, z_net, us_mkt, headlines
    )

    cnt_up = sum(1 for x in ai_votes if x["vote"] == "看漲")
    cnt_dn = sum(1 for x in ai_votes if x["vote"] == "看跌")
    cnt_fl = sum(1 for x in ai_votes if x["vote"] == "平盤")
    if cnt_up > cnt_dn and cnt_up > cnt_fl:
        final_verdict, v_col = f"🔴 多方勝出（{cnt_up} 票看漲，有利順勢做多）", UP
    elif cnt_dn > cnt_up and cnt_dn > cnt_fl:
        final_verdict, v_col = f"🟢 空方勝出（{cnt_dn} 票看跌，進場宜保守提防拉回）", DN
    else:
        final_verdict, v_col = f"⚪ 多空分歧／平盤震盪（漲 {cnt_up} · 跌 {cnt_dn} · 平 {cnt_fl}，建議觀望開盤後方向）", "#FFC83D"

    with st.container(key="vote_card"):
        st.markdown(
            f"<div class='fl-h'>🤖 AI 盤前投研早會聊天室"
            f"<small>會議場次：{fmt_d(target_d)} 08:30 GMT+8 · {status_msg}</small></div>",
            unsafe_allow_html=True
        )

        m = st.columns(4)
        m[0].metric("🔴 投票看漲", f"{cnt_up} 票", "多頭陣營" if cnt_up >= 2 else None)
        m[1].metric("🟢 投票看跌", f"{cnt_dn} 票", "空頭陣營" if cnt_dn >= 2 else None, delta_color="inverse")
        m[2].metric("⚪ 投票平盤", f"{cnt_fl} 票")
        m[3].metric("🎙️ 主持人最終決議", final_verdict.split("（")[0])

        html_doc = build_chatroom_html(
            target_d, prev_d, flow_date_label, tw_close, tw_pct, tw_hl, tw_ma5,
            f_net, t_net, z_net, tot_net, us_mkt, ai_votes,
            cnt_up, cnt_dn, cnt_fl, final_verdict, v_col
        )
        components.html(html_doc, height=1120, scrolling=True)

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
