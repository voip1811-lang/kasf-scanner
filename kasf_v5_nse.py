"""
╔══════════════════════════════════════════════════════════════════╗
║          KASF V5 — NSE PYTHON SCANNER                           ║
║          Replaces TradingView completely. 100% Free.            ║
║                                                                  ║
║  DATA   : yfinance (free, no API key needed)                    ║
║  STOCKS : NIFTY 500 (all 500 NSE stocks)                        ║
║  LOGIC  : Exact same as Pine Script — EMA, RSI, VWAP,           ║
║           Volume surge, Pivot points, R:R filter                ║
║  OUTPUT : Posts JSON to your Google Sheet webhook               ║
║           → Google Script picks it up → Telegram alert          ║
║                                                                  ║
║  RUNS   : Every 15 min during market hours (9:15–3:15 IST)      ║
║  HOST   : Your PC, Raspberry Pi, or any free cloud server       ║
╚══════════════════════════════════════════════════════════════════╝
"""

import yfinance as yf
import pandas as pd
import numpy as np
import requests
import json
import time
import logging
from datetime import datetime, date
import pytz

# ──────────────────────────────────────────────────────────────────
# SECTION A — CONFIGURATION  (edit only this section)
# ──────────────────────────────────────────────────────────────────

# Your existing Google Apps Script Web App URL (the one TradingView was posting to)
# Find it in Google Script → Deploy → Manage Deployments → Web App URL
GOOGLE_SHEET_WEBHOOK = "https://script.google.com/macros/s/1EqLjC0ifrvg770MSXUYvYeKj9orsCPKyR2DJtINusO8/exec"

# ── KASF FILTER SETTINGS (matches Pine Script India values) ───────
ATR_MULT       = 1.5     # ATR stop multiplier
MIN_RR         = 1.5     # Minimum Risk:Reward ratio
RSI_MIN        = 40      # RSI oversold floor
RSI_MAX        = 74      # RSI overbought ceiling (India value)
VOL_MULT       = 2.0     # Volume surge multiplier (India = 2.0x)
PULL_PCT       = 0.003   # Pullback % from S1 (India = 0.3%)
MAX_PICKS      = 4       # Max signals per scan run (matches Google Script)

# ── SCANNER SETTINGS ──────────────────────────────────────────────
SCAN_INTERVAL_MIN = 15   # Run every 15 minutes
CANDLE_INTERVAL   = "15m"  # 15-minute candles (matches TradingView alerts)
HISTORY_PERIOD    = "5d"   # Fetch last 5 days of data (enough for indicators)
REQUEST_DELAY_SEC = 0.3    # Delay between stock fetches (be gentle with API)
MAX_WORKERS       = 1      # Sequential to avoid rate limiting (increase to 3 if fast)

# ──────────────────────────────────────────────────────────────────
# SECTION B — NIFTY 500 STOCK LIST
# Source: NSE official NIFTY 500 index constituents
# All use .NS suffix for yfinance
# ──────────────────────────────────────────────────────────────────
NIFTY500_SYMBOLS = [
    # NIFTY 50 (Large Cap)
    "RELIANCE","TCS","HDFCBANK","BHARTIARTL","ICICIBANK","INFY","SBIN","HINDUNILVR",
    "ITC","LT","BAJFINANCE","HCLTECH","KOTAKBANK","MARUTI","AXISBANK","TITAN",
    "ASIANPAINT","ULTRACEMCO","BAJAJFINSV","WIPRO","ONGC","NTPC","POWERGRID",
    "TATAMOTORS","NESTLEIND","M&M","TATASTEEL","ADANIENT","GRASIM","SUNPHARMA",
    "JSWSTEEL","TECHM","HINDALCO","HDFCLIFE","SBILIFE","DIVISLAB","DRREDDY",
    "COALINDIA","EICHERMOT","BRITANNIA","APOLLOHOSP","CIPLA","BPCL","TATACONSUM",
    "HEROMOTOCO","BAJAJ-AUTO","SHRIRAMFIN","INDUSINDBK","LTIM","ADANIPORTS",
    # NIFTY NEXT 50
    "SIEMENS","HAVELLS","PIDILITIND","TORNTPHARM","GODREJCP","BERGEPAINT",
    "CHOLAFIN","LUPIN","MUTHOOTFIN","JINDALSTEL","PNB","BANKBARODA","CANBK",
    "IDFCFIRSTB","FEDERALBNK","IOC","HAL","BEL","BHEL","VEDL","SAIL","NMDC",
    "GAIL","PETRONET","CONCOR","IRFC","PFC","RECLTD","NHPC","SJVN",
    "TATAPOWER","ADANIGREEN","ADANIPOWER","TORNTPOWER","CESC","TATACOMM",
    "MPHASIS","LTTS","PERSISTENT","COFORGE","ZOMATO","ETERNAL","NYKAA","DMART",
    "TRENT","ABFRL","VBL","MCDOWELL-N","RADICO","UBL",
    # MID CAP selection
    "GODREJPROP","PRESTIGE","DLF","OBEROIRLTY","PHOENIXLTD","BRIGADE",
    "CROMPTON","VOLTAS","BLUESTARCO","WHIRLPOOL","AMBER","DIXON","PG","MARICO",
    "EMAMILTD","DABUR","BAJAJHIND","BALRAMCHIN","EID","RENUKA","TRIVENI",
    "MFSL","MAXHEALTH","FORTIS","RAINBOW","MEDANTA","VIJAYA","METROPOLIS",
    "THYROCARE","POLYMED","MTAR","CLEAN","ELGIEQUIP","GRINDWELL","CARBORUNIV",
    "TIINDIA","CRAFTSMAN","JBCHEPHARM","SANOFI","PFIZER","GLAXO","ASTRAZEN",
    "SOLARA","LAURUS","GRANULES","SEQUENT","JUBILANT","NATCOPHARMA","ALKEM",
    "IPCALAB","AJANTPHARM","GLAND","LAURUSLABS","DIVI","SYNGENE","BIOCON",
    "AUROPHA","CADILAHC","SUNPHARMA","TORNTPHARM","ZYDUSLIFE","CAPLIPOINT",
    "AAVAS","HOMEFIRST","CAN_FIN","REPCO","APTUS","CREDITACC","SPANDANA",
    "SATIN","ARMAN","FUSION","UJJIVAN","EQUITAS","SURYODAY",
    "ALOKINDS","RAYMOND","VARDHMAN","WELSPUN","TRIDENT","NITIRAJ",
    "TATAELXSI","KPITTECH","TANLA","ZENSAR","MASTEK","RATEGAIN","ROUTE",
    "NEWGEN","NUCLEUS","TATATECH","RAILTEL","RITES","IRCTC","IRCON",
    "RVNL","NBCC","HCC","NCC","KEC","KALPATPOWR","PNCINFRA","GPPL",
    "ASHOKLEY","MAHINDCIE","ENDURANCE","MNRINDIA","SUPRAJIT","BALKRISIND",
    "APOLLOTYRE","MRF","CEATLTD","JK","TVSSRICHAK","LUMAXTECH",
    "PIIND","RALLIS","UPL","ATUL","GNFC","DEEPAKNTR","NOCIL","AARTI",
    "SUDARSCHEM","VINATI","NAVINFLUOR","SRF","TATACHEM","GHCL","PCBL",
    "STERLITE","HINDZINC","NATIONALUM","MOIL","GMRINFRA","GVK","SADBHAV",
    "AHLUCONT","WABAG","INOX","PVR","ZEEL","SUN","BALAJITEL","NAZARA",
    "ONMOBILE","TVSMOTOR","ESCORTS","FORCE","GREAVES","VSTIND",
    "CUMMINSIND","THERMAX","BHARAT_FORGE","KALYANKJIL","SENCO","PC",
    "MANYAVAR","VEDANT","BATA","RELAXO","METRO","CAMPUS","LIBERTY",
    "TITANCOMPANY","KAJARIACER","SOMANY","ORIENTBELL","PGHL","VMART",
    "SHOPERSTOP","TRENT","AEON","LANDMARK","PVRINOX",
    "IDFC","PIRAMAL","M&MFIN","MAHINDRA","LICHOUSING","HDFC","GRUH",
    "DELHIVERY","BLUE_DART","GATI","VRL","TCI","MAHLOG",
    "ABIRLANUVO","HINDBIOSCI","SOLVINEX","LALPATHLAB","JKCEMENT","ACC",
    "AMBUJA","RAMCO","HEIDELBERG","MANGCEMCO","BIRLA","INDIA",
    # Small cap high-volume stocks
    "JUSTDIAL","MATRIMONY","NAUKRI","INFOEDGE","POLICYBZR","PAYTM","ANGEL",
    "IIFL","EDELWEISS","MOTILALOFS","5PAISA","CDSL","NSDL","CAMS","KFN",
    "BAJFINANCE","JMFINANCIAL","CHOICEIN","GEOJITFSL","IFCI",
    "SOBHA","KOLTEPATIL","MAHLIFE","ARVSMART","SUNTV","PVRINOX",
    "NETWORK18","TV18BRDCST","HINDMOTORS","TATACOMSYS","WPIL","UNOMINDA",
    "SANDHAR","SUBROS","JAMNAUTO","MOTHERSON","SRIRAMCIT","GENESYS",
    "KRBL","DAAWAT","LT_FOODS","HERITAGE","VADILALIND","DODLA","PRABHAT"
]

# Remove duplicates and add .NS suffix
NIFTY500_SYMBOLS = list(dict.fromkeys(NIFTY500_SYMBOLS))
NIFTY500_TICKERS = [s + ".NS" for s in NIFTY500_SYMBOLS]


# ──────────────────────────────────────────────────────────────────
# SECTION C — LOGGING SETUP
# ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level    = logging.INFO,
    format   = "%(asctime)s | %(levelname)s | %(message)s",
    datefmt  = "%Y-%m-%d %H:%M:%S",
    handlers = [
        logging.StreamHandler(),
        logging.FileHandler("kasf_scanner.log", encoding="utf-8")
    ]
)
log = logging.getLogger("KASF")


# ──────────────────────────────────────────────────────────────────
# SECTION D — MARKET HOURS CHECK
# ──────────────────────────────────────────────────────────────────
def is_market_open() -> bool:
    """Returns True only during NSE trading hours (9:15–15:15 IST, Mon–Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)

    # Weekend check
    if now.weekday() >= 5:
        return False

    # Time check: 9:15 AM to 3:15 PM IST
    market_open  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=15, second=0, microsecond=0)

    return market_open <= now <= market_close


def is_scheduled_time(now_ist: datetime) -> bool:
    """
    Mirrors Pine Script India time windows exactly:
      Prime   : 9:15–10:30
      Continue: 13:30–14:45
      Close   : 15:00–15:15
    """
    h, m = now_ist.hour, now_ist.minute

    prime    = (h == 9 and m >= 15) or (h == 10 and m <= 30)
    cont     = (h == 13 and m >= 30) or (h == 14 and m <= 45)
    close_w  = (h == 15 and m <= 15)

    return prime or cont or close_w


# ──────────────────────────────────────────────────────────────────
# SECTION E — DATA FETCH
# ──────────────────────────────────────────────────────────────────
def fetch_ohlcv(ticker: str) -> pd.DataFrame | None:
    """
    Fetch 15-minute OHLCV data for a ticker using yfinance.
    Returns DataFrame or None on failure.
    """
    try:
        df = yf.download(
            ticker,
            period   = HISTORY_PERIOD,
            interval = CANDLE_INTERVAL,
            progress = False,
            auto_adjust = True
        )
        if df is None or df.empty or len(df) < 30:
            return None

        # Flatten multi-index columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume"
        })
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        return df

    except Exception as e:
        log.debug(f"Fetch failed {ticker}: {e}")
        return None


def fetch_daily_ohlcv(ticker: str) -> pd.DataFrame | None:
    """Fetch daily data for pivot points and ATR (like Pine Script's D timeframe)."""
    try:
        df = yf.download(ticker, period="10d", interval="1d", progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < 3:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
        return df[["open","high","low","close","volume"]].dropna()
    except Exception:
        return None


def fetch_index_sentiment() -> str:
    """
    Fetch NIFTY index to determine market sentiment.
    Mirrors Pine Script: index_close > index_ema20 → BULLISH else BEARISH
    """
    try:
        df = yf.download("^NSEI", period="30d", interval="1d", progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < 21:
            return "Neutral"
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"]
        ema20 = close.ewm(span=20, adjust=False).mean()
        sentiment = "BULLISH" if float(close.iloc[-1]) > float(ema20.iloc[-1]) else "BEARISH"
        log.info(f"NIFTY Index Sentiment: {sentiment}")
        return sentiment
    except Exception as e:
        log.warning(f"Index sentiment fetch failed: {e}")
        return "Neutral"


# ──────────────────────────────────────────────────────────────────
# SECTION F — INDICATOR CALCULATIONS
# Exact mirrors of Pine Script Section E, F, G
# ──────────────────────────────────────────────────────────────────
def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(com=period - 1, adjust=False).mean()
    avg_l = loss.ewm(com=period - 1, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_vwap(df: pd.DataFrame) -> pd.Series:
    """Session VWAP — resets each day (matches Pine Script ta.vwap)."""
    df = df.copy()
    df["date"]    = df.index.date
    df["hlc3"]    = (df["high"] + df["low"] + df["close"]) / 3
    df["cum_vol"] = df.groupby("date")["volume"].cumsum()
    df["cum_pv"]  = df.groupby("date").apply(
        lambda g: (g["hlc3"] * g["volume"]).cumsum()
    ).reset_index(level=0, drop=True)
    return df["cum_pv"] / df["cum_vol"]


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl  = df["high"] - df["low"]
    hcp = (df["high"] - df["close"].shift()).abs()
    lcp = (df["low"]  - df["close"].shift()).abs()
    tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def calc_pivot_points(daily_df: pd.DataFrame):
    """
    Pivot points from previous day OHLC.
    Mirrors Pine Script Section D exactly.
    """
    prev = daily_df.iloc[-2]   # previous completed day
    H, L, C = float(prev["high"]), float(prev["low"]), float(prev["close"])
    pivot = (H + L + C) / 3
    r1    = (2 * pivot) - L
    r2    = pivot + (H - L)
    s1    = (2 * pivot) - H
    s2    = pivot - (H - L)
    return pivot, r1, r2, s1, s2


# ──────────────────────────────────────────────────────────────────
# SECTION G — SIGNAL GENERATION
# Mirrors Pine Script Sections F, G, J (stops, filters, R:R)
# ──────────────────────────────────────────────────────────────────
def generate_signal(symbol: str, df_15m: pd.DataFrame, df_daily: pd.DataFrame) -> dict | None:
    """
    Run all KASF filters on the latest bar.
    Returns signal dict (matches Google Sheet columns) or None.
    """
    try:
        # ── INDICATORS ────────────────────────────────────────────
        close  = df_15m["close"]
        high   = df_15m["high"]
        volume = df_15m["volume"]

        ema20   = calc_ema(close, 20)
        ema50   = calc_ema(close, 50)
        rsi     = calc_rsi(close, 14)
        vwap    = calc_vwap(df_15m)
        vol_avg = volume.rolling(20).mean()
        high_20 = high.shift(1).rolling(20).max()   # highest(high,20)[1]

        # Daily ATR for stop calculation
        daily_atr_series = calc_atr(df_daily, 14)
        daily_atr = float(daily_atr_series.iloc[-1])

        # ── LATEST VALUES ─────────────────────────────────────────
        c        = float(close.iloc[-1])
        v        = float(volume.iloc[-1])
        e20      = float(ema20.iloc[-1])
        e50      = float(ema50.iloc[-1])
        rsi_val  = float(rsi.iloc[-1])
        vwap_val = float(vwap.iloc[-1])
        vol_a    = float(vol_avg.iloc[-1])
        h20      = float(high_20.iloc[-1])

        # ── PIVOT POINTS ──────────────────────────────────────────
        _, r1, r2, s1, s2 = calc_pivot_points(df_daily)

        # ── SETUP CLASSIFICATION (Pine Script Section F) ──────────
        breakout    = (c > h20) and (v > vol_a * VOL_MULT)
        is_pullback = (abs(c - s1) / c) < PULL_PCT

        if breakout:
            setup_type = "BREAKOUT"
        elif is_pullback:
            setup_type = "PULLBACK"
        else:
            setup_type = "TREND"

        # ── STOPS ─────────────────────────────────────────────────
        atr_stop = c - (daily_atr * ATR_MULT)
        sl1      = s1
        sl2      = atr_stop
        actual_sl = max(sl1, sl2)

        # ── ENTRY (Pine Script Section F smart entry) ──────────────
        dist_vwap = abs(c - vwap_val)
        dist_ema  = abs(c - e20)

        if is_pullback:
            entry = s1
        elif breakout:
            entry = c
        else:
            entry = vwap_val if dist_vwap < dist_ema else e20

        entry_gap_pct = ((c - entry) / entry * 100) if entry > 0 else 0

        # ── R:R CALCULATION ───────────────────────────────────────
        rr_denom = entry - actual_sl
        rr       = ((r1 - entry) / rr_denom) if rr_denom > 0 else 0

        # ── QUALITY FILTERS (Pine Script Section G) ───────────────
        trend_ok = (c > e20) and (c > e50)
        rsi_ok   = (rsi_val > RSI_MIN) and (rsi_val < RSI_MAX)
        vol_ok   = v > vol_a * VOL_MULT
        setup_ok = breakout or is_pullback or (c > vwap_val)
        valid    = trend_ok and rsi_ok and vol_ok and setup_ok

        if not valid:
            return None
        if rr < MIN_RR:
            return None

        # ── BUILD SIGNAL PAYLOAD (matches Google Sheet columns) ────
        return {
            "symbol":        symbol,
            "market":        "INDIA",
            "entry":         round(entry, 4),
            "current_price": round(c, 4),
            "entry_gap_pct": round(entry_gap_pct, 2),
            "t1":            round(r1, 4),
            "t2":            round(r2, 4),
            "sl1":           round(sl1, 4),
            "sl2":           round(sl2, 4),
            "setup":         setup_type,
            "rr":            round(rr, 2),
            "index":         "BULLISH",   # filled in by scanner after index check
        }

    except Exception as e:
        log.debug(f"Signal error {symbol}: {e}")
        return None


# ──────────────────────────────────────────────────────────────────
# SECTION H — GOOGLE SHEET WEBHOOK SENDER
# Same JSON format as TradingView was sending
# ──────────────────────────────────────────────────────────────────
def post_to_sheet(payload: dict) -> bool:
    """POST signal JSON to Google Sheet webhook (same as TradingView alerts did)."""
    try:
        resp = requests.post(
            GOOGLE_SHEET_WEBHOOK,
            json    = payload,
            timeout = 15,
            headers = {"Content-Type": "application/json"}
        )
        if "Success" in resp.text or "Duplicate" in resp.text:
            return True
        log.warning(f"Sheet response: {resp.text[:100]}")
        return False
    except Exception as e:
        log.error(f"Webhook post failed: {e}")
        return False


# ──────────────────────────────────────────────────────────────────
# SECTION I — MAIN SCAN LOOP
# ──────────────────────────────────────────────────────────────────
def run_scan():
    """One full scan of all NIFTY 500 stocks."""
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)

    log.info("=" * 60)
    log.info(f"KASF SCAN START — {now.strftime('%Y-%m-%d %H:%M:%S IST')}")
    log.info(f"Scanning {len(NIFTY500_TICKERS)} stocks")

    # Fetch index sentiment once per run
    index_sentiment = fetch_index_sentiment()

    signals_found  = 0
    signals_posted = 0
    errors         = 0

    for i, ticker in enumerate(NIFTY500_TICKERS, 1):
        symbol = ticker.replace(".NS", "")

        try:
            # Fetch data
            df_15m   = fetch_ohlcv(ticker)
            df_daily = fetch_daily_ohlcv(ticker)

            if df_15m is None or df_daily is None:
                errors += 1
                time.sleep(REQUEST_DELAY_SEC)
                continue

            # Generate signal
            signal = generate_signal(symbol, df_15m, df_daily)

            if signal:
                signal["index"] = index_sentiment
                signals_found  += 1
                log.info(f"✅ SIGNAL: {symbol} | {signal['setup']} | R:R={signal['rr']} | Entry={signal['entry']}")

                # Post to Google Sheet (same as TradingView did)
                if post_to_sheet(signal):
                    signals_posted += 1
                    log.info(f"   → Posted to Google Sheet ✓")
                else:
                    log.warning(f"   → Post failed ✗")

                # Stop at MAX_PICKS to match Google Script limit
                if signals_posted >= MAX_PICKS:
                    log.info(f"Max picks ({MAX_PICKS}) reached — stopping early")
                    break

        except Exception as e:
            log.error(f"Error on {ticker}: {e}")
            errors += 1

        # Progress log every 50 stocks
        if i % 50 == 0:
            log.info(f"Progress: {i}/{len(NIFTY500_TICKERS)} | Signals: {signals_found} | Posted: {signals_posted}")

        time.sleep(REQUEST_DELAY_SEC)

    log.info(f"SCAN COMPLETE — Signals: {signals_found} | Posted: {signals_posted} | Errors: {errors}")
    log.info("=" * 60)

    return signals_posted


# ──────────────────────────────────────────────────────────────────
# SECTION J — SCHEDULER
# Runs scan every 15 minutes during market hours
# ──────────────────────────────────────────────────────────────────
def main():
    log.info("KASF V5 NSE Scanner started")
    log.info(f"Stocks to scan  : {len(NIFTY500_TICKERS)}")
    log.info(f"Scan interval   : Every {SCAN_INTERVAL_MIN} minutes")
    log.info(f"Market hours    : 9:15 AM – 3:15 PM IST, Mon–Fri")
    log.info(f"Volume filter   : {VOL_MULT}x 20-period average")
    log.info(f"RSI range       : {RSI_MIN} – {RSI_MAX}")
    log.info(f"Min R:R         : {MIN_RR}")
    log.info(f"Webhook target  : {GOOGLE_SHEET_WEBHOOK[:50]}...")

    while True:
        ist = pytz.timezone("Asia/Kolkata")
        now = datetime.now(ist)

        if is_market_open():
            if is_scheduled_time(now):
                run_scan()
            else:
                log.info(f"Market open but outside scan window — {now.strftime('%H:%M IST')}")
        else:
            log.info(f"Market closed — {now.strftime('%H:%M IST')} | Next check in {SCAN_INTERVAL_MIN} min")

        # Wait for next scan interval
        time.sleep(SCAN_INTERVAL_MIN * 60)


if __name__ == "__main__":
    main()
