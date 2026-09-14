import os
import time
import requests
import pandas as pd

# ------------------------------------------------------------------
# TELEGRAM CONFIGURATION
# ------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = "8570045911:AAF7YYb8sqTBICqIqSWAqa9r82dVGkr2g2Y"
TELEGRAM_CHAT_ID = "5071622091"

# 20 High-Volatility & Liquid Crypto Pairs
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT",
    "NEARUSDT", "APTUSDT", "FETUSDT", "RENDERUSDT", "PEPEUSDT",
    "WIFUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "TIAUSDT"
]

def send_telegram_alert(message):
    """Sends high-probability trade alerts directly to Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("[LOG] Alert successfully sent to Telegram!")
        else:
            print(f"[LOG] Failed to send alert: {response.text}")
    except Exception as e:
        print(f"[LOG] Error sending Telegram alert: {e}")

def fetch_klines(symbol, interval, limit=500):
    """Fetches historical OHLCV candle data from Binance API (Expanded Limit to 500 candles)."""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'
        ])
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df
    except Exception as e:
        print(f"[LOG] Error fetching data for {symbol}: {e}")
        return None

# ------------------------------------------------------------------
# MULTI-TIMEFRAME SCORING LOGIC (UNRESTRICTED DYNAMIC SUPPORT)
# ------------------------------------------------------------------
def analyze_symbol(symbol):
    score = 0
    reasons = []

    # 1. HTF (4H) Trend Bias & Unrestricted Swing Low Check
    df_4h = fetch_klines(symbol, interval="4h", limit=500)
    if df_4h is None or len(df_4h) < 200:
        return
    
    df_4h['ema200'] = df_4h['close'].ewm(span=200, adjust=False).mean()
    current_price = df_4h['close'].iloc[-1]
    ema_200 = df_4h['ema200'].iloc[-1]

    # Scan ALL historical candles in dataset for any Pivot Swing Lows (No candle limits)
    pivot_lows = []
    for i in range(2, len(df_4h) - 2):
        if df_4h['low'].iloc[i] < df_4h['low'].iloc[i-1] and \
           df_4h['low'].iloc[i] < df_4h['low'].iloc[i-2] and \
           df_4h['low'].iloc[i] < df_4h['low'].iloc[i+1] and \
           df_4h['low'].iloc[i] < df_4h['low'].iloc[i+2]:
            pivot_lows.append(df_4h['low'].iloc[i])

    # Check if current price touches or is within 1.2% buffer zone of ANY historical 4H Pivot Low
    is_at_4h_support = False
    for p_low in pivot_lows:
        if abs(current_price - p_low) / p_low <= 0.012: # Within 1.2% buffer
            is_at_4h_support = True
            break

    is_bullish_htf = current_price > ema_200
    if is_bullish_htf and is_at_4h_support:
        score += 1
        reasons.append("4H Trend is Bullish & Testing Major Historical 4H Swing Low Support")
    elif is_bullish_htf:
        reasons.append("4H Trend is Bullish (Price > 200 EMA)")
    else:
        reasons.append("4H Trend is Bearish (Price < 200 EMA)")

    # 2. LTF (15m) Execution Triggers
    df_15m = fetch_klines(symbol, interval="15m", limit=50)
    if df_15m is None or len(df_15m) < 30:
        return

    # A. Calculate RSI (14) & Divergence Logic
    delta = df_15m['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df_15m['rsi'] = 100 - (100 / (1 + rs))

    price_low_curr = df_15m['low'].iloc[-1]
    price_low_prev = df_15m['low'].iloc[-5:-1].min()
    
    rsi_curr = df_15m['rsi'].iloc[-1]
    rsi_prev_min = df_15m['rsi'].iloc[-5:-1].min()

    has_regular_div = (price_low_curr < price_low_prev) and (rsi_curr > rsi_prev_min)
    has_hidden_div = (price_low_curr > price_low_prev) and (rsi_curr < rsi_prev_min)

    if has_regular_div:
        score += 1
        reasons.append("15m Regular Bullish Divergence (Reversal)")
    elif has_hidden_div:
        score += 1
        reasons.append("15m Hidden Bullish Divergence (Continuation)")

    # B. Fair Value Gap (FVG) Detection
    c1_low = df_15m['low'].iloc[-1]
    c3_high = df_15m['high'].iloc[-3]
    if c1_low > c3_high:
        score += 1
        reasons.append("15m Bullish FVG Detected")

    # C. Volume Spike Filter (> 1.5x of 20 SMA Volume)
    df_15m['vol_sma'] = df_15m['volume'].rolling(20).mean()
    if df_15m['volume'].iloc[-1] > (1.5 * df_15m['vol_sma'].iloc[-1]):
        score += 1
        reasons.append("Volume Spike Confirmed (>1.5x SMA)")

    # ------------------------------------------------------------------
    # FINAL CONFLUENCE CHECK (Minimum 3/4 Points Required)
    # ------------------------------------------------------------------
    print(f"[LOG] {symbol} evaluated. Score: {score}/4")

    if score >= 3:
        msg = f"🚨 *HIGH-PROBABILITY SIGNAL DETECTED* 🚨\n\n"
        msg += f"📌 *Symbol*: `{symbol}`\n"
        msg += f"🎯 *Confluence Score*: `{score}/4`\n"
        msg += f"💵 *Current Price*: `${current_price:.4f}`\n\n"
        msg += "*Confluence Reasons*:\n"
        for r in reasons:
            msg += f"• {r}\n"

        send_telegram_alert(msg)

# ------------------------------------------------------------------
# MAIN BOT ENGINE
# ------------------------------------------------------------------
if __name__ == "__main__":
    print("Multi-Timeframe Scoring Bot is operational...")
    send_telegram_alert("🤖 *Bot Alert*: Bot updated! Historical 4H Swing Support + RSI Divergence engine live.")

    while True:
        for symbol in SYMBOLS:
            analyze_symbol(symbol)
            time.sleep(1)
        
        print("[LOG] Waiting 5 minutes for next candle scan...")
        time.sleep(300)
