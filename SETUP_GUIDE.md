# KASF V5 NSE Scanner — Setup Guide
# TradingView Replacement (100% Free)

## What This Does
Replaces TradingView completely. Python fetches live NSE data free via
yfinance, runs the same KASF logic from your Pine Script, and posts
signals to your existing Google Sheet. Your Google Script + Telegram
setup stays exactly the same — zero changes needed there.

## Flow
```
yfinance (free NSE data)
    ↓
kasf_v5_nse.py (KASF logic — EMA, RSI, VWAP, Pivots, R:R)
    ↓
POST JSON to Google Sheet Webhook  ← same URL TradingView used
    ↓
Google Script (unchanged) → Gemini analysis → Telegram
```

---

## Step 1 — Install Python Requirements

```bash
pip install -r requirements.txt
```

Or one-liner:
```bash
pip install yfinance pandas numpy requests pytz
```

---

## Step 2 — Set Your Webhook URL

Open `kasf_v5_nse.py`, find Section A, replace:
```python
GOOGLE_SHEET_WEBHOOK = "https://script.google.com/macros/s/YOUR_DEPLOYMENT_ID/exec"
```

With your actual Google Script Web App URL (the same one TradingView was posting to).
Find it in Google Script → Deploy → Manage Deployments → Copy Web App URL.

---

## Step 3 — Test First (Important!)

```bash
python test_kasf.py
```

This tests 5 stocks and shows you exactly what data is fetched and
whether signals fire. Run this before starting the full scanner.

---

## Step 4 — Run the Scanner

```bash
python kasf_v5_nse.py
```

The scanner will:
- Wait until market is open (9:15 AM IST, Mon–Fri)
- Scan during the same time windows as Pine Script (Prime/Continue/Close)
- Post signals to your Google Sheet
- Sleep 15 minutes and repeat
- Stop scanning after market close (3:15 PM IST)

---

## Hosting Options (run it 24/7 without your PC)

### Option A — Free: Railway.app
1. Create account at railway.app
2. New Project → Deploy from GitHub (upload these files)
3. Set Start Command: `python kasf_v5_nse.py`
4. Free tier: 500 hours/month (enough for market hours only)

### Option B — Free: Render.com
1. Create account at render.com
2. New → Background Worker
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `python kasf_v5_nse.py`

### Option C — ₹0: Your PC or Raspberry Pi
Just run `python kasf_v5_nse.py` in a terminal during market hours.
Use a simple bat file or cron job to auto-start at 9 AM.

### Option D — ₹200/month: DigitalOcean Droplet (smallest)
Most reliable. SSH in, run as a background service.

---

## What Changed vs TradingView

| Feature          | TradingView         | This Python Scanner     |
|------------------|---------------------|-------------------------|
| Cost             | ₹6,000+/month       | Free                    |
| Stocks scanned   | Your watchlist only | All 500 NIFTY stocks    |
| Data source      | TradingView servers | Yahoo Finance (free)    |
| Alert creation   | Manual per symbol   | Automatic               |
| KASF logic       | Pine Script         | Exact Python copy       |
| Google Sheet     | TradingView posts   | Python posts (same URL) |
| Telegram alerts  | Same                | Same (unchanged)        |
| Gemini analysis  | Same                | Same (unchanged)        |

---

## Adjusting Filters

All filters are in Section A of `kasf_v5_nse.py`:

```python
ATR_MULT  = 1.5   # wider = wider stops
MIN_RR    = 1.5   # higher = only higher quality setups
RSI_MIN   = 40    # lower = allows more oversold entries
RSI_MAX   = 74    # matches Pine Script India value
VOL_MULT  = 2.0   # matches Pine Script India value (2x volume surge)
PULL_PCT  = 0.003 # 0.3% pullback from S1 (India Pine Script value)
MAX_PICKS = 4     # max signals per scan (matches Google Script)
```

---

## Logs

The scanner writes to `kasf_scanner.log` in the same folder.
Check it to see what's happening:

```bash
tail -f kasf_scanner.log
```

---

## Troubleshooting

**"No data returned for stock"**
→ Normal for some small-cap stocks. yfinance occasionally has gaps.
→ The scanner skips and moves on automatically.

**"Webhook post failed"**
→ Check your GOOGLE_SHEET_WEBHOOK URL is correct and deployed as "Anyone" access.

**"No signals found"**
→ Outside market hours the volume filter will block most signals (normal).
→ Run during 9:15 AM – 3:15 PM IST on a weekday.

**Slow scanning**
→ Scanning 500 stocks with 0.3s delay ≈ 2.5 minutes per full scan.
→ This is intentional to avoid rate limiting by Yahoo Finance.
→ The scanner stops at MAX_PICKS anyway so usually finishes faster.
