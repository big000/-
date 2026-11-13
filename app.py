import xml.etree.ElementTree as ET
import hashlib

# ───────────────────────── 頁面三：AI 投研早會與多空投票 ─────────────────────────
VOTE_CSS = """<style>
.st-key-vote_card{background:#15111c;border-radius:18px;padding:1rem 1.4rem;color:#e8e6ee;box-shadow:0 10px 30px rgba(70,30,120,.25)}
.chat-room{display:flex;flex-direction:column;gap:14px;max-height:540px;overflow-y:auto;padding:10px 6px;margin-top:8px}
.chat-room::-webkit-scrollbar{width:6px}
.chat-room::-webkit-scrollbar-thumb{background:#3a324a;border-radius:3px}
.msg-row{display:flex;gap:12px;align-items:flex-start}
.msg-row.host{background:linear-gradient(90deg,rgba(255,200,61,.12),rgba(30,25,39,.9));border:1px solid rgba(255,200,61,.35);border-radius:14px;padding:12px 16px}
.avatar{width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:1.1rem;flex-shrink:0;color:#fff;box-shadow:0 4px 10px rgba(0,0,0,.3)}
.bubble{background:#1e1927;border:1px solid #2d263b;border-radius:0 14px 14px 14px;padding:11px 15px;flex:1;line-height:1.6;font-size:.9rem}
.b-head{display:flex;align-items:center;gap:10px;margin-bottom:6px;flex-wrap:wrap}
.b-name{font-weight:800;color:#fff;font-size:.98rem}
.b-role{font-size:.75rem;color:#8d8d99}
.b-time{font-size:.73rem;color:#6c6878;margin-left:auto}
.v-badge{padding:2px 10px;border-radius:99px;font-weight:800;font-size:.78rem;letter-spacing:.04em}
.v-up{background:rgba(255,77,90,.18);color:#ff4d5a;border:1px solid #ff4d5a}
.v-dn{background:rgba(34,197,94,.18);color:#22c55e;border:1px solid #22c55e}
.v-fl{background:rgba(169,166,181,.18);color:#d0cedb;border:1px solid #8d8d99}
.ev-list{margin:6px 0 8px 18px;padding:0;color:#cfcfd8;font-size:.86rem}
.ev-list li{margin-bottom:4px}
.reason-box{background:rgba(0,0,0,.28);border-left:3px solid #7c5cff;padding:6px 10px;border-radius:4px;font-size:.85rem;color:#dedbe8}
.tally-bar{display:flex;height:14px;border-radius:7px;overflow:hidden;background:#2a2433;margin:8px 0}
</style>"""

AI_AGENTS = [
    {"id": "chatgpt",  "name": "ChatGPT (GPT-4o)",     "short": "GPT", "color": "#10a37f", "role": "總經與外資期現貨解讀"},
    {"id": "deepseek", "name": "DeepSeek (R1-Quant)",  "short": "DS",  "color": "#3b82f6", "role": "量化動能與費半微結構"},
    {"id": "gemini",   "name": "Gemini (2.5 Pro)",     "short": "GEM", "color": "#8b5cf6", "role": "AI 供應鏈與台積電 ADR 連動"},
    {"id": "claude",   "name": "Claude (3.7 Sonnet)",  "short": "CLD", "color": "#d97706", "role": "風險控管與籌碼背離檢核"},
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

    # 若今日是交易日且已滿 08:30，會議目標日為今日；否則推算下一個（或最近一個已開會）交易日
    cur_d = now.date()
    if is_trading_day(cur_d) and (now.hour > 8 or (now.hour == 8 and now.minute >= 30)):
        target_d = cur_d
        status = "今日 08:30 盤前會議已召開"
    else:
        # 往回找最近一個已經過 08:30 的交易日作為當前展示的會議
        d = cur_d if (not is_trading_day(cur_d) or now.hour < 8 or (now.hour == 8 and now.minute < 30)) else cur_d
        if is_trading_day(cur_d) and (now.hour < 8 or (now.hour == 8 and now.minute < 30)):
            status = f"今日 08:30 會議準備中（目前顯示前次交易日早會紀錄）"
        else:
            status = "休市期間（目前顯示最近一個交易日 08:30 早會紀錄）"
        d = cur_d - timedelta(days=1)
        while not is_trading_day(d):
            d -= timedelta(days=1)
        target_d = d

    # 找前一個交易日（即上次開會日）
    prev_d = target_d - timedelta(days=1)
    while not is_trading_day(prev_d):
        prev_d -= timedelta(days=1)

    return target_d, prev_d, status

@st.cache_data(ttl=900, show_spinner=False)
def fetch_global_context(session_key):
    """抓取隔夜美股關鍵指標與 Google News 國際財經新聞"""
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
    rss_urls = [
        "https://news.google.com/rss/search?q=%E7%BE%8E%E8%82%A1+OR+%E5%8F%B0%E7%A9%8D%E9%9B%BB+OR+%E8%BC%9D%E9%81%94+OR+%E8%81%AF%E6%BA%96%E6%9C%83+when:2d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
        "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    ]
    for url in rss_urls:
        try:
            r = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                for item in root.findall(".//item")[:10]:
                    title = item.find("title").text if item.find("title") is not None else ""
                    title = re.sub(r"\s*-\s*[^-]+$", "", title).strip()
                    if title and title not in headlines and len(title) > 8:
                        headlines.append(title)
        except Exception:
            pass
        if len(headlines) >= 12:
            break

    return us_mkt, headlines[:12]

def _call_llm_json(agent_id, prompt):
    """若 st.secrets 有設定對應 API Key，則呼叫真實大模型回傳 JSON；否則回傳 None 交由內建量化引擎處理"""
    sec = st.secrets if hasattr(st, "secrets") else {}
    try:
        if agent_id == "chatgpt" and "OPENAI_API_KEY" in sec:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {sec['OPENAI_API_KEY']}"},
                json={"model": "gpt-4o-mini", "response_format": {"type": "json_object"},
                      "messages": [{"role": "user", "content": prompt}], "temperature": 0.4}, timeout=12
            ).json()
            return json.loads(r["choices"][0]["message"]["content"])

        if agent_id == "deepseek" and "DEEPSEEK_API_KEY" in sec:
            r
