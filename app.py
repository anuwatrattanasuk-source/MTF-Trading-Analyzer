import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import date, timedelta
import plotly.graph_objects as go

# --- 1. CONFIGURATION ---
st.set_page_config(layout="wide")
st.title("✅ Multi-Timeframe Trading System (MTF)")

# Timeframe mapping for yfinance (LTF/HTF)
YF_INTERVALS = {
    "1T": "1m",
    "5T": "5m",
    "15T": "15m",
    "30T": "30m",
    "1H": "1h",
    "1D": "1d",
}
# --- END CONFIGURATION ---


# --- 2. DATA CACHING AND FETCHING (with Error Handling and Caching) ---
@st.cache_data(show_spinner="กำลังดึงข้อมูลจาก yfinance...")
def get_data(ticker, interval, start_date, end_date):
    """
    ดึงข้อมูล OHLCV จาก yfinance โดยมีการจัดการข้อผิดพลาด
    """
    if interval not in YF_INTERVALS:
        return None, f"Error: Interval '{interval}' is not supported by yfinance."
    
    yf_interval = YF_INTERVALS[interval]
    
    try:
        data = yf.download(
            tickers=ticker,
            start=start_date,
            end=end_date,
            interval=yf_interval,
            progress=False
        )
        
        # *** ส่วนที่แก้ไข: เพิ่มการตรวจสอบ isinstance(data, pd.DataFrame) ***
        if not isinstance(data, pd.DataFrame):
             # ถ้า data ไม่ใช่ DataFrame (เช่น เป็น tuple ที่มี Error Message)
             return None, f"Error: Ticker '{ticker}' ไม่ถูกต้อง, ไม่มีข้อมูล, หรือช่วงวันที่ยาวเกินไปสำหรับ Timeframe '{interval}'"

        # ตรวจสอบว่ามีข้อมูลภายในหรือไม่
        if data.empty:
            return None, f"Error: ไม่พบข้อมูลสำหรับ '{ticker}' ในช่วงวันที่ที่เลือก กรุณาลองช่วงวันที่สั้นลง"
        
        # เปลี่ยนชื่อคอลัมน์ให้เป็นมาตรฐาน
        data.columns = [col.capitalize() for col in data.columns]
        
        # ลบคอลัมน์ที่ Streamlit ไม่ต้องการ
        if 'Adj Close' in data.columns:
            data = data.drop(columns=['Adj Close'])

        return data, None
    
    except Exception as e:
        # แจ้งเตือนข้อผิดพลาด API
        return None, f"API Error: การเรียก yfinance ล้มเหลว อาจเกิดจาก Ticker ไม่ถูกต้อง หรือปัญหาการเชื่อมต่อ: {e}"


# --- 3. MULTI-TIMEFRAME ANALYSIS AND PLOTTING ---

def analyze_and_plot(data_ltf, filter_timeframe_str):
    """
    ทำการวิเคราะห์ MTF และสร้างกราฟเชิงโต้ตอบด้วย Plotly
    """
    
    # 3.1 Resample (สร้างข้อมูล HTF/Filter)
    # ใช้วิธีการ Resample มาตรฐานสำหรับ OHLCV
    htf_data = data_ltf['Close'].resample(filter_timeframe_str).last().to_frame(name='Filter_Close')
    htf_data['Filter_Open'] = data_ltf['Open'].resample(filter_timeframe_str).first()
    htf_data['Filter_High'] = data_ltf['High'].resample(filter_timeframe_str).max()
    htf_data['Filter_Low'] = data_ltf['Low'].resample(filter_timeframe_str).min()
    
    # 3.2 Add Simple Filter (SMA) - สำหรับตัวอย่าง
    # คำนวณ Simple Moving Average (SMA) 200 บน HTF
    htf_data['Filter_SMA'] = htf_data['Filter_Close'].rolling(window=200).mean()

    # 3.3 Merge Filter Data back to LTF
    # นำสัญญาณ Filter (SMA) จาก HTF กลับมาใส่ในข้อมูล LTF
    # ffill จะเติมค่าไปข้างหน้าจนกว่าจะมีการสร้างแท่ง HTF ใหม่
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
        xaxis_rangeslider_visible=False, # ซ่อนตัวเลื่อนด้านล่าง
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
ticker = st.sidebar.text_input("Ticker Symbol (e.g., AAPL, BTC-USD)", "AAPL", key="ticker").upper()

# Date Range Selection (NEW FEATURE)
today = date.today()
default_start = today - timedelta(days=59) # yfinance 1m limit is about 60 days

date_col1, date_col2 = st.sidebar.columns(2)

with date_col1:
    start_date = st.date_input("Start Date", default_start)

with date_col2:
    end_date = st.date_input("End Date", today)

# Execution Timeframe (LTF)
ltf_options = list(YF_INTERVALS.keys())
ltf = st.sidebar.selectbox("Execution Timeframe (LTF)", ltf_options, index=ltf_options.index("5T"), key="ltf")

# Filter Timeframe (HTF)
# HTF ต้องมีค่ามากกว่า LTF
ltf_index = ltf_options.index(ltf)
htf_options_filtered = ltf_options[ltf_index:] 
# Ensure "30T" is available, if not, use the next available one
default_htf_index = htf_options_filtered.index("30T") if "30T" in htf_options_filtered else 0
htf = st.sidebar.selectbox("Filter Timeframe (HTF)", htf_options_filtered, index=default_htf_index, key="htf")

# Run Button
if st.sidebar.button("Run MTF Analysis"):
    st.session_state.run_analysis = True

# 4.2 Main Area: Run Analysis
if st.session_state.get('run_analysis', False):
    
    # 4.2.1 Data Fetching
    data_ltf, error_message = get_data(ticker, ltf, start_date, end_date)
    
    if error_message:
        # แสดงข้อผิดพลาด API/Data Error
        st.error(f"❌ Analysis Failed: {error_message}")
    else:
        # 4.2.2 Check Data Size
        if data_ltf.shape[0] < 200:
            st.warning(f"⚠️ คำเตือน: ข้อมูลที่ดึงมามีเพียง {data_ltf.shape[0]} แถว ซึ่งน้อยกว่า 200 แถวที่แนะนำ อาจทำให้การวิเคราะห์ Filter (SMA) ไม่แม่นยำ")
            
        # 4.2.3 Analysis and Plotting
        try:
            analyze_and_plot(data_ltf, htf)
        except Exception as plot_e:
            st.error(f"❌ เกิดข้อผิดพลาดในการวิเคราะห์หรือสร้างกราฟ: {plot_e}. กรุณาตรวจสอบช่วงวันที่หรือ Timeframe.")
            
# --- END CODE ---