import streamlit as st
import yfinance as yf
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
from datetime import datetime
import pytz
import plotly.graph_objects as go

st.set_page_config(page_title="量化交易監控面板", layout="wide")

@st.cache_resource
def init_gsheets():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key('1wFQpocCryShtp4s4o7vbGXrykayCcyp4').sheet1
        return sheet
    except Exception as e:
        st.error(f"Google Sheets 連線失敗: {e}")
        return None

@st.cache_data(ttl=3600)
def get_twse_institutional_data():
    url = "https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json"
    try:
        res = requests.get(url, timeout=5).json()
        if res['stat'] == 'OK':
            df = pd.DataFrame(res['data'], columns=res['fields'])
            return df
        return None
    except:
        return None

def sync_data_with_gsheet(sheet):
    if sheet is None:
        return pd.DataFrame()

    df_local = pd.DataFrame(sheet.get_all_records())
    if not df_local.empty:
        df_local.rename(columns={
            '年月日': 'Date', '開盤價(元)': 'Open', 
            '最高價(元)': 'High', '最低價(元)': 'Low', '收盤價(元)': 'Close'
        }, inplace=True)
        df_local['Date'] = pd.to_datetime(df_local['Date'].astype(str), format='%Y%m%d')
        df_local.set_index('Date', inplace=True)
    
    try:
        df_today = yf.download("00631L.TW", period="1d", interval="1d")
        if df_today.empty:
            return df_local
            
        df_today.columns = [col[0] if isinstance(col, tuple) else col for col in df_today.columns]
        latest_market_date = df_today.index[-1]
        
        tw_tz = pytz.timezone('Asia/Taipei')
        current_time = datetime.now(tw_tz)
        
        last_recorded_date = df_local.index[-1] if not df_local.empty else pd.Timestamp('2000-01-01')
        
        if latest_market_date > last_recorded_date:
            if current_time.hour >= 14:
                new_row = [
                    "00631L 元大台灣50正2", latest_market_date.strftime('%Y%m%d'),
                    round(float(df_today.iloc[-1]['Open']), 4), round(float(df_today.iloc[-1]['High']), 4),
                    round(float(df_today.iloc[-1]['Low']), 4), round(float(df_today.iloc[-1]['Close']), 4)
                ]
                sheet.append_row(new_row)
                st.toast(f"✅ {latest_market_date.strftime('%Y-%m-%d')} 收盤資料已寫入！")
                df_local.loc[latest_market_date] = df_today.iloc[-1][['Open', 'High', 'Low', 'Close']]
            else:
                st.toast("🕒 盤中即時試算，不寫入歷史資料庫")
                df_local.loc[latest_market_date] = df_today.iloc[-1][['Open', 'High', 'Low', 'Close']]
                
        return df_local
    except Exception as e:
        st.warning(f"即時報價抓取異常: {e}")
        return df_local

def plot_intraday(df, title):
    fig = go.Figure(data=[go.Scatter(x=df.index, y=df['Close'], mode='lines', fill='tozeroy')])
    fig.update_layout(title=title, template="plotly_white", margin=dict(l=20, r=20, t=40, b=20), height=350)
    return fig

st.title("📈 量化交易監控面板")

st.header("1. 大盤分時圖與三大法人動向")
col_chart, col_inst = st.columns([3, 2])

with col_chart:
    try:
        twii_intraday = yf.download("^TWII", period="1d", interval="1m")
        twii_intraday.columns = [col[0] if isinstance(col, tuple) else col for col in twii_intraday.columns]
        st.plotly_chart(plot_intraday(twii_intraday, "加權指數 (^TWII) 今日分時圖"), use_container_width=True)
    except:
        st.error("大盤分時資料載入失敗。")

with col_inst:
    st.subheader("三大法人買賣超 (上市)")
    inst_df = get_twse_institutional_data()
    if inst_df is not None:
        st.dataframe(inst_df, hide_index=True, use_container_width=True)
    else:
        st.error("目前無法取得證交所三大法人資料。")

st.divider()

st.header("2. 策略 B：狀態與訊號 (00631L)")

sheet = init_gsheets()
with st.spinner("同步 Google Sheets 歷史資料庫中..."):
    df = sync_data_with_gsheet(sheet)

if not df.empty and len(df) > 240:
    MA_Len, Entry_Mult, Exit_Mult, StopLoss_Pct = 5, 1.04, 0.
