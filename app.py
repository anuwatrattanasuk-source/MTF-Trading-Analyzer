code_content = '''
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import MetaTrader5 as mt5
import time
from datetime import datetime

# --- CONFIGURATION ---
st.set_page_config(layout="wide")
st.title("📊 MTF Trading Analyzer (MetaTrader 5)")

# Timeframe mapping for MetaTrader 5
MT5_TIMEFRAME_MAP = {
    "1T": mt5.TIMEFRAME_M1, "5T": mt5.TIMEFRAME_M5, "15T": mt5.TIMEFRAME_M15,
    "30T": mt5.TIMEFRAME_M30, "1H": mt5.TIMEFRAME_H1, "4H": mt5.TIMEFRAME_H4,
}

# --- DATA FETCHING ---
@st.cache_data(show_spinner="⏳ กำลังเชื่อมต่อและดึงข้อมูลจาก MetaTrader 5...")
def get_data(ticker, interval_str, count):
    if interval_str not in MT5_TIMEFRAME_MAP:
        return None, f"Error: Interval '{interval_str}' ไม่รองรับ"
    timeframe = MT5_TIMEFRAME_MAP[interval_str]

    if not mt5.initialize():
        return None, f"❌ MT5 Connection Failed: ตรวจสอบว่า MT5 Terminal เปิดอยู่. Error: {mt5.last_error()}"

    if not mt5.symbol_info(ticker):
        mt5.shutdown()
        return None, f"❌ Symbol Error: ไม่พบ Symbol '{ticker}' ใน Market Watch"

    rates = mt5.copy_rates_from_pos(ticker, timeframe, 0, count)
    mt5.shutdown()

    if rates is None or rates.size == 0:
        return None, f"❌ Data Error: ไม่สามารถดึงข้อมูลสำหรับ {ticker}"

    df = pd.DataFrame(rates)
    df.index = pd.to_datetime(df['time'], unit='s')
    df.columns = ['Time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Spread', 'Real_Volume']
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
    return df, None

# --- LIVE SIGNAL ---
def get_live_signal_state(ticker, current_sma_filter):
    if not mt5.initialize():
        return None, "MT5 Initialization Failed"
    tick_info = mt5.symbol_info_tick(ticker)
    mt5.shutdown()

    if tick_info is None or tick_info.last == 0:
        return None, "ไม่สามารถดึง Tick Data ล่าสุดได้"

    latest_price = tick_info.last if tick_info.last > 0 else tick_info.bid

    signal_state = ""
    if latest_price > current_sma_filter:
        signal_state = "⬆️ BULLISH - ราคาอยู่เหนือ Filter"
    elif latest_price < current_sma_filter:
        signal_state = "⬇️ BEARISH - ราคาอยู่ใต้ Filter"
    else:
        signal_state = "⏸️ NEUTRAL - ราคาทับ Filter"

    time_str = datetime.fromtimestamp(tick_info.time).strftime('%Y-%m-%d %H:%M:%S')

    return {"time": time_str, "price": latest_price, "signal": signal_state, "sma": current_sma_filter}, None

# --- ANALYSIS AND PLOT ---
def analyze_and_plot(data_ltf, filter_timeframe_str):
    htf_data = data_ltf['Close'].resample(filter_timeframe_str).last().to_frame(name='Filter_Close')
    htf_data['Filter_Open'] = data_ltf['Open'].resample(filter_timeframe_str).first()
    htf_data['Filter_High'] = data_ltf['High'].resample(filter_timeframe_str).max()
    htf_data['Filter_Low'] = data_ltf['Low'].resample(filter_timeframe_str).min()
    htf_data['Filter_SMA'] = htf_data['Filter_Close'].rolling(window=200).mean()

    data_ltf['Filter_SMA'] = htf_data['Filter_SMA'].ffill()

    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=data_ltf.index, open=data_ltf['Open'], high=data_ltf['High'],
                                  low=data_ltf['Low'], close=data_ltf['Close'],
                                  name=f'LTF Price ({st.session_state.ltf})',
                                  increasing_line_color='#00CC00', decreasing_line_color='#FF0000'))
    fig.add_trace(go.Scatter(x=data_ltf.index, y=data_ltf['Filter_SMA'],
                             line=dict(color='yellow', width=2),
                             name=f'HTF Filter (200 SMA on {st.session_state.htf})'))
    fig.update_layout(title=f"Candlestick Chart: {st.session_state.ticker} | LTF: {st.session_state.ltf}",
                      xaxis_rangeslider_visible=False, height=650,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True)
    return data_ltf['Filter_SMA'].iloc[-1]

# --- STREAMLIT UI ---
st.sidebar.header("⚙️ Settings & Parameters")
ticker = st.sidebar.text_input("Ticker Symbol", "EURUSD", key="ticker").upper()
bars_count = st.sidebar.number_input("จำนวนแท่งเทียน LTF (200-10000)", min_value=200, max_value=10000, value=5000, step=100, key="bars_count")
ltf_options = list(MT5_TIMEFRAME_MAP.keys())
ltf = st.sidebar.selectbox("Execution Timeframe (LTF)", ltf_options, index=ltf_options.index("5T"), key="ltf")
ltf_index = ltf_options.index(ltf)
htf_options_filtered = ltf_options[ltf_index:]
default_htf_index = htf_options_filtered.index("30T") if "30T" in htf_options_filtered else 0
htf = st.sidebar.selectbox("Filter Timeframe (HTF)", htf_options_filtered, index=default_htf_index, key="htf")

st.sidebar.markdown("---")
if st.sidebar.button("▶️ RUN MTF ANALYSIS"):
    st.session_state.run_analysis = True

if st.session_state.get('run_analysis', False):
    data_ltf, error_message = get_data(ticker, ltf, int(st.session_state.bars_count))
    if error_message:
        st.error(f"❌ Analysis Failed: {error_message}")
        st.session_state.run_analysis = False
    else:
        if data_ltf.shape[0] < 200:
            st.warning(f"⚠️ ข้อมูลมีเพียง {data_ltf.shape[0]} แถว อาจทำให้ SMA ไม่แม่น")
        try:
            latest_sma = analyze_and_plot(data_ltf, htf)
        except Exception as plot_e:
            st.error(f"❌ เกิดข้อผิดพลาด: {plot_e}")
            latest_sma = None

        st.markdown("---")
        tab_live, tab_raw = st.tabs(["🔴 Live Signal Monitor", "📋 Raw Data (LTF)"])
        with tab_live:
            if latest_sma is not None:
                st.subheader(f"🔴 Live Signal Monitor - {ticker}")
                if 'live_running' not in st.session_state:
                    st.session_state.live_running = False
                col_start, col_status = st.columns([1, 4])
                if col_start.button("🟢 Start Live Check", key="btn_start_live"):
                    st.session_state.live_running = True
                if col_start.button("🛑 Stop Live Check", key="btn_stop_live"):
                    st.session_state.live_running = False
                live_container = st.empty()
                if st.session_state.live_running:
                    while st.session_state.live_running:
                        live_data, live_error = get_live_signal_state(ticker, latest_sma)
                        if live_error:
                            col_status.error(f"Live Check Error: {live_error}")
                            st.session_state.live_running = False
                            break
                        with live_container.container():
                            st.markdown(f"### **Current Filter: <span style='color:yellow;'>{latest_sma:.5f}</span>**", unsafe_allow_html=True)
                            col_price, col_delta, col_time = st.columns([1.5, 1, 1])
                            col_price.metric("ราคาปัจจุบัน", f"{live_data['price']:.5f}", f"{live_data['price'] - latest_sma:.5f}")
                            signal_color = 'green' if 'BULLISH' in live_data['signal'] else ('red' if 'BEARISH' in live_data['signal'] else 'gray')
                            col_delta.markdown(f"### สัญญาณ")
                            col_delta.markdown(f"<p style='font-size:30px; color:{signal_color};'><b>{live_data['signal']}</b></p>", unsafe_allow_html=True)
                            col_time.markdown(f"### อัปเดตล่าสุด")
                            col_time.markdown(f"<p style='font-size:20px;'>{live_data['time']}</p>", unsafe_allow_html=True)
                        time.sleep(1)
                else:
                    col_status.info("Live Monitoring หยุดทำงานแล้ว")
            else:
                st.warning("⚠️ ไม่สามารถแสดง Live Signal ได้ เนื่องจากไม่สามารถคำนวณ Filter SMA ได้")
        with tab_raw:
            st.subheader(f"Raw Data (LTF: {ltf})")
            st.dataframe(data_ltf.tail(200), use_container_width=True)
'''

with open('mtf_trading_analyzer_fixed.py', 'w') as f:
    f.write(code_content)

print("✅ ไฟล์ mtf_trading_analyzer_fixed.py ถูกสร้างเรียบร้อยแล้ว")
