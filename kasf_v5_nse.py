"""
╔══════════════════════════════════════════════════════════════════╗
║          KASF V5 — NSE PYTHON SCANNER  (V2 SMART SCHEDULE)     ║
║                                                                  ║
║  SCHEDULE — 5 slots only, hardcoded in Python:                  ║
║                                                                  ║
║   9:15 AM IST → ENTRY SCAN  (full scan + Gemini + Telegram)    ║
║   9:30 AM IST → ENTRY SCAN  (full scan + Gemini + Telegram)    ║
║  10:00 AM IST → ENTRY SCAN  (full scan + Gemini + Telegram)    ║
║   2:30 PM IST → EXIT WARNING (Telegram only — zero tokens)     ║
║   3:15 PM IST → FINAL EXIT  (Telegram only — zero tokens)      ║
║                                                                  ║
║  All other cron fires → script exits in <1 second              ║
║  Railway cron stays: */15 3-10 * * 1-5                         ║
║                                                                  ║
║  TOKEN SAVINGS: ~87% vs previous version                        ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
import logging
import random
from logging.handlers import RotatingFileHandler
from datetime import datetime
import pytz

# ──────────────────────────────────────────────────────────────────
# SECTION A — CONFIGURATION
# ──────────────────────────────────────────────────────────────────
GOOGLE_SHEET_WEBHOOK = os.environ.get(
    "GOOGLE_SHEET_WEBHOOK",
    "https://script.google.com/macros/s/1EqLjC0ifrvg770MSXUYvYeKj9orsCPKyR2DJtINusO8/exec"
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")   # set in Railway Variables
CHAT_ID   = os.environ.get("CHAT_ID",   "")   # set in Railway Variables

# ── KASF FILTER SETTINGS ──────────────────────────────────────────
ATR_MULT  = 1.5
MIN_RR    = 2.0    # raised from 1.5 → fewer, higher quality signals
RSI_MIN   = 45     # raised from 40  → stronger momentum only
RSI_MAX   = 70     # lowered from 74 → avoid overbought entries
VOL_MULT  = 2.0    # BREAKOUT volume multiplier
PULL_PCT  = 0.003
MAX_PICKS = 3      # max 3 signals per entry scan

# ── SCANNER SETTINGS ──────────────────────────────────────────────
CANDLE_INTERVAL = "15m"
HISTORY_PERIOD  = "5d"
BATCH_SIZE      = 10
BATCH_DELAY_SEC = 1.5

# ── TIME SLOTS (IST) ──────────────────────────────────────────────
# Each slot: (hour, minute, type)
# type = "ENTRY" → full scan + post to sheet
# type = "EXIT"  → Telegram warning only, no scan, zero tokens
# tolerance = ±7 min window around each slot
SCAN_SLOTS = [
    (9,  15, "ENTRY"),   # 9:15 AM  — opening scan
    (9,  30, "ENTRY"),   # 9:30 AM  — confirmation scan
    (10,  0, "ENTRY"),   # 10:00 AM — final entry scan
    (14, 30, "EXIT"),    # 2:30 PM  — exit warning
    (15, 15, "EXIT"),    # 3:15 PM  — final exit alert
]
SLOT_TOLERANCE_MIN = 7   # fire if within ±7 min of slot time


# ──────────────────────────────────────────────────────────────────
# SECTION B — NIFTY 500 STOCK LIST
# ──────────────────────────────────────────────────────────────────
NIFTY500_SYMBOLS = [
    # ── NIFTY 50 ──────────────────────────────────────────────────
    "RELIANCE","TCS","HDFCBANK","BHARTIARTL","ICICIBANK","INFY","SBIN",
    "HINDUNILVR","ITC","LT","BAJFINANCE","HCLTECH","KOTAKBANK","MARUTI",
    "AXISBANK","TITAN","ASIANPAINT","ULTRACEMCO","BAJAJFINSV","WIPRO",
    "ONGC","NTPC","POWERGRID","TATAMOTORS","NESTLEIND","MM","TATASTEEL",
    "ADANIENT","GRASIM","SUNPHARMA","JSWSTEEL","TECHM","HINDALCO",
    "HDFCLIFE","SBILIFE","DIVISLAB","DRREDDY","COALINDIA","EICHERMOT",
    "BRITANNIA","APOLLOHOSP","CIPLA","BPCL","TATACONSUM","HEROMOTOCO",
    "BAJAJ-AUTO","SHRIRAMFIN","INDUSINDBK","LTIM","ADANIPORTS",

    # ── NIFTY NEXT 50 ─────────────────────────────────────────────
    "SIEMENS","HAVELLS","PIDILITIND","TORNTPHARM","GODREJCP","BERGEPAINT",
    "CHOLAFIN","LUPIN","MUTHOOTFIN","JINDALSTEL","PNB","BANKBARODA",
    "CANBK","IDFCFIRSTB","FEDERALBNK","IOC","HAL","BEL","BHEL","VEDL",
    "SAIL","NMDC","GAIL","PETRONET","CONCOR","IRFC","PFC","RECLTD",
    "NHPC","SJVN","TATAPOWER","ADANIGREEN","ADANIPOWER","TORNTPOWER",
    "CESC","TATACOMM","MPHASIS","LTTS","PERSISTENT","COFORGE","ZOMATO",
    "ETERNAL","NYKAA","DMART","TRENT","ABFRL","VBL","MCDOWELL-N",
    "RADICO","UBL",

    # ── NIFTY MIDCAP 150 ──────────────────────────────────────────
    "GODREJPROP","PRESTIGE","DLF","OBEROIRLTY","PHOENIXLTD","BRIGADE",
    "CROMPTON","VOLTAS","BLUESTARCO","WHIRLPOOL","AMBER","DIXON",
    "MARICO","EMAMILTD","DABUR","BAJAJHIND","BALRAMCHIN","RENUKA",
    "TRIVENI","MFSL","MAXHEALTH","FORTIS","METROPOLIS","THYROCARE",
    "POLYMED","MTAR","ELGIEQUIP","GRINDWELL","CARBORUNIV","TIINDIA",
    "CRAFTSMAN","JBCHEPHARM","SANOFI","PFIZER","GLAXO","ASTRAZEN",
    "SOLARA","LAURUS","GRANULES","JUBILANT","NATCOPHARMA","ALKEM",
    "IPCALAB","AJANTPHARM","GLAND","LAURUSLABS","SYNGENE","BIOCON",
    "AUROPHARMA","ZYDUSLIFE","CAPLIPOINT","AAVAS","HOMEFIRST",
    "CANFINHOME","REPCO","APTUS","SPANDANA","UJJIVAN","EQUITAS",
    "SURYODAY","RAYMOND","VARDHMAN","WELSPUN","TRIDENT",
    "TATAELXSI","KPITTECH","TANLA","ZENSAR","MASTEK","RATEGAIN",
    "ROUTE","NEWGEN","NUCLEUS","TATATECH","RAILTEL","RITES","IRCTC",
    "IRCON","RVNL","NBCC","NCC","KEC","KALPATPOWR","PNCINFRA",
    "ASHOKLEY","ENDURANCE","BALKRISIND","APOLLOTYRE","MRF","CEATLTD",
    "TVSSRICHAK","LUMAXTECH","PIIND","RALLIS","UPL","ATUL","GNFC",
    "DEEPAKNTR","NOCIL","AARTI","SUDARSCHEM","VINATI","NAVINFLUOR",
    "SRF","TATACHEM","GHCL","PCBL","HINDZINC","NATIONALUM","MOIL",
    "GMRINFRA","TVSMOTOR","ESCORTS","FORCEMOT","CUMMINSIND","THERMAX",
    "BHARATFORG","KALYANKJIL","SENCO","MANYAVAR","BATA","RELAXO",
    "METROBRANDS","KAJARIACER","SOMANY","ORIENTBELL","VMART",
    "SHOPERSTOP","PVRINOX","PIRAMAL","MAHINDFIN","LICHOUSING",
    "DELHIVERY","LALPATHLAB","JKCEMENT","ACC","AMBUJA","RAMCOCEM",
    "HEIDELBERGCEM","JUSTDIAL","NAUKRI","INFOEDGE","POLICYBZR",
    "ANGELONE","IIFL","EDELWEISS","MOTILALOFS","CDSL","CAMS",
    "JMFINANCIAL","GEOJITFSL","SOBHA","KOLTEPATIL",
    "SUNTV","NETWORK18","TV18BRDCST","UNOMINDA","SANDHAR","SUBROS",
    "JAMNAUTO","MOTHERSON","KRBL","LTFOODS","DODLA",

    # ── NIFTY SMALLCAP (liquid names) ─────────────────────────────
    "HAPPSTMNDS","BIRLASOFT","CYIENT","SONACOMS","SANSERA",
    "TITAGARH","IREDA","JYOTHYLAB","HATSUN","WOCKPHARMA",
    "STRIDES","ERIS","GLENMARK","INOXWIND","SUZLON",
    "ORIENTELEC","POLYCAB","KEI","GSFC","ASTRAL","SUPREME",
    "BALAMINES","CHEMPLASTS","ALKYLAMINE","FLUOROCHEM",
    "PGHL","GILLETTE","COLPAL","JKLAKSHMI","STARCEMENT",
    "BIRLACORPN","SHREECEM","AIAENG","SUPRAJIT","MNRINDIA",
    "WABAG","NAZARA","VSTIND","SAFARI","VGUARD","VOLTAMP",
    "RATNAMANI","WELCORP","JSPL","SEQUENT","SATIN","ARMAN",
    "FUSION","CREDITACC","IDFC","CHOICEIN","PAYTM",
    "GATI","VRL","TCI","BLUEDART","RBLBANK","BANDHANBNK",
    "DCBBANK","MANAPPURAM","FINEORG","VINATIORGA","POLYPLEX",
]

NIFTY500_SYMBOLS = list(dict.fromkeys(NIFTY500_SYMBOLS))
NIFTY500_TICKERS = [s + ".NS" for s in NIFTY500_SYMBOLS]


# ──────────────────────────────────────────────────────────────────
# SECTION C — LOGGING
# ──────────────────────────────────────────────────────────────────
def setup_logging():
    fmt      = "%(asctime)s | %(levelname)s | %(message)s"
    datefmt  = "%Y-%m-%d %H:%M:%S"
    handlers = [
        logging.StreamHandler(),
        RotatingFileHandler(
            "kasf_scanner.log",
            maxBytes    = 5 * 1024 * 1024,
            backupCount = 3,
            encoding    = "utf-8"
        )
    ]
    logging.basicConfig(level=logging.INFO, format=fmt,
                        datefmt=datefmt, handlers=handlers)

setup_logging()
log = logging.getLogger("KASF")


# ──────────────────────────────────────────────────────────────────
# SECTION D — SLOT DETECTION
# Checks current IST time against the 5 defined slots
# Returns ("ENTRY"/"EXIT", slot_label) or (None, None)
# ──────────────────────────────────────────────────────────────────
def get_current_slot() -> tuple[str | None, str | None]:
    """
    Matches current IST time to one of the 5 defined slots.
    Returns (slot_type, label) or (None, None) if no match.
    Tolerance = ±SLOT_TOLERANCE_MIN minutes around each slot.
    """
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)

    # Weekend — always skip
    if now.weekday() >= 5:
        return None, None

    now_minutes = now.hour * 60 + now.minute

    for (slot_h, slot_m, slot_type) in SCAN_SLOTS:
        slot_minutes = slot_h * 60 + slot_m
        diff = abs(now_minutes - slot_minutes)
        if diff <= SLOT_TOLERANCE_MIN:
            label = f"{slot_h:02d}:{slot_m:02d} IST"
            return slot_type, label

    return None, None


# ──────────────────────────────────────────────────────────────────
# SECTION E — TELEGRAM DIRECT SENDER
# Used for EXIT alerts — bypasses Google Sheet entirely
# No Gemini tokens consumed
# ──────────────────────────────────────────────────────────────────
def send_telegram_exit_alert(slot_label: str, is_final: bool):
    """
    Sends exit warning directly to Telegram.
    Zero Google Sheet calls. Zero Gemini tokens.
    """
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("BOT_TOKEN or CHAT_ID not set — cannot send exit alert directly")
        log.info("Exit alert would have been sent to Telegram")
        return

    if is_final:
        msg = (
            "🚨 <b>KASF — FINAL EXIT ALERT</b> 🚨\n"
            "⏰ Time: <b>3:15 PM IST</b>\n\n"
            "🛑 <b>EXIT ALL INTRADAY POSITIONS NOW!</b>\n"
            "NSE market closes in 15 minutes.\n\n"
            "✅ Book profits on all open trades.\n"
            "✅ Do not carry intraday positions overnight.\n\n"
            "⚠️ <i>KASF Auto-Alert — No new entries after this.</i>"
        )
    else:
        msg = (
            "⚠️ <b>KASF — EXIT WARNING</b> ⚠️\n"
            "⏰ Time: <b>2:30 PM IST</b>\n\n"
            "📢 Market closes in <b>45 minutes</b>.\n\n"
            "🔍 Review all open intraday positions.\n"
            "💰 Consider booking partial profits now.\n"
            "🛑 Plan your exits before 3:15 PM IST.\n\n"
            "⚠️ <i>KASF Auto-Alert — Next alert at 3:15 PM.</i>"
        )

    try:
        url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id":    CHAT_ID,
            "text":       msg,
            "parse_mode": "HTML"
        }, timeout=10)
        if resp.ok:
            log.info(f"✅ Exit alert sent to Telegram — {slot_label}")
        else:
            log.warning(f"Telegram send failed: {resp.text[:100]}")
    except Exception as e:
        log.error(f"Telegram send error: {e}")


# ──────────────────────────────────────────────────────────────────
# SECTION F — DATA FETCH
# ──────────────────────────────────────────────────────────────────
def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    return df


def fetch_batch_15m(tickers: list) -> dict:
    try:
        raw = yf.download(
            tickers, period=HISTORY_PERIOD, interval=CANDLE_INTERVAL,
            progress=False, auto_adjust=True, group_by="ticker"
        )
        result = {}
        for ticker in tickers:
            try:
                df = raw.copy() if len(tickers) == 1 else raw[ticker].copy()
                df = _normalise_columns(df)
                needed = [c for c in ["open","high","low","close","volume"] if c in df.columns]
                if len(needed) < 5:
                    continue
                df = df[["open","high","low","close","volume"]].dropna()
                if len(df) >= 30:
                    result[ticker] = df
            except Exception:
                continue
        return result
    except Exception as e:
        log.warning(f"Batch 15m fetch failed: {e}")
        return {}


def fetch_batch_daily(tickers: list) -> dict:
    try:
        raw = yf.download(
            tickers, period="15d", interval="1d",
            progress=False, auto_adjust=True, group_by="ticker"
        )
        result = {}
        for ticker in tickers:
            try:
                df = raw.copy() if len(tickers) == 1 else raw[ticker].copy()
                df = _normalise_columns(df)
                needed = [c for c in ["open","high","low","close","volume"] if c in df.columns]
                if len(needed) < 5:
                    continue
                df = df[["open","high","low","close","volume"]].dropna()
                if len(df) >= 3:
                    result[ticker] = df
            except Exception:
                continue
        return result
    except Exception as e:
        log.warning(f"Batch daily fetch failed: {e}")
        return {}


def fetch_index_sentiment() -> str:
    try:
        raw = yf.download("^NSEI", period="30d", interval="1d",
                          progress=False, auto_adjust=True)
        df  = _normalise_columns(raw)
        if df.empty or len(df) < 21:
            return "Neutral"
        c     = df["close"]
        ema20 = c.ewm(span=20, adjust=False).mean()
        sent  = "BULLISH" if float(c.iloc[-1]) > float(ema20.iloc[-1]) else "BEARISH"
        log.info(f"NIFTY Sentiment: {sent}")
        return sent
    except Exception as e:
        log.warning(f"Index sentiment failed: {e}")
        return "Neutral"


# ──────────────────────────────────────────────────────────────────
# SECTION G — INDICATORS
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
    """Session VWAP — resets daily. pandas 3.x safe."""
    df2          = df.copy()
    df2["date"]  = df2.index.date
    df2["hlc3"]  = (df2["high"] + df2["low"] + df2["close"]) / 3
    df2["pv"]    = df2["hlc3"] * df2["volume"]
    df2["cum_pv"]  = df2.groupby("date")["pv"].cumsum()
    df2["cum_vol"] = df2.groupby("date")["volume"].cumsum()
    return df2["cum_pv"] / df2["cum_vol"]


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl  = df["high"] - df["low"]
    hcp = (df["high"] - df["close"].shift()).abs()
    lcp = (df["low"]  - df["close"].shift()).abs()
    tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def calc_pivot_points(daily_df: pd.DataFrame):
    prev  = daily_df.iloc[-2]
    H, L, C = float(prev["high"]), float(prev["low"]), float(prev["close"])
    pivot = (H + L + C) / 3
    r1    = (2 * pivot) - L
    r2    = pivot + (H - L)
    s1    = (2 * pivot) - H
    s2    = pivot - (H - L)
    return pivot, r1, r2, s1, s2


# ──────────────────────────────────────────────────────────────────
# SECTION H — SIGNAL GENERATION
# ──────────────────────────────────────────────────────────────────
def generate_signal(symbol: str,
                    df_15m: pd.DataFrame,
                    df_daily: pd.DataFrame) -> dict | None:
    try:
        close  = df_15m["close"]
        high   = df_15m["high"]
        volume = df_15m["volume"]

        ema20   = calc_ema(close, 20)
        ema50   = calc_ema(close, 50)
        rsi     = calc_rsi(close, 14)
        vwap    = calc_vwap(df_15m)
        vol_avg = volume.rolling(20).mean()
        high_20 = high.shift(1).rolling(20).max()
        daily_atr = float(calc_atr(df_daily, 14).iloc[-1])

        c        = float(close.iloc[-1])
        v        = float(volume.iloc[-1])
        e20      = float(ema20.iloc[-1])
        e50      = float(ema50.iloc[-1])
        rsi_val  = float(rsi.iloc[-1])
        vwap_val = float(vwap.iloc[-1])
        vol_a    = float(vol_avg.iloc[-1])
        h20      = float(high_20.iloc[-1])

        if any(np.isnan(x) for x in [e20, e50, rsi_val, vwap_val, vol_a, h20, daily_atr]):
            return None

        _, r1, r2, s1, s2 = calc_pivot_points(df_daily)

        breakout    = (c > h20) and (v > vol_a * VOL_MULT)
        is_pullback = (abs(c - s1) / c) < PULL_PCT

        if breakout:
            setup_type = "BREAKOUT"
        elif is_pullback:
            setup_type = "PULLBACK"
        else:
            setup_type = "TREND"

        sl1       = s1
        sl2       = c - (daily_atr * ATR_MULT)
        actual_sl = max(sl1, sl2)

        if is_pullback:
            entry = s1
        elif breakout:
            entry = c
        else:
            entry = vwap_val if abs(c - vwap_val) < abs(c - e20) else e20

        entry_gap_pct = max(0.0, ((c - entry) / entry * 100)) if entry > 0 else 0.0

        rr_denom = entry - actual_sl
        if rr_denom <= 0:
            return None
        rr = (r1 - entry) / rr_denom

        trend_ok = (c > e20) and (c > e50)
        rsi_ok   = RSI_MIN < rsi_val < RSI_MAX

        if setup_type == "BREAKOUT":
            vol_ok = v > vol_a * VOL_MULT
        elif setup_type == "PULLBACK":
            vol_ok = v > vol_a * 0.8
        else:
            vol_ok = v > vol_a * 1.2

        setup_ok = breakout or is_pullback or (c > vwap_val)
        valid    = trend_ok and rsi_ok and vol_ok and setup_ok

        if not valid or rr < MIN_RR:
            return None

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
            "index":         "BULLISH",
        }

    except Exception as e:
        log.debug(f"Signal error {symbol}: {e}")
        return None


# ──────────────────────────────────────────────────────────────────
# SECTION I — POST TO GOOGLE SHEET
# ──────────────────────────────────────────────────────────────────
def post_to_sheet(payload: dict) -> bool:
    try:
        resp = requests.post(
            GOOGLE_SHEET_WEBHOOK,
            json    = payload,
            timeout = 15,
            headers = {"Content-Type": "application/json"}
        )
        if "Success" in resp.text or "Duplicate" in resp.text:
            return True
        log.warning(f"Sheet response: {resp.text[:120]}")
        return False
    except Exception as e:
        log.error(f"Webhook post failed: {e}")
        return False


# ──────────────────────────────────────────────────────────────────
# SECTION J — ENTRY SCAN
# ──────────────────────────────────────────────────────────────────
def run_entry_scan(slot_label: str, index_sentiment: str) -> int:
    log.info("=" * 62)
    log.info(f"ENTRY SCAN — {slot_label}")
    log.info(f"Stocks        : {len(NIFTY500_TICKERS)}")
    log.info(f"Index         : {index_sentiment}")
    log.info(f"Filters       : RR≥{MIN_RR} | RSI {RSI_MIN}–{RSI_MAX} | Vol {VOL_MULT}x")

    tickers = NIFTY500_TICKERS.copy()
    random.shuffle(tickers)   # fair coverage every run

    signals_found  = 0
    signals_posted = 0
    errors         = 0

    for batch_start in range(0, len(tickers), BATCH_SIZE):
        if signals_posted >= MAX_PICKS:
            log.info(f"MAX_PICKS ({MAX_PICKS}) reached — stopping")
            break

        batch      = tickers[batch_start : batch_start + BATCH_SIZE]
        data_15m   = fetch_batch_15m(batch)
        data_daily = fetch_batch_daily(batch)

        for ticker in batch:
            if signals_posted >= MAX_PICKS:
                break

            symbol   = ticker.replace(".NS", "")
            df_15m   = data_15m.get(ticker)
            df_daily = data_daily.get(ticker)

            if df_15m is None or df_daily is None:
                errors += 1
                continue

            signal = generate_signal(symbol, df_15m, df_daily)
            if signal:
                signal["index"] = index_sentiment
                signals_found  += 1
                log.info(
                    f"✅ {symbol:15s} | {signal['setup']:8s} "
                    f"| R:R={signal['rr']:4.2f} | Entry=₹{signal['entry']}"
                )
                if post_to_sheet(signal):
                    signals_posted += 1
                    log.info(f"   → Sheet ✓")
                else:
                    log.warning(f"   → Sheet FAILED ✗")

        batch_num     = (batch_start // BATCH_SIZE) + 1
        total_batches = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE
        log.info(f"Batch {batch_num}/{total_batches} | Signals: {signals_found} | Posted: {signals_posted}")
        time.sleep(BATCH_DELAY_SEC)

    log.info(f"SCAN DONE — Signals: {signals_found} | Posted: {signals_posted} | Errors: {errors}")
    log.info("=" * 62)
    return signals_posted


# ──────────────────────────────────────────────────────────────────
# SECTION K — MAIN ENTRY POINT
# ──────────────────────────────────────────────────────────────────
def main():
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)

    log.info(f"KASF V5 — cron fire at {now.strftime('%Y-%m-%d %H:%M:%S IST')}")

    # ── Step 1: Which slot are we in? ─────────────────────────────
    slot_type, slot_label = get_current_slot()

    if slot_type is None:
        log.info(f"No active slot at {now.strftime('%H:%M IST')} — exiting (0 tokens used)")
        return

    log.info(f"Matched slot: {slot_label} → {slot_type}")

    # ── Step 2: EXIT slot → direct Telegram, no scan, no tokens ──
    if slot_type == "EXIT":
        is_final = (now.hour == 15)   # 3:15 PM = final exit
        send_telegram_exit_alert(slot_label, is_final)
        log.info("Exit alert sent — exiting (0 Gemini tokens used)")
        return

    # ── Step 3: ENTRY slot → full scan ────────────────────────────
    if slot_type == "ENTRY":
        index_sentiment = fetch_index_sentiment()
        run_entry_scan(slot_label, index_sentiment)
        log.info("Entry scan complete — exiting")
        return


if __name__ == "__main__":
    main()
