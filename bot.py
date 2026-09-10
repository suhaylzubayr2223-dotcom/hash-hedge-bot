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
# HASH HEDGE CRYPTO LIST
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
MIN_SCORE = 75
SIGNAL_COOLDOWN = 45

# =========================
# BINANCE FUTURES
# =========================
exchange = ccxt.binance({
    "enableRateLimit": True,
    "options": {
        "defaultType": "future"
    }
})

# =========================
# TELEGRAM SEND
# =========================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=10
        )
    except Exception as e:
        print("Telegram error:", e)

# =========================
# LOAD SYMBOLS
# =========================
def load_symbols():
    exchange.load_markets()

    result = []

    for coin in RAW_SYMBOLS:
        symbol = f"{coin}/USDT:USDT"

        if symbol in exchange.markets:
            market = exchange.markets[symbol]

            if (
                market.get("active", True)
                and market.get("swap", False)
                and market.get("linear", False)
                and market.get("quote") == "USDT"
            ):
                result.append(symbol)

    return result

# =========================
# OHLCV
# =========================
def get_data(symbol, timeframe, limit=250):
    try:
        data = exchange.fetch_ohlcv(
            symbol,
            timeframe=timeframe,
            limit=limit
        )

        df = pd.DataFrame(
            data,
            columns=[
                "time",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]
        )

        if len(df) < 100:
            return None

        # Faqat yopilgan shamlar
        df = df.iloc[:-1].copy()

        df["ema9"] = ta.ema(df["close"], length=9)
        df["ema21"] = ta.ema(df["close"], length=21)
        df["ema50"] = ta.ema(df["close"], length=50)

        df["rsi"] = ta.rsi(df["close"], length=14)

        df["vol_ma"] = df["volume"].rolling(20).mean()

        df["atr"] = ta.atr(
            df["high"],
            df["low"],
            df["close"],
            length=14
        )

        return df

    except Exception as e:
        print(symbol, timeframe, "error:", e)
        return None

# =========================
# TREND
# =========================
def get_trend(df):
    last = df.iloc[-1]

    if (
        last["close"] > last["ema21"]
        and last["ema21"] > last["ema50"]
    ):
        return "LONG"

    if (
        last["close"] < last["ema21"]
        and last["ema21"] < last["ema50"]
    ):
        return "SHORT"

    return "NEUTRAL"

# =========================
# MARKET STRUCTURE
# =========================
def market_structure(df):
    highs = df["high"].tail(30)
    lows = df["low"].tail(30)

    recent_high = highs.iloc[-1]
    previous_high = highs.iloc[-10:-1].max()

    recent_low = lows.iloc[-1]
    previous_low = lows.iloc[-10:-1].min()

    close = df["close"].iloc[-1]

    if close > previous_high:
        return "BULLISH"

    if close < previous_low:
        return "BEARISH"

    return "NEUTRAL"

# =========================
# BOS / CHOCH
# =========================
def detect_bos_choch(df):
    close = df["close"].iloc[-1]

    high_level = df["high"].iloc[-15:-2].max()
    low_level = df["low"].iloc[-15:-2].min()

    if close > high_level:
        return "BULLISH_BOS"

    if close < low_level:
        return "BEARISH_BOS"

    return "NONE"

# =========================
# LIQUIDITY SWEEP
# =========================
def liquidity_sweep(df):
    last = df.iloc[-1]

    previous_high = df["high"].iloc[-10:-2].max()
    previous_low = df["low"].iloc[-10:-2].min()

    if (
        last["high"] > previous_high
        and last["close"] < previous_high
    ):
        return "BEARISH_SWEEP"

    if (
        last["low"] < previous_low
        and last["close"] > previous_low
    ):
        return "BULLISH_SWEEP"

    return "NONE"

# =========================
# FVG
# =========================
def detect_fvg(df):
    if len(df) < 5:
        return "NONE"

    a = df.iloc[-3]
    c = df.iloc[-1]

    if c["low"] > a["high"]:
        return "BULLISH_FVG"

    if c["high"] < a["low"]:
        return "BEARISH_FVG"

    return "NONE"

# =========================
# ORDER BLOCK
# =========================
def detect_order_block(df):
    if len(df) < 10:
        return "NONE"

    last = df.iloc[-1]
    prev = df.iloc[-2]

    if (
        prev["close"] < prev["open"]
        and last["close"] > prev["high"]
    ):
        return "BULLISH_OB"

    if (
        prev["close"] > prev["open"]
        and last["close"] < prev["low"]
    ):
        return "BEARISH_OB"

    return "NONE"

# =========================
# EMA CONFIRMATION
# =========================
def ema_confirmation(df):
    last = df.iloc[-1]

    if (
        last["ema9"] > last["ema21"]
        and last["close"] > last["ema9"]
    ):
        return "LONG"

    if (
        last["ema9"] < last["ema21"]
        and last["close"] < last["ema9"]
    ):
        return "SHORT"

    return "NONE"

# =========================
# VOLUME
# =========================
def volume_confirmation(df):
    last = df.iloc[-1]

    if pd.isna(last["vol_ma"]):
        return False

    return last["volume"] > last["vol_ma"] * 1.2

# =========================
# 5M TRIGGER
# =========================
def trigger_5m(df, direction):
    last = df.iloc[-1]

    if direction == "LONG":
        return (
            last["close"] > last["open"]
            and last["close"] > last["ema9"]
        )

    if direction == "SHORT":
        return (
            last["close"] < last["open"]
            and last["close"] < last["ema9"]
        )

    return False

# =========================
# ANALYSIS
# =========================
def analyze(symbol):
    data = {}

    for tf in TIMEFRAMES:
        df = get_data(symbol, tf)

        if df is None:
            return None

        data[tf] = df

    d1 = data["1d"]
    h4 = data["4h"]
    h1 = data["1h"]
    m15 = data["15m"]
    m5 = data["5m"]

    score_long = 0
    score_short = 0

    reasons_long = []
    reasons_short = []

    # =========================
    # 4H TREND
    # =========================
    h4_trend = get_trend(h4)

    if h4_trend == "LONG":
        score_long += 15
        reasons_long.append("4H bullish trend")

    elif h4_trend == "SHORT":
        score_short += 15
        reasons_short.append("4H bearish trend")

    # =========================
    # 1H TREND
    # =========================
    h1_trend = get_trend(h1)

    if h1_trend == "LONG":
        score_long += 15
        reasons_long.append("1H bullish trend")

    elif h1_trend == "SHORT":
        score_short += 15
        reasons_short.append("1H bearish trend")

    # =========================
    # MARKET STRUCTURE
    # =========================
    structure = market_structure(h1)

    if structure == "BULLISH":
        score_long += 20
        reasons_long.append("Bullish market structure")

    elif structure == "BEARISH":
        score_short += 20
        reasons_short.append("Bearish market structure")

    # =========================
    # BOS
    # =========================
    bos = detect_bos_choch(m15)

    if bos == "BULLISH_BOS":
        score_long += 15
        reasons_long.append("15M bullish BOS")

    elif bos == "BEARISH_BOS":
        score_short += 15
        reasons_short.append("15M bearish BOS")

    # =========================
    # LIQUIDITY
    # =========================
    sweep = liquidity_sweep(m15)

    if sweep == "BULLISH_SWEEP":
        score_long += 15
        reasons_long.append("Liquidity sweep bullish")

    elif sweep == "BEARISH_SWEEP":
        score_short += 15
        reasons_short.append("Liquidity sweep bearish")

    # =========================
    # ORDER BLOCK
    # =========================
    ob = detect_order_block(m15)

    if ob == "BULLISH_OB":
        score_long += 15
        reasons_long.append("Bullish order block")

    elif ob == "BEARISH_OB":
        score_short += 15
        reasons_short.append("Bearish order block")

    # =========================
    # FVG
    # =========================
    fvg = detect_fvg(m15)

    if fvg == "BULLISH_FVG":
        score_long += 5
        reasons_long.append("Bullish FVG")

    elif fvg == "BEARISH_FVG":
        score_short += 5
        reasons_short.append("Bearish FVG")

    # =========================
    # EMA
    # =========================
    ema = ema_confirmation(m15)

    if ema == "LONG":
        score_long += 10
        reasons_long.append("EMA confirmation")

    elif ema == "SHORT":
        score_short += 10
        reasons_short.append("EMA confirmation")

    # =========================
    # VOLUME
    # =========================
    if volume_confirmation(m15):

        if m15["close"].iloc[-1] > m15["open"].iloc[-1]:
            score_long += 10
            reasons_long.append("Volume confirmation")

        else:
            score_short += 10
            reasons_short.append("Volume confirmation")

    # =========================
    # 5M TRIGGER
    # =========================
    if trigger_5m(m5, "LONG"):
        score_long += 5
        reasons_long.append("5M entry trigger")

    if trigger_5m(m5, "SHORT"):
        score_short += 5
        reasons_short.append("5M entry trigger")

    # =========================
    # FINAL DIRECTION
    # =========================
    if score_long >= MIN_SCORE and score_long >= score_short + 10:
        direction = "LONG"
        score = min(score_long, 100)
        reasons = reasons_long

    elif score_short >= MIN_SCORE and score_short >= score_long + 10:
        direction = "SHORT"
        score = min(score_short, 100)
        reasons = reasons_short

    else:
        return None

    # =========================
    # ENTRY
    # =========================
    entry = float(m15["close"].iloc[-1])
    atr = float(m15["atr"].iloc[-1])

    if pd.isna(atr) or atr <= 0:
        return None

    # =========================
    # STOP LOSS
    # =========================
    recent_low = float(m15["low"].tail(12).min())
    recent_high = float(m15["high"].tail(12).max())

    if direction == "LONG":
        sl = min(recent_low, entry - atr * 1.2)
        risk = entry - sl

    else:
        sl = max(recent_high, entry + atr * 1.2)
        risk = sl - entry

    if risk <= 0:
        return None

    # =========================
    # TAKE PROFITS
    # =========================
    if direction == "LONG":
        tp1 = entry + risk * 2
        tp2 = entry + risk * 3
        tp3 = entry + risk * 4

    else:
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
        "risk": risk,
        "reasons": reasons
    }

# =========================
# COOLDOWN
# =========================
last_signal = {}

def can_send(symbol):
    now = datetime.utcnow()

    if symbol not in last_signal:
        return True

    return now - last_signal[symbol] >= timedelta(
        minutes=SIGNAL_COOLDOWN
    )

# =========================
# PROCESS
# =========================
def process_symbol(symbol):

    try:
        signal = analyze(symbol)

        if not signal:
            return

        if not can_send(symbol):
            return

        direction = signal["direction"]

        message = (
            f"🚨 HASH HEDGE SIGNAL\n\n"
            f"📊 {signal['symbol']}\n"
            f"📌 {direction}\n"
            f"💯 Confidence: {signal['score']}/100\n\n"
            f"🎯 Entry: {signal['entry']:.8g}\n"
            f"🛑 SL: {signal['sl']:.8g}\n"
            f"✅ TP1: {signal['tp1']:.8g}\n"
            f"✅ TP2: {signal['tp2']:.8g}\n"
            f"✅ TP3: {signal['tp3']:.8g}\n\n"
            f"📈 R:R to TP1 = 1:2\n\n"
            f"🔎 Reasons:\n"
        )

        for reason in signal["reasons"]:
            message += f"• {reason}\n"

        message += (
            f"\n⏱ Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

        send_telegram(message)

        last_signal[symbol] = datetime.utcnow()

        print(
            signal["symbol"],
            direction,
            signal["score"]
        )

    except Exception as e:
        print("Process error:", symbol, e)

# =========================
# MAIN
# =========================
def main():

    print("Bot starting...")

    symbols = load_symbols()

    print(
        f"Hash Hedge crypto ro‘yxatidan "
        f"Binance’da topilgan {len(symbols)} ta coin kuzatilmoqda."
    )

    send_telegram(
        f"🤖 Hash Hedge signal bot ishga tushdi.\n"
        f"Binance Futures orqali {len(symbols)} ta crypto kuzatilmoqda."
    )

    while True:

        cycle_start = time.time()

        for symbol in symbols:
            process_symbol(symbol)

        elapsed = time.time() - cycle_start

        sleep_time = max(
            5,
            CHECK_INTERVAL - elapsed
        )

        time.sleep(sleep_time)


if __name__ == "__main__":
    main()
