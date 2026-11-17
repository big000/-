import os, io, csv, json, time, re, math
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date, time as dtime, timedelta
import numpy as np, pandas as pd, pytz, requests, yfinance as yf
import streamlit as st
import streamlit.components.v1 as components

# ── 解決 Streamlit Cloud 或部分環境的 SSL 憑證問題 ──
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

st.set_page_config(
    page_title="破產後重生之我要靠量化交易發財",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)
TZ = pytz.timezone("Asia/Taipei")
UP, DN = "#ff4d5a", "#22c55e"                    # 台股慣例：紅漲(多)綠跌(空)

# ───────────────────────── 系統設定與白名單設定 ─────────────────────────
INDEX_TICKER = "^TWII"
ETF_TICKER = "00631L.TW"
FX_TICKER = "TWD=X"
SYM = ETF_TICKER
MAX_ARCHIVE_DAYS = 5
MAX_NEWS_COUNT = 10                              # 網站新聞擷取數量提升為 10 則

NEWS_WHITELIST = [
    {"name": "中央社",   "domain": "cna.com.tw",       "lang": "zh", "paywall": False},
    {"name": "經濟日報", "domain": "money.udn.com",    "lang": "zh", "paywall": False},
    {"name": "工商時報", "domain": "ctee.com.tw",      "lang": "zh", "paywall": False},
    {"name": "鉅亨網",   "domain": "cnyes.com",        "lang": "zh", "paywall": False},
    {"name": "Reuters",  "domain": "reuters.com",      "lang": "en", "paywall": False},
    {"name": "CNBC",     "domain": "cnbc.com",         "lang": "en", "paywall": False},
    {"name": "Bloomberg","domain": "bloomberg.com",    "lang": "en", "paywall": True},
    {"name": "WSJ",      "domain": "wsj.com",          "lang": "en", "paywall": True},
    {"name": "FT",       "domain": "ft.com",           "lang": "en", "paywall": True},
]
NEWS_BLACKLIST = [
    "ptt.cc", "dcard.tw", "kknews.cc", "mobile01.com", "facebook.com",
    "youtube.com", "threads.net", "cmoney.tw", "medium.com"
]

# ───────────────────────── 全域樣式（高對比字體） ─────────────────────────
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
.st-key-chart_card,.st-key-chart_card_s,.st-key-chart_card_fx{background:#000;border-radius:18px;padding:.8rem 1rem .6rem;box-shadow:0 10px 30px rgba(70,30,120,.3)}
.st-key-flow_card,.st-key-fx_flow_card,.st-key-strat_card,.st-key-trade_card,.st-key-vote_card{background:#15111c;border-radius:18px;padding:1rem 1.3rem;color:#ffffff;box-shadow:0 10px 30px rgba(70,30,120,.25)}
.st-key-chart_card iframe,.st-key-chart_card_s iframe,.st-key-chart_card_fx iframe,.st-key-flow_card iframe,.st-key-fx_flow_card iframe,.st-key-vote_card iframe{border-radius:12px;display:block}

/* 標題與副標題高對比顯示 */
.ttl{color:#fff;font-size:1.1rem;font-weight:800}.ttl span{color:#d0cde0;font-size:.88rem;margin-left:.45rem;font-weight:600}
.fl-h{color:#fff;font-size:1.18rem;font-weight:800;margin-bottom:.5rem}
.fl-h small{color:#e2dff0!important;font-weight:500;margin-left:.6rem;font-size:.92rem}

/* 強制深色卡片內所有表單標籤為亮金粗體 */
.st-key-vote_card [data-testid=stWidgetLabel],
.st-key-vote_card [data-testid=stWidgetLabel] p,
.st-key-vote_card label p,
.st-key-strat_card [data-testid=stWidgetLabel],
.st-key-strat_card [data-testid=stWidgetLabel] p,
.st-key-strat_card label p{
  color:#FFC83D!important;
  font-size:.98rem!important;
  font-weight:800!important;
  opacity:1!important;
}

/* 下拉選單與數字輸入框內文字高對比清晰化 */
.st-key-vote_card [data-baseweb=select] div,
.st-key-strat_card [data-baseweb=select] div{
  color:#111111!important;
  font-weight:700!important;
  font-size:.96rem!important;
}
.st-key-vote_card input,
.st-key-strat_card input{
  color:#111111!important;
  -webkit-text-fill-color:#111111!important;
  font-weight:700!important;
  font-size:.96rem!important;
  opacity:1!important;
}
.st-key-vote_card input:disabled,
.st-key-strat_card input:disabled{
  color:#4b5563!important;
  -webkit-text-fill-color:#4b5563!important;
  background-color:#e5e7eb!important;
  font-weight:700!important;
  opacity:1!important;
}

/* Expander 摺疊列標題與邊框高對比 */
.st-key-vote_card [data-testid=stExpander],
.st-key-strat_card [data-testid=stExpander]{
  background:#1e1927!important;
  border:1px solid #4b3f66!important;
  border-radius:12px!important;
}
.st-key-vote_card [data-testid=stExpander] summary p,
.st-key-strat_card [data-testid=stExpander] summary p{
  color:#ffffff!important;
  font-size:.98rem!important;
  font-weight:700!important;
}
.st-key-vote_card [data-testid=stExpander] summary svg,
.st-key-strat_card [data-testid=stExpander] summary svg{
  fill:#FFC83D!important;
  color:#FFC83D!important;
}

/* Caption 狀態小字與提示框放大提亮 */
.st-key-vote_card [data-testid=stCaptionContainer],
.st-key-vote_card [data-testid=stCaptionContainer] p,
.st-key-strat_card [data-testid=stCaptionContainer],
.st-key-strat_card [data-testid=stCaptionContainer] p{
  color:#f1f5f9!important;
  font-size:.94rem!important;
  font-weight:600!important;
}
[data-testid=stAlert] p{
  font-size:1rem!important;
  font-weight:700!important;
}

div[data-testid=stMetric]{background:#1e1927;border:1px solid #352c47;border-radius:12px;padding:.55rem .85rem}
div[data-testid=stMetric] label p{color:#e2dff0!important;font-weight:700!important;font-size:.92rem!important}
div[data-testid=stMetricValue]{color:#fff!important;font-weight:800!important}

/* 晨會快照高對比字卡（紅漲綠跌） */
.snap-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:8px}
@media(max-width:900px){.snap-grid{grid-template-columns:repeat(2,1fr)}}
.snap-card{background:#1e1927;border:1px solid #352c47;border-radius:12px;padding:10px 14px;display:flex;flex-direction:column;gap:4px}
.snap-lbl{color:#e2dff0;font-weight:700;font-size:.92rem}
.snap-val{color:#ffffff;font-weight:800;font-size:1.55rem;line-height:1.2}
.snap-chg{font-weight:800;font-size:.92rem;display:flex;align-items:center;gap:4px}

/* 晨會卡片與新聞列表專用樣式 */
.fact-box{background:#1e1927;border:1px solid #3d3354;border-radius:12px;padding:12px 16px;margin-bottom:10px;line-height:1.65;font-size:.95rem;color:#f1f5f9}
.fact-box b{color:#FFC83D}
.news-item{background:#1e1927;border:1px solid #352c47;border-radius:10px;padding:10px 14px;margin-bottom:8px;display:flex;flex-direction:column;gap:4px}
.news-item a{color:#60a5fa;font-weight:800;font-size:1rem;text-decoration:none}
.news-item a:hover{text-decoration:underline;color:#93c5fd}
.news-meta{font-size:.85rem;color:#cbd5e1;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.badge{background:#312645;color:#FFC83D;padding:2px 8px;border-radius:6px;font-weight:700;font-size:.8rem;border:1px solid rgba(255,200,61,.4)}
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
    if not s or s in ("-", "--", "N/A", "None", "X"):
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
def load_fx_intraday():
    d = _clean(yf.download(FX_TICKER, period="5d", interval="5m", progress=False))
    if d.empty:
        return d
    d.index = d.index.tz_convert(TZ)
    last_d = d.index[-1].date()
    sub = d[d.index.date == last_d]
    if len(sub) < 3:
        dates = sorted(list(set(d.index.date)))
        if len(dates) >= 2:
            sub = d[d.index.date == dates[-2]]
    return sub

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
        time.sleep(0.12)
        if r.get("stat") != "OK":
            return None
        t = {row[0]: int(row[3].replace(",", "")) for row in r["data"]}
        f = lambda k: sum(v for n, v in t.items() if n.startswith(k))
        return {"外資": f("外資"), "投信": f("投信"), "自營": f("自營商"), "ymd": ymd}
    except Exception:
        return None

def _fetch_margin_and_maint_raw(ymd):
    """單日抓取上市融資融券餘額、增減與大盤融資維持率（供多執行緒批次呼叫）"""
    headers = {"User-Agent": "Mozilla/5.0"}
    margin_bal = margin_chg = None
    short_bal = short_chg = None
    total_loan_k = None
    maint_ratio = None
    stock_rows = []

    try:
        r_m = requests.get(
            "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN",
            timeout=10,
            params={"date": ymd, "selectType": "ALL", "response": "json"},
            headers=headers,
        ).json()
        if r_m.get("stat") == "OK":
            for tbl in r_m.get("tables", []):
                flds = tbl.get("fields", [])
                data_rows = tbl.get("data", [])
                if any("項目" in str(f) for f in flds) or (data_rows and "融資" in str(data_rows[0][0])):
                    for row in data_rows:
                        item_name = str(row[0])
                        if "融資金額" in item_name:
                            prev_v = _parse_num(row[4])
                            curr_v = _parse_num(row[5])
                            if curr_v is not None:
                                total_loan_k = curr_v
                                margin_bal = curr_v / 1e5
                                margin_chg = (curr_v - prev_v) / 1e5 if prev_v is not None else 0.0
                        elif "融券" in item_name and "交易單位" in item_name:
                            prev_s = _parse_num(row[4])
                            curr_s = _parse_num(row[5])
                            if curr_s is not None:
                                short_bal = int(curr_s)
                                short_chg = int(curr_s - prev_s) if prev_s is not None else 0
                elif any("代號" in str(f) for f in flds):
                    stock_rows = data_rows
    except Exception:
        pass

    # 若 ALL 模式的統計表未取到，退回 MS 模式取融資融券總額
    if margin_bal is None:
        try:
            r_ms = requests.get(
                "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN",
                timeout=8,
                params={"date": ymd, "selectType": "MS", "response": "json"},
                headers=headers,
            ).json()
            if r_ms.get("stat") == "OK" and r_ms.get("tables"):
                for row in r_ms["tables"][0].get("data", []):
                    item_name = str(row[0])
                    if "融資金額" in item_name:
                        prev_v = _parse_num(row[4])
                        curr_v = _parse_num(row[5])
                        if curr_v is not None:
                            total_loan_k = curr_v
                            margin_bal = curr_v / 1e5
                            margin_chg = (curr_v - prev_v) / 1e5 if prev_v is not None else 0.0
                    elif "融券" in item_name and "交易單位" in item_name:
                        prev_s = _parse_num(row[4])
                        curr_s = _parse_num(row[5])
                        if curr_s is not None:
                            short_bal = int(curr_s)
                            short_chg = int(curr_s - prev_s) if prev_s is not None else 0
        except Exception:
            pass

    # 計算該日大盤融資維持率 (%)
    if total_loan_k and total_loan_k > 0 and stock_rows:
        price_map = {}
        try:
            r_idx = requests.get(
                "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
                timeout=10,
                params={"date": ymd, "type": "ALLBUT0999", "response": "json"},
                headers=headers,
            ).json()
            for tbl in r_idx.get("tables", []):
                flds = tbl.get("fields", [])
                if "證券代號" in flds and "收盤價" in flds:
                    c_i = flds.index("證券代號")
                    p_i = flds.index("收盤價")
                    b_i = flds.index("最後揭示買價") if "最後揭示買價" in flds else None
                    for row in tbl.get("data", []):
                        code = str(row[c_i]).strip()
                        pr = _parse_num(row[p_i])
                        if pr is None and b_i is not None:
                            pr = _parse_num(row[b_i])
                        if pr is not None:
                            price_map[code] = pr
        except Exception:
            pass

        if price_map:
            total_mkt_val_k = 0.0
            for row in stock_rows:
                code = str(row[0]).strip()
                lots = _parse_num(row[6])
                if lots and lots > 0 and code in price_map:
                    total_mkt_val_k += lots * price_map[code]
            if total_mkt_val_k > 0:
                maint_ratio = round((total_mkt_val_k / total_loan_k) * 100.0, 1)

    if margin_bal is not None:
        maint_txt = f"｜大盤維持率 {maint_ratio:.1f}%" if maint_ratio is not None else ""
        return {
            "ok": True,
            "margin_yi": round(margin_bal, 2),
            "margin_chg_yi": round(margin_chg, 2),
            "short_lots": short_bal or 0,
            "short_chg_lots": short_chg or 0,
            "maint_ratio": maint_ratio,
            "label": f"融資餘額 {margin_bal:,.1f} 億（日增減 {margin_chg:+.2f} 億）{maint_txt}｜融券 {short_bal or 0:,d} 張（{short_chg or 0:+,d} 張）",
        }
    return {"ok": False, "label": "未取得", "maint_ratio": None}

@st.cache_data(ttl=900, show_spinner=False)
def twse_margin_day(ymd):
    return _fetch_margin_and_maint_raw(ymd)

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
    out = out[::-1]

    # 為近 10 個交易日平行補齊：融資增減、融資總額、融券增減、融券總額、大盤融資維持率
    target_days = out[-10:]
    with ThreadPoolExecutor(max_workers=5) as ex:
        margin_results = list(ex.map(lambda item: _fetch_margin_and_maint_raw(item["ymd"]), target_days))

    for item, mg in zip(target_days, margin_results):
        if mg and mg.get("ok"):
            item["融資"] = mg["margin_chg_yi"]
            item["融資餘額"] = mg["margin_yi"]
            item["維持率"] = mg.get("maint_ratio")
            item["融券"] = mg["short_chg_lots"]
            item["融券餘額"] = mg["short_lots"]
        else:
            item["融資"] = 0.0
            item["融資餘額"] = None
            item["維持率"] = None
            item["融券"] = 0
            item["融券餘額"] = None

    return out

def last_10_flows():
    return last_15_flows()[-10:]

def _fetch_taifex_tx_single_day(ymd):
    """單日備援：從期交所 futContractsDate 網頁擷取外資臺股期貨未平倉數據"""
    q_date = f"{ymd[:4]}/{ymd[4:6]}/{ymd[6:8]}"
    try:
        r = requests.post(
            "https://www.taifex.com.tw/cht/3/futContractsDate",
            data={"queryType": "1", "doQuery": "1", "queryDate": q_date, "commodityId": "TXF"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        if r.status_code != 200:
            return None
        html = r.text
        idx = html.find("外資及陸資")
        if idx == -1:
            return None
        sub = html[idx:idx + 3500]
        tr_end = sub.find("</tr>")
        if tr_end != -1:
            sub = sub[:tr_end]
        cells = re.findall(r"<td[^>]*>(.*?)</td>", sub, flags=re.S)
        nums = []
        for c in cells:
            clean_c = re.sub(r"<[^>]+>", "", c).strip()
            v = _parse_num(clean_c)
            if v is not None:
                nums.append(int(round(v)))
        if len(nums) >= 11:
            long_oi = nums[6]
            short_oi = nums[8]
            net_oi = nums[10]
            return {
                "ymd": ymd,
                "long_oi": long_oi,
                "short_oi": short_oi,
                "net_oi": net_oi,
                "net_short": -net_oi,
            }
    except Exception:
        pass
    return None

@st.cache_data(ttl=900, show_spinner=False)
def last_10_taifex_fx_oi():
    """取得近 10 個交易日外資台指期未平倉空單與每日增減（含前 1 日基準以計算第 1 日增減）"""
    flows = last_15_flows()
    if not flows:
        return []
    need_days = flows[-11:] if len(flows) >= 11 else flows
    start_d = need_days[0]["dt"] - timedelta(days=3)
    end_d = need_days[-1]["dt"]

    by_ymd = {}
    # 1. 優先使用期交所 CSV 批次下載端點
    try:
        r = requests.post(
            "https://www.taifex.com.tw/cht/3/futContractsDateDown",
            data={
                "queryStartDate": start_d.strftime("%Y/%m/%d"),
                "queryEndDate": end_d.strftime("%Y/%m/%d"),
                "commodityId": "TXF",
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if r.status_code == 200 and len(r.content) > 100:
            txt = r.content.decode("cp950", errors="ignore")
            for row in csv.reader(io.StringIO(txt)):
                if len(row) >= 14 and "外資" in row[2] and ("臺股" in row[1] or "台股" in row[1] or "TX" in row[1]):
                    raw_d = row[0].strip().replace("/", "").replace("-", "")
                    if len(raw_d) == 8 and raw_d.isdigit():
                        long_oi = int(_parse_num(row[9]) or 0)
                        short_oi = int(_parse_num(row[11]) or 0)
                        net_oi = int(_parse_num(row[13]) or 0)
                        by_ymd[raw_d] = {
                            "ymd": raw_d,
                            "long_oi": long_oi,
                            "short_oi": short_oi,
                            "net_oi": net_oi,
                            "net_short": -net_oi,
                        }
    except Exception:
        pass

    # 2. 若有缺漏日期，平行以單日網頁查詢補齊
    missing_ymds = [x["ymd"] for x in need_days if x["ymd"] not in by_ymd]
    if missing_ymds:
        with ThreadPoolExecutor(max_workers=5) as ex:
            fetched = list(ex.map(_fetch_taifex_tx_single_day, missing_ymds))
        for ymd, res in zip(missing_ymds, fetched):
            if res:
                by_ymd[ymd] = res

    ordered = []
    for x in need_days:
        ymd = x["ymd"]
        info = by_ymd.get(ymd)
        if info:
            ordered.append({
                "ymd": ymd,
                "d": x["d"],
                "dt": x["dt"],
                "net_short": info["net_short"],
                "short_oi": info["short_oi"],
                "net_oi": info["net_oi"],
            })
        else:
            ordered.append({
                "ymd": ymd,
                "d": x["d"],
                "dt": x["dt"],
                "net_short": None,
                "short_oi": None,
                "net_oi": None,
            })

    # 計算每日未平倉空單增減
    for i in range(len(ordered)):
        cur_ns = ordered[i]["net_short"]
        prev_ns = ordered[i - 1]["net_short"] if i > 0 else None
        if cur_ns is not None and prev_ns is not None:
            ordered[i]["chg"] = cur_ns - prev_ns
        else:
            ordered[i]["chg"] = 0

    return ordered[-10:]

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

DAILY_LINE_JS = (
    'chart=mk({timeScale:{borderColor:"#1f1f26",rightOffset:3}});const n=D.k.length;'
    'const ls=chart.addAreaSeries({lineColor:"#60a5fa",topColor:"rgba(96,165,250,.28)",bottomColor:"rgba(96,165,250,.02)",lineWidth:2,priceLineVisible:true,lastValueVisible:true});'
    'ls.setData(D.k.map(b=>({time:b.time,value:b.close})));'
    'ls.priceScale().applyOptions({scaleMargins:{top:.12,bottom:.12}});'
    'chart.timeScale().setVisibleLogicalRange({from:Math.max(0,n-60),to:n+2});'
    'const idx={};D.k.forEach((b,i)=>idx[b.time]=i);'
    'function show(t){const i=(t in idx)?idx[t]:n-1,b=D.k[i],p=i?D.k[i-1].close:b.open,ch=b.close-p,pc=p?ch/p*100:0,c=ch>=0?UP:DN,s=ch>=0?"+":"";'
    'lg.innerHTML=`<b style="color:#fff">${b.time.replace(/-/g,"/")}</b> 收盤 <b style="color:${c}">${f2(b.close)}</b> <span style="color:${c}">${s}${f2(ch)} (${s}${pc.toFixed(2)}%)</span> ｜ 高 ${f2(b.high)} 低 ${f2(b.low)}`}'
    'chart.subscribeCrosshairMove(q=>show(tkey(q.time)));show();</script>'
)

INTRA_JS = (
    'chart=mk({handleScroll:false,handleScale:false,timeScale:{visible:false,fixLeftEdge:true,fixRightEdge:true},'
    'rightPriceScale:{borderColor:"#1f1f26",scaleMargins:{top:.1,bottom:.12}}});'
    'const s=chart.addBaselineSeries({baseValue:{type:"price",price:0},topLineColor:UP,topFillColor1:"rgba(255,77,90,.38)",topFillColor2:"rgba(255,77,90,.03)",'
    'bottomLineColor:DN,bottomFillColor1:"rgba(34,197,94,.03)",bottomFillColor2:"rgba(34,197,94,.38)",lineWidth:2,priceLineVisible:false,'
    'priceFormat:{type:"custom",minMove:__MM__,formatter:v=>(D.prev+v).toLocaleString("en",{minimumFractionDigits:__DEC__,maximumFractionDigits:__DEC__})},'
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

def daily_line_html(df, h=390, n=180):
    d = df.copy().tail(n)
    k = [dict(time=i.strftime("%Y-%m-%d"), open=round(float(r.Open), 3), high=round(float(r.High), 3),
              low=round(float(r.Low), 3), close=round(float(r.Close), 3)) for i, r in d.iterrows()]
    data = dict(k=k)
    return (BASE + DAILY_LINE_JS).replace("__H__", str(h)).replace("__DATA__", json.dumps(data))

def intraday_html(d, prev, h=390, step=60, floor=20, dec=0, mm=1, start_hr=9, dur_min=270, grid_sec=1800):
    off = 8 * 3600
    base = int(d.index[-1].normalize().timestamp()) + off
    pts = [[int(t.timestamp()) + off, round(float(c) - prev, 4), round(float(c), 2)] for t, c in d.Close.items()]
    allt = [base + start_hr * 3600 + k * step for k in range(dur_min * 60 // step + 1)]
    data = dict(pts=pts, prev=float(prev), all=allt, grid=[t for t in allt if (t - base) % grid_sec == 0])
    js = INTRA_JS.replace("__FLOOR__", str(floor)).replace("__DEC__", str(dec)).replace("__MM__", str(mm))
    return (BASE + js).replace("__H__", str(h)).replace("__DATA__", json.dumps(data))

def pick(label, opts, key):
    return st.segmented_control(label, opts, default=opts[0], key=key, label_visibility="collapsed") or opts[0]

def prev_close(daily, d):
    dts = pd.DatetimeIndex(daily.index).tz_localize(None).date
    sub = daily.Close[dts < d.index[-1].date()]
    if not sub.empty:
        c_last = float(d.Close.iloc[-1])
        for val in reversed(sub.values):
            if abs(float(val) - c_last) > 1e-5:
                return float(val)
        return float(sub.iloc[-1])
    return float(daily.Close.iloc[-1])

# ───────────────────────── 頁面一：大盤 ─────────────────────────
def _bar(a, mx, up):
    ok = (a >= 0) == up
    return f"<i style='height:{abs(a) / mx * 100:.0f}%;background:{UP if up else DN}'></i>" if ok else ""

def _col(a):
    return UP if a >= 0 else DN

def _bar_short(a, mx, up):
    """外資期貨空單專用柱狀：空單增加(a>=0)為綠色(看空)，空單減少(a<0)為紅色"""
    ok = (a >= 0) == up
    return f"<i style='height:{abs(a) / mx * 100:.0f}%;background:{DN if up else UP}'></i>" if ok else ""

def _col_short(a):
    """外資期貨空單專用文字顏色：空單增加(>0)為綠色(看空)，空單減少(<0)為紅色"""
    return DN if a >= 0 else UP

def _tag_pos_cls(i, total=10):
    if i <= 2:
        return "pos-l"
    if i >= total - 3:
        return "pos-r"
    return "pos-c"

FL_HEAD = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{margin:0;background:transparent;color:#e8e6ee;font-family:-apple-system,"Noto Sans TC","Microsoft JhengHei",sans-serif;overflow:hidden}
.fl-h{color:#fff;font-size:.98rem;font-weight:800;margin-bottom:.3rem}
.fl-h small{color:#d8d4e8;font-weight:500;margin-left:.5rem}
.fl{display:grid;grid-template-columns:64px 140px 1fr 250px;gap:18px;align-items:center;padding:6px 0;border-top:1px solid #2a2433}
.fl.has-bal{padding-top:26px}
.fl .nm{font-weight:700;color:#fff}
.fl .lt{font-size:1.12rem;font-weight:800}
.fl .sm{font-size:.98rem;color:#d0cde0}
.fl .sm .row{display:flex;gap:20px;white-space:nowrap}
.fl .sm b{font-weight:700;font-size:1.02rem}
.bars{display:grid;grid-template-columns:repeat(10,1fr);gap:5px;height:42px}
.bars>div{position:relative;display:flex;flex-direction:column;cursor:pointer;border-radius:3px}
.bars>div.hi{background:rgba(255,255,255,.10)}
.bars .u,.bars .d{flex:1;display:flex}
.bars .u{align-items:flex-end}.bars .d{align-items:flex-start}
.bars i{display:block;width:100%;border-radius:2px}
.bal-tag{
  display:none;
  position:absolute;
  bottom:100%;
  margin-bottom:4px;
  white-space:nowrap;
  background:#261f35;
  border:1px solid rgba(255,200,61,.75);
  color:#FFC83D;
  font-size:.73rem;
  font-weight:800;
  padding:1px 8px;
  border-radius:5px;
  pointer-events:none;
  z-index:6;
  box-shadow:0 2px 8px rgba(0,0,0,.55);
}
.bal-tag.show{display:block}
.bal-tag.pos-l{left:0}
.bal-tag.pos-c{left:50%;transform:translateX(-50%)}
.bal-tag.pos-r{right:0}
.dates{display:grid;grid-template-columns:repeat(10,1fr);gap:5px;color:#b8b4c9;font-size:.72rem;text-align:center}
.dates div{cursor:pointer;border-radius:3px}.dates div.hi{color:#fff;background:rgba(255,255,255,.10)}
</style></head><body>
"""

FL_JS = """
<script>
const flowData=__DATA__, keys=__KEYS__, lastIdx=flowData.length-1;
function updateFlow(i,hl){
  const d=flowData[i]; if(!d) return;
  keys.forEach(k=>{
    const e=document.getElementById('val_'+k);
    if(e){e.innerText=d[k];e.style.color=d[k+'c'];}
  });
  document.getElementById('dlab').innerText=(hl?d.d:'最新 '+d.d)+' __DLAB_SUFFIX__';
  document.querySelectorAll('[data-i]').forEach(e=>e.classList.toggle('hi',hl&&Number(e.dataset.i)===i));
  document.querySelectorAll('[data-bal-i]').forEach(e=>e.classList.toggle('show',Number(e.dataset.balI)===i));
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
    m_tags, s_tags = [], []
    for x in days:
        f, t, z = x["外資"] / 1e8, x["投信"] / 1e8, x["自營"] / 1e8
        m_chg = float(x.get("融資", 0.0) or 0.0)
        s_chg = int(x.get("融券", 0) or 0)
        m_bal = x.get("融資餘額")
        maint = x.get("維持率")
        s_bal = x.get("融券餘額")

        maint_str = f"{maint:.1f}%" if maint is not None else "未取得"
        m_bal_str = f"{x['d']} 融資總額 {m_bal:,.1f}億｜大盤維持率 {maint_str}" if m_bal is not None else f"{x['d']} 融資總額 未取得｜大盤維持率 {maint_str}"
        s_bal_str = f"{x['d']} 融券總額 {s_bal:,d}張" if s_bal is not None else f"{x['d']} 融券總額 未取得"

        m_tags.append(m_bal_str)
        s_tags.append(s_bal_str)
        raw.append({
            "d": x["d"],
            "外資": f"{f:+,.1f}億", "外資c": _col(f),
            "投信": f"{t:+,.1f}億", "投信c": _col(t),
            "自營": f"{z:+,.1f}億", "自營c": _col(z),
            "融資": f"{m_chg:+,.2f}億", "融資c": _col(m_chg),
            "融券": f"{s_chg:+,d}張", "融券c": _col(s_chg),
        })

    total_n = len(days)
    row_configs = [
        ("外資", [x["外資"] / 1e8 for x in days], lambda v: f"{v:+,.1f}億", None),
        ("投信", [x["投信"] / 1e8 for x in days], lambda v: f"{v:+,.1f}億", None),
        ("自營", [x["自營"] / 1e8 for x in days], lambda v: f"{v:+,.1f}億", None),
        ("融資", [float(x.get("融資", 0.0) or 0.0) for x in days], lambda v: f"{v:+,.2f}億", m_tags),
        ("融券", [int(x.get("融券", 0) or 0) for x in days], lambda v: f"{int(round(v)):+,d}張", s_tags),
    ]

    header_block = (
        '<div class="fl-h">近10日三大法人買賣超及融資融券'
        '<small>上市 · 紅＝買超/增加 綠＝賣超/減少（游標移到長條或日期上，左側數值與柱狀上方總額/維持率會同步切換為該日資料）</small></div>'
        '<div class="fl" style="border:0;padding-bottom:2px">'
        '<div></div><div class="lt" id="dlab" style="font-size:.82rem;color:#d0cde0">最新 當日買賣超/增減</div>'
        '<div></div><div class="sm"><div class="row" style="font-size:.78rem;color:#d0cde0">'
        '<div style="width:105px">近 5 日累積</div><div style="width:105px">近 10 日累積</div></div></div></div>'
    )

    rows = ""
    for k, v, fmt_fn, tag_list in row_configs:
        mx = max(abs(a) for a in v) or 1
        bar_cells = []
        for i, a in enumerate(v):
            pos_cls = _tag_pos_cls(i, total_n)
            tag_html = f"<span class='bal-tag {pos_cls}' data-bal-i='{i}'>{tag_list[i]}</span>" if tag_list else ""
            bar_cells.append(
                f"<div data-i='{i}'>{tag_html}<div class='u'>{_bar(a, mx, True)}</div><div class='d'>{_bar(a, mx, False)}</div></div>"
            )
        bars = "".join(bar_cells)
        s5, s10 = sum(v[-5:]), sum(v)
        row_cls = "fl has-bal" if tag_list else "fl"
        rows += (
            f"<div class='{row_cls}'><div class='nm'>{k}</div>"
            f"<div class='lt' id='val_{k}' style='color:{_col(v[-1])}'>{fmt_fn(v[-1])}</div>"
            f"<div class='bars'>{bars}</div>"
            f"<div class='sm'><div class='row'>"
            f"<div style='width:105px'><b style='color:{_col(s5)}'>{fmt_fn(s5)}</b></div>"
            f"<div style='width:105px'><b style='color:{_col(s10)}'>{fmt_fn(s10)}</b></div>"
            f"</div></div></div>"
        )

    dates = "".join(f"<div data-i='{i}'>{x['d']}</div>" for i, x in enumerate(days))
    rows += f"<div class='fl' style='border:0;padding-top:0'><div></div><div></div><div class='dates'>{dates}</div><div></div></div>"
    js_str = (
        FL_JS.replace("__DATA__", json.dumps(raw))
        .replace("__KEYS__", json.dumps(["外資", "投信", "自營", "融資", "融券"]))
        .replace("__DLAB_SUFFIX__", "當日買賣超/增減")
    )
    return FL_HEAD + header_block + rows + js_str

def fx_oi_html(fx_days):
    """近 10 日外資期貨未平倉空單互動式圖表（空單增加為綠色看空、空單減少為紅色）"""
    raw = []
    oi_tags = []
    vals = []
    for x in fx_days:
        chg = int(x.get("chg", 0) or 0)
        ns = x.get("net_short")
        vals.append(chg)
        if ns is not None:
            oi_tags.append(f"{x['d']} 未平倉空單 {ns:,d}口")
        else:
            oi_tags.append(f"{x['d']} 未平倉空單 未取得")
        raw.append({
            "d": x["d"],
            "外資空單": f"{chg:+,d}口",
            "外資空單c": _col_short(chg),
        })

    total_n = len(fx_days)
    mx = max((abs(a) for a in vals), default=1) or 1
    bar_cells = []
    for i, a in enumerate(vals):
        pos_cls = _tag_pos_cls(i, total_n)
        tag_html = f"<span class='bal-tag {pos_cls}' data-bal-i='{i}'>{oi_tags[i]}</span>"
        bar_cells.append(
            f"<div data-i='{i}'>{tag_html}<div class='u'>{_bar_short(a, mx, True)}</div><div class='d'>{_bar_short(a, mx, False)}</div></div>"
        )
    bars = "".join(bar_cells)
    s5, s10 = sum(vals[-5:]), sum(vals)

    header_block = (
        '<div class="fl-h">近10日外資期貨未平倉空單'
        '<small>臺股期貨(TX) · 口 · 綠＝空單增加(看空) 紅＝空單減少（游標移到長條或日期上，左側當日增減與柱狀上方未平倉總額會同步切換）</small></div>'
        '<div class="fl" style="border:0;padding-bottom:2px">'
        '<div></div><div class="lt" id="dlab" style="font-size:.82rem;color:#d0cde0">最新 當日空單增減</div>'
        '<div></div><div class="sm"><div class="row" style="font-size:.78rem;color:#d0cde0">'
        '<div style="width:105px">近 5 日累積</div><div style="width:105px">近 10 日累積</div></div></div></div>'
    )

    last_v = vals[-1] if vals else 0
    rows = (
        f"<div class='fl has-bal'><div class='nm'>外資空單</div>"
        f"<div class='lt' id='val_外資空單' style='color:{_col_short(last_v)}'>{last_v:+,d}口</div>"
        f"<div class='bars'>{bars}</div>"
        f"<div class='sm'><div class='row'>"
        f"<div style='width:105px'><b style='color:{_col_short(s5)}'>{s5:+,d}口</b></div>"
        f"<div style='width:105px'><b style='color:{_col_short(s10)}'>{s10:+,d}口</b></div>"
        f"</div></div></div>"
    )
    dates = "".join(f"<div data-i='{i}'>{x['d']}</div>" for i, x in enumerate(fx_days))
    rows += f"<div class='fl' style='border:0;padding-top:0'><div></div><div></div><div class='dates'>{dates}</div><div></div></div>"

    js_str = (
        FL_JS.replace("__DATA__", json.dumps(raw))
        .replace("__KEYS__", json.dumps(["外資空單"]))
        .replace("__DLAB_SUFFIX__", "當日空單增減")
    )
    return FL_HEAD + header_block + rows + js_str

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
        with st.spinner("讀取證交所三大法人、融資融券與近 10 日大盤維持率…"):
            days = last_10_flows()
        if days:
            components.html(flows_html(days), height=395, scrolling=False)
        else:
            st.warning("目前無法取得證交所三大法人與融資融券資料。")

# ───────────────────────── 頁面二：策略 (00631L.TW) ─────────────────────────
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

def simulate(df, intra, em=1.04, xm=0.98, sl=0.03, tp1=0.20, sl1=0.03, cool=5):
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
        st.markdown("<div class='fl-h'>策略：狀態與訊號<small>00631L · 進出場以 5 分 K 時序精準判定（避免開高走低／開低走高的假訊號）</small></div>",
                    unsafe_allow_html=True)
        with st.spinner("同步歷史資料…"):
            df, intra = strategy_data()
        if len(df) < 245:
            st.error("歷史資料不足 245 根，無法計算 240MA。")
            return
        if not intra:
            st.warning("抓不到 5 分 K，回測退回日 K 判斷。")
        with st.expander("⚙️ 策略參數設定"):
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

# ───────────────────────── 頁面三：匯率 (USD/TWD & 外資期貨空單) ─────────────────────────
def fx_page():
    daily = load_daily(FX_TICKER)
    with st.container(key="chart_card_fx"):
        l, r = st.columns([5, 2], vertical_alignment="center")
        l.markdown(f"<div class='ttl'>美元兌新台幣<span>USD/TWD ({FX_TICKER})</span></div>", unsafe_allow_html=True)
        with r:
            tf = pick("週期", ["分時圖", "日線圖"], "tf_fx")
        if tf == "分時圖":
            d = load_fx_intraday()
            if d.empty or daily.empty:
                st.warning("目前抓不到匯率分時資料，請切換至日線圖或稍後再試。")
            else:
                components.html(
                    intraday_html(
                        d,
                        prev_close(daily, d),
                        h=390,
                        step=300,
                        floor=0.05,
                        dec=2,
                        mm=0.01,
                        start_hr=0,
                        dur_min=1435,
                        grid_sec=7200,
                    ),
                    height=400,
                )
        elif daily.empty:
            st.warning("匯率日線資料載入失敗。")
        else:
            components.html(daily_line_html(daily, h=390), height=400)

    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
    with st.container(key="fx_flow_card"):
        with st.spinner("讀取期交所近 10 日外資台指期未平倉空單…"):
            fx_days = last_10_taifex_fx_oi()
        if fx_days:
            components.html(fx_oi_html(fx_days), height=165, scrolling=False)
        else:
            st.warning("目前無法取得期交所外資台指期未平倉資料。")

# ───────────────────────── 頁面四：晨會與一鍵問問 AI ─────────────────────────
@st.cache_data(ttl=900, show_spinner=False)
def fetch_taifex_oi_and_pcr_for_date(ymd):
    fx_days = last_10_taifex_fx_oi()
    sub = [x for x in fx_days if x["ymd"] <= ymd and x.get("net_short") is not None]
    if sub:
        last_item = sub[-1]
        chg = int(last_item.get("chg", 0) or 0)
        s5 = sum(int(x.get("chg", 0) or 0) for x in sub[-5:])
        return {
            "fx_oi_ok": True,
            "net_short": last_item["net_short"],
            "chg": chg,
            "s5": s5,
            "fx_label": f"未平倉淨空單 {last_item['net_short']:,d} 口｜今日變化量 {chg:+,d} 口（近 5 日累積 {s5:+,d} 口）",
            "pcr_ok": False,
            "pcr_label": "未取得",
        }
    return {"fx_oi_ok": False, "fx_label": "未取得", "pcr_ok": False, "pcr_label": "未取得"}

@st.cache_data(ttl=600, show_spinner=False)
def fetch_overnight_us_market(upto_date):
    tickers = {
        "sox": "^SOX",
        "tsm": "TSM",
        "nvda": "NVDA",
        "sp": "^GSPC",
        "vix": "^VIX",
        "tnx": "^TNX",
        "fx": "TWD=X",
    }
    res = {
        "sox_close": 0.0, "sox_pct": 0.0,
        "tsm_close": 0.0, "tsm_pct": 0.0,
        "nvda_close": 0.0, "nvda_pct": 0.0,
        "sp_close": 0.0, "sp_pct": 0.0,
        "vix_close": 0.0, "vix_pct": 0.0,
        "tnx_close": 0.0, "tnx_pct": 0.0,
        "fx_close": 32.0, "fx_chg": 0.0, "fx_pct": 0.0,
    }
    for k, sym in tickers.items():
        try:
            d = load_daily(sym, period="1mo")
            if d.empty:
                continue
            dts = pd.DatetimeIndex(d.index).tz_localize(None).date
            sub = d[dts <= upto_date]
            if len(sub) < 2:
                sub = d
            c = float(sub["Close"].iloc[-1])
            p = float(sub["Close"].iloc[-2]) if len(sub) >= 2 else c
            # 針對匯率跨日重複報價防呆：往前找最後一個有變動的收盤價
            if k == "fx" and abs(c - p) < 1e-4 and len(sub) >= 3:
                for prev_candidate in reversed(sub["Close"].iloc[:-1].values):
                    if abs(c - float(prev_candidate)) >= 1e-4:
                        p = float(prev_candidate)
                        break
            pct = (c / p - 1.0) * 100.0 if p else 0.0
            res[f"{k}_close"] = round(c, 2)
            res[f"{k}_pct"] = round(pct, 2)
            if k == "fx":
                res["fx_chg"] = round(c - p, 3)
        except Exception:
            continue
    return res

def get_schedule_state(tw_df):
    now = datetime.now(TZ)
    cur_d = now.date()
    dts = [i.date() if hasattr(i, "date") else i for i in tw_df.index]
    unique_dates = sorted(list(set(dts)), reverse=True)
    is_trading, _ = is_tw_trading_day(cur_d)

    if is_trading and cur_d not in unique_dates:
        unique_dates.insert(0, cur_d)

    archive_dates = unique_dates[:MAX_ARCHIVE_DAYS]
    has_live_meeting = cur_d in archive_dates

    if is_trading:
        if now.time() < dtime(8, 30):
            banner_state = "waiting"
            banner_msg = f"⏳ 今日（{cur_d:%Y/%m/%d}）晨會將於 08:30 準時開始。目前時間：{now.strftime('%H:%M')}。"
        else:
            banner_state = "live"
            banner_msg = f"🟢 今日（{cur_d:%Y/%m/%d}）08:30 盤前晨會簡報已上線！"
    else:
        banner_state = "closed"
        banner_msg = f"🔴 今日（{cur_d:%Y/%m/%d}）非台股交易日。顯示最近交易日（{archive_dates[0]:%Y/%m/%d}）的盤前晨會簡報。"

    return {
        "archive_dates": archive_dates,
        "now": now,
        "cur_d": cur_d,
        "has_live_meeting": has_live_meeting,
        "banner_state": banner_state,
        "banner_msg": banner_msg,
    }

def compute_tech_fact_card(df_full, upto_date, label_name):
    dts = pd.DatetimeIndex(df_full.index).tz_localize(None).date
    d = df_full[dts <= upto_date].copy()
    if len(d) < 30:
        return None

    for p in (5, 10, 20, 60, 240):
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
    ma10 = float(r_last["MA10"]) if pd.notna(r_last["MA10"]) else ma5
    ma20 = float(r_last["MA20"])
    ma60 = float(r_last["MA60"]) if pd.notna(r_last["MA60"]) else ma20
    ma240 = float(r_last["MA240"]) if pd.notna(r_last["MA240"]) else ma60

    def _pos_str(p_val, m_val, m_name):
        diff_pct = (p_val / m_val - 1.0) * 100.0
        rel = "上方" if p_val >= m_val else "下方"
        return f"{m_name} {m_val:,.2f}（位於{rel} {diff_pct:+.2f}%）"

    # 依數值由高至低排列：5MA、10MA、20MA、60MA、240MA、收盤價
    rank_items = [
        ("收盤價", c),
        ("5MA", ma5),
        ("10MA", ma10),
        ("20MA", ma20),
        ("60MA", ma60),
        ("240MA", ma240),
    ]
    rank_sorted = sorted(rank_items, key=lambda x: x[1], reverse=True)
    ma_align_order = " > ".join(f"{k}({v:,.2f})" for k, v in rank_sorted)

    trend_fact = (
        f"收盤價為 {c:,.2f}（{chg:+.2f}，{pct:+.2f}%）｜"
        f"{_pos_str(c, ma5, '5MA')}、{_pos_str(c, ma10, '10MA')}、{_pos_str(c, ma20, '20MA')}、"
        f"{_pos_str(c, ma60, '60MA')}、{_pos_str(c, ma240, '240MA')}｜"
        f"排列狀態：{ma_align_order}"
    )

    vol_cur = float(r_last["Volume"]) if pd.notna(r_last["Volume"]) else 0.0
    vol_prev = float(r_prev["Volume"]) if pd.notna(r_prev["Volume"]) else 0.0
    vol_ma5 = float(r_last["VolMA5"]) if (pd.notna(r_last["VolMA5"]) and r_last["VolMA5"] > 0) else 1.0
    vol_ratio = vol_cur / vol_ma5 if vol_ma5 > 0 else 0.0
    if vol_prev > 0:
        vol_chg = vol_cur - vol_prev
        vol_chg_pct = (vol_cur / vol_prev - 1.0) * 100.0
        vol_vs_prev_str = f"較前一交易日 {vol_chg:+,.0f} / {vol_chg_pct:+.2f}%"
    else:
        vol_vs_prev_str = "前一交易日量能無資料"

    vol_fact = (
        f"交易量 {vol_cur:,.0f}（{vol_vs_prev_str}）"
        f"（五日均量 {vol_ma5:,.0f}，為五日均量的 {vol_ratio:.2f} 倍）"
    )

    body = abs(c - o)
    body_pct = body / prev_c * 100.0 if prev_c else 0.0
    body_color = "紅K（收高於開）" if c > o else ("黑K（收低於開）" if c < o else "十字線（收等於開）")
    u_wick = h - max(o, c)
    l_wick = min(o, c) - l
    kbar_fact = (
        f"開 {o:,.2f} / 高 {h:,.2f} / 低 {l:,.2f} / 收 {c:,.2f}｜"
        f"型態為{body_color}，實體長度：{body:,.2f}（{body_pct:.2f}%），"
        f"上影線長 {u_wick:,.2f}，下影線長 {l_wick:,.2f}，全天高低振幅 {h - l:,.2f}"
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
    step_round = 500.0
    upper_round = math.ceil(c / step_round) * step_round
    lower_round = math.floor(c / step_round) * step_round
    if upper_round == c:
        upper_round += step_round
    if lower_round == c:
        lower_round -= step_round

    levels_fact = (
        f"前日高點 {h:,.2f}、前日低點 {l:,.2f}｜"
        f"近 20 日高點 {h20:,.2f}、近 20 日低點 {l20:,.2f}｜"
        f"鄰近整數關卡：{lower_round:,.0f} 與 {upper_round:,.0f}（未回補缺口：{gap_str}）"
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

    return {
        "name": label_name, "date_str": r_last.name.strftime("%Y/%m/%d"),
        "close": c, "open": o, "high": h, "low": l, "prev_close": prev_c,
        "chg": chg, "pct": pct, "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60, "ma240": ma240,
        "ma_align_order": ma_align_order,
        "vol_cur": vol_cur, "vol_prev": vol_prev, "vol_ma5": vol_ma5, "vol_ratio": round(vol_ratio, 2),
        "h20": h20, "l20": l20, "gap_str": gap_str,
        "upper_round": upper_round, "lower_round": lower_round,
        "pivot_up": round(pivot_up, 2), "res_1": round(res_1, 2), "res_2": round(res_2, 2),
        "pivot_dn": round(pivot_dn, 2), "sup_1": round(sup_1, 2), "sup_2": round(sup_2, 2),
        "trend_fact": trend_fact, "vol_fact": vol_fact, "kbar_fact": kbar_fact,
        "levels_fact": levels_fact, "cond_fact": cond_fact,
    }

TOPIC_CLUSTERS = [
    {"id": "tsmc_semi", "name": "台積電 / 晶圓代工 / 先進封裝", "kw": ["台積", "TSM", "2330", "CoWoS", "晶圓", "2奈米", "先進製程", "費半", "semiconductor", "foundry"]},
    {"id": "nvda_ai",   "name": "輝達 NVIDIA / AI 伺服器供應鏈", "kw": ["輝達", "NVIDIA", "NVDA", "Blackwell", "GB200", "GB300", "AI伺服器", "鴻海", "廣達", "緯穎", "CSP"]},
    {"id": "fed_macro", "name": "聯準會利率 / 通膨數據 / 美債匯率", "kw": ["聯準會", "Fed", "降息", "利率", "CPI", "PPI", "非農", "鮑爾", "Powell", "美債", "殖利率", "通膨", "inflation", "匯率", "台幣"]},
    {"id": "tariff_geo","name": "關稅貿易政策 / 出口管制 / 地緣", "kw": ["關稅", "川普", "Trump", "tariff", "出口管制", "禁令", "晶片法", "制裁", "貿易"]},
    {"id": "tw_flow",   "name": "台股外資期現貨 / 投信 ETF 籌碼", "kw": ["外資", "投信", "三大法人", "台指期", "融資", "ETF", "0050", "權值股", "加權指數"]},
]

def _assign_topic_cluster(title_txt):
    t_up = title_txt.upper()
    for cl in TOPIC_CLUSTERS:
        if any(k.upper() in t_up for k in cl["kw"]):
            return cl["id"], cl["name"]
    return "general_mkt", "國際財經與市場焦點"

@st.cache_data(ttl=900, show_spinner=False)
def fetch_and_select_top10_news(window_hours, max_count=MAX_NEWS_COUNT):
    """擷取 10 則白名單新聞標題、媒體、時間與新聞網址（主題分群輪詢平衡）"""
    days_param = max(2, math.ceil(window_hours / 24.0) + 1)
    raw_candidates = []
    seen_titles = set()
    headers = {"User-Agent": "Mozilla/5.0"}

    # 1. 優先從鉅亨網台股公開 API 抓取真實直連新聞網址
    try:
        r_cn = requests.get("https://api.cnyes.com/media/api/v1/newslist/category/tw_stock?limit=15",
                            headers=headers, timeout=5)
        if r_cn.status_code == 200:
            items = r_cn.json().get("items", {}).get("data", [])
            for it in items[:8]:
                nid = it.get("newsId")
                title = str(it.get("title", "")).strip()
                pub_ts = it.get("publishAt", 0)
                if nid and title and len(title) >= 8 and title not in seen_titles:
                    url = f"https://news.cnyes.com/news/id/{nid}"
                    pub_str = datetime.fromtimestamp(pub_ts, TZ).strftime("%Y/%m/%d %H:%M") if pub_ts else ""
                    cid, cname = _assign_topic_cluster(title)
                    seen_titles.add(title)
                    raw_candidates.append({
                        "source": "鉅亨網", "domain": "cnyes.com", "title": title, "url": url,
                        "pub": pub_str, "cluster_id": cid, "cluster_name": cname,
                        "is_paywall": False,
                    })
    except Exception:
        pass

    # 2. 從白名單 Google News RSS 收集新聞網址與標題
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
                if cnt >= 4:
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
                })
        except Exception:
            continue

    # 3. 依主題分群輪詢挑選代表新聞（最多 10 則）
    clusters = {}
    for c in raw_candidates:
        clusters.setdefault(c["cluster_id"], []).append(c)

    for cid in clusters:
        clusters[cid] = sorted(clusters[cid], key=lambda x: (x["domain"] != "cnyes.com", x["is_paywall"]))

    sorted_cids = sorted(clusters.keys(), key=lambda k: (len(clusters[k]), k != "general_mkt"), reverse=True)
    selected, used_urls = [], set()

    for round_idx in range(3):
        for cid in sorted_cids:
            if len(selected) >= max_count:
                break
            group = clusters[cid]
            if round_idx < len(group):
                rep = group[round_idx]
                if rep["url"] not in used_urls:
                    selected.append(rep)
                    used_urls.add(rep["url"])
        if len(selected) >= max_count:
            break

    for c in raw_candidates:
        if len(selected) >= max_count:
            break
        if c["url"] not in used_urls:
            selected.append(c)
            used_urls.add(c["url"])

    return selected[:max_count]

# ───────────────────────── 動態生成新版 AI 提示詞 ─────────────────────────
def build_external_ai_prompt(briefing):
    target_d = briefing["target_d"]
    tw_c = briefing["tw_card"]
    fl = briefing["flow"]
    mg = briefing["margin"]
    mg5 = briefing["margin_5d"]
    op = briefing["oi_pcr"]
    us = briefing["us"]
    news_list = briefing["news_list"]

    # A. 新聞網址（共 N 則）(主持人提供之晨會內容)
    if news_list:
        news_lines = []
        for idx, n in enumerate(news_list, 1):
            pub_info = f"｜發布時間：{n['pub']}" if n.get("pub") else ""
            news_lines.append(
                f"{idx}. [{n['title']}]({n['url']}) （媒體：{n['source']}{pub_info}｜網址：{n['url']}）"
            )
        news_sec = "\n".join(news_lines)
    else:
        news_sec = "1. （目前時間窗內未擷取到新聞網址）"

    # C. 籌碼面欄位格式化（含融資融券五日平均與外資期貨未平倉今日變化量）
    if mg.get("ok"):
        m_avg_str = (
            f"｜五日平均餘額 {mg5['m_bal_avg']:,.2f} 億、五日平均增減 {mg5['m_chg_avg']:+.2f} 億"
            if mg5.get("m_bal_avg") is not None else ""
        )
        s_avg_str = (
            f"｜五日平均餘額 {mg5['s_bal_avg']:,.0f} 張、五日平均增減 {mg5['s_chg_avg']:+,.0f} 張"
            if mg5.get("s_bal_avg") is not None else ""
        )
        maint_part = f"｜大盤維持率 {mg['maint_ratio']:.1f}%" if mg.get("maint_ratio") is not None else ""
        margin_line = (
            f"- 融資餘額：{mg['margin_yi']:,.2f} 億（日增減 {mg['margin_chg_yi']:+.2f} 億{m_avg_str}{maint_part}）｜"
            f"融券：{mg['short_lots']:,d} 張（日增減 {mg['short_chg_lots']:+,d} 張{s_avg_str}）"
        )
    else:
        margin_line = "- 融資餘額：未取得（日增減：未取得｜五日平均：未取得）｜融券：未取得（日增減：未取得｜五日平均：未取得）"

    fx_oi_str = op.get("fx_label", "未取得")

    prompt_text = f"""# 角色
「請擔任專業的台股短線策略分析師。根據我給的資料，為我分析下一個交易日的台股大盤走勢。
請依序評估以下四個維度：
1. 國際盤連動：最新美股四大指數表現、費城半導體指數漲跌幅，以及台積電 ADR 與台指期夜盤的收盤狀況。
2. 籌碼面動向：最近一日外資、投信、自營商的現貨買賣超金額，以及外資在台指期未平倉淨口數、融資融券的增減變化。
3. 技術面位階：加權指數目前相對於 5 日線、月線、季線的位置，以及量價關係是否背離。
4. 題材與風險：近期強勢主流族群（如 AI、半導體、重電或金融等），以及明天的重大財經事件或法說會。
5. 資金面:
=>從匯率去看資金動向
=>看市場的分別流入什麼市場?流出什麼市場?
6. 看法總結
=> 目前多空力道誰佔上風？資金是在輪動還是撤出？
=>明天開盤的預估走勢（開高走低、開高走高、或低開震盪）與關鍵觀察時間點（如 9:30 前的量能）。

# 硬性規則
1. 新聞：放棄 Google News RSS 的加密重導向網址直接命令 AI改用「標題＋關鍵字」搜尋；讀不到的網址請用「標題＋媒體名稱」搜尋同一則報導，並從中挑出你覺得對於台股市場最有影響力的5篇去分析。 仍然讀不到的，標註「僅憑標題／未能讀取」，不得編造內容。
2. 所有論點必須引用下方提供的具體數字（例如「外資 -35.4 億」「收盤低於 5MA 1.2%」），禁止空泛形容，若提供資料過少，不足於提供分析使用，可自行上網搜尋，但需標示哪些是你去另外找的。
3. 區分「事實」與「推論」。
4. 不給單一「買／不買」標籤，要給「條件式」結論：在什麼價位或條件下可以買、什麼條件下不要買、何處停損。

# 輸入資料

## A. 新聞網址（共 {len(news_list)} 則）(主持人提供之晨會內容)
{news_sec}

## B. 交易日：{target_d.strftime('%Y/%m/%d')}（台股籌碼與日K基準日：{tw_c['date_str']}）

## C. 籌碼面（上市，億元）
- 外資現貨：當日 {fl['f1']:+.2f} 億｜近 5 日 {fl['f5']:+.2f} 億｜近 10 日 {fl['f10']:+.2f} 億
- 投信：當日 {fl['t1']:+.2f} 億｜近 5 日 {fl['t5']:+.2f} 億
- 自營商：當日 {fl['z1']:+.2f} 億
{margin_line}
- 外資期貨未平倉數量以及今日變化量：{fx_oi_str}

## D. 技術面
加權指數（^TWII）：
- 趨勢與均線位階：{tw_c['trend_fact']}
- 量能變化：{tw_c['vol_fact']}
- K 棒結構：{tw_c['kbar_fact']}
- 關鍵價位：{tw_c['levels_fact']}
- 條件式支撐壓力：{tw_c['cond_fact']}

## E. 隔夜國際市場(數值，變化%)
- 費半：{us['sox_close']:,.2f}（{us['sox_pct']:+.2f}%）
- 台積電 ADR：{us['tsm_close']:,.2f}（{us['tsm_pct']:+.2f}%）
- VIX：{us['vix_close']:.2f}（{us['vix_pct']:+.2f}%）
- 美債 10Y 殖利率：{us['tnx_close']:.2f}%（{us['tnx_pct']:+.2f}%）
- 台美匯率：{us['fx_close']:.2f}（{us['fx_chg']:+.3f} / {us['fx_pct']:+.2f}%）

# 分析流程（請依序完成）
步驟 1：逐則整理新聞，並依照你挑選的八則新聞，輸出「事情發展」（發生什麼、關鍵數字、時間點），並放棄 Google News RSS 的加密重導向網址直接命令 AI改用「標題＋關鍵字」搜尋。
步驟 2：逐則分析「對台股大盤的影響」，除了分析字面上的因果關係，也去思考是否會有其他的連鎖反應，並標註利多／利空／、影響產業或個股
步驟 3：解讀籌碼面，透過籌碼面妳看到了什麼?
步驟 4：解讀技術面，指出趨勢位階、量價、關鍵支撐與壓力。
步驟 5 : 解讀資金面，透過外匯去了解外資動向，並且利用產業類別去分析資金去向
步驟 6：整合上述，找出「最可能的短線情境」

# 輸出格式（嚴格依此）
## 一、新聞重點
| # | 事情發展（100字內） | 方向 | 影響標的 | 其他相關影響 |

## 二、籌碼面解讀
（哪些消息代表多方、哪些消息代表空方）
=>根據上述資訊，列出你的解讀及思考這些數據背後的意義
## 三、技術面解讀
（3~5 點，含明確支撐／壓力價位）

## 四、資金面解讀
=>

## 五、大盤短線展望（1~3 個交易日）
請用表格列出下一個交易日『偏多、震盪、偏空』三種劇本的觸發條件、關鍵支撐與壓力點位，以及對應的操作建議。」

- 基準情境（機率估計）：…
- 偏多情境（機率估計）：…
- 偏空情境（機率估計）：…
- 三者最關鍵的分歧訊號：…

## 六、風險與資料限制
- 本次分析哪些來源讀取失敗或只憑標題
- 缺值與異常值優先去網路找尋正確數據不得推論；如資料依舊缺失則標記說(缺值或異常)
- 市場上你認為還有甚麼還未反映在價格裡面的利多或利空消息，在此處提出來，警示我目前市場上還有什麼風險"""
    return prompt_text

def render_ask_ai_buttons_html(prompt_text):
    """產生問問 GPT、Gemini、Claude 的一鍵跳轉＋同步強制複製提示詞組件"""
    encoded_q = urllib.parse.quote(prompt_text)
    gpt_url = f"https://chatgpt.com/?q={encoded_q}"
    claude_url = f"https://claude.ai/new?q={encoded_q}"
    gemini_url = "https://gemini.google.com/app"
    prompt_json = json.dumps(prompt_text)

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{{margin:0;background:transparent;font-family:-apple-system,"Noto Sans TC","Microsoft JhengHei",sans-serif;color:#ffffff}}
.ai-bar{{background:linear-gradient(90deg,rgba(255,200,61,.16),rgba(139,92,246,.20));border:1.5px solid rgba(255,200,61,.65);
  border-radius:14px;padding:13px 18px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}}
.ai-title{{font-weight:800;color:#FFC83D;font-size:1.05rem;display:flex;flex-direction:column;gap:4px}}
.ai-title small{{color:#f8fafc;font-weight:600;font-size:.86rem}}
.btn-group{{display:flex;gap:10px;flex-wrap:wrap;align-items:center}}
.ai-btn{{display:inline-flex;align-items:center;gap:7px;padding:9px 16px;border-radius:10px;font-weight:800;font-size:.95rem;
  text-decoration:none;color:#fff;cursor:pointer;border:1px solid rgba(255,255,255,.25);transition:all .15s ease;
  box-shadow:0 4px 12px rgba(0,0,0,.35);font-family:inherit}}
.ai-btn:hover{{transform:translateY(-2px);filter:brightness(1.12)}}
.btn-gpt{{background:linear-gradient(135deg,#10a37f,#0d8a6a)}}
.btn-gemini{{background:linear-gradient(135deg,#3b82f6,#8b5cf6)}}
.btn-claude{{background:linear-gradient(135deg,#d97706,#b45309)}}
.btn-copy{{background:#2a2436;color:#FFC83D;border-color:#FFC83D}}
#toast{{font-size:.88rem;color:#34d399;font-weight:800;display:none;width:100%;margin-top:4px}}
</style></head><body>
<div class="ai-bar">
  <div class="ai-title">
    <span>🚀 一鍵問問 AI（已自動替換為今日最新 10 則新聞網址、籌碼與技術面數據）</span>
    <small>GPT／Claude 點擊即自動帶入對話框；Gemini 因 Google 官方不開放網址填入，點擊時已自動複製提示詞，進頁面直接按 Ctrl+V 貼上即可送出</small>
  </div>
  <div class="btn-group">
    <button type="button" class="ai-btn btn-gpt" onclick="openAI('gpt')">💬 問問 GPT</button>
    <button type="button" class="ai-btn btn-gemini" onclick="openAI('gemini')">✨ 問問 Gemini</button>
    <button type="button" class="ai-btn btn-claude" onclick="openAI('claude')">🧠 問問 Claude</button>
    <button type="button" class="ai-btn btn-copy" onclick="openAI('copy')">📋 僅複製提示詞</button>
  </div>
  <div id="toast"></div>
</div>
<script>
const PROMPT_TEXT = {prompt_json};
const URL_MAP = {{
  gpt: {json.dumps(gpt_url)},
  gemini: {json.dumps(gemini_url)},
  claude: {json.dumps(claude_url)}
}};

function syncCopyText(text) {{
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.position = 'fixed';
  ta.style.top = '0';
  ta.style.left = '0';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  ta.setSelectionRange(0, text.length);
  try {{ document.execCommand('copy'); }} catch (e) {{}}
  document.body.removeChild(ta);
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    try {{ navigator.clipboard.writeText(text); }} catch (e) {{}}
  }}
}}

function openAI(mode) {{
  syncCopyText(PROMPT_TEXT);

  const t = document.getElementById('toast');
  if (mode === 'copy') {{
    t.innerText = '✅ 已成功複製最新提示詞到剪貼簿！';
    t.style.display = 'block';
    return;
  }}
  if (mode === 'gemini') {{
    t.innerText = '✅ 已自動複製提示詞！正在開啟 Gemini，進入後請直接按 Ctrl+V 貼上送出。';
  }} else {{
    t.innerText = '✅ 已同步複製提示詞並正在開啟對話視窗（若網址過長被截斷，直接按 Ctrl+V 貼上即可）！';
  }}
  t.style.display = 'block';
  window.open(URL_MAP[mode], '_blank', 'noopener,noreferrer');
}}
</script></body></html>"""

def _render_snapshot_cards(us_info):
    """渲染晨會 5 張國際市場與匯率快照卡（下方以紅漲綠跌顯示變化數值與 %）"""
    def _chg_html(pct_val, extra_chg=None):
        c = UP if pct_val >= 0 else DN
        arr = "▲" if pct_val > 0 else ("▼" if pct_val < 0 else "—")
        if extra_chg is not None:
            return f"<div class='snap-chg' style='color:{c}'>{arr} {extra_chg:+.2f}（{pct_val:+.2f}%）</div>"
        return f"<div class='snap-chg' style='color:{c}'>{arr} {pct_val:+.2f}%</div>"

    cards_html = f"""
    <div class="snap-grid">
      <div class="snap-card">
        <div class="snap-lbl">費半</div>
        <div class="snap-val">{us_info['sox_close']:,.2f}</div>
        {_chg_html(us_info['sox_pct'])}
      </div>
      <div class="snap-card">
        <div class="snap-lbl">台積電 ADR</div>
        <div class="snap-val">{us_info['tsm_close']:,.2f}</div>
        {_chg_html(us_info['tsm_pct'])}
      </div>
      <div class="snap-card">
        <div class="snap-lbl">VIX</div>
        <div class="snap-val">{us_info['vix_close']:,.2f}</div>
        {_chg_html(us_info['vix_pct'])}
      </div>
      <div class="snap-card">
        <div class="snap-lbl">美債 10Y 殖利率</div>
        <div class="snap-val">{us_info['tnx_close']:.2f}%</div>
        {_chg_html(us_info['tnx_pct'])}
      </div>
      <div class="snap-card">
        <div class="snap-lbl">匯率 (USD/TWD)</div>
        <div class="snap-val">{us_info['fx_close']:.2f}</div>
        {_chg_html(us_info['fx_pct'], extra_chg=us_info['fx_chg'])}
      </div>
    </div>
    """
    st.markdown(cards_html, unsafe_allow_html=True)

def _render_tech_card_box(title_label, card):
    if not card:
        st.warning(f"{title_label} 資料不足，無法產生技術面事實卡。")
        return
    html = f"""
    <div class="fact-box">
      <div style="font-size:1.05rem;font-weight:800;color:#ffffff;margin-bottom:6px">
        📊 {title_label}（基準日：{card['date_str']}）
      </div>
      <div><b>• 趨勢與均線位階：</b>{card['trend_fact']}</div>
      <div><b>• 量能變化：</b>{card['vol_fact']}</div>
      <div><b>• K 棒結構：</b>{card['kbar_fact']}</div>
      <div><b>• 關鍵價位：</b>{card['levels_fact']}</div>
      <div><b>• 條件式支撐壓力：</b>{card['cond_fact']}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

def briefing_page():
    with st.container(key="vote_card"):
        st.markdown(
            "<div class='fl-h'>晨會"
            "<small>08:30 盤前簡報 & 一鍵問問 AI（自動彙整 10 則白名單新聞網址、上市籌碼、隔夜美股與大盤技術面數據）</small></div>",
            unsafe_allow_html=True,
        )
        with st.spinner("正在載入晨會簡報、籌碼與最新新聞…"):
            tw_df = load_daily(INDEX_TICKER)
            flows_all = last_15_flows()

        if tw_df.empty:
            st.error("無法取得台股歷史日線資料，請稍後再試。")
            return

        sched = get_schedule_state(tw_df)
        if sched["banner_state"] == "live":
            st.success(sched["banner_msg"])
        elif sched["banner_state"] == "waiting":
            st.info(sched["banner_msg"])
        else:
            st.warning(sched["banner_msg"])

        c1, c2 = st.columns(2)
        archive_dates = sched["archive_dates"]
        sel_d = c1.selectbox(
            "📅 選擇晨會交易日",
            archive_dates,
            format_func=lambda d: f"{d:%Y/%m/%d}（週{WD[d.weekday()]}）",
        )
        win_hr = c2.selectbox("📰 新聞擷取時間窗（小時）", [24, 36, 48, 72], index=1)

        tw_card = compute_tech_fact_card(tw_df, sel_d, "加權指數 (^TWII)")
        if not tw_card:
            st.warning("所選日期的歷史資料不足以計算技術指標。")
            return

        sub_flows = [x for x in flows_all if x["dt"] <= sel_d] or flows_all
        if sub_flows:
            f_last = sub_flows[-1]
            f1 = f_last["外資"] / 1e8
            t1 = f_last["投信"] / 1e8
            z1 = f_last["自營"] / 1e8
            f5 = sum(x["外資"] for x in sub_flows[-5:]) / 1e8
            f10 = sum(x["外資"] for x in sub_flows[-10:]) / 1e8
            t5 = sum(x["投信"] for x in sub_flows[-5:]) / 1e8
            ref_ymd = f_last["ymd"]
        else:
            f1 = t1 = z1 = f5 = f10 = t5 = 0.0
            ref_ymd = sel_d.strftime("%Y%m%d")

        # 計算近 5 日融資融券平均餘額與平均增減
        recent_5 = sub_flows[-5:] if sub_flows else []
        m_bals_5 = [x["融資餘額"] for x in recent_5 if x.get("融資餘額") is not None]
        m_chgs_5 = [x["融資"] for x in recent_5 if x.get("融資") is not None]
        s_bals_5 = [x["融券餘額"] for x in recent_5 if x.get("融券餘額") is not None]
        s_chgs_5 = [x["融券"] for x in recent_5 if x.get("融券") is not None]

        margin_5d_dict = {
            "m_bal_avg": round(float(np.mean(m_bals_5)), 2) if m_bals_5 else None,
            "m_chg_avg": round(float(np.mean(m_chgs_5)), 2) if m_chgs_5 else None,
            "s_bal_avg": round(float(np.mean(s_bals_5)), 0) if s_bals_5 else None,
            "s_chg_avg": round(float(np.mean(s_chgs_5)), 0) if s_chgs_5 else None,
        }

        flow_dict = {
            "f1": round(f1, 2), "f5": round(f5, 2), "f10": round(f10, 2),
            "t1": round(t1, 2), "t5": round(t5, 2), "z1": round(z1, 2),
            "ymd": ref_ymd,
        }
        margin_info = twse_margin_day(ref_ymd)
        oi_pcr_info = fetch_taifex_oi_and_pcr_for_date(ref_ymd)
        us_info = fetch_overnight_us_market(sel_d)
        news_list = fetch_and_select_top10_news(win_hr, max_count=MAX_NEWS_COUNT)

        briefing = {
            "target_d": sel_d,
            "tw_card": tw_card,
            "flow": flow_dict,
            "margin": margin_info,
            "margin_5d": margin_5d_dict,
            "oi_pcr": oi_pcr_info,
            "us": us_info,
            "news_list": news_list,
        }

        prompt_text = build_external_ai_prompt(briefing)
        components.html(render_ask_ai_buttons_html(prompt_text), height=120, scrolling=False)

        with st.expander("📋 檢視／手動複製完整 AI 提示詞內容"):
            st.code(prompt_text, language="markdown")

        st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)
        st.markdown("<div class='fl-h'>一、隔夜國際市場與台股籌碼快照</div>", unsafe_allow_html=True)
        _render_snapshot_cards(us_info)

        st.caption(
            f"📌 籌碼補充：外資當日 {flow_dict['f1']:+.2f} 億（近5日 {flow_dict['f5']:+.2f} 億）｜"
            f"投信當日 {flow_dict['t1']:+.2f} 億（近5日 {flow_dict['t5']:+.2f} 億）｜"
            f"自營商當日 {flow_dict['z1']:+.2f} 億｜{margin_info.get('label', '融資融券：未取得')}｜"
            f"外資期貨：{oi_pcr_info.get('fx_label', '未取得')}"
        )

        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
        st.markdown("<div class='fl-h'>二、技術面數據摘要</div>", unsafe_allow_html=True)
        _render_tech_card_box("加權指數 (^TWII)", tw_card)

        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='fl-h'>三、最新精選白名單財經新聞（共 {len(news_list)} 則）</div>", unsafe_allow_html=True)
        if not news_list:
            st.info("目前時間窗內未抓取到符合條件的新聞。")
        else:
            for idx, n in enumerate(news_list, 1):
                pub_txt = f"<span>🕒 {n['pub']}</span>" if n.get("pub") else ""
                st.markdown(
                    f"""<div class="news-item">
                        <a href="{n['url']}" target="_blank" rel="noopener noreferrer">{idx}. {n['title']} ↗</a>
                        <div class="news-meta">
                            <span class="badge">{n['source']}</span>
                            <span class="badge">{n['cluster_name']}</span>
                            {pub_txt}
                        </div>
                    </div>""",
                    unsafe_allow_html=True,
                )

# ───────────────────────── 頂部導覽列與主程式入口 ─────────────────────────
with st.container(key="nav"):
    nl, nr = st.columns([5, 4], vertical_alignment="center")
    nl.markdown("<h1>📈 破產後重生之我要靠量化交易發財</h1>", unsafe_allow_html=True)
    with nr:
        page = pick("導覽", ["大盤", "策略", "匯率", "晨會"], "nav_page")

with st.container(key="body"):
    if page == "大盤":
        market_page()
    elif page == "策略":
        strategy_page()
    elif page == "匯率":
        fx_page()
    elif page == "晨會":
        briefing_page()
