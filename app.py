import streamlit as st
import pandas as pd
import requests
from datetime import date, timedelta
import plotly.graph_objects as go
import numpy as np

# --- 1. CONFIGURATION ---
st.set_page_config(layout="wide")
st.title("✅ Multi-Timeframe Trading System (MTF) - Alpha Vantage")

# Timeframe mapping for Alpha Vantage (LTF/HTF)
# Alpha Vantage API uses '1min', '5min', etc. for TIME_SERIES_INTRADAY
AV_INTERVALS = {
    "1T": "1min",
    "5T": "5min",
    "15T": "15min",
    "30T": "30min",
    "1H": "60min",
    # Note: 1D is not supported by the TIME_SERIES_INTRADAY function
}

# --- END CONFIGURATION ---


# --- 2. DATA CACHING AND FETCHING (Alpha Vantage) ---
@st.cache_data(show_spinner="กำลังดึงข้อมูลจาก Alpha Vantage...")
def get_data(ticker, interval, output_size):
    """
    ดึงข้อมูล OHLCV จาก Alpha Vantage (TIME_SERIES_INTRADAY)
    """
    if interval not in AV_INTERVALS:
        return None, f"Error: Interval '{interval}' is not supported by Alpha Vantage Intraday."
    
    av_interval = AV_INTERVALS[interval]
    
    # ดึง API Key จาก Streamlit Secrets
    try:
        api_key = st.secrets["ALPHA_VANTAGE_API_KEY"]
    except KeyError:
        return None, "Configuration Error: ไม่พบ API Key ของ Alpha Vantage ใน Streamlit Secrets"

    # สร้าง URL สำหรับ API call
    url = (
        f'https://www.alphavantage.co/query?'
        f'function=TIME_SERIES_INTRADAY&'
        f'symbol={ticker}&'
        f'interval={av_interval}&'
        f'outputsize={output_size}&' # 'compact' (100 bars) or 'full' (all history)
        f'apikey={api_key}'
    )
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status() # ตรวจสอบ HTTP errors
        data_json = response.json()
        
        # ตรวจสอบข้อผิดพลาด API (เช่น Limit Reached, Invalid Ticker)
        if "Error Message" in data_json:
            return None, f"Alpha Vantage API Error: {data_json['Error Message']}"
        if "Note" in data_json and "limit" in data_json['Note']:
            return None, f"API Limit Reached: กรุณารอ 1 นาที หรือพิจารณาอัปเกรดแผนบริการ"

        # ค้นหา Key ที่เป็น Time Series (เช่น 'Time Series (5min)')
        time_series_key = next((key for key in data_json.keys() if 'Time Series' in key), None)
        
        if not time_series_key:
            return None, "Data Error: Alpha Vantage ไม่พบข้อมูล Time Series สำหรับ Ticker นี้"

        # แปลง JSON เป็น DataFrame
        raw_data = data_json[time_series_key]
        df = pd.DataFrame.from_dict(raw_data, orient='index').astype(float)
        
        # จัดรูปแบบ DataFrame
        df.index = pd.to_datetime(df.index)
        df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        df = df.sort_index() # เรียงจากเก่าไปใหม่
        
        return df, None
    
    except requests.exceptions.HTTPError as http_err:
        return None, f"HTTP Error: การเรียก Alpha Vantage ล้มเหลว ({http_err})"
    except Exception as e:
        return None, f"General Error: เกิดข้อผิดพลาดในการดึงข้อมูล: {e}"


# --- 3. MULTI-TIMEFRAME ANALYSIS AND PLOTTING ---
# (ใช้ฟังก์ชันเดิมได้ เพราะรับ DataFrame ที่จัดรูปแบบเหมือนกัน)
def analyze_and_plot(data_ltf, filter_timeframe_str):
    """
    ทำการวิเคราะห์ MTF และสร้างกราฟเชิงโต้ตอบด้วย Plotly
    """
    
    # 3.1 Resample (สร้างข้อมูล HTF/Filter)
    htf_data = data_ltf['Close'].resample(filter_timeframe_str).last().to_frame(name='Filter_Close')
    htf_data['Filter_Open'] = data_ltf['Open'].resample(filter_timeframe_str).first()
    htf_data['Filter_High'] = data_ltf['High'].resample(filter_timeframe_str).max()
    htf_data['Filter_Low'] = data_ltf['Low'].resample(filter_timeframe_str).min()
    
    # 3.2 Add Simple Filter (SMA) - คำนวณ Simple Moving Average (SMA) 200 บน HTF
    htf_data['Filter_SMA'] = htf_data['Filter_Close'].rolling(window=200).mean()

    # 3.3 Merge Filter Data back to LTF
    data_ltf['Filter_SMA'] = htf_data['Filter_SMA'].ffill() 

    # 3.4 Plotly Chart (กราฟแบบโต้ตอบ)
    fig = go.Figure()

    # Candlestick Chart (LTF)
    fig.add_trace(go.Candlestick(
        x=data_ltf.index,
        open=data_ltf['Open'],
        high=data_ltf['High'],
        low=data_ltf['Low'],
        close=data_ltf['Close'],
        name=f'LTF Price ({st.session_state.ltf})',
        increasing_line_color='#00CC00',
        decreasing_line_color='#FF0000'
    ))

    # Filter Line (HTF SMA)
    fig.add_trace(go.Scatter(
        x=data_ltf.index,
        y=data_ltf['Filter_SMA'],
        line=dict(color='yellow', width=2),
        name=f'HTF Filter (200 SMA on {st.session_state.htf})'
    ))

    # Layout Customization
    fig.update_layout(
        title=f"MTF Analysis: {st.session_state.ticker} | LTF: {st.session_state.ltf} vs HTF Filter: {st.session_state.htf}",
        xaxis_rangeslider_visible=False,
        xaxis_title="Time",
        yaxis_title="Price",
        hovermode="x unified",
        height=700
    )

    st.plotly_chart(fig, use_container_width=True)
    
    # แสดงข้อมูลดิบ (เพื่อดีบัก)
    st.subheader("ข้อมูลดิบ (LTF) พร้อม Filter")
    st.dataframe(data_ltf.tail(200))


# --- 4. STREAMLIT UI ---

# 4.1 Sidebar: Settings & Data Source
st.sidebar.header("Settings & Data Source")

# Ticker Symbol
ticker = st.sidebar.text_input("Ticker Symbol (e.g., AAPL, TSLA)", "AAPL", key="ticker").upper()

# Alpha Vantage Intraday only provides up to 100 bars (compact) or all history (full).
# We set it to 'full' for wider history, but be aware of the 5 calls/minute limit.
output_size = 'full' 

# Execution Timeframe (LTF)
ltf_options = list(AV_INTERVALS.keys())
ltf = st.sidebar.selectbox("Execution Timeframe (LTF)", ltf_options, index=ltf_options.index("5T"), key="ltf")

# Filter Timeframe (HTF)
ltf_index = ltf_options.index(ltf)
htf_options_filtered = ltf_options[ltf_index:] 
default_htf_index = htf_options_filtered.index("30T") if "30T" in htf_options_filtered else 0
htf = st.sidebar.selectbox("Filter Timeframe (HTF)", htf_options_filtered, index=default_htf_index, key="htf")

# Run Button
if st.sidebar.button("Run MTF Analysis"):
    st.session_state.run_analysis = True

# 4.2 Main Area: Run Analysis
if st.session_state.get('run_analysis', False):
    
    # 4.2.1 Data Fetching
    # Alpha Vantage TIME_SERIES_INTRADAY doesn't use start/end date inputs directly
    data_ltf, error_message = get_data(ticker, ltf, output_size)
    
    if error_message:
        st.error(f"❌ Analysis Failed: {error_message}")
    else:
        # 4.2.2 Check Data Size
        if data_ltf.shape[0] < 200:
            st.warning(f"⚠️ คำเตือน: ข้อมูลที่ดึงมามีเพียง {data_ltf.shape[0]} แถว ซึ่งน้อยกว่า 200 แถวที่แนะนำ อาจทำให้การวิเคราะห์ Filter (SMA) ไม่แม่นยำ")
            
        # 4.2.3 Analysis and Plotting
        try:
            analyze_and_plot(data_ltf, htf)
        except Exception as plot_e:
            st.error(f"❌ เกิดข้อผิดพลาดในการวิเคราะห์หรือสร้างกราฟ: {plot_e}. ตรวจสอบ Timeframe หรือลองใช้ Ticker อื่น.")
            
# --- END CODE ---
