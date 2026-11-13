# ───────────────────────── 頁面三：AI 投研早會與多空投票 ─────────────────────────
AI_AGENTS = [
    {"id": "chatgpt",  "name": "ChatGPT (GPT-4o)",     "short": "GPT", "color": "#10a37f", "role": "總經宏觀與外資期現貨解讀"},
    {"id": "deepseek", "name": "DeepSeek (R1-Quant)",  "short": "DS",  "color": "#3b82f6", "role": "量化動能因子與費半微結構"},
    {"id": "gemini",   "name": "Gemini (2.5 Pro)",     "short": "GEM", "color": "#8b5cf6", "role": "AI 供應鏈與台積電 ADR 溢價"},
    {"id": "claude",   "name": "Claude (3.7 Sonnet)",  "short": "CLD", "color": "#d97706", "role": "風險控管與土洋籌碼背離檢核"},
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
                for item in root.findall(".//item")[:12]:
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
        f"美股費城半導體指數隔夜收盤變動 {sox_pct:+.2f}%，牽動台股半導體與電子權值股開盤定價",
        f"台積電 ADR (TSM) 隔夜漲跌幅達 {tsm_pct:+.2f}%，外資對台積電現貨套利空間成為開盤焦點",
        f"AI 領頭羊 NVIDIA 隔夜表現 {nvda_pct:+.2f}%，直接影響台灣 AI 伺服器、組裝與散熱族群買氣",
        f"標普 500 指數收盤變動 {sp_pct:+.2f}%，反映華爾街對最新總經通膨與聯準會利率路徑之預期",
        f"外資昨日於台股集中市場{'買超' if f_net>=0 else '賣超'} {abs(f_net):.1f} 億元，熱錢流向與匯率連動密切",
        f"投信與自營商昨日分別{'買超' if t_net>=0 else '賣超'} {abs(t_net):.1f} 億與{'買超' if z_net>=0 else '賣超'} {abs(z_net):.1f} 億"
    ]
    all_news = headlines + default_pool

    base_prompt = (
        f"現在是台北時間 {target_date_str} 早上 08:30 的台股盤前投研早會。上次會議為 {prev_date_str} 08:30。\n"
        f"【昨日台股盤勢】加權指數收 {tw_close:,.2f}（{tw_pct:+.2f}%），5MA 為 {tw_ma5:,.2f}（乖離 {bias_5ma:+.2f}%）。\n"
        f"【昨日三大法人】外資 {f_net:+.1f} 億、投信 {t_net:+.1f} 億、自營商 {z_net:+.1f} 億（合計 {tot_flow:+.1f} 億）。\n"
        f"【隔夜國際盤勢】費半 {sox_pct:+.2f}%、台積電ADR {tsm_pct:+.2f}%、NVDA {nvda_pct:+.2f}%、S&P500 {sp_pct:+.2f}%。\n"
        f"【最新國際新聞標題】{'; '.join(all_news[:8])}\n"
        "請挑出距離上次開會後，國際間最影響今日台股的 3 件事，並詳細說明你的【推論過程】（包含國際新聞衝擊、籌碼面解讀、進場操作建議），最後投票決定今日台股走勢為「看漲」、「看跌」或「平盤」。\n"
        "請嚴格回傳 JSON 格式：{\"events\": [\"事件1\", \"事件2\", \"事件3\"], \"news_view\": \"新聞與美股連動解析\", \"chip_view\": \"三大法人籌碼解讀\", \"reason\": \"最終投票理由與操作判斷\", \"vote\": \"看漲|看跌|平盤\"}"
    )

    results = []
    for idx, ag in enumerate(AI_AGENTS):
        llm_res = _call_llm_json(ag["id"], f"你是 {ag['name']}，專長為{ag['role']}。\n" + base_prompt)
        if llm_res and isinstance(llm_res.get("events"), list) and llm_res.get("vote") in ("看漲", "看跌", "平盤"):
            results.append({
                **ag,
                "events": llm_res["events"][:3],
                "news_view": llm_res.get("news_view", "依隔夜美股與國際新聞進行宏觀定價。"),
                "chip_view": llm_res.get("chip_view", f"外資 {f_net:+.1f} 億、投信 {t_net:+.1f} 億之籌碼結構分析。"),
                "reason": llm_res.get("reason", ""),
                "vote": llm_res["vote"],
                "time": f"08:30:{12 + idx*9:02d}"
            })
            continue

        # ─── 內建深度推演引擎（完整呈現新聞 + 籌碼 + 進場思考過程） ───
        if ag["id"] == "chatgpt":
            evs = [
                f"【國際焦點】{all_news[0]}",
                f"【總經與美股】S&P 500 隔夜變動 {sp_pct:+.2f}%、台積電 ADR 變動 {tsm_pct:+.2f}%，反映美股最新風險偏好",
                f"【跨國資金】外資前一交易日於台股現貨{'大舉買超' if f_net>100 else ('買超' if f_net>=0 else '調節賣超')} {abs(f_net):.1f} 億元"
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
            evs = [
                f"【硬體動能】費城半導體指數 (^SOX) 隔夜變動 {sox_pct:+.2f}%，NVIDIA 變動 {nvda_pct:+.2f}%",
                f"【產業新聞】{all_news[1] if len(all_news)>1 else default_pool[1]}",
                f"【技術結構】台股昨日收 {tw_close:,.2f} 點 ({tw_pct:+.2f}%)，與 5MA ({tw_ma5:,.2f}) 乖離率為 {bias_5ma:+.2f}%"
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
            evs = [
                f"【AI 算力鏈】NVIDIA 隔夜收盤 {nvda_pct:+.2f}%、台積電 ADR {tsm_pct:+.2f}%，連動台股超過 40% 權重",
                f"【市場熱點】{all_news[2] if len(all_news)>2 else default_pool[2]}",
                f"【內資動向】投信昨日於集中市場{'買超' if t_net>=0 else '賣超'} {abs(t_net):.1f} 億元，鎖定 AI 與高息 ETF 成分股"
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
            evs = [
                f"【風險事件】{all_news[3] if len(all_news)>3 else default_pool[3]}",
                f"【避險情緒】自營商昨日買賣超 {z_net:+.1f} 億元（含權證避險與自營部位），反映短線波動率預期",
                f"【多空比對】昨日台股漲跌 {tw_pct:+.2f}% vs 隔夜美股費半 {sox_pct:+.2f}%、TSM {tsm_pct:+.2f}% 之背離檢核"
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
    """使用獨立 HTML 組裝聊天室，徹底避免 Streamlit Markdown 縮排變程式碼的 Bug"""
    us_summary = " ｜ ".join(
        f"{k} <b style='color:{UP if v['pct']>=0 else DN}'>{v['pct']:+.2f}%</b>"
        for k, v in us_mkt.items()
    ) or "隔夜美股資料載入中"

    cards_html = ""
    for ag in ai_votes:
        v_cls = "v-up" if ag["vote"] == "看漲" else ("v-dn" if ag["vote"] == "看跌" else "v-fl")
        v_icon = "📈 投票：看漲" if ag["vote"] == "看漲" else ("📉 投票：看跌" if ag["vote"] == "看跌" else "⚖️ 投票：平盤")
        ev_items = "".join(f"<li>{e}</li>" for e in ag["events"][:3])
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
            f"<div class='sec-title'>📌 距上次開會（{prev_d:%m/%d} 08:30）後最影響台股之 3 大國際與市場事件：</div>"
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
.chat-room{{display:flex;flex-direction:column;gap:14px;padding:4px 4px 12px 4px}}
.msg-row{{display:flex;gap:12px;align-items:flex-start}}
.msg-row.host{{background:linear-gradient(90deg,rgba(255,200,61,.13),rgba(30,25,39,.95));border:1px solid rgba(255,200,61,.38);border-radius:14px;padding:13px 16px}}
.avatar{{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:1.05rem;flex-shrink:0;color:#fff;box-shadow:0 4px 10px rgba(0,0,0,.35)}}
.bubble{{background:#1e1927;border:1px solid #2f2840;border-radius:0 14px 14px 14px;padding:12px 16px;flex:1;line-height:1.6;font-size:.9rem}}
.b-head{{display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap}}
.b-name{{font-weight:800;color:#fff;font-size:1rem}}
.b-role{{font-size:.76rem;color:#9a97a8;background:#2a2436;padding:2px 8px;border-radius:6px}}
.b-time{{font-size:.74rem;color:#7d7a8a;margin-left:auto}}
.v-badge{{padding:3px 11px;border-radius:99px;font-weight:800;font-size:.8rem;letter-spacing:.03em}}
.v-up{{background:rgba(255,77,90,.2);color:#ff4d5a;border:1px solid #ff4d5a}}
.v-dn{{background:rgba(34,197,94,.2);color:#22c55e;border:1px solid #22c55e}}
.v-fl{{background:rgba(169,166,181,.2);color:#e2e0ec;border:1px solid #8d8d99}}
.sec-title{{font-size:.83rem;color:#b5b1c4;font-weight:600;margin-top:4px}}
.ev-list{{margin:5px 0 10px 20px;padding:0;color:#e8e6ee;font-size:.87rem}}
.ev-list li{{margin-bottom:4px}}
.think-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:9px}}
@media(max-width:768px){{.think-grid{{grid-template-columns:1fr}}}}
.think-box{{background:rgba(255,255,255,.04);border:1px solid #322b42;border-radius:8px;padding:8px 11px;font-size:.83rem;color:#cfcfd8}}
.think-box b{{color:#fff}}
.reason-box{{background:rgba(124,92,255,.12);border-left:4px solid #8b5cf6;padding:8px 12px;border-radius:6px;font-size:.87rem;color:#fff}}
.tally-bar{{display:flex;height:14px;border-radius:7px;overflow:hidden;background:#2a2433;margin:8px 0}}
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
      <div style="font-size:.88rem;line-height:1.7">
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
      <div style="font-size:.9rem;line-height:1.65">
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
        components.html(html_doc, height=980, scrolling=True)

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
