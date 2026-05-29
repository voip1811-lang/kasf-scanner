"""
KASF — Quick Test Script
Run this FIRST to verify everything works before starting the full scanner.
Tests: data fetch, indicator calc, signal logic — on 5 stocks.

Usage: python test_kasf.py
"""

import sys
sys.path.insert(0, ".")
from kasf_v5_nse import (
    fetch_ohlcv, fetch_daily_ohlcv, fetch_index_sentiment,
    generate_signal, is_market_open, is_scheduled_time,
    GOOGLE_SHEET_WEBHOOK
)
from datetime import datetime
import pytz

TEST_STOCKS = ["RELIANCE", "HDFCBANK", "INFY", "TCS", "ICICIBANK"]

print("=" * 55)
print("KASF V5 NSE — Pre-Flight Test")
print("=" * 55)

# 1. Config check
print("\n[1] CONFIG CHECK")
if "YOUR_DEPLOYMENT_ID" in GOOGLE_SHEET_WEBHOOK:
    print("   ⚠️  GOOGLE_SHEET_WEBHOOK not set yet!")
    print("      Open kasf_v5_nse.py → Section A → set your webhook URL")
else:
    print(f"   ✅ Webhook: {GOOGLE_SHEET_WEBHOOK[:60]}...")

# 2. Market hours check
ist = pytz.timezone("Asia/Kolkata")
now = datetime.now(ist)
print(f"\n[2] MARKET HOURS CHECK")
print(f"   Current IST time : {now.strftime('%A %H:%M')}")
print(f"   Market open      : {is_market_open()}")
print(f"   In scan window   : {is_scheduled_time(now)}")

# 3. Index sentiment
print("\n[3] NIFTY INDEX SENTIMENT")
try:
    sentiment = fetch_index_sentiment()
    print(f"   ✅ Sentiment: {sentiment}")
except Exception as e:
    print(f"   ❌ Failed: {e}")

# 4. Data fetch + signal test
print(f"\n[4] DATA + SIGNAL TEST ({len(TEST_STOCKS)} stocks)")
signals_found = 0

for sym in TEST_STOCKS:
    ticker = sym + ".NS"
    print(f"\n   Testing {sym}...")

    df_15m   = fetch_ohlcv(ticker)
    df_daily = fetch_daily_ohlcv(ticker)

    if df_15m is None:
        print(f"      ❌ 15m data fetch failed")
        continue
    if df_daily is None:
        print(f"      ❌ Daily data fetch failed")
        continue

    print(f"      ✅ 15m bars: {len(df_15m)} | Daily bars: {len(df_daily)}")
    print(f"         Latest close: ₹{df_15m['close'].iloc[-1]:.2f}")
    print(f"         Latest volume: {df_15m['volume'].iloc[-1]:,.0f}")

    signal = generate_signal(sym, df_15m, df_daily)
    if signal:
        signals_found += 1
        print(f"      🚨 SIGNAL FOUND!")
        print(f"         Setup  : {signal['setup']}")
        print(f"         Entry  : ₹{signal['entry']}")
        print(f"         T1     : ₹{signal['t1']}")
        print(f"         T2     : ₹{signal['t2']}")
        print(f"         SL1    : ₹{signal['sl1']}")
        print(f"         SL2    : ₹{signal['sl2']}")
        print(f"         R:R    : {signal['rr']}")
    else:
        print(f"      ○ No signal (filters not met — normal outside market hours)")

print("\n" + "=" * 55)
print(f"TEST COMPLETE")
print(f"Signals found in test: {signals_found}/{len(TEST_STOCKS)}")
print("\nIf data fetched correctly → you're ready to run the full scanner:")
print("   python kasf_v5_nse.py")
print("=" * 55)
