# Stock Data Automation Tool

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Kite Connect 5.0](https://img.shields.io/badge/API-Kite_Connect_5.0-orange.svg)](https://kite.trade/)
[![Google Sheets API](https://img.shields.io/badge/Integration-Google_Sheets-brightgreen.svg)](https://developers.google.com/sheets/api)

A modular, production-grade financial market data automation pipeline that interfaces with the **Zerodha Kite Connect API** and **Google Sheets API**. The tool automates multi-year historical data retrieval for equities, benchmark indices, and derivatives (Futures), computes mathematically rigorous technical indicators (RSI) across dynamic trading-day sessions, and exports clean, formatted analytical datasets to Excel and CSV.

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [How It Works](#how-it-works)
  - [1. RSI Historical Analysis Pipeline](#1-rsi-historical-analysis-pipeline)
  - [2. Raw Expiry-Week Market Data Pipeline](#2-raw-expiry-week-market-data-pipeline)
  - [3. Dynamic Weekly Expiry Day Resolution](#3-dynamic-weekly-expiry-day-resolution)
- [Project Structure](#project-structure)
- [Technologies Used](#technologies-used)
- [Prerequisites & Setup](#prerequisites--setup)
  - [1. Environment Setup](#1-environment-setup)
  - [2. Kite Connect API Credentials](#2-kite-connect-api-credentials)
  - [3. Google Sheets & Service Account Setup](#3-google-sheets--service-account-setup)
  - [4. Environment Variables Configuration](#4-environment-variables-configuration)
- [Usage & CLI Options](#usage--cli-options)
  - [Running the Default RSI Pipeline](#running-the-default-rsi-pipeline)
  - [Running with CLI Stock Overrides](#running-with-cli-stock-overrides)
  - [Running the Raw Expiry-Week Export](#running-the-raw-expiry-week-export)
- [Output Format & Data Schema](#output-format--data-schema)
- [Security Best Practices](#security-best-practices)
- [Troubleshooting & FAQ](#troubleshooting--faq)

---

## Overview

Quantitative analysis and backtesting often require synchronized historical intraday data across dozens of symbols, specific trading sessions, and historical exchange rule changes. Manual collection is tedious, error-prone, and constrained by API rate limits and exchange holiday calendars.

This project solves these challenges with an end-to-end automated pipeline:
- **Cloud-Synced Universe:** Dynamically reads target equity symbols from a cloud-hosted Google Sheet, allowing traders and researchers to update the target watchlist without modifying code.
- **Session-Aware Ingestion:** Automatically downloads historical 1-minute intraday candles from Zerodha Kite Connect, handling instrument token resolution, rate-limiting, exponential backoff, and market holiday fallbacks.
- **Accurate Mathematical Indicators:** Calculates RSI(14) and RSI(10) across complete market sessions using Welles Wilder's exact smoothing formulation (avoiding cut-off errors common in truncated window calculations).
- **Exchange Rule Adaptation:** Dynamically applies NSE weekly expiry schedule changes (transitioning from Thursdays to Tuesdays) without hardcoded dates.
- **Standardized Multi-Format Output:** Generates structured multi-column Excel workbooks for snapshot analytics and consolidated CSV datasets for machine learning or statistical backtesting.

---

## Key Features

- **Dual Operational Modes:**
  - **`rsi` Mode (Default):** Fetches watchlists from Google Sheets, retrieves 3 years of weekly intraday minute data from Kite Connect, computes Wilder's RSI(14) and RSI(10), and produces an aligned 65-column Excel report.
  - **`raw-export` Mode:** Consolidates raw 1-minute OHLC market data for key market benchmarks and derivatives (`NIFTY 50`, `NIFTY BANK`, `NIFTY Futures`, and `INDIA VIX`) across Monday and weekly expiry sessions.
- **Google Sheets Cloud Integration:** Seamless authentication using Google Service Accounts via `gspread` and `google-auth` to consume watchlist data in real time.
- **Robust API Resilience:**
  - On-disk caching of instrument tokens (`instrument_cache.json`) with a 24-hour TTL, saving bandwidth and startup time.
  - Rate-limit enforcement ensuring requests adhere to Zerodha's ~3 req/sec threshold.
  - Exponential backoff with configurable retry limits for transient networking glitches.
- **Fault-Tolerant Processing:** A failure in an individual stock or missing trading session writes explicit `N/A` placeholders rather than crashing the execution batch, ensuring data alignment across all columns.
- **Strict Separation of Secrets:** All API credentials, tokens, and sheet keys are managed via environment variables with `.env` support.

---

## System Architecture

```
                  ┌───────────────────────────────┐
                  │         Google Sheet          │
                  │   (Target Stocks in Col A)    │
                  └───────────────┬───────────────┘
                                  │ (gspread)
                                  ▼
                     ┌─────────────────────────┐
                     │    google_sheets.py     │
                     └────────────┬────────────┘
                                  │ Stock Symbols
                                  ▼
┌──────────────────────┐     ┌─────────┐     ┌──────────────────────┐
│  Zerodha Kite API    │◄───►│ main.py │◄───►│   kite_helper.py     │
│  (Historical Candles)│     └────┬────┘     │  (Cache & Throttler) │
└──────────────────────┘          │          └──────────────────────┘
                                  ▼
                     ┌─────────────────────────┐
                     │   historical_data.py    │
                     │ (Dynamic Expiry Switch) │
                     └────────────┬────────────┘
                                  │ Intraday Candles
                                  ▼
                     ┌─────────────────────────┐
                     │      indicators.py      │
                     │  (Wilder's RSI 14 & 10) │
                     └────────────┬────────────┘
                                  │
                  ┌───────────────┴───────────────┐
                  ▼                               ▼
       [--mode rsi]                     [--mode raw-export]
┌─────────────────────────┐         ┌─────────────────────────┐
│     excel_writer.py     │         │   historical_data.py    │
│  (Multi-column Matrix)  │         │   (Consolidated CSV)    │
└────────────┬────────────┘         └────────────┬────────────┘
             ▼                                   ▼
    rsi_output.xlsx               raw_data/all_expiry_weeks_data.csv
```

---

## How It Works

### 1. RSI Historical Analysis Pipeline

1. **Watchlist Ingestion:** `google_sheets.py` queries column A of the configured Google Spreadsheet (e.g. `nifty`) and extracts valid trading symbols.
2. **Instrument Mapping:** `kite_helper.py` checks the local instrument cache (`instrument_cache.json`). If expired (>24h) or missing, it retrieves the master NSE instrument list and maps trading symbols to Kite instrument tokens.
3. **Session Retrieval:** `historical_data.py` generates weekly target dates for the configured historical window (default 3 years). For each date, it fetches full 09:15-15:30 intraday minute candles.
4. **Indicator Computation:** `indicators.py` runs Wilder's smoothing algorithm across the complete day's close series to establish valid running averages.
5. **Window Snapshot & Export:** `excel_writer.py` extracts the snapshot window (default: 14:55 to 15:15, 21 minutes) and writes a 65-column formatted row per (stock, week) to `rsi_output.xlsx`.

### 2. Raw Expiry-Week Market Data Pipeline

1. Resolves Monday sessions (09:15-15:30) and weekly expiry sessions (09:15-15:15) across all target weeks.
2. Concurrently maps tokens for spot indices (`NIFTY 50`, `NIFTY BANK`), nearest `NIFTY` Futures contract (`NFO`), and `INDIA VIX`.
3. Merges the timestamps and exports clean OHLC minute bars to `raw_data/all_expiry_weeks_data.csv`.

### 3. Dynamic Weekly Expiry Day Resolution

The National Stock Exchange of India (NSE) switched derivative weekly expiries from **Thursday** to **Tuesday** (effective September 2025). The tool mirrors this transition algorithmically:

```python
# config.py
WEEKLY_EXPIRY_CHANGE_DATE = date(2025, 9, 1)
OLD_WEEKLY_DAY = "THURSDAY"
NEW_WEEKLY_DAY = "TUESDAY"
```

- **Weeks starting before switch date:** Samples Thursday.
- **Weeks starting on/after switch date:** Samples Tuesday.
- **Holiday Fallback:** If Kite returns 0 candles (trading holiday), the tool automatically steps back one calendar day at a time (skipping weekends) until a valid session is resolved.

---

## Project Structure

```
Stock-Data-Automation-Tool/
│
├── config.py                 # Central configuration loaded from environment variables
├── main.py                   # Unified CLI entry point supporting multiple pipeline modes
├── google_sheets.py          # Google Sheets integration wrapper (gspread & google-auth)
├── kite_helper.py            # Zerodha Kite Connect client wrapper with cache & throttling
├── historical_data.py        # Date calculation, holiday fallbacks, & candle retrieval
├── indicators.py             # Pure NumPy/Pandas implementation of Wilder's RSI(14) & RSI(10)
├── excel_writer.py           # openpyxl workbook generator with snapshot matrix layout
├── logger.py                 # Dual stream/file logging utility with timer benchmarks
├── utils.py                  # Date arithmetic, weekday resolvers, and safe numeric parsing
│
├── futures.py                # Auxiliary helper: Nearest-month futures lookup & batch quoting
├── option_chain.py           # Auxiliary helper: Option chain strike mapper (ATM/OTM/ITM)
├── nfo_downloader.py         # Auxiliary helper: Daily NFO master instruments manager
├── historical_analysis.py    # Auxiliary helper: 3-year weekly statistical analytics
├── analytics_cache.py        # Auxiliary helper: JSON cache manager for historical analytics
├── token_manager.py          # Auxiliary helper: Kite Connect session & access token helper
├── validators.py             # Auxiliary helper: Startup validation & health check suite
│
├── requirements.txt          # Production dependencies
├── .env.example              # Environment variable template with documentation
├── .gitignore                # Git ignore rules for security, logs, caches, and datasets
└── README.md                 # Complete project documentation
```

---

## Technologies Used

- **Language:** Python 3.10+
- **Trading & Market API:** [Zerodha Kite Connect Python SDK](https://github.com/zerodha/pykiteconnect) (`kiteconnect`)
- **Cloud Storage & Google APIs:** [gspread](https://github.com/burnash/gspread), [google-auth](https://github.com/googleapis/google-auth-library-python)
- **Data Manipulation & Mathematics:** [pandas](https://pandas.pydata.org/), [NumPy](https://numpy.org/)
- **Excel Spreadsheet Formatting:** [openpyxl](https://openpyxl.readthedocs.io/)
- **Configuration & Environment:** [python-dotenv](https://github.com/theskumar/python-dotenv)

---

## Prerequisites & Setup

### 1. Environment Setup

Clone this repository and create an isolated Python virtual environment:

```bash
# Clone the repository
git clone https://github.com/your-username/Stock-Data-Automation-Tool.git
cd Stock-Data-Automation-Tool

# Create and activate virtual environment
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate

# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

### 2. Kite Connect API Credentials

1. Register a developer account at [Zerodha Kite Developer Console](https://developers.kite.trade/apps).
2. Create a new Kite Connect app to obtain your **API Key** and **API Secret**.
3. Generate your daily **Access Token**:
   - Access tokens in Kite Connect expire every 24 hours.
   - Open the login URL in your browser:
     ```
     https://kite.zerodha.com/connect/login?v=3&api_key=YOUR_API_KEY
     ```
   - Log in and authorize the app. You will be redirected to your registered Redirect URL containing a `request_token` parameter:
     ```
     https://127.0.0.1/?request_token=YOUR_REQUEST_TOKEN&action=login
     ```
   - Exchange the `request_token` for an `access_token` using Python:
     ```python
     from kiteconnect import KiteConnect

     kite = KiteConnect(api_key="YOUR_API_KEY")
     session = kite.generate_session("YOUR_REQUEST_TOKEN", api_secret="YOUR_API_SECRET")
     print("Access Token:", session["access_token"])
     ```

### 3. Google Sheets & Service Account Setup

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project and navigate to **APIs & Services -> Library**.
3. Enable **Google Sheets API** and **Google Drive API**.
4. Go to **IAM & Admin -> Service Accounts**, click **Create Service Account**, and grant it a descriptive name.
5. In the **Keys** tab of the newly created Service Account, click **Add Key -> Create new key -> JSON**.
6. Save the downloaded file as `service_account.json` in your project root.
7. Open the JSON file, copy the `client_email` address, and **share your target Google Spreadsheet with this email** (Viewer or Editor permission).
8. Ensure column A of your spreadsheet contains the stock ticker symbols (e.g. `RELIANCE`, `INFY`, `TCS`).

### 4. Environment Variables Configuration

Copy the sample environment file:

```bash
cp .env.example .env     # Windows PowerShell: Copy-Item .env.example .env
```

Open `.env` and configure your credentials:

```ini
KITE_API_KEY="your_actual_kite_api_key"
KITE_API_SECRET="your_actual_kite_api_secret"
KITE_ACCESS_TOKEN="your_generated_daily_access_token"

GOOGLE_SERVICE_ACCOUNT_JSON="service_account.json"
SPREADSHEET_NAME="nifty"
WORKSHEET_NAME=""

OUTPUT_EXCEL="rsi_output.xlsx"
RAW_DATA_OUTPUT_DIR="raw_data"
LOG_FILE="app.log"
LOG_LEVEL="INFO"
```

---

## Usage & CLI Options

### Running the Default RSI Pipeline

Reads stock symbols from the configured Google Sheet, computes RSI over 3 years of weekly sessions, and exports `rsi_output.xlsx`:

```bash
python main.py
# or explicitly:
python main.py --mode rsi
```

### Running with CLI Stock Overrides

Test specific stock symbols directly without querying Google Sheets:

```bash
python main.py --mode rsi --stocks INFY TCS RELIANCE
```

### Running the Raw Expiry-Week Export

Downloads consolidated 1-minute OHLC data for `NIFTY 50`, `NIFTY BANK`, `NIFTY Futures`, and `INDIA VIX` across Monday and Expiry sessions:

```bash
python main.py --mode raw-export
```

### Displaying Command-Line Help

```bash
python main.py --help
```

---

## Output Format & Data Schema

### 1. Excel Output (`rsi_output.xlsx`)

The generated workbook contains a single worksheet named **`RSI Data`** formatted with 65 structured columns:

| Column Number | Column Header | Description |
|---|---|---|
| 1 | `Stock` | Trading symbol (e.g. `INFY`, `RELIANCE`) |
| 2 | `Date` | Actual trading date sampled (YYYY-MM-DD) |
| 3 - 65 | `2:55 Spot`, `2:55 RSI14`, `2:55 RSI10`, ... `3:15 Spot`, `3:15 RSI14`, `3:15 RSI10` | 21 minute-by-minute triples spanning 14:55 to 15:15 |

*Missing candles or holiday sessions preserve column alignment with explicit `N/A` entries.*

### 2. Consolidated CSV Output (`raw_data/all_expiry_weeks_data.csv`)

| Column Header | Type | Description |
|---|---|---|
| `Expiry_Week` | String (Date) | Target expiry week identifier (YYYY-MM-DD) |
| `Trading_Day` | String | Session category: `Monday` or `Expiry` |
| `Date` | String (Date) | Date of candle bar (YYYY-MM-DD) |
| `Time` | String (Time) | Intraday candle minute (HH:MM) |
| `NIFTY_Open`, `NIFTY_High`, `NIFTY_Low`, `NIFTY_Close` | Float | Spot NIFTY 50 OHLC bars |
| `BANKNIFTY_Open` ... `BANKNIFTY_Close` | Float | Spot NIFTY BANK OHLC bars |
| `NIFTY_FUT_Open` ... `NIFTY_FUT_Close` | Float | NIFTY Index Futures OHLC bars |
| `INDIA_VIX_Open` ... `INDIA_VIX_Close` | Float | INDIA VIX Volatility Index bars |

---

## Security Best Practices

- **Never Commit Secrets:** Real API keys, API secrets, access tokens, and Google Service Account credentials (`service_account.json`) must never be committed to Git.
- **Git Tracking Exclusions:** All sensitive credentials, output spreadsheets, downloaded raw CSVs, cache files, and logs are excluded by `.gitignore`.
- **Daily Token Invalidation:** Kite Connect access tokens naturally invalidate every 24 hours, mitigating prolonged risk in the event of local workstation exposure.
- **Key Revocation Notice:** If credentials were ever accidentally tracked in earlier commits before cloning, revoke them immediately via the Zerodha Developer Console and Google Cloud IAM Console.

---

## Troubleshooting & FAQ

**Q: `GoogleSheetsError: Spreadsheet '...' not found or not shared with the service account email.`**  
A: Ensure the Google Spreadsheet title matches `SPREADSHEET_NAME` in your `.env` file, and verify you shared the spreadsheet with the `client_email` listed in your `service_account.json`.

**Q: `KiteHelperError: API_KEY and ACCESS_TOKEN must be set...`**  
A: Ensure `KITE_API_KEY` and `KITE_ACCESS_TOKEN` are defined in your `.env` file. Access tokens expire at the end of each trading day and must be refreshed each morning.

**Q: `TokenException: Incorrect api_key or access_token.`**  
A: Your daily access token has expired or is invalid. Regenerate a new access token via the Kite login flow and update `KITE_ACCESS_TOKEN` in `.env`.

**Q: PermissionError when saving `rsi_output.xlsx`**  
A: Close Microsoft Excel if the file is currently open, as Windows file locking prevents external processes from overwriting open spreadsheets.

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
