"""
Real-Time Stock Market Data Processor — India Edition
=======================================================
Fetches live stock prices via yfinance library,
converts to INR using live forex rates, cleans with Pandas,
and outputs structured CSV + JSON reports.

Usage:
  pip install -r requirements.txt
  python data_processor.py
"""

import yfinance as yf
import requests
import pandas as pd
import json
import time
import os
from datetime import datetime, timezone, timedelta

OUTPUT_DIR = "outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

# IST = UTC + 5:30
IST = timezone(timedelta(hours=5, minutes=30))

STOCKS = {
    "Tata Motors":   "TATAMOTORS.NS",
    "TCS":           "TCS.NS",
    "Tata Steel":    "TATASTEEL.NS",
    "Reliance":      "RELIANCE.NS",
    "Infosys":       "INFY.NS",
    "HDFC Bank":     "HDFCBANK.NS",
    "Wipro":         "WIPRO.NS",
    "Bajaj Finance": "BAJFINANCE.NS",
    "ONGC":          "ONGC.NS",
    "ITC":           "ITC.NS",
    "Apple":         "AAPL",
    "Microsoft":     "MSFT",
    "Tesla":         "TSLA",
    "Alphabet":      "GOOGL",
    "Meta":          "META",
    "Amazon":        "AMZN",
    "NVIDIA":        "NVDA",
    "Samsung":       "005930.KS",
}

PRIVATE_NOTES = {
    "SpaceX": (
        "Private company — not listed on any public exchange. "
        "Last known valuation: ~$350 Billion USD (~Rs.29,20,000 Crore)"
    )
}


def fetch_inr_rates() -> dict:
    """Fetch live exchange rates. Returns INR per 1 unit of foreign currency."""
    print("[INFO] Fetching live exchange rates...")
    url = "https://open.er-api.com/v6/latest/INR"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("result") != "success":
            raise ValueError(f"API returned non-success: {data.get('result')}")
        rates = data.get("rates", {})
        # rates["USD"] = how many USD per 1 INR (e.g. ~0.0118)
        # So 1/rates["USD"] = INR per 1 USD (e.g. ~84.7)
        inr_per = {
            "USD": 1.0 / rates["USD"],
            "KRW": 1.0 / rates["KRW"],
            "EUR": 1.0 / rates["EUR"],
            "INR": 1.0,
        }
        print(f"  OK  1 USD = Rs.{inr_per['USD']:.2f}  |  1 KRW = Rs.{inr_per['KRW']:.4f}  |  1 EUR = Rs.{inr_per['EUR']:.2f}")
        return inr_per
    except Exception as e:
        print(f"  WARN  Forex API error: {e}. Using fallback rates.")
        return {"USD": 84.5, "KRW": 0.063, "EUR": 91.2, "INR": 1.0}


def get_ticker_info(ticker: str) -> dict:
    """Fetch price and statistics for a single ticker. Returns {} on failure."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5d", interval="1d")
        if hist.empty:
            print(f"  WARN  No history data for {ticker}")
            return {}

        latest = hist.iloc[-1]
        # Safely get previous close — fall back to latest if only 1 row available
        prev = hist.iloc[-2] if len(hist) >= 2 else hist.iloc[-1]

        price      = float(latest["Close"])
        prev_close = float(prev["Close"])
        change     = price - prev_close
        change_pct = (change / prev_close * 100) if prev_close != 0 else 0.0
        high       = float(latest["High"])
        low        = float(latest["Low"])
        volume     = int(latest["Volume"])

        hist52    = t.history(period="1y", interval="1d")
        wk52_high = float(hist52["High"].max()) if not hist52.empty else price
        wk52_low  = float(hist52["Low"].min())  if not hist52.empty else price

        try:
            mkt_cap  = t.fast_info.market_cap or 0
            currency = (t.fast_info.currency or "USD").upper()
        except Exception:
            mkt_cap  = 0
            currency = "USD"

        return {
            "price": price, "prev_close": prev_close, "change": change,
            "change_pct": change_pct, "high": high, "low": low,
            "volume": volume, "wk52_high": wk52_high, "wk52_low": wk52_low,
            "market_cap": mkt_cap, "currency": currency,
        }
    except Exception as e:
        print(f"  WARN  Could not fetch {ticker}: {e}")
        return {}


def build_stock_df(stock_map: dict, inr_rates: dict) -> pd.DataFrame:
    """Fetch all stocks and return a cleaned DataFrame with INR prices."""
    print("[INFO] Fetching stock quotes via yfinance...")
    rows = []
    for company, ticker in stock_map.items():
        print(f"  Fetching {company} ({ticker})...")
        q = get_ticker_info(ticker)
        if not q:
            continue

        currency = q.get("currency", "USD")
        # Fall back to USD rate if currency not in our table
        rate = inr_rates.get(currency, inr_rates["USD"])
        is_indian = ticker.endswith(".NS") or ticker.endswith(".BO")

        rows.append({
            "company":           company,
            "ticker":            ticker,
            "exchange_currency": currency,
            "price_inr":         round(q["price"] * rate, 2),
            "price_orig":        round(q["price"], 2),
            "change_inr":        round(q["change"] * rate, 2),
            "change_pct":        round(q["change_pct"], 2),
            "high_inr":          round(q["high"] * rate, 2),
            "low_inr":           round(q["low"] * rate, 2),
            "prev_close_inr":    round(q["prev_close"] * rate, 2),
            "week52_high_inr":   round(q["wk52_high"] * rate, 2),
            "week52_low_inr":    round(q["wk52_low"] * rate, 2),
            "market_cap_inr_cr": round(q["market_cap"] * rate / 1e7, 2),
            "volume":            q["volume"],
            "inr_rate_used":     rate,
            "category":          "Indian" if is_indian else "Global",
            # Use IST timestamps (relevant for Indian users)
            "fetched_at_ist":    datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Derived columns
    df["spread_inr"] = (df["high_inr"] - df["low_inr"]).round(2)
    df["from_52w_high_pct"] = (
        (df["price_inr"] - df["week52_high_inr"]) /
        df["week52_high_inr"].replace(0.0, float("nan")) * 100
    ).round(2)
    df["sentiment"] = df["change_pct"].apply(
        lambda x: "Bullish" if x > 1 else ("Bearish" if x < -1 else "Neutral")
    )

    # Sort: Indian first (alphabetically 'Global' > 'Indian' so we flip),
    # then by market cap descending within each group
    df.sort_values(
        ["category", "market_cap_inr_cr"],
        ascending=[False, False],   # False on category puts 'Indian' before 'Global'
        inplace=True,
    )
    df.reset_index(drop=True, inplace=True)
    print(f"  OK  {len(df)} stocks fetched and cleaned.")
    return df


def analyse(df: pd.DataFrame) -> dict:
    """Compute market-level summary statistics from the stock DataFrame."""
    if df.empty:
        return {}

    indian  = df[df["category"] == "Indian"]
    global_ = df[df["category"] == "Global"]

    # Guard against empty subsets for idxmax/idxmin
    top_gainer_row  = df.loc[df["change_pct"].idxmax()]
    top_loser_row   = df.loc[df["change_pct"].idxmin()]
    largest_cap_row = df.loc[df["market_cap_inr_cr"].idxmax()]

    return {
        "generated_at_ist":  datetime.now(IST).isoformat(),
        "total_stocks":      len(df),
        "indian_stocks":     len(indian),
        "global_stocks":     len(global_),
        "avg_change_pct":    round(float(df["change_pct"].mean()), 2),
        "top_gainer":        {"company": top_gainer_row["company"],  "change_pct": round(float(top_gainer_row["change_pct"]), 2)},
        "top_loser":         {"company": top_loser_row["company"],   "change_pct": round(float(top_loser_row["change_pct"]), 2)},
        "largest_by_mcap":   {"company": largest_cap_row["company"], "market_cap_inr_cr": round(float(largest_cap_row["market_cap_inr_cr"]), 2)},
        "bullish_count":     int((df["sentiment"] == "Bullish").sum()),
        "bearish_count":     int((df["sentiment"] == "Bearish").sum()),
        "neutral_count":     int((df["sentiment"] == "Neutral").sum()),
        "private_notes":     PRIVATE_NOTES,
        "all_stocks": df[[
            "company", "ticker", "price_inr", "change_pct",
            "market_cap_inr_cr", "sentiment", "category",
        ]].to_dict("records"),
    }


def print_banner():
    now_ist = datetime.now(IST)
    print("\n" + "=" * 70)
    print("  STOCK MARKET DATA PROCESSOR  |  India Edition  |  Prices in INR")
    print(f"  {now_ist.strftime('%Y-%m-%d %H:%M:%S')} IST")
    print("=" * 70)


def print_table(df: pd.DataFrame, category: str):
    sub = df[df["category"] == category]
    if sub.empty:
        return
    label = "INDIAN STOCKS  (NSE)" if category == "Indian" else "GLOBAL STOCKS  (converted to INR)"
    print(f"\n  {label}")
    print("-" * 82)
    print(f"  {'Company':<16} {'Price (Rs.)':>13} {'Change (Rs.)':>13} {'Change%':>8} {'Mkt Cap Cr':>14}  Signal")
    print("-" * 82)
    for _, r in sub.iterrows():
        sign = "+" if r["change_inr"] >= 0 else "-"
        print(
            f"  {r['company']:<16}"
            f"  Rs.{r['price_inr']:>10,.2f}"
            f"  {sign}Rs.{abs(r['change_inr']):>8,.2f}"
            f"  {r['change_pct']:>+7.2f}%"
            f"  Rs.{r['market_cap_inr_cr']:>11,.0f} Cr"
            f"  {r['sentiment']}"
        )


def print_summary(a: dict, inr_rates: dict):
    print(f"\n{'=' * 70}")
    print("  MARKET SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Live Rate    : 1 USD = Rs.{inr_rates['USD']:.2f}  |  1 EUR = Rs.{inr_rates['EUR']:.2f}  |  1 KRW = Rs.{inr_rates['KRW']:.4f}")
    print(f"  Tracked      : {a['total_stocks']} stocks ({a['indian_stocks']} Indian + {a['global_stocks']} Global)")
    print(f"  Avg Change   : {a['avg_change_pct']:+.2f}%")
    g = a["top_gainer"]
    l = a["top_loser"]
    m = a["largest_by_mcap"]
    print(f"  Top Gainer   : {g['company']} ({g['change_pct']:+.2f}%)")
    print(f"  Top Loser    : {l['company']} ({l['change_pct']:+.2f}%)")
    print(f"  Largest MCap : {m['company']} (Rs.{m['market_cap_inr_cr']:,.0f} Cr)")
    print(f"  Bullish: {a['bullish_count']}   Bearish: {a['bearish_count']}   Neutral: {a['neutral_count']}")
    for name, note in PRIVATE_NOTES.items():
        print(f"\n  NOTE — {name}: {note}")


def save(df: pd.DataFrame, analysis: dict):
    """Save timestamped + always-latest CSV and JSON outputs."""
    ts = datetime.now(IST).strftime("%Y%m%d_%H%M%S")

    # Timestamped snapshots
    csv_ts   = os.path.join(OUTPUT_DIR, f"stocks_{ts}.csv")
    json_ts  = os.path.join(OUTPUT_DIR, f"report_{ts}.json")
    # Always-latest files (overwritten each run)
    csv_lat  = os.path.join(OUTPUT_DIR, "stocks_latest.csv")
    json_lat = os.path.join(OUTPUT_DIR, "report_latest.json")

    df.to_csv(csv_ts,  index=False)
    df.to_csv(csv_lat, index=False)

    for path in [json_ts, json_lat]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(analysis, f, indent=2, default=str)

    print(f"\n  Saved : {csv_ts}")
    print(f"  Saved : {json_ts}")
    print(f"  Latest: {csv_lat}  +  {json_lat}")


def run():
    print_banner()
    inr_rates = fetch_inr_rates()
    time.sleep(0.5)

    df = build_stock_df(STOCKS, inr_rates)
    if df.empty:
        print("\nERROR: No data fetched. Check your internet connection and try again.")
        return

    print_table(df, "Indian")
    print_table(df, "Global")

    analysis = analyse(df)
    print_summary(analysis, inr_rates)
    save(df, analysis)

    print("\n  Done!")
    print("  Run 'python server.py' then open http://localhost:5000 for the dashboard.\n")


if __name__ == "__main__":
    run()
