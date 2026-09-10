import ccxt
import pandas as pd
import pandas_ta as ta
import requests
import time
import os
from datetime import datetime

# ================== SOZLAMALAR ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Kuzatiladigan coinlar
SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    "MATIC/USDT", "NEAR/USDT", "APT/USDT", "SUI/USDT", "ARB/USDT",
    "OP/USDT", "INJ/USDT", "FET/USDT", "RENDER/USDT", "PEPE/USDT",
    "WIF/USDT", "BONK/USDT", "FLOKI/USDT", "SHIB/USDT", "UNI/USDT",
    "AAVE/USDT", "MKR/USDT", "LTC/USDT", "BCH/USDT", "ATOM/USDT",
    "FIL/USDT", "ICP/USDT", "HBAR/USDT", "VET/USDT", "ALGO/USDT",
    "XLM/USDT", "TRX/USDT", "ETC/USDT", "EOS/USDT", "XTZ/USDT",
    "THETA/USDT", "AXS/USDT", "SAND/USDT", "MANA/USDT", "GALA/USDT",
    "CHZ/USDT", "ENJ/USDT", "BAT/USDT", "ZIL/USDT", "IOTA/USDT"
]

TIMEFRAMES = ["15m", "1h"]
CHECK_INTERVAL = 90
MIN_REASONS = 3
SIGNAL_COOLDOWN = 45 * 60

# ================================================

exchange = ccxt.binance({
    "enableRateLimit": True,
    "options": {"defaultType": "future"}
})

last_signals = {}

def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Token yoki Chat ID topilmadi")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Telegram xato:", e)

def get_ohlcv(symbol, timeframe, limit=100):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception as e:
        print(f"{symbol} {timeframe} olishda xato: {e}")
        return None

def analyze(df):
    if df is None or len(df) < 50:
        return None
    df = df.copy()
    df["rsi"] = ta.rsi(df["close"], length=14)
    df["ema9"] = ta.ema(df["close"], length=9)
    df["ema21"] = ta.ema(df["close"], length=21)
    df["ema50"] = ta.ema(df["close"], length=50)
    df["vol_ma"] = ta.sma(df["volume"], length=20)
    df["mom"] = ta.mom(df["close"], length=10)
    df["roc"] = ta.roc(df["close"], length=10)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    return last, prev, df

def check_long(last, prev):
    reasons = []
    if last["rsi"] < 42 and last["rsi"] > prev["rsi"]:
        reasons.append(f"RSI o'smoqda ({last['rsi']:.1f})")
    if last["close"] > last["ema21"] and prev["close"] <= prev["ema21"]:
        reasons.append("Narx EMA21 dan yuqoriga kesdi")
    if last["close"] > last["ema9"]:
        reasons.append("Narx EMA9 dan yuqorida")
    if last["volume"] > last["vol_ma"] * 1.4:
        reasons.append(f"Volume kuchli ({last['volume']/last['vol_ma']:.1f}x)")
    if last["mom"] > 0 and last["roc"] > 0:
        reasons.append("Momentum ijobiy")
    if last["close"] > last["ema50"]:
        reasons.append("Umumiy trend yuqoriga (EMA50)")
    return reasons

def check_short(last, prev):
    reasons = []
    if last["rsi"] > 58 and last["rsi"] < prev["rsi"]:
        reasons.append(f"RSI tushmoqda ({last['rsi']:.1f})")
    if last["close"] < last["ema21"] and prev["close"] >= prev["ema21"]:
        reasons.append("Narx EMA21 dan pastga kesdi")
    if last["close"] < last["ema9"]:
        reasons.append("Narx EMA9 dan pastida")
    if last["volume"] > last["vol_ma"] * 1.4:
        reasons.append(f"Volume kuchli ({last['volume']/last['vol_ma']:.1f}x)")
    if last["mom"] < 0 and last["roc"] < 0:
        reasons.append("Momentum salbiy")
    if last["close"] < last["ema50"]:
        reasons.append("Umumiy trend pastga (EMA50)")
    return reasons

def process_symbol(symbol):
    now = time.time()
    key = symbol
    if key in last_signals and now - last_signals[key] < SIGNAL_COOLDOWN:
        return

    df_15 = get_ohlcv(symbol, "15m")
    result_15 = analyze(df_15)
    if not result_15:
        return
    last15, prev15, _ = result_15

    df_1h = get_ohlcv(symbol, "1h", limit=60)
    result_1h = analyze(df_1h)
    if not result_1h:
        return
    last1h, _, _ = result_1h

    long_reasons = check_long(last15, prev15)
    if len(long_reasons) >= MIN_REASONS:
        if last1h["close"] > last1h["ema50"] * 0.98:
            price = last15["close"]
            msg = f"""🚀 <b>LONG SIGNAL</b>

Coin: <b>{symbol}</b>
Timeframe: 15m
Kirish: ≈ {price:.6g}
Vaqt: {datetime.now().strftime('%H:%M:%S')}

Sabablari:
"""
            for r in long_reasons:
                msg += f"• {r}\n"
            msg += f"\n1H holat: {'Bullish' if last1h['close'] > last1h['ema21'] else 'Neutral/Bearish'}"
            send_telegram(msg)
            last_signals[key] = now
            print(f"LONG yuborildi → {symbol}")
            return

    short_reasons = check_short(last15, prev15)
    if len(short_reasons) >= MIN_REASONS:
        if last1h["close"] < last1h["ema50"] * 1.02:
            price = last15["close"]
            msg = f"""🔻 <b>SHORT SIGNAL</b>

Coin: <b>{symbol}</b>
Timeframe: 15m
Kirish: ≈ {price:.6g}
Vaqt: {datetime.now().strftime('%H:%M:%S')}

Sabablari:
"""
            for r in short_reasons:
                msg += f"• {r}\n"
            msg += f"\n1H holat: {'Bearish' if last1h['close'] < last1h['ema21'] else 'Neutral/Bullish'}"
            send_telegram(msg)
            last_signals[key] = now
            print(f"SHORT yuborildi → {symbol}")

def main():
    print("Bot ishga tushdi...")
    send_telegram("✅ Hash Hedge Signal Bot ishga tushdi!\n15m + 1H kuzatuv boshlandi.")
    
    while True:
        start = time.time()
        for symbol in SYMBOLS:
            try:
                process_symbol(symbol)
                time.sleep(0.35)
            except Exception as e:
                print(f"Xato {symbol}: {e}")
                time.sleep(1)
        
        elapsed = time.time() - start
        sleep_time = max(10, CHECK_INTERVAL - elapsed)
        print(f"Bir aylanma tugadi. {sleep_time:.0f} sekund kutamiz...")
        time.sleep(sleep_time)

if __name__ == "__main__":
    main()
