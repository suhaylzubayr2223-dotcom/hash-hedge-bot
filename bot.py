import ccxt
import pandas as pd
import pandas_ta as ta
import requests
import time
import os
from datetime import datetime, timedelta

# =========================
# TELEGRAM
# =========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# =========================
# HASH HEDGE COIN LIST (saqlab qolindi)
# =========================
RAW_SYMBOLS = [
    "BTC","ETH","LTC","BCH","TRX","FIL","CHZ","LINK","DOT","XRP","DOGE","ADA",
    "SHIB","SOL","BNB","AVAX","MANA","UNI","DASH","GMX","BICO","ILV","ARKM",
    "ANKR","IMX","WIF","FET","CFX","EDU","SSV","APE","ICP","SEI","W","WOO","LDO",
    "STX","ENA","NEO","CAKE","DYM","ZETA","API3","TNSR","GAS","YGG","XLM","CYBER",
    "EGLD","RUNE","STRK","CRV","1INCH","ID","ETHFI","AEVO","PYTH","XAI","JOE","ZRX",
    "OP","ENJ","TAO","DODOX","MAV","AUCTION","ACE","LSK","SAND","PENDLE","TRB","VET",
    "INJ","JTO","JUP","APT","BSV","BOME","METIS","ACH","STG","BLUR","MANTA","IOST",
    "SUI","FLOKI","JASMY","SPELL","ORDI","ONG","SAGA","ALT","BEAMX","DUSK","BEL","UMA",
    "GRT","ONDO","PEPE","BONK","LQTY","ENS","HBAR","MASK","TIA","POLYX","BIGTIME","USTC",
    "GMT","RATS","WLD","ROSE","PEOPLE","COMP","LPT","ATOM","RSR","ARB","AR","CATY","HMSTR",
    "TRUMP","HYPE","VIRTUAL","WFLI","PUMP","LINEA","ASTER","LAB","RIVER","UB","ZEC","MON",
    "LIT","XMR"
]

TIMEFRAMES = ["1d", "4h", "1h", "15m", "5m"]
CHECK_INTERVAL = 90
MIN_SCORE = 82
SIGNAL_COOLDOWN = 50

exchange = ccxt.binance({
    "enableRateLimit": True,
    "options": {"defaultType": "future"}
})

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": message},
            timeout=10
        )
    except Exception as e:
        print("Telegram error:", e)

def load_symbols():
    exchange.load_markets()
    result = []
    for coin in RAW_SYMBOLS:
        symbol = f"{coin}/USDT:USDT"
        if symbol in exchange.markets:
            m = exchange.markets[symbol]
            if m.get("active", True) and m.get("swap") and m.get("linear") and m.get("quote") == "USDT":
                result.append(symbol)
    return result

def get_data(symbol, timeframe, limit=250):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["time","open","high","low","close","volume"])
        if len(df) < 100:
            return None
        df = df.iloc[:-1].copy()
        df["ema9"]  = ta.ema(df["close"], length=9)
        df["ema21"] = ta.ema(df["close"], length=21)
        df["ema50"] = ta.ema(df["close"], length=50)
        df["rsi"]   = ta.rsi(df["close"], length=14)
        df["vol_ma"]= df["volume"].rolling(20).mean()
        df["atr"]   = ta.atr(df["high"], df["low"], df["close"], length=14)
        return df
    except Exception as e:
        print(symbol, timeframe, e)
        return None

def get_trend(df):
    last = df.iloc[-1]
    if last["close"] > last["ema21"] and last["ema21"] > last["ema50"]:
        return "LONG"
    if last["close"] < last["ema21"] and last["ema21"] < last["ema50"]:
        return "SHORT"
    return "NEUTRAL"

def market_structure(df):
    highs = df["high"].tail(30)
    lows  = df["low"].tail(30)
    prev_high = highs.iloc[-10:-1].max()
    prev_low  = lows.iloc[-10:-1].min()
    close = df["close"].iloc[-1]
    if close > prev_high: return "BULLISH"
    if close < prev_low:  return "BEARISH"
    return "NEUTRAL"

def detect_bos(df):
    close = df["close"].iloc[-1]
    high_lvl = df["high"].iloc[-15:-2].max()
    low_lvl  = df["low"].iloc[-15:-2].min()
    if close > high_lvl: return "BULLISH_BOS"
    if close < low_lvl:  return "BEARISH_BOS"
    return "NONE"

def liquidity_sweep(df):
    last = df.iloc[-1]
    prev_high = df["high"].iloc[-10:-2].max()
    prev_low  = df["low"].iloc[-10:-2].min()
    if last["high"] > prev_high and last["close"] < prev_high:
        return "BEARISH_SWEEP"
    if last["low"] < prev_low and last["close"] > prev_low:
        return "BULLISH_SWEEP"
    return "NONE"

def detect_order_block(df):
    if len(df) < 8: return "NONE"
    last, prev = df.iloc[-1], df.iloc[-2]
    if prev["close"] < prev["open"] and last["close"] > prev["high"]:
        return "BULLISH_OB"
    if prev["close"] > prev["open"] and last["close"] < prev["low"]:
        return "BEARISH_OB"
    return "NONE"

def detect_fvg(df):
    if len(df) < 5: return "NONE"
    a, c = df.iloc[-3], df.iloc[-1]
    if c["low"] > a["high"]: return "BULLISH_FVG"
    if c["high"] < a["low"]: return "BEARISH_FVG"
    return "NONE"

def ema_confirmation(df):
    last = df.iloc[-1]
    if last["ema9"] > last["ema21"] and last["close"] > last["ema9"]:
        return "LONG"
    if last["ema9"] < last["ema21"] and last["close"] < last["ema9"]:
        return "SHORT"
    return "NONE"

def volume_ok(df):
    last = df.iloc[-1]
    if pd.isna(last["vol_ma"]): return False
    return last["volume"] > last["vol_ma"] * 1.35

def trigger_5m(df, direction):
    last = df.iloc[-1]
    if direction == "LONG":
        return last["close"] > last["open"] and last["close"] > last["ema9"]
    if direction == "SHORT":
        return last["close"] < last["open"] and last["close"] < last["ema9"]
    return False

# =========================
# PROFESSIONAL BTC BIAS (1D + 4H + 1H)
# =========================
def get_btc_bias():
    d1 = get_data("BTC/USDT:USDT", "1d")
    h4 = get_data("BTC/USDT:USDT", "4h")
    h1 = get_data("BTC/USDT:USDT", "1h")

    if d1 is None or h4 is None or h1 is None:
        return "NEUTRAL"

    t_d1 = get_trend(d1)
    t_h4 = get_trend(h4)
    t_h1 = get_trend(h1)

    bull_count = sum(1 for t in [t_d1, t_h4, t_h1] if t == "LONG")
    bear_count = sum(1 for t in [t_d1, t_h4, t_h1] if t == "SHORT")

    if bull_count == 3:
        return "STRONG_BULLISH"
    if bear_count == 3:
        return "STRONG_BEARISH"
    if bull_count >= 2 and t_h4 == "LONG" and t_h1 == "LONG":
        return "BULLISH"
    if bear_count >= 2 and t_h4 == "SHORT" and t_h1 == "SHORT":
        return "BEARISH"
    return "NEUTRAL"

def analyze(symbol, btc_bias):
    data = {}
    for tf in TIMEFRAMES:
        df = get_data(symbol, tf)
        if df is None:
            return None
        data[tf] = df

    d1, h4, h1, m15, m5 = data["1d"], data["4h"], data["1h"], data["15m"], data["5m"]

    score_long = 0
    score_short = 0
    reasons_long = []
    reasons_short = []

    # ----- BTC FILTER (eng muhim qism) -----
    if btc_bias == "STRONG_BEARISH":
        score_long -= 50
        reasons_long.append("BTC Strong Bearish (blocked)")
    elif btc_bias == "BEARISH":
        score_long -= 30
        reasons_long.append("BTC Bearish filter")
    elif btc_bias == "STRONG_BULLISH":
        score_short -= 50
        reasons_short.append("BTC Strong Bullish (blocked)")
    elif btc_bias == "BULLISH":
        score_short -= 30
        reasons_short.append("BTC Bullish filter")

    # Higher timeframes
    for tf_name, df, points in [("1D", d1, 12), ("4H", h4, 15), ("1H", h1, 15)]:
        trend = get_trend(df)
        if trend == "LONG":
            score_long += points
            reasons_long.append(f"{tf_name} bullish")
        elif trend == "SHORT":
            score_short += points
            reasons_short.append(f"{tf_name} bearish")

    # Structure
    struct = market_structure(h1)
    if struct == "BULLISH":
        score_long += 18
        reasons_long.append("Bullish structure")
    elif struct == "BEARISH":
        score_short += 18
        reasons_short.append("Bearish structure")

    # 15m confirmations
    bos = detect_bos(m15)
    if bos == "BULLISH_BOS":
        score_long += 12
        reasons_long.append("15M BOS")
    elif bos == "BEARISH_BOS":
        score_short += 12
        reasons_short.append("15M BOS")

    sweep = liquidity_sweep(m15)
    if sweep == "BULLISH_SWEEP":
        score_long += 12
        reasons_long.append("Bullish liquidity sweep")
    elif sweep == "BEARISH_SWEEP":
        score_short += 12
        reasons_short.append("Bearish liquidity sweep")

    ob = detect_order_block(m15)
    if ob == "BULLISH_OB":
        score_long += 10
        reasons_long.append("Bullish OB")
    elif ob == "BEARISH_OB":
        score_short += 10
        reasons_short.append("Bearish OB")

    fvg = detect_fvg(m15)
    if fvg == "BULLISH_FVG":
        score_long += 5
        reasons_long.append("Bullish FVG")
    elif fvg == "BEARISH_FVG":
        score_short += 5
        reasons_short.append("Bearish FVG")

    ema = ema_confirmation(m15)
    if ema == "LONG":
        score_long += 10
        reasons_long.append("EMA confirm")
    elif ema == "SHORT":
        score_short += 10
        reasons_short.append("EMA confirm")

    if volume_ok(m15):
        if m15["close"].iloc[-1] > m15["open"].iloc[-1]:
            score_long += 10
            reasons_long.append("Volume")
        else:
            score_short += 10
            reasons_short.append("Volume")

    if trigger_5m(m5, "LONG"):
        score_long += 5
        reasons_long.append("5M trigger")
    if trigger_5m(m5, "SHORT"):
        score_short += 5
        reasons_short.append("5M trigger")

    # Decision
    if score_long >= MIN_SCORE and score_long >= score_short + 18:
        direction = "LONG"
        score = min(score_long, 100)
        reasons = reasons_long
    elif score_short >= MIN_SCORE and score_short >= score_long + 18:
        direction = "SHORT"
        score = min(score_short, 100)
        reasons = reasons_short
    else:
        return None

    # SL / TP
    entry = float(m15["close"].iloc[-1])
    atr = float(m15["atr"].iloc[-1])
    if pd.isna(atr) or atr <= 0:
        return None

    recent_low  = float(m15["low"].tail(12).min())
    recent_high = float(m15["high"].tail(12).max())

    if direction == "LONG":
        sl = min(recent_low, entry - atr * 1.25)
        risk = entry - sl
        if risk <= 0: return None
        tp1 = entry + risk * 2
        tp2 = entry + risk * 3
        tp3 = entry + risk * 4
    else:
        sl = max(recent_high, entry + atr * 1.25)
        risk = sl - entry
        if risk <= 0: return None
        tp1 = entry - risk * 2
        tp2 = entry - risk * 3
        tp3 = entry - risk * 4

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "reasons": reasons,
        "btc_bias": btc_bias
    }

last_signal = {}

def can_send(symbol):
    now = datetime.utcnow()
    if symbol not in last_signal:
        return True
    return now - last_signal[symbol] >= timedelta(minutes=SIGNAL_COOLDOWN)

def process_symbol(symbol, btc_bias):
    try:
        signal = analyze(symbol, btc_bias)
        if not signal or not can_send(symbol):
            return

        msg = (
            f"🚨 HASH HEDGE SIGNAL\n\n"
            f"📊 {signal['symbol']}\n"
            f"📌 {signal['direction']}\n"
            f"💯 Score: {signal['score']}/100\n"
            f"🌐 BTC Bias: {signal['btc_bias']}\n\n"
            f"🎯 Entry: {signal['entry']:.8g}\n"
            f"🛑 SL: {signal['sl']:.8g}\n"
            f"✅ TP1: {signal['tp1']:.8g}\n"
            f"✅ TP2: {signal['tp2']:.8g}\n"
            f"✅ TP3: {signal['tp3']:.8g}\n\n"
            f"📈 R:R ≈ 1:2\n\n"
            f"🔎 Reasons:\n"
        )
        for r in signal["reasons"]:
            msg += f"• {r}\n"
        msg += f"\n⏱ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"

        send_telegram(msg)
        last_signal[symbol] = datetime.utcnow()
        print(signal["symbol"], signal["direction"], signal["score"], signal["btc_bias"])

    except Exception as e:
        print("Error:", symbol, e)

def main():
    print("Professional bot starting...")
    symbols = load_symbols()
    print(f"{len(symbols)} ta coin yuklandi.")

    send_telegram(
        f"🤖 Hash Hedge Professional Bot ishga tushdi\n"
        f"BTC Bias: 1D + 4H + 1H\n"
        f"Kuzatilayotgan coinlar: {len(symbols)}"
    )

    while True:
        start = time.time()
        btc_bias = get_btc_bias()
        print("BTC Bias →", btc_bias)

        for symbol in symbols:
            process_symbol(symbol, btc_bias)

        sleep = max(8, CHECK_INTERVAL - (time.time() - start))
        time.sleep(sleep)

if __name__ == "__main__":
    main()
