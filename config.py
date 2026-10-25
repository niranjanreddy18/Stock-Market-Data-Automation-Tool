"""
config.py
=========

Central configuration for the RSI Historical Data project.

All secrets and environment-specific values are read from environment
variables where available, falling back to the empty-string / sensible
default values defined below. Edit the values below directly, or (recommended)
export the corresponding environment variables before running the project,
for example (Linux / macOS):

    export KITE_API_KEY="your_api_key"
    export KITE_API_SECRET="your_api_secret"
    export KITE_ACCESS_TOKEN="your_access_token"

or on Windows (PowerShell):

    $env:KITE_API_KEY="your_api_key"

Nothing in this file needs to be edited elsewhere in the codebase -- every
other module imports its settings from here.
"""

import os
from datetime import date, time

try:
    import dotenv  # type: ignore

    dotenv.load_dotenv()
except Exception:
    pass

# ---------------------------------------------------------------------------
# Zerodha Kite Connect credentials
# ---------------------------------------------------------------------------

#: Kite Connect API key (from https://developers.kite.trade/apps)
API_KEY: str = os.getenv("KITE_API_KEY", "")

#: Kite Connect API secret
API_SECRET: str = os.getenv("KITE_API_SECRET", "")

#: Kite Connect access token generated for the current trading day.
#: See README.md -> "Generating Kite Access Token" for details on how
#: to generate this value.
ACCESS_TOKEN: str = os.getenv("KITE_ACCESS_TOKEN", "")

# ---------------------------------------------------------------------------
# Google Sheets / Google Service Account configuration
# ---------------------------------------------------------------------------

#: Path to the Google service account JSON credentials file.
GOOGLE_SERVICE_ACCOUNT_JSON: str = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json"
)

#: Name of the Google Spreadsheet that contains the stock names in column A.
SPREADSHEET_NAME: str = os.getenv("SPREADSHEET_NAME", "nifty")

#: Optional: name of the worksheet/tab to read from. If empty, the first
#: worksheet in the spreadsheet is used.
WORKSHEET_NAME: str = os.getenv("WORKSHEET_NAME", "")

# ---------------------------------------------------------------------------
# Output configuration
# ---------------------------------------------------------------------------

#: Path to the Excel workbook that will be generated.
OUTPUT_EXCEL: str = os.getenv("OUTPUT_EXCEL", "rsi_output.xlsx")

#: Directory used for the raw expiry-week CSV exports created by the
#: historical price downloader.
RAW_DATA_OUTPUT_DIR: str = os.getenv("RAW_DATA_OUTPUT_DIR", "raw_data")

# ---------------------------------------------------------------------------
# Market session / data window configuration
# ---------------------------------------------------------------------------

#: NSE regular market session start time.
MARKET_OPEN: time = time(9, 15)

#: NSE regular market session end time for Monday-style sessions.
MARKET_CLOSE: time = time(15, 30)

#: NSE regular market session end time for weekly-expiry day data.
EXPIRY_DAY_CLOSE: time = time(15, 15)

#: Start of the window that is written to the Excel output (inclusive).
OUTPUT_WINDOW_START: time = time(14, 55)

#: End of the window that is written to the Excel output (inclusive).
OUTPUT_WINDOW_END: time = time(15, 15)

# ---------------------------------------------------------------------------
# RSI configuration
# ---------------------------------------------------------------------------

#: RSI periods to calculate. Kept as a list so more periods can be added
#: easily; the Excel writer will automatically add matching columns as long
#: as this stays as (14, 10) to match the required output format.
RSI_PERIODS = (14, 10)
 
# ---------------------------------------------------------------------------
# Historical range configuration
# ---------------------------------------------------------------------------

#: Number of years of history (counting back from today) to process.
YEARS_BACK: int = 3

#: Maximum number of calendar days to step backwards when looking for the
#: nearest previous trading day if the target weekly day is a market holiday.
MAX_TRADING_DAY_LOOKBACK: int = 7

# ---------------------------------------------------------------------------
# Weekly trading day selection rules
# ---------------------------------------------------------------------------
#
# NSE changed the weekly F&O expiry day from Thursday to Tuesday effective
# WEEKLY_EXPIRY_CHANGE_DATE. This project mirrors that same switch when
# choosing which day of each week to sample:
#
#   * For weeks starting strictly before WEEKLY_EXPIRY_CHANGE_DATE, the
#     weekly day named in OLD_WEEKLY_DAY is used (e.g. "THURSDAY").
#   * For weeks starting on/after WEEKLY_EXPIRY_CHANGE_DATE, the weekly day
#     named in NEW_WEEKLY_DAY is used (e.g. "TUESDAY").
#
# Weekly target dates are always computed dynamically from these three
# values (see historical_data.generate_weekly_target_dates) -- no calendar
# dates are ever hardcoded.

#: Date on which the weekly sampling day switches from OLD_WEEKLY_DAY to
#: NEW_WEEKLY_DAY.
WEEKLY_EXPIRY_CHANGE_DATE: date = date(2025, 9, 1)

#: Name of the weekday (e.g. "MONDAY".."SUNDAY") used for weeks that start
#: strictly before WEEKLY_EXPIRY_CHANGE_DATE.
OLD_WEEKLY_DAY: str = "THURSDAY"

#: Name of the weekday used for weeks that start on/after
#: WEEKLY_EXPIRY_CHANGE_DATE.
NEW_WEEKLY_DAY: str = "TUESDAY"

# ---------------------------------------------------------------------------
# Networking / rate limit configuration
# ---------------------------------------------------------------------------

#: Minimum delay (in seconds) enforced between consecutive Kite historical
#: data API calls, to stay within Kite's published rate limits
#: (historical data: ~3 requests/second).
API_CALL_MIN_INTERVAL: float = 0.35

#: Maximum number of retry attempts for a failing API call.
MAX_RETRIES: int = 3

#: Base delay (seconds) used for exponential backoff between retries.
RETRY_BACKOFF_BASE: float = 1.5

# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

#: File used to cache the instrument token lookup table so that the full
#: instrument dump does not need to be re-downloaded on every run.
INSTRUMENT_CACHE_FILE: str = os.getenv("INSTRUMENT_CACHE_FILE", "instrument_cache.json")

#: Number of hours the instrument cache remains valid before being refreshed.
INSTRUMENT_CACHE_TTL_HOURS: int = 24

#: Default exchange used when looking up instrument tokens.
DEFAULT_EXCHANGE: str = "NSE"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

#: Path to the log file written by logger.py.
LOG_FILE: str = os.getenv("LOG_FILE", "app.log")

#: Logging level (e.g. "DEBUG", "INFO", "WARNING", "ERROR").
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ---------------------------------------------------------------------------
# Auxiliary / Derivatives & Token Manager Configuration
# ---------------------------------------------------------------------------

#: Path to optional access token file
ACCESS_TOKEN_FILE: str = os.getenv("KITE_ACCESS_TOKEN_FILE", "access_token.txt")

#: Path to Google credentials alias used by validators
GOOGLE_CREDENTIALS_FILE: str = GOOGLE_SERVICE_ACCOUNT_JSON

#: Spreadsheet key / name alias
SHEET_KEY: str = SPREADSHEET_NAME

#: Path to local NFO instruments cache CSV
NFO_CSV_PATH: str = os.getenv("NFO_CSV_PATH", "nfo_instruments.csv")

#: Date stamp tracking file for NFO instruments
NFO_DATE_FILE: str = os.getenv("NFO_DATE_FILE", ".nfo_last_download")

#: Path to analytics cache file
ANALYTICS_CACHE_FILE: str = os.getenv("ANALYTICS_CACHE_FILE", "analytics_cache.json")

#: Historical interval for analytics
HISTORICAL_INTERVAL: str = os.getenv("HISTORICAL_INTERVAL", "day")

#: Historical lookback years for analytics
HISTORICAL_YEARS: int = int(os.getenv("HISTORICAL_YEARS", "3"))

