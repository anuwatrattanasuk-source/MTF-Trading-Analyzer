# ================================================
# 📈 Multi-Timeframe Trading System (MTF)
# ✅ ไฟล์: app.py
# ------------------------------------------------
# โค้ดนี้รวม Indicators, Swings, MMC, MTF Logic, EODHD API และ Streamlit UI
# ================================================

import pandas as pd
import numpy as np
import requests
import matplotlib.pyplot as plt
import streamlit as st
import copy 
import time

# ================================================
# 1️⃣ ฟังก์ชัน MTF Logic และ Indicators
# ================================================

# ----------------------------
# Indicators
# ----------------------------
def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = dif - dea
    return pd.DataFrame({'DIF': dif, 'DEA': dea, 'MACD_HIST': hist})

def add_indicators(df: pd.DataFrame,
                   ema_spans=(50, 200),
                   macd_params=(12, 26, 9),
                   inplace=True):
    df2 = df if inplace else df.copy()
    if 'EMA50' not in df2.columns:
        df2['EMA50'] = ema(df2['Close'], ema_spans[0])
    if 'EMA200' not in df2.columns:
        df2['EMA200'] = ema(df2['Close'], ema_spans[1])
    need_macd = not {'DIF', 'DEA', 'MACD_HIST'}.issubset(df2.columns)
    if need_macd:
        macd_df = macd(df2['Close'], *macd_params)
        df2[['DIF', 'DEA', 'MACD_HIST']] = macd_df
    return df2

# ----------------------------
# Swings (Fractals) & Fibo Time
# ----------------------------
def find_swings(high: pd.Series, low: pd.Series, left=2, right=2):
    n = len(high)
    swing_high, swing_low = [], []
    start_index = left
    end_index = n - right
    
    if end_index <= start_index:
        return [], []
        
    for i in range(start_index, end_index):
        if high.iloc[i] == high.iloc[i-left:i+right+1].max():
            swing_high.append(i)
        if low.iloc[i] == low.iloc[i-left:i+right+1].min():
            swing_low.append(i)
    return swing_high, swing_low

def bars_since_last_pivot(idx: int, swing_high: list, swing_low: list):
    pivots = [p for p in swing_high + swing_low if p <= idx]
    if not pivots:
        return None
    last = max(pivots)
    return idx - last

def fibo_time_pass(bars_since_pivot: int, fibo_set=(3,5,8,13,21), tolerance=0):
    if bars_since_pivot is None:
        return False
    return any(abs(bars_since_pivot - f) <= tolerance for f in fibo_set)

# ----------------------------
# Hidden Divergence
# ----------------------------
def hidden_divergence(df: pd.DataFrame, use_hist=False, left=2, right=2):
    if len(df) < left + right + 1:
        return {'hidden_bull': False, 'hidden_bear': False, 'last_swing_low_idx': None, 'last_swing_high_idx': None}
        
    osc = df['MACD_HIST'] if use_hist else df['DIF']
    swing_h, swing_l = find_swings(df['High'], df['Low'], left=left, right=right)

    hidden_bull = False
    if len(swing_l) >= 2:
        i1, i2 = swing_l[-2], swing_l[-1]
        price_hl = df['Low'].iloc[i2] > df['Low'].iloc[i1]
        osc_ll = osc.iloc[i2] < osc.iloc[i1]
        hidden_bull = bool(price_hl and osc_ll)

    hidden_bear = False
    if len(swing_h) >= 2:
        j1, j2 = swing_h[-2], swing_h[-1]
        price_lh = df['High'].iloc[j2] < df['High'].iloc[j1]
        osc_hh = osc.iloc[j2] > osc.iloc[j1]
        hidden_bear = bool(price_lh and osc_hh)

    return {'hidden_bull': hidden_bull, 'hidden_bear': hidden_bear,
            'last_swing_low_idx': swing_l[-1] if swing_l else None,
            'last_swing_high_idx': swing_h[-1] if swing_h else None}

# ----------------------------
# MMC (3 Confirm)
# ----------------------------
def check_3_confirm(df: pd.DataFrame,
                    fibo_set=(3,5,8,13,21),
                    fibo_tol=0,
                    ema_source='EMA200'):
    if len(df) < 2:
        return 0, 0, {}
        
    if ema_source not in df.columns or not {'DIF','DEA'}.issubset(df.columns):
         add_indicators(df, inplace=True)
         
    t, t1 = len(df) - 1, len(df) - 2
    latest, prev = df.iloc[t], df.iloc[t1]
    
    ms_buy = (latest['Close'] > latest[ema_source]) and (prev['Close'] <= prev[ema_source])
    ms_sell = (latest['Close'] < latest[ema_source]) and (prev['Close'] >= prev[ema_source])
    macd_buy = (latest['DIF'] > latest['DEA']) and (prev['DIF'] <= prev['DEA'])
    macd_sell = (latest['DIF'] < latest['DEA']) and (prev['DIF'] >= prev['DEA'])
    
    swing_h, swing_l = find_swings(df['High'], df['Low'], left=2, right=2)
    bslp = bars_since_last_pivot(t, swing_h, swing_l)
    fibo_ok = fibo_time_pass(bslp, fibo_set=fibo_set, tolerance=fibo_tol)
    
    confirms_buy = sum([ms_buy, macd_buy, fibo_ok])
    confirms_sell = sum([ms_sell, macd_sell, fibo_ok])

    return confirms_buy, confirms_sell, {
        'ms_buy': ms_buy, 'ms_sell': ms_sell,
        'macd_buy': macd_buy, 'macd_sell': macd_sell,
        'fibo_ok': fibo_ok, 'bars_since_last_pivot': bslp
    }

# ----------------------------
# HTF Filter
# ----------------------------
def htf_filter_30m(df30: pd.DataFrame,
                   ema_spans=(50,200),
                   macd_params=(12,26,9),
                   min_bars_above_below=3):
    add_indicators(df30, ema_spans=ema_spans, macd_params=macd_params, inplace=True)
    if len(df30) < min_bars_above_below:
        return False, False, {}
    n = min_bars_above_below
    last_n = df30.iloc[-n:]
    
    cond_trend_up = (last_n['Close'] > last_n['EMA200']).all()
    cond_ema_align_up = df30['EMA50'].iloc[-1] > df30['EMA200'].iloc[-1]
    cond_momentum_up = (df30['DIF'].iloc[-1] > df30['DEA'].iloc[-1]) or (df30['MACD_HIST'].iloc[-1] > 0)
    htf_up = bool(cond_trend_up and cond_ema_align_up and cond_momentum_up)
    
    cond_trend_down = (last_n['Close'] < last_n['EMA200']).all()
    cond_ema_align_down = df30['EMA50'].iloc[-1] < df30['EMA200'].iloc[-1]
    cond_momentum_down = (df30['DIF'].iloc[-1] < df30['DEA'].iloc[-1]) or (df30['MACD_HIST'].iloc[-1] < 0)
    htf_down = bool(cond_trend_down and cond_ema_align_down and cond_momentum_down)
    
    details = {
        'trend_up_last_n_above_ema200': cond_trend_up, 'ema_align_up': cond_ema_align_up, 'momentum_up': cond_momentum_up,
        'trend_down_last_n_below_ema200': cond_trend_down, 'ema_align_down': cond_ema_align_down, 'momentum_down': cond_momentum_down,
    }
    return htf_up, htf_down, details

# ----------------------------
# Resample OHLC
# ----------------------------
def resample_ohlc(df: pd.DataFrame, rule: str):
    ohlc = df.resample(rule).agg({
        'Open': 'first', 'High': 'max', 'Low': 'min',
        'Close': 'last', 'Volume': 'sum'
    }).dropna(subset=['Close'])
    return ohlc

# ----------------------------
# MTF Signal Core Logic
# ----------------------------
def mtf_signal(df_raw: pd.DataFrame,
               tf_exec='15T', tf_filter='30T',
               ema_spans=(50,200), macd_params=(12,26,9),
               fibo_set=(3,5,8,13,21), fibo_tol=0,
               min_bars_htf=3, use_hidden=True):
    df15 = resample_ohlc(df_raw, tf_exec)
    df30 = resample_ohlc(df_raw, tf_filter)
    
    if len(df15) < 2 or len(df30) < 2:
        return {'price_15m': df_raw['Close'].iloc[-1] if not df_raw.empty else None, 
                'action': "HOLD/WAIT", 'reasons': ['Not enough bars for calculation']}

    add_indicators(df15, ema_spans=ema_spans, macd_params=macd_params)
    add_indicators(df30, ema_spans=ema_spans, macd_params=macd_params)
    
    htf_up, htf_down, htf_det = htf_filter_30m(df30, ema_spans, macd_params, min_bars_htf)
    c_buy, c_sell, mmc_det = check_3_confirm(df15, fibo_set, fibo_tol, 'EMA200')
    hidden_det = hidden_divergence(df15) if use_hidden else {'hidden_bull': False, 'hidden_bear': False}
    
    action, reason = "HOLD/WAIT", []
    if htf_up and c_buy >= 2:
        action = "BUY: Confirmed (MTF aligned)"
        if c_buy == 3: action = "BUY: ALL-IN (3/3, MTF aligned)"
        if use_hidden and hidden_det.get('hidden_bull'): reason.append('Hidden Bullish boost')
    elif htf_down and c_sell >= 2:
        action = "SELL: Confirmed (MTF aligned)"
        if c_sell == 3: action = "SELL: ALL-IN (3/3, MTF aligned)"
        if use_hidden and hidden_det.get('hidden_bear'): reason.append('Hidden Bearish boost')
    else:
        if not htf_up and not htf_down: reason.append('30m filter not aligned')
        if c_buy < 2 and c_sell < 2: reason.append('15m MMC < 2/3')
        
    latest15 = df15.iloc[-1]
    return {
        'time': str(latest15.name),
        'price_15m': float(latest15['Close']),
        'BUY_confirms_15m': c_buy,
        'SELL_confirms_15m': c_sell,
        'action': action,
        'reasons': reason,
        'htf_details': htf_det,
        'mmc_details_15m': mmc_det,
        'hidden_div_15m': hidden_det
    }

# ------------------------------------------------
# 2️⃣ EODHD Data Fetcher (with Streamlit Cache)
# ------------------------------------------------
@st.cache_data(ttl=600) # Cache data for 10 minutes
def get_intraday_data(ticker, interval, api_token):
    url = f"https://eodhd.com/api/intraday/{ticker}?interval={interval}&api_token={api_token}&fmt=json"
    
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        
        if not data:
             return pd.DataFrame()
             
        df = pd.DataFrame(data)
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low',
                                'close': 'Close', 'volume': 'Volume'})
        df = df.set_index('datetime')
        return df
        
    except requests.exceptions.HTTPError as http_err:
        st.error(f"HTTP Error: API returned status {r.status_code}. Please check your EODHD API usage or token.")
    except requests.exceptions.RequestException as e:
        st.error(f"Connection Error: Could not connect to EODHD API. Check network.")
    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
        
    return pd.DataFrame()


# ------------------------------------------------
# 3️⃣ Plotting Function
# ------------------------------------------------
def plot_mtf_result(df, result, ticker):
    fig, ax = plt.subplots(figsize=(10, 5))
    df_plot = df.copy()
    
    # Ensure indicators are calculated for plotting
    add_indicators(df_plot, inplace=True)
    
    ax.plot(df_plot['Close'], label='Close Price', color='gray', alpha=0.7)
    ax.plot(df_plot['EMA50'], label='EMA50', color='orange')
    ax.plot(df_plot['EMA200'], label='EMA200', color='blue')
    
    ax.set_title(f"Price Action & EMAs for {ticker} (1-Min Data)", fontsize=14)
    ax.set_ylabel("Price")
    ax.legend()
    ax.grid(True, linestyle='--', alpha=0.6)
    
    st.pyplot(fig)


# ------------------------------------------------
# 4️⃣ Streamlit UI / Main Application
# ------------------------------------------------
def main():
    st.set_page_config(page_title="MTF Trading Signal Analyzer", layout="wide")
    st.title("📈 Multi-Timeframe Trading System (MTF)")
    st.markdown("---")
    
    # ดึง API Key จาก Streamlit Secrets (ปลอดภัยบน Cloud)
    if "eodhd_api_key" in st.secrets:
        api_token = st.secrets["eodhd_api_key"]
    else:
        st.warning("EODHD API Key not found in Streamlit Secrets. Running in 'demo' mode. Results may be limited.")
        api_token = "demo" 

    # Sidebar: User Inputs
    st.sidebar.header("⚙️ Settings & Data Source")
    ticker = st.sidebar.text_input("Ticker Symbol (e.g., AAPL.US, BTC-USD)", "AAPL.US")
    tf_exec = st.sidebar.selectbox("Execution Timeframe (LTF)", options=['15T', '10T', '5T'], index=0)
    tf_filter = st.sidebar.selectbox("Filter Timeframe (HTF)", options=['30T', '60T'], index=0)

    # ปุ่ม Run
    if st.sidebar.button("Run MTF Analysis"):
        if not ticker:
            st.warning("Please enter Ticker Symbol.")
            return
        
        # 1. ดึงข้อมูล
        with st.spinner(f"Fetching 1-Minute data for {ticker}..."):
            df_raw = get_intraday_data(ticker, "1m", api_token)

        if df_raw.empty or len(df_raw) < 200:
            st.error("Not enough historical data (min 200 bars recommended). Please try again later.")
            return
        
        # 2. รันการวิเคราะห์ MTF
        with st.spinner("Calculating MTF Signals..."):
            result = mtf_signal(copy.deepcopy(df_raw), 
                                tf_exec=tf_exec, 
                                tf_filter=tf_filter)
        
        st.subheader(f"✅ Analysis Result for {ticker} (Time: {result.get('time', 'N/A')})")
        
        # 3. แสดงผลลัพธ์หลัก
        col1, col2, col3 = st.columns(3)
        col1.metric("Current 15m Close Price", f"${result['price_15m']:.2f}" if result['price_15m'] else "N/A")
        
        if 'BUY' in result['action']:
            color = 'green'
        elif 'SELL' in result['action']:
            color = 'red'
        else:
            color = 'orange'
            
        col2.markdown(f"**MTF Action:** <span style='color:{color}; font-size: 24px;'>{result['action']}</span>", unsafe_allow_html=True)
        col3.metric("15m Confirms (Buy/Sell)", f"{result['BUY_confirms_15m']} / {result['SELL_confirms_15m']}")

        st.markdown(f"**Reasons:** {' | '.join(result['reasons'])}")

        st.markdown("---")

        # 4. แสดงกราฟ
        st.subheader("📊 Price Chart & Indicators (1-Minute)")
        plot_mtf_result(df_raw, result, ticker)
        
        # 5. แสดงรายละเอียดเชิงลึก
        st.subheader("📚 Detailed Confirmation Breakdown")
        st.markdown("#### 30m Filter (HTF) Status")
        st.json(result['htf_details'])
        st.markdown("#### 15m MMC (3 Confirms) Status")
        st.json(result['mmc_details_15m'])


if __name__ == "__main__":
    main()