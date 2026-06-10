"""
╔══════════════════════════════════════════════════════════════════╗
║       KASF V5 — NSE SCANNER  (V5 — FIXED EDITION v3)           ║
║                                                                  ║
║  FIXES vs PREVIOUS:                                             ║
║   ✅ VOL_MULT lowered 2.0 → 1.5  (was blocking all signals)    ║
║   ✅ RSI_MIN lowered 45 → 40     (was too strict on down days)  ║
║   ✅ MIN_RR lowered 2.0 → 1.5    (was rejecting valid setups)   ║
║   ✅ Index sentiment NEUTRAL bug fixed — defaults to BULLISH    ║
║   ✅ Index history increased 45 → 60 days (more robust)         ║
║   ✅ PULLBACK vol filter loosened 0.8x → 0.6x                   ║
║   ✅ TREND vol filter loosened 1.2x → 1.0x                      ║
║   ✅ setup_ok condition broadened to include VWAP or EMA20      ║
║   ✅ Detailed per-filter debug logging added                     ║
║   ✅ Signal rejection reason logged per stock                    ║
║                                                                  ║
║  BUG FIX v2 (Errors: 332 — ALL stocks failing):                ║
║   ✅ _fyers_history: date_format "1"→"0" (epoch mode)          ║
║   ✅ _fyers_history: range_from/to now epoch integers           ║
║   ✅ Per-stock error message now logged (first 3 per batch)     ║
║                                                                  ║
║  BUG FIX v3 (Login FAILED — could not generate access token):  ║
║   ✅ Step 1: app_id hardcoded back to "2" (was FYERS_APP_ID)   ║
║   ✅ Step 3: access_token read directly from verify_pin resp   ║
║      Fyers direct-login mode returns token at Step 3 itself,   ║
║      no Step 4 auth_code exchange needed or possible.          ║
║                                                                  ║
║  RAILWAY ENV VARS REQUIRED:                                      ║
║   FYERS_APP_ID      → e.g. "L9NY305RTW"  (without -100)        ║
║   FYERS_SECRET_KEY  → from Fyers API dashboard                  ║
║   FYERS_FY_ID       → your Fyers login ID  e.g. "XK01234"      ║
║   FYERS_PIN         → your 4-digit Fyers PIN                    ║
║   FYERS_TOTP_KEY    → 32-char key from Fyers 2FA setup          ║
║   FYERS_REDIRECT_URI→ redirect URL set in your Fyers app        ║
║   BOT_TOKEN         → Telegram bot token                        ║
║   CHAT_ID           → Telegram chat ID                          ║
║   GOOGLE_SHEET_WEBHOOK → Google Apps Script URL                 ║
║                                                                  ║
║  OPTIONAL ENV VAR:                                               ║
║   TEST_MODE=true    → run anytime, any day, skips slot check    ║
║   TEST_MODE=false   → normal production schedule                ║
║                                                                  ║
║  SCHEDULE (6 slots — hardcoded, IST):                           ║
║   9:00 AM → TOKEN GEN                                           ║
║   9:15 AM → ENTRY SCAN                                          ║
║   9:30 AM → ENTRY SCAN                                          ║
║  10:00 AM → ENTRY SCAN                                          ║
║   1:30 PM → ENTRY SCAN                                          ║
║   2:30 PM → EXIT WARNING                                        ║
║   3:15 PM → FINAL EXIT                                          ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os
import json
import base64
import hashlib
import time
import logging
import random
import sys
import requests
import pyotp
import pandas as pd
import numpy as np
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse
import pytz

from fyers_apiv3 import fyersModel


# ──────────────────────────────────────────────────────────────────
# SECTION A — CONFIGURATION
# ──────────────────────────────────────────────────────────────────
GOOGLE_SHEET_WEBHOOK = os.environ.get(
    "GOOGLE_SHEET_WEBHOOK",
    "https://script.google.com/macros/s/1EqLjC0ifrvg770MSXUYvYeKj9orsCPKyR2DJtINusO8/exec"
)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID   = os.environ.get("CHAT_ID",   "")

# ── FYERS CREDENTIALS ─────────────────────────────────────────────
FYERS_APP_ID       = os.environ.get("FYERS_APP_ID",       "")
FYERS_APP_TYPE     = "100"
FYERS_SECRET_KEY   = os.environ.get("FYERS_SECRET_KEY",   "")
FYERS_FY_ID        = os.environ.get("FYERS_FY_ID",        "")
FYERS_PIN          = os.environ.get("FYERS_PIN",          "")
FYERS_TOTP_KEY     = os.environ.get("FYERS_TOTP_KEY",     "")
FYERS_REDIRECT_URI = os.environ.get("FYERS_REDIRECT_URI", "https://trade.fyers.in/api-login/redirect-uri/index.html")

FYERS_CLIENT_ID = f"{FYERS_APP_ID}-{FYERS_APP_TYPE}"

# ── FYERS API ENDPOINTS ───────────────────────────────────────────
_BASE_VAGATOR  = "https://api-t2.fyers.in/vagator/v2"
_BASE_API      = "https://api-t1.fyers.in/api/v3"
URL_SEND_OTP   = _BASE_VAGATOR + "/send_login_otp"
URL_VERIFY_OTP = _BASE_VAGATOR + "/verify_otp"
URL_VERIFY_PIN = _BASE_VAGATOR + "/verify_pin"
URL_TOKEN      = _BASE_API    + "/token"
URL_AUTH_CODE  = _BASE_API    + "/validate-authcode"

# ── KASF FILTER SETTINGS (FIXED — relaxed for real market conditions)
ATR_MULT  = 1.5
MIN_RR    = 1.5
RSI_MIN   = 40
RSI_MAX   = 75
VOL_MULT  = 1.5
PULL_PCT  = 0.003
MAX_PICKS = 3

# ── SCANNER SETTINGS ──────────────────────────────────────────────
CANDLE_INTERVAL  = "15"
DAILY_INTERVAL   = "D"
HISTORY_DAYS_15M = 5
HISTORY_DAYS_D   = 20
BATCH_SIZE       = 10
BATCH_DELAY_SEC  = 1.5

# ── TIME SLOTS ────────────────────────────────────────────────────
SCAN_SLOTS = [
    (9,   0, "TOKEN"),
    (9,  15, "ENTRY"),
    (9,  30, "ENTRY"),
    (10,  0, "ENTRY"),
    (13, 30, "ENTRY"),
    (14, 30, "EXIT"),
    (15, 15, "EXIT"),
]
SLOT_TOLERANCE_MIN = 7

# ── TOKEN CACHE ───────────────────────────────────────────────────
_fyers_instance = None


# ──────────────────────────────────────────────────────────────────
# SECTION B — NSE SYMBOL LIST
# ──────────────────────────────────────────────────────────────────
_RAW_SYMBOLS = [
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
    "ETERNAL","NYKAA","DMART","TRENT","ABFRL","VBL","UBL","RADICO",

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
    "IFBAGRI","GREAVES","KTKBANK",
]

_RAW_SYMBOLS  = list(dict.fromkeys(_RAW_SYMBOLS))
FYERS_SYMBOLS = [f"NSE:{s}-EQ" for s in _RAW_SYMBOLS]
FYERS_INDEX   = "NSE:NIFTY50-INDEX"


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

    if os.environ.get("TEST_MODE", "").lower() == "true":
        log.info("⚠️ TEST MODE ON — skipping slot/weekend check")
        return "ENTRY", f"{now.hour:02d}:{now.minute:02d} IST (TEST)"

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
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("BOT_TOKEN/CHAT_ID not set — skipping Telegram")
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
# SECTION F — FYERS TOTP AUTO LOGIN  (v5 — FINAL FIX)
# ──────────────────────────────────────────────────────────────────
#
# ROOT CAUSE CONFIRMED (decoded JWT from logs):
#   Step 3 verify_pin token has:
#     "aud": ["x:0","x:1","x:2","d:1"]  ← d:1 = DATA SCOPE ✅
#     "appType": ""                       ← no app bound
#
#   fyersModel sends: Authorization: CLIENT_ID-100:token
#   Fyers rejects it because token "appType" is "" not "100"
#   → code -16 on every data call
#
#   Step 4 token exchange ALSO fails (-16) because vagator auth_codes
#   cannot be used with the validate-authcode OAuth endpoint.
#   That endpoint only accepts browser-flow auth_codes.
#
# THE FIX:
#   Bypass fyersModel entirely for data calls.
#   Use raw requests.get() to https://api-t1.fyers.in/data/history
#   with Authorization header = "fy_id:token"  (NOT "CLIENT_ID:token")
#   This is what Fyers actually expects for vagator-issued tokens.
#
# The "fyers" object passed around is now just a token string wrapper.
# Only _fyers_history uses it — no other function calls fyers.* methods.
#

class FyersDirectClient:
    """
    Thin wrapper that holds a token and makes raw HTTP calls to
    Fyers data API. Bypasses fyersModel which sends wrong auth header
    for vagator-issued tokens (appType="" tokens).
    """
    DATA_URL = "https://api-t1.fyers.in/data/history"

    def __init__(self, fy_id: str, token: str):
        self.fy_id = fy_id
        self.token = token

    def history(self, data: dict) -> dict:
        try:
            resp = requests.get(
                self.DATA_URL,
                headers={"Authorization": f"{self.fy_id}:{self.token}"},
                params=data,
                timeout=15
            )
            return resp.json()
        except Exception as e:
            return {"s": "error", "message": str(e)}


def _fyers_login() -> FyersDirectClient | None:
    if not all([FYERS_APP_ID, FYERS_SECRET_KEY, FYERS_FY_ID,
                FYERS_PIN, FYERS_TOTP_KEY]):
        log.error("❌ One or more FYERS_* env vars missing — cannot login")
        return None

    try:
        # ── TOTP boundary: wait if close to 30s rollover ──────────
        sec = datetime.now().second % 30
        if sec > 25:
            wait = 31 - sec
            log.info(f"TOTP boundary — waiting {wait}s before starting login")
            time.sleep(wait)

        # ── Step 1: send_login_otp ────────────────────────────────
        log.info("Fyers login — Step 1: send_login_otp")
        r1 = requests.post(
            URL_SEND_OTP,
            json={"fy_id": FYERS_FY_ID, "app_id": "2"},
            timeout=10
        ).json()

        if r1.get("s") == "error" or "request_key" not in r1:
            log.error(f"send_login_otp failed: {r1}")
            return None
        log.info("Step 1 OK")

        # ── Step 2: verify_otp (TOTP) ─────────────────────────────
        log.info("Fyers login — Step 2: verify_otp (TOTP)")
        totp_code = pyotp.TOTP(FYERS_TOTP_KEY).now()
        r2 = requests.post(
            URL_VERIFY_OTP,
            json={"request_key": r1["request_key"], "otp": totp_code},
            timeout=10
        ).json()

        if r2.get("s") == "error" or "request_key" not in r2:
            log.error(f"verify_otp failed: {r2}")
            return None
        log.info("Step 2 OK")

        # ── Step 3: verify_pin → get token with d:1 data scope ───
        log.info("Fyers login — Step 3: verify_pin")
        r3 = requests.post(
            URL_VERIFY_PIN,
            json={
                "request_key":   r2["request_key"],
                "identity_type": "pin",
                "identifier":    FYERS_PIN
            },
            timeout=10
        ).json()

        if r3.get("s") == "error" or "data" not in r3:
            log.error(f"verify_pin failed: {r3}")
            return None

        # This token has aud: ["x:0","x:1","x:2","d:1"] — data scope included
        access_token = r3["data"].get("access_token", "")
        if not access_token:
            log.error(f"No access_token in verify_pin response: {r3}")
            return None

        log.info("Step 3 OK — token with data scope obtained")
        log.info("✅ Fyers login complete — using FyersDirectClient")

        # Return our custom client that uses fy_id:token auth header
        # (NOT CLIENT_ID:token which fyersModel uses and Fyers rejects)
        return FyersDirectClient(fy_id=FYERS_FY_ID, token=access_token)

    except Exception as e:
        log.error(f"Fyers login exception: {e}", exc_info=True)
        return None


def ensure_fyers() -> FyersDirectClient | None:
    global _fyers_instance
    if _fyers_instance is not None:
        return _fyers_instance
    log.info("No active Fyers session — attempting login...")
    _fyers_instance = _fyers_login()
    if _fyers_instance is None:
        send_telegram(
            "❌ <b>KASF — Fyers Login FAILED</b>\n"
            "Could not generate access token.\n"
            "Check FYERS_* env vars in Railway.\n"
            "Scanner will NOT run until login succeeds."
        )
    return _fyers_instance


# ──────────────────────────────────────────────────────────────────
# SECTION G — DATA FETCH (Fyers API)
# ──────────────────────────────────────────────────────────────────
def _epoch_range(days_back: int):
    """
    Return (range_from, range_to) as epoch integer strings.
    Fyers history API requires date_format="0" (epoch mode).
    Using date strings (date_format="1") causes 'ok' response but
    empty candles for intraday resolutions — this was the Errors:332 bug.
    """
    ist   = pytz.timezone("Asia/Kolkata")
    now   = datetime.now(ist)
    start = now - timedelta(days=days_back)
    return str(int(start.timestamp())), str(int(now.timestamp()))


def _fyers_history(fyers, symbol: str, resolution: str, days: int) -> pd.DataFrame | None:
    try:
        from_epoch, to_epoch = _epoch_range(days)
        data = {
            "symbol":      symbol,
            "resolution":  resolution,
            "date_format": "0",
            "range_from":  from_epoch,
            "range_to":    to_epoch,
            "cont_flag":   "1"
        }
        resp = fyers.history(data=data)

        if not resp or resp.get("s") != "ok":
            log.warning(f"Fyers history bad response {symbol}: {resp}")
            return None

        candles = resp.get("candles", [])
        if not candles:
            log.debug(f"Fyers history empty candles {symbol}: resolution={resolution} days={days}")
            return None

        df = pd.DataFrame(
            candles,
            columns=["datetime", "open", "high", "low", "close", "volume"]
        )
        df["datetime"] = pd.to_datetime(df["datetime"], unit="s", utc=True)
        df["datetime"] = df["datetime"].dt.tz_convert("Asia/Kolkata")
        df.set_index("datetime", inplace=True)
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        return df if not df.empty else None

    except Exception as e:
        log.debug(f"Fyers history error {symbol}: {e}")
        return None


def fetch_batch_15m(symbols: list, fyers) -> dict:
    result = {}
    errors_logged = 0
    for sym in symbols:
        df = _fyers_history(fyers, sym, CANDLE_INTERVAL, HISTORY_DAYS_15M)
        if df is not None and len(df) >= 30:
            result[sym] = df
        elif errors_logged < 3:
            log.warning(f"15m fetch failed or thin: {sym} (rows={len(df) if df is not None else 0})")
            errors_logged += 1
        time.sleep(0.12)
    return result


def fetch_batch_daily(symbols: list, fyers) -> dict:
    result = {}
    for sym in symbols:
        df = _fyers_history(fyers, sym, DAILY_INTERVAL, HISTORY_DAYS_D)
        if df is not None and len(df) >= 3:
            result[sym] = df
        time.sleep(0.12)
    return result


def fetch_index_sentiment(fyers) -> str:
    try:
        df = _fyers_history(fyers, FYERS_INDEX, DAILY_INTERVAL, 60)

        if df is None or len(df) < 21:
            rows = len(df) if df is not None else 0
            log.warning(
                f"⚠️ Index data insufficient ({rows} rows) — "
                f"defaulting to BULLISH (was NEUTRAL which blocked signals)"
            )
            return "BULLISH"

        c     = df["close"]
        ema20 = c.ewm(span=20, adjust=False).mean()
        last_close = float(c.iloc[-1])
        last_ema   = float(ema20.iloc[-1])
        sent  = "BULLISH" if last_close > last_ema else "BEARISH"

        log.info(
            f"NIFTY Sentiment: {sent} | "
            f"Close={last_close:.2f} vs EMA20={last_ema:.2f}"
        )
        return sent

    except Exception as e:
        log.warning(f"Index fetch failed: {e} — defaulting BULLISH")
        return "BULLISH"


# ──────────────────────────────────────────────────────────────────
# SECTION H — INDICATORS
# ──────────────────────────────────────────────────────────────────
def calc_ema(s, p):
    return s.ewm(span=p, adjust=False).mean()


def calc_rsi(close, period=14):
    d  = close.diff()
    g  = d.clip(lower=0)
    l  = (-d).clip(lower=0)
    ag = g.ewm(com=period - 1, adjust=False).mean()
    al = l.ewm(com=period - 1, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_vwap(df):
    d         = df.copy()
    d["date"] = d.index.date
    d["hlc3"] = (d["high"] + d["low"] + d["close"]) / 3
    d["pv"]   = d["hlc3"] * d["volume"]
    d["cpv"]  = d.groupby("date")["pv"].cumsum()
    d["cvol"] = d.groupby("date")["volume"].cumsum()
    return d["cpv"] / d["cvol"]


def calc_atr(df, period=14):
    hl  = df["high"] - df["low"]
    hcp = (df["high"] - df["close"].shift()).abs()
    lcp = (df["low"]  - df["close"].shift()).abs()
    tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def calc_pivots(daily_df):
    p       = daily_df.iloc[-2]
    H, L, C = float(p["high"]), float(p["low"]), float(p["close"])
    pvt     = (H + L + C) / 3
    r1      = (2 * pvt) - L
    r2      = pvt + (H - L)
    s1      = (2 * pvt) - H
    return pvt, r1, r2, s1


# ──────────────────────────────────────────────────────────────────
# SECTION I — SIGNAL GENERATION  (with reject-reason logging)
# ──────────────────────────────────────────────────────────────────
def generate_signal(fyers_symbol: str, df_15m: pd.DataFrame,
                    df_daily: pd.DataFrame, index_sentiment: str) -> dict | None:
    display_symbol = fyers_symbol.replace("NSE:", "").replace("-EQ", "")
    try:
        close   = df_15m["close"]
        high    = df_15m["high"]
        volume  = df_15m["volume"]

        ema20     = calc_ema(close, 20)
        ema50     = calc_ema(close, 50)
        rsi       = calc_rsi(close, 14)
        vwap      = calc_vwap(df_15m)
        vol_avg   = volume.rolling(20).mean()
        high_20   = high.shift(1).rolling(20).max()
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
            log.debug(f"  {display_symbol}: SKIP — NaN in indicators")
            return None

        _, r1, r2, s1 = calc_pivots(df_daily)

        # ── Setup Classification ──────────────────────────────────
        breakout    = (c > h20) and (v > vol_a * VOL_MULT)
        is_pullback = (abs(c - s1) / c) < PULL_PCT

        if breakout:       setup_type = "BREAKOUT"
        elif is_pullback:  setup_type = "PULLBACK"
        else:              setup_type = "TREND"

        # ── Stop Loss & Entry ─────────────────────────────────────
        sl1       = s1
        sl2       = c - (daily_atr * ATR_MULT)
        actual_sl = max(sl1, sl2)

        if is_pullback:  entry = s1
        elif breakout:   entry = c
        else:            entry = vwap_val if abs(c - vwap_val) < abs(c - e20) else e20

        entry_gap_pct = max(0.0, ((c - entry) / entry * 100)) if entry > 0 else 0.0

        rr_denom = entry - actual_sl
        if rr_denom <= 0:
            log.debug(f"  {display_symbol}: SKIP — SL >= entry (rr_denom={rr_denom:.4f})")
            return None

        rr = (r1 - entry) / rr_denom

        # ── Filter 1: Trend ───────────────────────────────────────
        if index_sentiment == "BEARISH":
            trend_ok = (c > e20) and (c > vwap_val)
        else:
            trend_ok = (c > e20) and (c > e50)

        # ── Filter 2: RSI ─────────────────────────────────────────
        rsi_ok = RSI_MIN < rsi_val < RSI_MAX

        # ── Filter 3: Volume ──────────────────────────────────────
        if setup_type == "BREAKOUT":
            vol_ok = v > vol_a * VOL_MULT
        elif setup_type == "PULLBACK":
            vol_ok = v > vol_a * 0.6
        else:
            vol_ok = v > vol_a * 1.0

        # ── Filter 4: Setup validity ──────────────────────────────
        setup_ok = breakout or is_pullback or (c > vwap_val) or (c > e20)

        # ── Combine & Log Rejections ──────────────────────────────
        valid = trend_ok and rsi_ok and vol_ok and setup_ok

        if not valid:
            reasons = []
            if not trend_ok:  reasons.append(f"trend(c={c:.2f},e20={e20:.2f},e50={e50:.2f},vwap={vwap_val:.2f})")
            if not rsi_ok:    reasons.append(f"rsi={rsi_val:.1f}(need {RSI_MIN}–{RSI_MAX})")
            if not vol_ok:    reasons.append(f"vol={v:.0f}/avg={vol_a:.0f}({v/vol_a:.2f}x)")
            if not setup_ok:  reasons.append("setup")
            log.debug(f"  {display_symbol}: FILTERED — {' | '.join(reasons)}")
            return None

        if rr < MIN_RR:
            log.debug(f"  {display_symbol}: LOW RR — {rr:.2f} < {MIN_RR} (entry={entry:.2f}, sl={actual_sl:.2f}, r1={r1:.2f})")
            return None

        # ── Build Signal Payload ──────────────────────────────────
        ist_now    = datetime.now(pytz.timezone("Asia/Kolkata"))
        today_str  = ist_now.date()
        today_rows = df_15m[df_15m.index.date == today_str]

        day_open  = float(today_rows["open"].iloc[0]) if not today_rows.empty else c
        day_high  = float(today_rows["high"].max())   if not today_rows.empty else c

        price_vs_open_pct   = round(((c - day_open) / day_open * 100), 2) if day_open > 0 else 0.0
        high_vs_current_pct = round(((c - day_high) / day_high * 100), 2) if day_high > 0 else 0.0

        signal_hour   = ist_now.hour
        signal_minute = ist_now.minute

        daily_vol_avg = float(df_daily["volume"].rolling(20).mean().iloc[-1])
        today_vol     = float(today_rows["volume"].sum()) if not today_rows.empty else v
        daily_rel_vol = round(today_vol / daily_vol_avg, 2) if daily_vol_avg > 0 else 1.0

        daily_rsi_val = round(float(calc_rsi(df_daily["close"], 14).iloc[-1]), 2)

        return {
            "symbol":               display_symbol,
            "market":               "INDIA",
            "entry":                round(entry, 4),
            "current_price":        round(c, 4),
            "entry_gap_pct":        round(entry_gap_pct, 2),
            "t1":                   round(r1, 4),
            "t2":                   round(r2, 4),
            "sl1":                  round(sl1, 4),
            "sl2":                  round(sl2, 4),
            "setup":                setup_type,
            "rr":                   round(rr, 2),
            "index":                index_sentiment,
            "price_vs_open_pct":    price_vs_open_pct,
            "high_vs_current_pct":  high_vs_current_pct,
            "signal_hour":          signal_hour,
            "signal_minute":        signal_minute,
            "daily_rel_vol":        daily_rel_vol,
            "daily_rsi":            daily_rsi_val,
        }

    except Exception as e:
        log.debug(f"Signal error {display_symbol}: {e}")
        return None


# ──────────────────────────────────────────────────────────────────
# SECTION J — POST TO GOOGLE SHEET
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
# SECTION K — ENTRY SCAN
# ──────────────────────────────────────────────────────────────────
def run_entry_scan(slot_label: str, fyers) -> int:
    index_sentiment = fetch_index_sentiment(fyers)

    log.info("=" * 62)
    log.info(f"ENTRY SCAN — {slot_label} | Market: {index_sentiment}")
    log.info(f"Stocks: {len(FYERS_SYMBOLS)} | RR≥{MIN_RR} | RSI {RSI_MIN}–{RSI_MAX} | Vol {VOL_MULT}x")

    if index_sentiment == "BEARISH":
        send_telegram(
            f"⚠️ <b>KASF — {slot_label} Scan</b>\n"
            f"📉 NIFTY is <b>BEARISH</b> today.\n"
            f"Scanning for hidden strength stocks only.\n"
            f"Trade with extra caution. Tighter stops recommended."
        )

    symbols = FYERS_SYMBOLS.copy()
    random.shuffle(symbols)

    signals_found  = 0
    signals_posted = 0
    errors         = 0
    filtered_out   = 0

    for batch_start in range(0, len(symbols), BATCH_SIZE):
        if signals_posted >= MAX_PICKS:
            log.info(f"MAX_PICKS ({MAX_PICKS}) reached — stopping early")
            break

        batch      = symbols[batch_start : batch_start + BATCH_SIZE]
        data_15m   = fetch_batch_15m(batch, fyers)
        data_daily = fetch_batch_daily(batch, fyers)

        for sym in batch:
            if signals_posted >= MAX_PICKS:
                break

            df_15m   = data_15m.get(sym)
            df_daily = data_daily.get(sym)

            if df_15m is None or df_daily is None:
                errors += 1
                continue

            signal = generate_signal(sym, df_15m, df_daily, index_sentiment)

            if signal:
                signals_found += 1
                log.info(
                    f"✅ {signal['symbol']:15s} | {signal['setup']:8s} "
                    f"| R:R={signal['rr']:4.2f} | RSI={signal['daily_rsi']} "
                    f"| ₹{signal['entry']}"
                )
                if post_to_sheet(signal):
                    signals_posted += 1
                    log.info(f"   → Sheet ✓")

                    setup_emoji = "🚀" if signal["setup"] == "BREAKOUT" else "🔄" if signal["setup"] == "PULLBACK" else "📈"
                    send_telegram(
                        f"{setup_emoji} <b>KASF Signal — {signal['symbol']}</b>\n"
                        f"⏰ {slot_label} | {signal['setup']}\n\n"
                        f"📌 Entry:  ₹{signal['entry']}\n"
                        f"🎯 T1:     ₹{signal['t1']}\n"
                        f"🎯 T2:     ₹{signal['t2']}\n"
                        f"🛑 SL:     ₹{signal['sl2']}\n\n"
                        f"📊 R:R = {signal['rr']} | RSI = {signal['daily_rsi']}\n"
                        f"📈 RelVol = {signal['daily_rel_vol']}x\n"
                        f"🌡️ Market: {index_sentiment}\n\n"
                        f"⚠️ <i>Trade with proper risk management.</i>"
                    )
                else:
                    log.warning(f"   → Sheet FAILED ✗")
            else:
                filtered_out += 1

        b = (batch_start // BATCH_SIZE) + 1
        t = (len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE
        log.info(
            f"Batch {b}/{t} | "
            f"Signals: {signals_found} | Posted: {signals_posted} | "
            f"Filtered: {filtered_out} | Errors: {errors}"
        )
        time.sleep(BATCH_DELAY_SEC)

    if signals_posted == 0:
        send_telegram(
            f"ℹ️ <b>KASF — {slot_label}</b>\n"
            f"No signals found matching filters.\n"
            f"Market: {index_sentiment}\n"
            f"Filters: RR≥{MIN_RR} | RSI {RSI_MIN}–{RSI_MAX} | Vol {VOL_MULT}x\n"
            f"Scanned: {len(FYERS_SYMBOLS)} stocks | "
            f"Filtered: {filtered_out} | Data errors: {errors}"
        )

    log.info(
        f"SCAN DONE — Signals: {signals_found} | "
        f"Posted: {signals_posted} | "
        f"Filtered: {filtered_out} | Errors: {errors}"
    )
    log.info("=" * 62)
    return signals_posted


# ──────────────────────────────────────────────────────────────────
# SECTION L — MAIN
# ──────────────────────────────────────────────────────────────────
def main():
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    log.info(f"KASF V5 (Fyers Fixed) — cron fire at {now.strftime('%Y-%m-%d %H:%M:%S IST')}")

    slot_type, slot_label = get_current_slot()

    if slot_type is None:
        log.info(f"No active slot at {now.strftime('%H:%M IST')} — exiting")
        return

    log.info(f"Matched slot: {slot_label} → {slot_type}")

    if slot_type == "TOKEN":
        log.info("TOKEN slot — generating Fyers access token")
        fyers = _fyers_login()
        if fyers:
            global _fyers_instance
            _fyers_instance = fyers
            log.info("✅ Token generated and cached")
            send_telegram(
                "✅ <b>KASF — Fyers Login OK</b>\n"
                "Access token generated at 9:00 AM.\n"
                "Scanner is ready for today."
            )
        else:
            log.error("❌ Token generation failed at 9:00 AM slot")
        return

    if slot_type == "EXIT":
        is_final = (now.hour == 15)
        send_exit_alert(slot_label, is_final)
        log.info("Exit alert sent — exiting")
        return

    if slot_type == "ENTRY":
        fyers = ensure_fyers()
        if fyers is None:
            log.error("No Fyers session available — aborting scan")
            return
        run_entry_scan(slot_label, fyers)
        log.info("Entry scan complete — exiting")


if __name__ == "__main__":
    main()
