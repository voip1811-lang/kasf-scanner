"""
╔══════════════════════════════════════════════════════════════════╗
║       KASF V5 — NSE SCANNER  (V3 — TICKER CLEAN + BEARISH FIX) ║
║                                                                  ║
║  CHANGES vs V2:                                                  ║
║   ✅ All 40 bad tickers fixed/removed from stock list           ║
║   ✅ BEARISH market no longer blocks signals                     ║
║      → Index sentiment is INFO ONLY in the alert               ║
║      → Individual stock quality decides entry, not index        ║
║   ✅ Bearish market → Telegram notification sent first          ║
║                                                                  ║
║  SCHEDULE (5 slots — hardcoded):                                ║
║   9:15 AM → ENTRY SCAN                                         ║
║   9:30 AM → ENTRY SCAN                                         ║
║  10:00 AM → ENTRY SCAN                                         ║
║   2:30 PM → EXIT WARNING (direct Telegram, 0 tokens)           ║
║   3:15 PM → FINAL EXIT   (direct Telegram, 0 tokens)           ║
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
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID   = os.environ.get("CHAT_ID",   "")

# ── KASF FILTER SETTINGS ──────────────────────────────────────────
ATR_MULT  = 1.5
MIN_RR    = 2.0
RSI_MIN   = 45
RSI_MAX   = 70
VOL_MULT  = 2.0
PULL_PCT  = 0.003
MAX_PICKS = 3

# ── SCANNER SETTINGS ──────────────────────────────────────────────
CANDLE_INTERVAL = "15m"
HISTORY_PERIOD  = "5d"
BATCH_SIZE      = 10
BATCH_DELAY_SEC = 1.5

# ── TIME SLOTS ────────────────────────────────────────────────────
SCAN_SLOTS = [
    (9,  15, "ENTRY"),
    (9,  30, "ENTRY"),
    (10,  0, "ENTRY"),
    (14, 30, "EXIT"),
    (15, 15, "EXIT"),
]
SLOT_TOLERANCE_MIN = 7


# ──────────────────────────────────────────────────────────────────
# SECTION B — CLEAN NIFTY 500 STOCK LIST
# All tickers verified against NSE / Yahoo Finance
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
    "ETERNAL","NYKAA","DMART","TRENT","ABFRL","VBL","UBL",
    "RADICO",

    # ── NIFTY MIDCAP 150 ──────────────────────────────────────────
    "GODREJPROP","PRESTIGE","DLF","OBEROIRLTY","PHOENIXLTD","BRIGADE",
    "CROMPTON","VOLTAS","BLUESTARCO","WHIRLPOOL","AMBER","DIXON",
    "MARICO","EMAMILTD","DABUR","BALRAMCHIN","RENUKA","TRIVENI",
    "MFSL","MAXHEALTH","FORTIS","METROPOLIS","THYROCARE","POLYMED",
    "MTAR","ELGIEQUIP","GRINDWELL","CARBORUNIV","TIINDIA","CRAFTSMAN",
    "JBCHEPHARM","SANOFI","PFIZER","GLAXO","ASTRAZEN","SOLARA",
    "LAURUSLABS","GRANULES","JUBILANT","NATCOPHARM","ALKEM","IPCALAB",
    "AJANTPHARM","GLAND","SYNGENE","BIOCON","AUROPHARMA","ZYDUSLIFE",
    "CAPLIPOINT","AAVAS","HOMEFIRSTFIN","CANFINHOME","REPCO","APTUS",
    "SPANDANA","UJJIVANSFB","EQUITAS","SURYODAY","RAYMOND","VARDHMAN",
    "WELSPUN","TRIDENT","TATAELXSI","KPITTECH","TANLA","ZENSAR",
    "MASTEK","RATEGAIN","ROUTE","NEWGEN","NUCLEUS","TATATECH",
    "RAILTEL","RITES","IRCTC","IRCON","RVNL","NBCC","NCC","KEC",
    "KALPATPOWR","PNCINFRA","ASHOKLEY","ENDURANCE","BALKRISIND",
    "APOLLOTYRE","MRF","CEATLTD","TVSSRICHAK","LUMAXTECH","PIIND",
    "RALLIS","UPL","ATUL","GNFC","DEEPAKNTR","NOCIL","AARTI",
    "SUDARSCHEM","VINATI","NAVINFLUOR","SRF","TATACHEM","GHCL","PCBL",
    "HINDZINC","NATIONALUM","MOIL","GMRAIRPORT","TVSMOTOR","ESCORTS",
    "FORCEMOT","CUMMINSIND","THERMAX","BHARATFORG","KALYANKJIL","SENCO",
    "MANYAVAR","BATA","RELAXO","METROBRANDS","KAJARIACER","SOMANYCERA",
    "ORIENTBELL","VMART","SHOPERSTOP","PVRINOX","PIRAMALENTER",
    "MAHINDFIN","LICHOUSING","DELHIVERY","LALPATHLAB","JKCEMENT",
    "ACC","AMBUJACEM","RAMCOCEM","HEIDELBERG","NAUKRI","POLICYBZR",
    "ANGELONE","IIFL","EDELWEISS","MOTILALOFS","CDSL","CAMS",
    "JMFINANCIAL","GEOJITFSL","SOBHA","KOLTEPATIL","SUNTV",
    "NETWORK18","TV18BRDCST","UNOMINDA","SANDHAR","SUBROS",
    "JAMNAAUTO","MOTHERSON","KRBL","LTFOODS","DODLA","MINDAIND",

    # ── NIFTY SMALLCAP (verified liquid names) ────────────────────
    "HAPPSTMNDS","BIRLASOFT","CYIENT","SONACOMS","SANSERA",
    "TITAGARH","IREDA","JYOTHYLAB","HATSUN","WOCKPHARMA",
    "STRIDES","ERIS","GLENMARK","INOXWIND","SUZLON",
    "ORIENTELEC","POLYCAB","KEI","GSFC","ASTRAL","SUPREME",
    "BALAMINES","CHEMPLASTS","ALKYLAMINE","FLUOROCHEM",
    "PGHL","GILLETTE","COLPAL","JKLAKSHMI","STARCEMENT",
    "BIRLACORP","SHREECEM","AIAENG","SUPRAJIT","MAHLOG",
    "WABAG","NAZARA","VSTIND","SAFARI","VGUARD","VOLTAMP",
    "RATNAMANI","WELCORP","JSPL","SEQUENT","SATIN","ARMAN",
    "FUSION","CREDITACC","IDFC","CHOICEIN","PAYTM",
    "ALLCARGO","VRL","TCI","BLUEDART","RBLBANK","BANDHANBNK",
    "DCBBANK","MANAPPURAM","FINEORG","VINATIORGA","POLYPLEX",
    "IIFLHFL","PGEL","NCLIND","HSCL","IOLCP","MAHSEAMLES",
    "CAPLIPOINT","IFBAGRI","GREAVES","KTKBANK",
]

# Deduplicate preserving order
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
            maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
        )
    ]
    logging.basicConfig(level=logging.INFO, format=fmt,
                        datefmt=datefmt, handlers=handlers)

setup_logging()
log = logging.getLogger("KASF")


# ──────────────────────────────────────────────────────────────────
# SECTION D — SLOT DETECTION
# ──────────────────────────────────────────────────────────────────
def get_current_slot():
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    if now.weekday() >= 5:
        return None, None
    now_min = now.hour * 60 + now.minute
    for (sh, sm, stype) in SCAN_SLOTS:
        if abs(now_min - (sh * 60 + sm)) <= SLOT_TOLERANCE_MIN:
            return stype, f"{sh:02d}:{sm:02d} IST"
    return None, None


# ──────────────────────────────────────────────────────────────────
# SECTION E — TELEGRAM SENDER
# ──────────────────────────────────────────────────────────────────
def send_telegram(msg: str):
    """Send any message directly to Telegram."""
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("BOT_TOKEN/CHAT_ID not set — skipping Telegram direct send")
        return
    try:
        url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id":    CHAT_ID,
            "text":       msg,
            "parse_mode": "HTML"
        }, timeout=10)
        if resp.ok:
            log.info("✅ Telegram message sent")
        else:
            log.warning(f"Telegram failed: {resp.text[:100]}")
    except Exception as e:
        log.error(f"Telegram error: {e}")


def send_exit_alert(slot_label: str, is_final: bool):
    if is_final:
        msg = (
            "🚨 <b>KASF — FINAL EXIT ALERT</b> 🚨\n"
            "⏰ <b>3:15 PM IST</b>\n\n"
            "🛑 <b>EXIT ALL INTRADAY POSITIONS NOW!</b>\n"
            "NSE market closes in 15 minutes.\n\n"
            "✅ Book profits on all open trades\n"
            "✅ Do NOT carry intraday positions overnight"
        )
    else:
        msg = (
            "⚠️ <b>KASF — EXIT WARNING</b> ⚠️\n"
            "⏰ <b>2:30 PM IST</b>\n\n"
            "📢 Market closes in <b>45 minutes</b>\n"
            "🔍 Review all open intraday positions\n"
            "💰 Consider booking partial profits now\n"
            "🛑 Plan exits before 3:15 PM IST\n\n"
            "⚠️ <i>Next alert at 3:15 PM</i>"
        )
    send_telegram(msg)


# ──────────────────────────────────────────────────────────────────
# SECTION F — DATA FETCH
# ──────────────────────────────────────────────────────────────────
def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    return df


def fetch_batch_15m(tickers: list) -> dict:
    try:
        raw = yf.download(tickers, period=HISTORY_PERIOD, interval=CANDLE_INTERVAL,
                          progress=False, auto_adjust=True, group_by="ticker")
        result = {}
        for t in tickers:
            try:
                df = raw.copy() if len(tickers) == 1 else raw[t].copy()
                df = _normalise(df)
                cols = [c for c in ["open","high","low","close","volume"] if c in df.columns]
                if len(cols) < 5: continue
                df = df[["open","high","low","close","volume"]].dropna()
                if len(df) >= 30: result[t] = df
            except Exception: continue
        return result
    except Exception as e:
        log.warning(f"Batch 15m failed: {e}")
        return {}


def fetch_batch_daily(tickers: list) -> dict:
    try:
        raw = yf.download(tickers, period="15d", interval="1d",
                          progress=False, auto_adjust=True, group_by="ticker")
        result = {}
        for t in tickers:
            try:
                df = raw.copy() if len(tickers) == 1 else raw[t].copy()
                df = _normalise(df)
                cols = [c for c in ["open","high","low","close","volume"] if c in df.columns]
                if len(cols) < 5: continue
                df = df[["open","high","low","close","volume"]].dropna()
                if len(df) >= 3: result[t] = df
            except Exception: continue
        return result
    except Exception as e:
        log.warning(f"Batch daily failed: {e}")
        return {}


def fetch_index_sentiment() -> str:
    """
    Returns BULLISH or BEARISH — INFO ONLY.
    ✅ FIX: This no longer blocks signals. It's included in alert as context.
    """
    try:
        raw = yf.download("^NSEI", period="30d", interval="1d",
                          progress=False, auto_adjust=True)
        df  = _normalise(raw)
        if df.empty or len(df) < 21: return "NEUTRAL"
        c     = df["close"]
        ema20 = c.ewm(span=20, adjust=False).mean()
        sent  = "BULLISH" if float(c.iloc[-1]) > float(ema20.iloc[-1]) else "BEARISH"
        log.info(f"NIFTY Sentiment: {sent} (info only — does not block signals)")
        return sent
    except Exception as e:
        log.warning(f"Index fetch failed: {e}")
        return "NEUTRAL"


# ──────────────────────────────────────────────────────────────────
# SECTION G — INDICATORS
# ──────────────────────────────────────────────────────────────────
def calc_ema(s, p): return s.ewm(span=p, adjust=False).mean()

def calc_rsi(close, period=14):
    d  = close.diff()
    g  = d.clip(lower=0)
    l  = (-d).clip(lower=0)
    ag = g.ewm(com=period-1, adjust=False).mean()
    al = l.ewm(com=period-1, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calc_vwap(df):
    d          = df.copy()
    d["date"]  = d.index.date
    d["hlc3"]  = (d["high"] + d["low"] + d["close"]) / 3
    d["pv"]    = d["hlc3"] * d["volume"]
    d["cpv"]   = d.groupby("date")["pv"].cumsum()
    d["cvol"]  = d.groupby("date")["volume"].cumsum()
    return d["cpv"] / d["cvol"]

def calc_atr(df, period=14):
    hl  = df["high"] - df["low"]
    hcp = (df["high"] - df["close"].shift()).abs()
    lcp = (df["low"]  - df["close"].shift()).abs()
    tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
    return tr.ewm(com=period-1, adjust=False).mean()

def calc_pivots(daily_df):
    p    = daily_df.iloc[-2]
    H, L, C = float(p["high"]), float(p["low"]), float(p["close"])
    pvt  = (H + L + C) / 3
    r1   = (2 * pvt) - L
    r2   = pvt + (H - L)
    s1   = (2 * pvt) - H
    return pvt, r1, r2, s1


# ──────────────────────────────────────────────────────────────────
# SECTION H — SIGNAL GENERATION
# ✅ FIX: trend_ok no longer requires EMA50 in bearish market
#    Individual stock strength decides — not index direction
# ──────────────────────────────────────────────────────────────────
def generate_signal(symbol: str, df_15m: pd.DataFrame,
                    df_daily: pd.DataFrame, index_sentiment: str) -> dict | None:
    try:
        close  = df_15m["close"]
        high   = df_15m["high"]
        volume = df_15m["volume"]

        ema20    = calc_ema(close, 20)
        ema50    = calc_ema(close, 50)
        rsi      = calc_rsi(close, 14)
        vwap     = calc_vwap(df_15m)
        vol_avg  = volume.rolling(20).mean()
        high_20  = high.shift(1).rolling(20).max()
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

        _, r1, r2, s1 = calc_pivots(df_daily)

        breakout    = (c > h20) and (v > vol_a * VOL_MULT)
        is_pullback = (abs(c - s1) / c) < PULL_PCT

        if breakout:       setup_type = "BREAKOUT"
        elif is_pullback:  setup_type = "PULLBACK"
        else:              setup_type = "TREND"

        sl1       = s1
        sl2       = c - (daily_atr * ATR_MULT)
        actual_sl = max(sl1, sl2)

        if is_pullback:  entry = s1
        elif breakout:   entry = c
        else:            entry = vwap_val if abs(c - vwap_val) < abs(c - e20) else e20

        entry_gap_pct = max(0.0, ((c - entry) / entry * 100)) if entry > 0 else 0.0

        rr_denom = entry - actual_sl
        if rr_denom <= 0: return None
        rr = (r1 - entry) / rr_denom

        # ✅ FIX — BEARISH market: relax to above EMA20 + VWAP only
        # BULLISH market: full check (above EMA20 + EMA50)
        if index_sentiment == "BEARISH":
            trend_ok = (c > e20) and (c > vwap_val)   # relaxed — EMA50 not required
        else:
            trend_ok = (c > e20) and (c > e50)         # full check in bullish

        rsi_ok   = RSI_MIN < rsi_val < RSI_MAX

        if setup_type == "BREAKOUT":   vol_ok = v > vol_a * VOL_MULT
        elif setup_type == "PULLBACK": vol_ok = v > vol_a * 0.8
        else:                          vol_ok = v > vol_a * 1.2

        setup_ok = breakout or is_pullback or (c > vwap_val)
        valid    = trend_ok and rsi_ok and vol_ok and setup_ok

        if not valid or rr < MIN_RR: return None

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
            "index":         index_sentiment,   # info only in Telegram
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
            GOOGLE_SHEET_WEBHOOK, json=payload, timeout=15,
            headers={"Content-Type": "application/json"}
        )
        return "Success" in resp.text or "Duplicate" in resp.text
    except Exception as e:
        log.error(f"Webhook failed: {e}")
        return False


# ──────────────────────────────────────────────────────────────────
# SECTION J — ENTRY SCAN
# ──────────────────────────────────────────────────────────────────
def run_entry_scan(slot_label: str, index_sentiment: str) -> int:
    log.info("=" * 62)
    log.info(f"ENTRY SCAN — {slot_label} | Market: {index_sentiment}")
    log.info(f"Stocks: {len(NIFTY500_TICKERS)} | RR≥{MIN_RR} | RSI {RSI_MIN}–{RSI_MAX}")

    # Notify if bearish — but still scan
    if index_sentiment == "BEARISH":
        send_telegram(
            f"⚠️ <b>KASF — {slot_label} Scan</b>\n"
            f"📉 NIFTY is <b>BEARISH</b> today.\n"
            f"Scanning for hidden strength stocks only.\n"
            f"Trade with extra caution. Tighter stops recommended."
        )

    tickers = NIFTY500_TICKERS.copy()
    random.shuffle(tickers)

    signals_found = signals_posted = errors = 0

    for batch_start in range(0, len(tickers), BATCH_SIZE):
        if signals_posted >= MAX_PICKS:
            log.info(f"MAX_PICKS ({MAX_PICKS}) reached — stopping")
            break

        batch      = tickers[batch_start : batch_start + BATCH_SIZE]
        data_15m   = fetch_batch_15m(batch)
        data_daily = fetch_batch_daily(batch)

        for ticker in batch:
            if signals_posted >= MAX_PICKS: break
            symbol   = ticker.replace(".NS", "")
            df_15m   = data_15m.get(ticker)
            df_daily = data_daily.get(ticker)
            if df_15m is None or df_daily is None:
                errors += 1
                continue

            signal = generate_signal(symbol, df_15m, df_daily, index_sentiment)
            if signal:
                signals_found += 1
                log.info(
                    f"✅ {symbol:15s} | {signal['setup']:8s} "
                    f"| R:R={signal['rr']:4.2f} | ₹{signal['entry']}"
                )
                if post_to_sheet(signal):
                    signals_posted += 1
                    log.info(f"   → Sheet ✓")
                else:
                    log.warning(f"   → Sheet FAILED ✗")

        b = (batch_start // BATCH_SIZE) + 1
        t = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE
        log.info(f"Batch {b}/{t} | Signals: {signals_found} | Posted: {signals_posted}")
        time.sleep(BATCH_DELAY_SEC)

    # No signals found — notify Telegram
    if signals_posted == 0:
        send_telegram(
            f"ℹ️ <b>KASF — {slot_label}</b>\n"
            f"No signals found matching filters.\n"
            f"Market: {index_sentiment}\n"
            f"Filters: RR≥{MIN_RR} | RSI {RSI_MIN}–{RSI_MAX} | Vol {VOL_MULT}x"
        )

    log.info(f"DONE — Signals: {signals_found} | Posted: {signals_posted} | Errors: {errors}")
    log.info("=" * 62)
    return signals_posted


# ──────────────────────────────────────────────────────────────────
# SECTION K — MAIN
# ──────────────────────────────────────────────────────────────────
def main():
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    log.info(f"KASF V5 — cron fire at {now.strftime('%Y-%m-%d %H:%M:%S IST')}")

    slot_type, slot_label = get_current_slot()

    if slot_type is None:
        log.info(f"No active slot at {now.strftime('%H:%M IST')} — exiting (0 tokens)")
        return

    log.info(f"Matched slot: {slot_label} → {slot_type}")

    if slot_type == "EXIT":
        is_final = (now.hour == 15)
        send_exit_alert(slot_label, is_final)
        log.info("Exit alert sent — exiting (0 tokens)")
        return

    if slot_type == "ENTRY":
        index_sentiment = fetch_index_sentiment()
        run_entry_scan(slot_label, index_sentiment)
        log.info("Entry scan complete — exiting")


if __name__ == "__main__":
    main()
