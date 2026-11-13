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
            r = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {sec['DEEPSEEK_API_KEY']}"},
                json={"model": "deepseek-chat", "response_format": {"type": "json_object"},
                      "messages": [{"role": "user", "content": prompt}], "temperature": 0.4}, timeout=12
            ).json()
            return json.loads(r["choices"][0]["message"]["content"])

        if agent_id == "gemini" and "GEMINI_API_KEY" in sec:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={sec['GEMINI_API_KEY']}"
            r = requests.post(
                url, json={"contents": [{"parts": [{"text": prompt}]}],
                           "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4}}, timeout=12
            ).json()
            txt = r["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(txt)

        if agent_id == "claude" and "ANTHROPIC_API_KEY" in sec:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": sec["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-3-5-sonnet-latest", "max_tokens": 500,
                      "messages": [{"role": "user", "content": prompt + "\n請只輸出純 JSON，不要加 Markdown。"}]}, timeout=12
            ).json()
            return json.loads(r["content"][0]["text"])
    except Exception:
        return None
    return None

@st.cache_data(ttl=900, show_spinner=False)
def generate_ai_meeting(target_date_str, prev_date_str, tw_close, tw_pct, tw_ma5, f_net, t_net, z_net, us_mkt, headlines):
    """產生四位 AI 的獨立國際事件整理與投票結果"""
    sox_pct = us_mkt.get("費城半導體", {}).get("pct", 0.0)
    tsm_pct = us_mkt.get("台積電 ADR", {}).get("pct", 0.0)
    nvda_pct = us_mkt.get("NVIDIA", {}).get("pct", 0.0)
    sp_pct = us_mkt.get("S&P 500", {}).get("pct", 0.0)
    tot_flow = f_net + t_net + z_net

    # 補足預設國際事件池（當 RSS 被阻擋或不足時也能根據真實美股數據生成）
    default_pool = [
        f"美股費城半導體指數隔夜變動 {sox_pct:+.2f}%，直接牽動台股電子權值股開盤氣勢",
        f"台積電 ADR (TSM) 最新收盤漲跌幅 {tsm_pct:+.2f}%，折溢價效應影響今日大盤點數空間",
        f"AI 指標股 NVIDIA 隔夜表現 {nvda_pct:+.2f}%，伺服器與散熱供應鏈情緒受關注",
        f"S&P 500 指數收盤變動 {sp_pct:+.2f}%，反映華爾街對最新聯準會利率路徑與通膨數據之定價",
        f"外資前一交易日於台股現貨{'買超' if f_net>=0 else '賣超'} {abs(f_net):.1f} 億元，新台幣匯率與亞幣資金流向成關鍵",
        f"投信與內資法人單日合計{'買超' if (t_net+z_net)>=0 else '賣超'} {abs(t_net+z_net):.1f} 億元，高股息與主動式 ETF 換股動能持續"
    ]
    all_news = headlines + default_pool

    base_prompt = (
        f"現在是台北時間 {target_date_str} 早上 08:30 的台股盤前投研早會。上次會議為 {prev_date_str} 08:30。\n"
        f"【昨日台股盤勢】加權指數收 {tw_close:,.2f}（{tw_pct:+.2f}%），5MA 為 {tw_ma5:,.2f}。\n"
        f"【昨日三大法人】外資 {f_net:+.1f} 億、投信 {t_net:+.1f} 億、自營商 {z_net:+.1f} 億（合計 {tot_flow:+.1f} 億）。\n"
        f"【隔夜國際盤勢】費半 {sox_pct:+.2f}%、台積電ADR {tsm_pct:+.2f}%、NVDA {nvda_pct:+.2f}%、S&P500 {sp_pct:+.2f}%。\n"
        f"【最新國際新聞標題】{'; '.join(all_news[:8])}\n"
        "請挑出距離上次開會後，國際間最影響今日台股的 3 件事，並結合籌碼面投票決定今日台股走勢為「看漲」、「看跌」或「平盤」。\n"
        "請嚴格回傳 JSON 格式：{\"events\": [\"事件1\", \"事件2\", \"事件3\"], \"vote\": \"看漲|看跌|平盤\", \"reason\": \"60字內結合新聞與籌碼的投票理由\"}"
    )

    results = []
    for idx, ag in enumerate(AI_AGENTS):
        llm_res = _call_llm_json(ag["id"], f"你是 {ag['name']}，專長為{ag['role']}。\n" + base_prompt)
        if llm_res and isinstance(llm_res.get("events"), list) and llm_res.get("vote") in ("看漲", "看跌", "平盤"):
            results.append({**ag, **llm_res, "time": f"08:30:{12 + idx*9:02d}"})
            continue

        # ─── 內建量化推演引擎（無 API Key 時，依各模型權重與真實數據推算） ───
        if ag["id"] == "chatgpt":
            evs = [
                all_news[0] if len(all_news) > 0 else default_pool[0],
                f"S&P 500 隔夜變動 {sp_pct:+.2f}%，美債殖利率與聯準會政策預期主導外資風險偏好",
                f"外資昨日於集中市場{'買超' if f_net>=0 else '賣超'} {abs(f_net):.1f} 億元，跨國資金配置方向明確"
            ]
            score = sp_pct * 0.35 + tsm_pct * 0.35 + (f_net / 120.0) * 0.30
            if score > 0.25:
                v, rsn = "看漲", f"隔夜美股與 TSM ADR ({tsm_pct:+.2f}%) 提供支撐，搭配外資昨日{f_net:+.1f}億籌碼動向，有利多方開高。"
            elif score < -0.25:
                v, rsn = "看跌", f"國際宏觀面偏弱且外資昨日調節 ({f_net:+.1f}億)，大型權值股短線面臨提款壓力。"
            else:
                v, rsn = "平盤", f"美股漲跌互見（S&P {sp_pct:+.2f}%），外資籌碼與國際消息多空抵銷，預期指數於平盤附近狹幅震盪。"

        elif ag["id"] == "deepseek":
            evs = [
                f"費城半導體指數 (^SOX) 收盤變動 {sox_pct:+.2f}%，半導體硬體因子動能顯著",
                all_news[1] if len(all_news) > 1 else default_pool[1],
                f"加權指數收盤 ({tw_close:,.0f}) 相對 5MA ({tw_ma5:,.0f}) 乖離率為 {(tw_close/tw_ma5-1)*100:+.2f}%"
            ]
            score = sox_pct * 0.45 + tw_pct * 0.25 + (tot_flow / 150.0) * 0.30
            if score > 0.30:
                v, rsn = "看漲", f"費半動能 ({sox_pct:+.2f}%) 與三大法人合計 ({tot_flow:+.1f}億) 形成正向共振，量化多頭訊號觸發。"
            elif score < -0.30:
                v, rsn = "看跌", f"費半動能轉弱 ({sox_pct:+.2f}%) 且法人合計 {tot_flow:+.1f}億，短線均線動能承壓，偏空看待。"
            else:
                v, rsn = "平盤", f"量化動能指標處於中性區間，均線乖離收斂，今日大機率維持區間整理格局。"

        elif ag["id"] == "gemini":
            evs = [
                f"台積電 ADR 隔夜表現 {tsm_pct:+.2f}%、NVIDIA 變動 {nvda_pct:+.2f}%，AI 算力鏈直接定調台股開盤",
                all_news[2] if len(all_news) > 2 else default_pool[2],
                f"內資投信昨日{'買超' if t_net>=0 else '賣超'} {abs(t_net):.1f} 億元，AI 權值與 ETF 成分股資金池變化關鍵"
            ]
            score = tsm_pct * 0.50 + nvda_pct * 0.30 + (t_net / 50.0) * 0.20
            if score > 0.25:
                v, rsn = "看漲", f"TSM ADR ({tsm_pct:+.2f}%) 與 NVDA ({nvda_pct:+.2f}%) 領軍，加上投信 ({t_net:+.1f}億) 助攻，電子權值看漲。"
            elif score < -0.25:
                v, rsn = "看跌", f"美股 AI 雙雄隔夜回檔（TSM {tsm_pct:+.2f}%），台股電子權值股今日開盤將承受補跌壓力。"
            else:
                v, rsn = "平盤", f"AI 供應鏈隔夜表現分歧，權值股缺乏單邊突破動能，預期資金轉向中小型題材股輪動。"

        else:  # claude
            evs = [
                all_news[3] if len(all_news) > 3 else default_pool[4],
                f"自營商昨日部位變動 {z_net:+.1f} 億元，反映短線避險與選擇權造市商波動率態度",
                f"外資 ({f_net:+.1f}億) 與投信 ({t_net:+.1f}億) 呈現{'同向共振' if f_net*t_net>0 else '土洋對作'}格局"
            ]
            score = (f_net / 100.0) * 0.40 + (z_net / 40.0) * 0.25 + sox_pct * 0.35
            if score > 0.35 and tw_close >= tw_ma5:
                v, rsn = "看漲", f"指數站穩 5MA 之上，且法人籌碼 ({tot_flow:+.1f}億) 與國際盤勢無明顯下行風險，審慎看多。"
            elif score < -0.20 or (f_net < -150 and tsm_pct < 0):
                v, rsn = "看跌", f"風險控管視角：外資與自營商避險賣壓浮現，加上國際科技股波動，需提防開高走低或回測均線。"
            else:
                v, rsn = "平盤", f"土洋籌碼對作（外資 {f_net:+.1f}億 / 投信 {t_net:+.1f}億），追價風險偏高，判定今日以平盤震盪消化賣壓為主。"

        results.append({**ag, "events": evs, "vote": v, "reason": rsn, "time": f"08:30:{12 + idx*9:02d}"})

    return results

def vote_page():
    st.markdown(VOTE_CSS, unsafe_allow_html=True)
    target_d, prev_d, status_msg = get_meeting_session_info()

    with st.spinner("召開 08:30 AI 投研早會，彙整前日籌碼與國際新聞中…"):
        daily = load_daily("^TWII", "6mo")
        days_flow = last_10_flows()
        us_mkt, headlines = fetch_global_context(target_d.strftime("%Y%m%d"))

    if daily.empty or len(daily) < 6:
        st.error("無法取得大盤歷史資料，會議暫停。")
        return

    # 取得前一日盤勢與三大法人數據
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

    # 統計票數
    cnt_up = sum(1 for x in ai_votes if x["vote"] == "看漲")
    cnt_dn = sum(1 for x in ai_votes if x["vote"] == "看跌")
    cnt_fl = sum(1 for x in ai_votes if x["vote"] == "平盤")
    if cnt_up > cnt_dn and cnt_up > cnt_fl:
        final_verdict, v_col = f"🔴 多方勝出（{cnt_up} 票看漲）", UP
    elif cnt_dn > cnt_up and cnt_dn > cnt_fl:
        final_verdict, v_col = f"🟢 空方勝出（{cnt_dn} 票看跌）", DN
    else:
        final_verdict, v_col = f"⚪ 多空分歧／平盤震盪（漲 {cnt_up} · 跌 {cnt_dn} · 平 {cnt_fl}）", "#FFC83D"

    with st.container(key="vote_card"):
        st.markdown(
            f"<div class='fl-h'>🤖 AI 盤前投研早會聊天室"
            f"<small>會議場次：{fmt_d(target_d)} 08:30 GMT+8 · {status_msg}</small></div>",
            unsafe_allow_html=True
        )

        # 頂部票數統計儀表板
        m = st.columns(4)
        m[0].metric("🔴 投票看漲", f"{cnt_up} 票", "多頭陣營" if cnt_up >= 2 else None)
        m[1].metric("🟢 投票看跌", f"{cnt_dn} 票", "空頭陣營" if cnt_dn >= 2 else None, delta_color="inverse")
        m[2].metric("⚪ 投票平盤", f"{cnt_fl} 票")
        m[3].metric("🎙️ 主持人最終決議", final_verdict.split("（")[0])

        # 組裝聊天室 HTML
        us_summary = " ｜ ".join(
            f"{k} <b style='color:{UP if v['pct']>=0 else DN}'>{v['pct']:+.2f}%</b>"
            for k, v in us_mkt.items()
        ) or "隔夜美股資料載入中"

        chat_html = "<div class='chat-room'>"

        # 1. 主持人開場報告
        chat_html += f"""
        <div class='msg-row host'>
          <div class='avatar' style='background:linear-gradient(135deg,#FFC83D,#d97706);color:#000'>主</div>
          <div style='flex:1'>
            <div class='b-head'>
              <span class='b-name' style='color:#FFC83D'>網站主持人（量化中控台）</span>
              <span class='b-role'>盤前數據餵價與議程主持</span>
              <span class='b-time'>{target_d:%m/%d} 08:30:00</span>
            </div>
            <div style='font-size:.88rem;line-height:1.65'>
              各位 AI 投研委員早安，現在是台北時間 <b>{target_d:%m/%d} 08:30</b>，開始今日台股開盤前決策會議。<br>
              📊 <b>前一交易日（{flow_date_label}）台股盤勢</b>：加權指數收 <b>{tw_close:,.2f}</b> 點
              （<b style='color:{_col(tw_pct)}'>{tw_pct:+.2f}%</b>，高低震幅 {tw_hl:,.0f} 點），5MA 位於 <b>{tw_ma5:,.2f}</b>。<br>
              💰 <b>三大法人買賣超</b>：外資 <b style='color:{_col(f_net)}'>{f_net:+,.1f}億</b> ｜
              投信 <b style='color:{_col(t_net)}'>{t_net:+,.1f}億</b> ｜
              自營商 <b style='color:{_col(z_net)}'>{z_net:+,.1f}億</b>（合計 <b style='color:{_col(tot_net)}'>{tot_net:+,.1f}億</b>）。<br>
              🌎 <b>隔夜美股關鍵指標</b>：{us_summary}。<br>
              請四位模型依序報告距離上次開會（{prev_d:%m/%d} 08:30）後<b>最影響台股的 3 件國際大事</b>，並投下今日漲跌選票！
            </div>
          </div>
        </div>
        """

        # 2. 四位 AI 模型依序發言與投票
        for ag in ai_votes:
            v_cls = "v-up" if ag["vote"] == "看漲" else ("v-dn" if ag["vote"] == "看跌" else "v-fl")
            v_icon = "📈 看漲" if ag["vote"] == "看漲" else ("📉 看跌" if ag["vote"] == "看跌" else "⚖️ 平盤")
            ev_items = "".join(f"<li>{e}</li>" for e in ag["events"][:3])
            chat_html += f"""
            <div class='msg-row'>
              <div class='avatar' style='background:{ag["color"]}'>{ag["short"]}</div>
              <div class='bubble'>
                <div class='b-head'>
                  <span class='b-name'>{ag["name"]}</span>
                  <span class='b-role'>{ag["role"]}</span>
                  <span class='v-badge {v_cls}'>投票：{v_icon}</span>
                  <span class='b-time'>{target_d:%m/%d} {ag["time"]}</span>
                </div>
                <div style='font-size:.82rem;color:#9a97a8'>📌 距上次開會後最影響台股之 3 大國際事件：</div>
                <ol class='ev-list'>{ev_items}</ol>
                <div class='reason-box'><b>🗳️ 籌碼與新聞綜合研判：</b>{ag["reason"]}</div>
              </div>
            </div>
            """

        # 3. 主持人最終唱票與總結
        w_up, w_fl, w_dn = cnt_up * 25, cnt_fl * 25, cnt_dn * 25
        chat_html += f"""
        <div class='msg-row host'>
          <div class='avatar' style='background:linear-gradient(135deg,#FFC83D,#d97706);color:#000'>結</div>
          <div style='flex:1'>
            <div class='b-head'>
              <span class='b-name' style='color:#FFC83D'>網站主持人（計票中心）</span>
              <span class='b-role'>08:30 盤前會議最終統計</span>
              <span class='b-time'>{target_d:%m/%d} 08:31:00</span>
            </div>
            <div style='font-size:.9rem'>
              感謝四位委員發言！今日（{fmt_d(target_d)}）盤前多空投票統計結果：<br>
              <b>看漲 {cnt_up} 票 ｜ 平盤 {cnt_fl} 票 ｜ 看跌 {cnt_dn} 票</b>
              <div class='tally-bar'>
                <div style='width:{w_up}%;background:{UP}'></div>
                <div style='width:{w_fl}%;background:#8d8d99'></div>
                <div style='width:{w_dn}%;background:{DN}'></div>
              </div>
              📢 <b>今日早會結論：<span style='color:{v_col}'>{final_verdict}</span></b>
            </div>
          </div>
        </div>
        </div>
        """

        st.markdown(chat_html, unsafe_allow_html=True)

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
