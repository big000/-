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
.st-key-nav{background:#0b0b0e;padding:.5rem 1.5rem;border-bottom:1px solid #26262d;box-shadow:0 4px 24px rgba(60,20,100,.35)}
.st-key-nav h1{color:#FFC83D;font-size:1.35rem;font-weight:800;letter-spacing:.05em;margin:0;padding:0}
.st-key-nav [data-testid=stHorizontalBlock]{align-items:center}
.st-key-body{padding:.8rem 1.2rem 1.2rem}
.st-key-chart_card{background:#000;border-radius:18px;padding:.8rem 1rem .6rem;box-shadow:0 10px 30px rgba(70,30,120,.3)}
.st-key-flow_card,.st-key-strat_card{background:#15111c;border-radius:18px;padding:.9rem 1.2rem;color:#e8e6ee;box-shadow:0 10px 30px rgba(70,30,120,.25)}
.st-key-chart_card iframe{border-radius:12px}
.ttl{color:#fff;font-size:1.05rem;font-weight:700}.ttl span{color:#8d8d99;font-size:.8rem;margin-left:.4rem;font-weight:500}
.fl-h{color:#fff;font-size:0.95rem;font-weight:700;margin-bottom:.3rem}.fl-h small{color:#8d8d99;font-weight:400;margin-left:.5rem}
.fl{display:grid;grid-template-columns:50px 130px 1fr 280px;gap:12px;align-items:center;padding:6px 0;border-top:1px solid #2a2433}
.fl .nm{font-weight:700;color:#fff}.fl .lt{font-size:1.15rem;font-weight:800}
.fl .sm{font-size:0.8rem;color:#a9a6b5;display:flex;gap:16px;white-space:nowrap}
.fl .sm b{font-weight:700}
.bars{display:grid;grid-template-columns:repeat(10,1fr);gap:5px;height:42px}
.bars>div{display:flex;flex-direction:column;cursor:pointer}.bars .u,.bars .d{flex:1;display:flex}.bars .u{align-items:flex-end}.bars .d{align-items:flex-start}
.bars i{display:block;width:100%;border-radius:2px;transition:opacity .2s}
.bars>div:hover i{opacity:0.7}
.dates{display:grid;grid-template-columns:repeat(10,1fr);gap:5px;color:#7d7a8a;font-size:0.68rem;text-align:center}
div[data-testid=stMetric]{background:#1e1927;border-radius:12px;padding:.5rem .8rem}
div[data-testid=stMetric] label p{color:#a9a6b5!important}div[data-testid=stMetricValue]{color:#fff}
</style>""", unsafe_allow_html=True)

# ───────────────────────── 資料 ─────────────────────────
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
    return d[np.array([x.date() for x in d.index]) == d.index[-1].date()]

@st.cache_data(ttl=60, show_spinner=False)
def load_5m_intraday(sym):
    d = _clean(yf.download(sym, period="5d", interval="5m", progress=False))
    if d.empty: return d
    d.index = d.index.tz_convert(TZ)
    return d[np.array([x.date() for x in d.index]) == d.index[-1].date()]

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
                x["d"] = d.strftime("%m/%d")
                out.append(x)
        d = d - pd.Timedelta(days=1)
    return out[::-1]

# ───────────────────────── 圖表(TradingView lightweight-charts) ─────────────────────────
LW = '<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>'
BASE = LW + """<style>
html,body{margin:0;background:#000;font-family:-apple-system,"Noto Sans TC","Microsoft JhengHei",sans-serif}
#w{position:relative}#cv{position:absolute;left:0;top:0;pointer-events:none}
#lg{position:absolute;left:12px;top:8px;z-index:5;font-size:12px;line-height:1.6;color:#cfcfd8;pointer-events:none;text-shadow:0 0 5px #000}
</style>
<div id="w"><div id="c"></div><canvas id="cv"></canvas><div id="lg"></div></div>
<script>
const UP="#ff4d5a",DN="#22c55e",H=__H__,el=document.getElementById("c"),lg=document.getElementById("lg"),D=__DATA__;
const pad=n=>String(n).padStart(2,"0"),f2=x=>x.toLocaleString("en",{minimumFractionDigits:2,maximumFractionDigits:2});
const big=v=>v>=1e8?(v/1e8).toFixed(1)+"億":v>=1e4?(v/1e4).toFixed(0)+"萬":v;
const mk=o=>LightweightCharts.createChart(el,Object.assign({width:el.clientWidth,height:H,
layout:{background:{color:"#000"},textColor:"#9a9aa6",fontSize:11},
grid:{vertLines:{color:"rgba(255,255,255,.04)"},horzLines:{color:"rgba(255,255,255,.04)"}},
crosshair:{mode:0,vertLine:{style:2,width:1,color:"rgba(255,255,255,.4)",labelBackgroundColor:"#3b3b46"},
horzLine:{style:2,width:1,color:"rgba(255,255,255,.4)",labelBackgroundColor:"#3b3b46"}},
rightPriceScale:{borderColor:"#1f1f26"}},o));
const tkey=t=>typeof t==="string"?t:(t&&t.year?t.year+"-"+pad(t.month)+"-"+pad(t.day):t);
let chart;addEventListener("resize",()=>{chart.applyOptions({width:el.clientWidth});window.redraw&&redraw()});
"""

DAILY_JS = """chart=mk({timeScale:{borderColor:"#1f1f26",rightOffset:3}});const n=D.k.length;
const cs=chart.addCandlestickSeries({upColor:UP,downColor:DN,borderUpColor:UP,borderDownColor:DN,wickUpColor:UP,wickDownColor:DN});
cs.setData(D.k);cs.priceScale().applyOptions({scaleMargins:{top:.1,bottom:.22}});
const vs=chart.addHistogramSeries({priceFormat:{type:"volume"},priceScaleId:"v",lastValueVisible:false,priceLineVisible:false});
vs.setData(D.k.map((b,i)=>({time:b.time,value:D.v[i],color:b.close>=b.open?"rgba(255,77,90,.55)":"rgba(34,197,94,.55)"})));
chart.priceScale("v").applyOptions({scaleMargins:{top:.82,bottom:0}});
const C={5:"#fbbf24",10:"#60a5fa",20:"#c084fc",60:"#34d399",240:"#f472b6"};
for(const p in C){const s=chart.addLineSeries({color:C[p],lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
s.setData(D.k.map((b,i)=>({time:b.time,value:D.m[p][i]})).filter(x=>x.value!=null))}
chart.timeScale().setVisibleLogicalRange({from:n-35,to:n+2});
const idx={};D.k.forEach((b,i)=>idx[b.time]=i);
function show(t){const i=(t in idx)?idx[t]:n-1,b=D.k[i],p=i?D.k[i-1].close:b.open,ch=b.close-p,pc=ch/p*100,c=ch>=0?UP:DN,s=ch>=0?"+":"";
lg.innerHTML=`<b style="color:#fff">${b.time}</b> 開 ${f2(b.open)} 高 ${f2(b.high)} 低 ${f2(b.low)} 收 <b style="color:${c}">${f2(b.close)}</b> <span style="color:${c}">${s}${f2(ch)} (${s}${pc.toFixed(2)}%)</span> 量 ${big(D.v[i])}<br>`+
Object.keys(C).map(k=>`<span style="color:${C[k]}">MA${k} ${D.m[k][i]==null?"--":f2(D.m[k][i])}</span>`).join(" ")}
chart.subscribeCrosshairMove(q=>show(tkey(q.time)));show();</script>"""

INTRA_JS = """chart=mk({handleScroll:false,handleScale:false,timeScale:{visible:false,fixLeftEdge:true,fixRightEdge:true},
rightPriceScale:{borderColor:"#1f1f26",scaleMargins:{top:.1,bottom:.12}}});
const s=chart.addBaselineSeries({baseValue:{type:"price",price:0},topLineColor:UP,topFillColor1:"rgba(255,77,90,.38)",topFillColor2:"rgba(255,77,90,.03)",
bottomLineColor:DN,bottomFillColor1:"rgba(34,197,94,.03)",bottomFillColor2:"rgba(34,197,94,.38)",lineWidth:2,priceLineVisible:false,
priceFormat:{type:"custom",minMove:1,formatter:v=>(v>0?"+":"")+v.toFixed(0)},
autoscaleInfoProvider:o=>{const r=o(),m=r?Math.max(Math.abs(r.priceRange.minValue),Math.abs(r.priceRange.maxValue),20):50;return{priceRange:{minValue:-m,maxValue:m}}}});
const have={};D.pts.forEach(p=>have[p[0]]=p);
s.setData(D.all.map(t=>have[t]?{time:t,value:have[t][1]}:{time:t}));
s.createPriceLine({price:0,color:"rgba(255,255,255,.6)",lineWidth:1,lineStyle:2,axisLabelVisible:true,title:"昨收 "+f2(D.prev)});
chart.timeScale().fitContent();
const cv=document.getElementById("cv"),dpr=window.devicePixelRatio||1;
function redraw(){const w=el.clientWidth;cv.width=w*dpr;cv.height=H*dpr;cv.style.width=w+"px";cv.style.height=H+"px";
const g=cv.getContext("2d");g.scale(dpr,dpr);g.font="11px sans-serif";g.textAlign="center";
D.grid.forEach(t=>{const x=chart.timeScale().timeToCoordinate(t);if(x==null)return;const hr=t%3600===0,d=new Date(t*1000);
g.strokeStyle=hr?"rgba(255,255,255,.30)":"rgba(255,255,255,.10)";g.lineWidth=hr?1.8:.8;g.beginPath();g.moveTo(x,0);g.lineTo(x,H-20);g.stroke();
g.fillStyle=hr?"#cfcfd8":"#7d7d8a";g.fillText(pad(d.getUTCHours())+":"+pad(d.getUTCMinutes()),x,H-5)})}
chart.timeScale().subscribeVisibleLogicalRangeChange(redraw);setTimeout(redraw,80);setTimeout(redraw,400);
function show(t){const p=have[t]||D.pts[D.pts.length-1];if(!p){lg.textContent="尚無資料";return}
const ch=p[1],pc=ch/D.prev*100,c=ch>=0?UP:DN,s=ch>=0?"+":"",d=new Date(p[0]*1000);
lg.innerHTML=`<b style="color:#fff">${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}</b> 指數 <b style="color:${c}">${f2(p[2])}</b> <span style="color:${c}">${s}${f2(ch)} (${s}${pc.toFixed(2)}%)</span> 昨收 ${f2(D.prev)}`}
chart.subscribeCrosshairMove(q=>show(q.time));show();</script>"""

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

def intraday_html(d, prev, h=390):
    off = 8 * 3600
    base = int(d.index[-1].normalize().timestamp()) + off
    pts = [[int(t.timestamp()) + off, round(float(c) - prev, 2), round(float(c), 2)] for t, c in d.Close.items()]
    allt = [base + 9 * 3600 + m * 60 for m in range(271)]
    data = dict(pts=pts, prev=float(prev), all=allt, grid=[t for t in allt if (t - base) % 1800 == 0])
    return (BASE + INTRA_JS).replace("__H__", str(h)).replace("__DATA__", json.dumps(data))

def pick(label, opts, key):
    return st.segmented_control(label, opts, default=opts[0], key=key, label_visibility="collapsed") or opts[0]

# ───────────────────────── 頁面一：大盤 ─────────────────────────
def flows_html(days):
    def bar(a, mx, up):
        ok = (a >= 0) == up
        return f"<i style='height:{abs(a) / mx * 100:.0f}%;background:{UP if up else DN}'></i>" if ok else ""
    col = lambda a: UP if a >= 0 else DN
    
    # 準備各日數據的 JSON 結構供前端互動使用
    raw_data = []
    for i, x in enumerate(days):
        v_f, v_t, v_z = x["外資"]/1e8, x["投信"]/1e8, x["自營"]/1e8
        raw_data.append({
            "d": x["d"],
            "外資": f"{v_f:+,.1f}億", "外資c": col(v_f),
            "投信": f"{v_t:+,.1f}億", "投信c": col(v_t),
            "自營": f"{v_z:+,.1f}億", "自營c": col(v_z)
        })

    h = "<div class='fl-h'>近 10 日三大法人買賣超<small>上市 · 億元 · 紅＝買超 綠＝賣超（滑鼠移至長條可查看該日數值）</small></div>"
    
    for k in ("外資", "投信", "自營"):
        v = [x[k] / 1e8 for x in days]; mx = max(abs(a) for a in v) or 1
        bars = "".join(f"<div onmouseover='updateFlow({i})'><div class='u'>{bar(a, mx, True)}</div><div class='d'>{bar(a, mx, False)}</div></div>" for i, a in enumerate(v))
        s5, s10 = sum(v[-5:]), sum(v)
        last_v = v[-1]
        
        h += (f"<div class='fl'><div class='nm'>{k}</div>"
              f"<div class='lt' id='val_{k}' style='color:{col(last_v)}'>{last_v:+,.1f}億</div>"
              f"<div class='bars' onmouseleave='resetFlow()'>{bars}</div>"
              f"<div class='sm'><div>近 5 日 <b style='color:{col(s5)}'>{s5:+,.1f}億</b></div>"
              f"<div>近 10 日 <b style='color:{col(s10)}'>{s10:+,.1f}億</b></div></div></div>")
        
    dates = "".join(f"<div style='cursor:pointer' onmouseover='updateFlow({i})'>{x['d']}</div>" for i, x in enumerate(days))
    
    # 注入前端互動 JavaScript
    js_code = f"""
    <script>
    const flowData = {json.dumps(raw_data)};
    const lastIdx = flowData.length - 1;
    function updateFlow(i) {{
        const d = flowData[i];
        if(!d) return;
        ['外資', '投信', '自營'].forEach(k => {{
            const el = document.getElementById('val_' + k);
            if(el) {{
                el.innerText = d[k];
                el.style.color = d[k + 'c'];
            }}
        }});
    }}
    function resetFlow() {{
        updateFlow(lastIdx);
    }}
    </script>
    """
    return h + f"<div class='fl' style='border:0;padding-top:0'><div></div><div></div><div class='dates'>{dates}</div><div></div></div>" + js_code

def market_page():
    daily = load_daily("^TWII")
    with st.container(key="chart_card"):
        l, r = st.columns([5, 2], vertical_alignment="center")
        l.markdown("<div class='ttl'>加權指數<span>^TWII</span></div>", unsafe_allow_html=True)
        with r: tf = pick("週期", ["分時圖", "日線圖"], "tf")
        if tf == "分時圖":
            d = load_intraday()
            if d.empty or daily.empty: st.warning("目前抓不到分時資料(可能休市或 Yahoo 暫時無回應)。")
            else:
                dts = pd.DatetimeIndex(daily.index).tz_localize(None).date
                prev = daily.Close[dts < d.index[-1].date()].iloc[-1]
                components.html(intraday_html(d, prev, h=390), height=400)
        elif daily.empty: st.warning("日線資料載入失敗。")
        else: components.html(daily_html(daily, h=390), height=400)
    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
    with st.container(key="flow_card"):
        with st.spinner("讀取證交所三大法人…"): days = last_10_flows()
        if days: st.markdown(flows_html(days), unsafe_allow_html=True)
        else: st.warning("目前無法取得證交所三大法人資料。")

# ───────────────────────── 頁面二：策略 B ─────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def strategy_data():
    df = load_daily("00631L.TW", "3y")
    df_5m = load_5m_intraday("00631L.TW")
    
    if not df.empty and not df_5m.empty:
        last_idx = df.index[-1]
        if df_5m.index[-1].date() == last_idx.date():
            df.loc[last_idx, "High"] = max(df.loc[last_idx, "Open"], df.loc[last_idx, "Close"], df_5m["High"].max())
            df.loc[last_idx, "Low"] = min(df.loc[last_idx, "Open"], df.loc[last_idx, "Close"], df_5m["Low"].min())
            df.loc[last_idx, "Close"] = df_5m["Close"].iloc[-1]
            df.loc[last_idx, "Volume"] += df_5m["Volume"].sum()
            
    return df, None

def simulate(df, em, xm, sl, tp1, sl1, cool):
    d = df.copy()
    for p in (5, 10, 240): d[f"m{p}"] = d.Close.rolling(p).mean()
    O, Hh, L, C, M5, M10, M240 = (d[c].values for c in ("Open", "High", "Low", "Close", "m5", "m10", "m240"))
    pos, ep, reg, ei, last, tr = 0, 0., 0, 0, -9999, []
    line = lambda ep, reg, m5: (ep * (1 - sl1), ep * (1 + tp1)) if reg == 1 else (max(ep * (1 - sl), m5 * xm), None)
    def close(i, xp, why):
        nonlocal pos, last
        tr.append(dict(進場日=d.index[ei].date(), 進場價=round(ep, 2), 出場日=d.index[i].date(), 出場價=round(xp, 2),
                       報酬率=f"{(xp / ep - 1) * 100 - 0.4:+.2f}%", 原因=why)); pos, last = 0, i
    for i in range(241, len(d)):
        m5, m10, m240, m5b, m10b = M5[i-1], M10[i-1], M240[i-1], M5[i-2], M10[i-2]
        if pos:
            ln, tp = line(ep, reg, m5)
            if O[i] <= ln or (tp and O[i] >= tp): close(i, O[i], "跳空出場")
            elif L[i] <= ln: close(i, ln, ("弱勢停損" if reg == 1 else "停損" if ep * (1 - sl) >= m5 * xm else "跌破均線"))
            elif tp and Hh[i] >= tp: close(i, tp, "弱勢停利")
        if not pos and i - last > cool:
            ent = None
            if m5 < m240:
                if m5 > m10 and m5b <= m10b: ent, r = O[i], 1
            else:
                lv = m5 * em
                if O[i] >= lv: ent, r = O[i], 2
                elif Hh[i] >= lv: ent, r = lv, 2
            if ent:
                pos, ep, reg, ei = 1, ent, r, i
                ln, tp = line(ep, reg, m5)
                if L[i] <= ln if ent == O[i] else C[i] <= ln: close(i, ln, "當日停損")
    N = len(d)
    return dict(pos=pos, ep=ep, reg=reg, since=d.index[ei].date() if pos else None,
                cd=max(0, cool + 1 - (N - last)) if last > 0 else 0,
                m5=M5[-1], m10=M10[-1], m240=M240[-1], m5b=M5[-2], m10b=M10[-2], trades=tr)

def strategy_page():
    with st.container(key="strat_card"):
        st.markdown("<div class='fl-h'>策略 B：狀態與訊號<small>00631L · 結合 5 分 K 數據精準判定進出場</small></div>", unsafe_allow_html=True)
        with st.spinner("同步歷史資料…"): df, note = strategy_data()
        if note: st.warning(note)
        if len(df) < 245: st.error("歷史資料不足 245 根，無法計算 240MA。"); return
        with st.expander("策略參數"):
            c = st.columns(6)
            em = c[0].number_input("強勢進場乘數", value=1.04, step=0.01)
            xm = c[1].number_input("強勢出場乘數", value=0.98, step=0.01)
            sl = c[2].number_input("強勢停損 %", value=3.0, step=0.5) / 100
            tp1 = c[3].number_input("弱勢停利 %", value=20.0, step=1.0) / 100
            sl1 = c[4].number_input("弱勢停損 %", value=3.0, step=0.5) / 100
            cool = int(c[5].number_input("冷卻交易日", value=5, step=1))
        s = simulate(df, em, xm, sl, tp1, sl1, cool)
        weak = s["m5"] < s["m240"]
        last = float(df.Close.iloc[-1])
        m = st.columns(4)
        m[0].metric("最新收盤", f"{last:,.2f}", f"{(last / df.Close.iloc[-2] - 1) * 100:+.2f}%")
        m[1].metric("區間", "弱勢 (5MA<240MA)" if weak else "強勢 (5MA≥240MA)")
        m[2].metric("5MA / 10MA", f"{s['m5']:,.1f} / {s['m10']:,.1f}")
        m[3].metric("240MA", f"{s['m240']:,.1f}")
        if s["pos"]:
            ln, tp = (s["ep"] * (1 - sl1), s["ep"] * (1 + tp1)) if s["reg"] == 1 else (max(s["ep"] * (1 - sl), s["m5"] * xm), None)
            msg = f"🟢 模擬持有中（{'弱勢' if s['reg'] == 1 else '強勢'}單，{s['since']} 進場，成本 {s['ep']:,.2f}） 出場線 {ln:,.2f}" + (f" 停利 {tp:,.2f}" if tp else "")
        elif s["cd"]: msg = f"⏳ 冷卻中，還需 {s['cd']} 個交易日才能再進場"
        elif weak:
            hit = s["m5"] > s["m10"] and s["m5b"] <= s["m10b"]
            msg = "🔔 昨日 5MA 上穿 10MA：明日開盤進場" if hit else "⚪ 空手：等待 5MA 上穿 10MA"
        else: msg = f"⚪ 空手：盤中價 ≥ {s['m5'] * em:,.2f}（5MA × {em}）即進場"
        st.info(msg)
        components.html(daily_html(df, h=370, n=120), height=380)
        if s["trades"]: st.dataframe(pd.DataFrame(s["trades"][-5:][::-1]), hide_index=True, use_container_width=True)

# ───────────────────────── 組版 ─────────────────────────
with st.container(key="nav"):
    a, b = st.columns([5, 2])
    a.markdown("<h1>破產後重生之我要靠量化交易發財</h1>", unsafe_allow_html=True)
    with b: view = pick("頁面", ["大盤", "策略"], "view")
with st.container(key="body"):
    market_page() if view == "大盤" else strategy_page()
