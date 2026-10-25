"""
historical_data.py
===================

Handles generation of the list of target weekly dates and downloading of
the corresponding full intraday minute-candle session from Kite Connect.

Weekly target date selection implements a dynamic switch: weeks starting
strictly before ``config.WEEKLY_EXPIRY_CHANGE_DATE`` use
``config.OLD_WEEKLY_DAY`` (e.g. Thursday), while weeks starting on/after
that date use ``config.NEW_WEEKLY_DAY`` (e.g. Tuesday). If the resulting
target date is a market holiday (no candles returned by Kite), the nearest
previous trading day is used instead. No calendar dates are ever
hardcoded -- everything is derived dynamically from the configuration
values and the current date.
"""

import logging
import os
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

import config
from kite_helper import KiteHelper, KiteHelperError
from utils import is_weekend, monday_of_week, resolve_weekly_target_date

logger = logging.getLogger("rsi_project")


def generate_weekly_target_dates(
    years_back: int = config.YEARS_BACK,
    change_date: date = config.WEEKLY_EXPIRY_CHANGE_DATE,
    old_weekly_day: str = config.OLD_WEEKLY_DAY,
    new_weekly_day: str = config.NEW_WEEKLY_DAY,
) -> List[date]:
    """Generate the list of weekly target dates spanning the last N years.

    For every week in the range ``[today - years_back years, today]``, the
    target sampling date is computed dynamically:

    * If the week's Monday falls strictly before ``change_date``, the
      weekday named in ``old_weekly_day`` is used (e.g. Thursday).
    * If the week's Monday falls on/after ``change_date``, the weekday
      named in ``new_weekly_day`` is used (e.g. Tuesday).

    Dates that fall after today are excluded (since there is no data for
    the future). The returned list is chronologically ordered and contains
    no duplicates.

    Args:
        years_back: Number of years to look back from today.
        change_date: Date on which the weekly sampling day switches from
            ``old_weekly_day`` to ``new_weekly_day``.
        old_weekly_day: Weekday name used for weeks before ``change_date``.
        new_weekly_day: Weekday name used for weeks on/after ``change_date``.

    Returns:
        A chronologically sorted list of unique ``datetime.date`` objects,
        one per week.
    """
    today = date.today()
    range_start = today - timedelta(days=365 * years_back)

    first_week_monday = monday_of_week(range_start)
    last_week_monday = monday_of_week(today)

    target_dates: List[date] = []
    seen = set()

    current_monday = first_week_monday
    while current_monday <= last_week_monday:
        target_date = resolve_weekly_target_date(
            week_monday=current_monday,
            change_date=change_date,
            old_weekly_day=old_weekly_day,
            new_weekly_day=new_weekly_day,
        )

        if target_date <= today and target_date not in seen:
            target_dates.append(target_date)
            seen.add(target_date)

        current_monday += timedelta(weeks=1)

    target_dates.sort()
    return target_dates


def fetch_candles_for_session(
    kite_helper: KiteHelper,
    instrument_token: int,
    session_date: date,
    market_close: Optional[time] = None,
) -> List[dict]:
    """Fetch intraday minute candles for one instrument and one trading day."""
    if market_close is None:
        market_close = config.MARKET_CLOSE

    from_dt = datetime.combine(session_date, config.MARKET_OPEN)
    to_dt = datetime.combine(session_date, market_close)

    try:
        return kite_helper.fetch_historical_data(
            instrument_token,
            from_dt,
            to_dt,
            interval="minute",
        )
    except KiteHelperError as exc:
        logger.error(
            "Failed to fetch historical data for token %s on %s: %s",
            instrument_token,
            session_date,
            exc,
        )
        return []


def get_trading_day_data(
    kite_helper: KiteHelper,
    instrument_token: int,
    target_date: date,
    max_lookback_days: int = config.MAX_TRADING_DAY_LOOKBACK,
    market_close: Optional[time] = None,
) -> Tuple[Optional[date], List[dict]]:
    """Find the nearest previous trading day (starting at ``target_date``)
    that has available intraday candle data, and return its full market
    session candles.

    The function first tries ``target_date`` itself. If no candles are
    returned (typically because it is a market holiday), it steps backwards
    one calendar day at a time (skipping weekends) until candles are found
    or ``max_lookback_days`` calendar days have been tried.

    Args:
        kite_helper: An initialized ``KiteHelper`` instance.
        instrument_token: Kite instrument token for the stock.
        target_date: The preferred date to fetch data for (a weekly
            Thursday or Tuesday, depending on the configured switch date).
        max_lookback_days: Maximum number of calendar days to step
            backwards while searching for a trading day with data.
        market_close: Optional market close for the requested session.

    Returns:
        A tuple of ``(actual_date_used, candles)``. If no trading day with
        data is found within the lookback window, returns ``(None, [])``.
    """
    candidate = target_date
    attempts = 0

    while attempts <= max_lookback_days:
        if is_weekend(candidate):
            candidate -= timedelta(days=1)
            continue

        candles = fetch_candles_for_session(
            kite_helper,
            instrument_token,
            candidate,
            market_close=market_close,
        )

        if candles:
            logger.info(
                "Downloaded %d candle(s) for token %s on %s.",
                len(candles),
                instrument_token,
                candidate,
            )
            return candidate, candles

        logger.info(
            "No candles for token %s on %s (likely a holiday); trying "
            "previous trading day.",
            instrument_token,
            candidate,
        )
        candidate -= timedelta(days=1)
        attempts += 1

    logger.warning(
        "No trading day with data found for token %s within %d days before %s.",
        instrument_token,
        max_lookback_days,
        target_date,
    )
    return None, []


def candles_to_dataframe(candles: List[dict]) -> pd.DataFrame:
    """Convert a list of raw Kite candle dicts into a sorted DataFrame.

    Args:
        candles: List of candle dictionaries as returned by
            ``KiteHelper.fetch_historical_data``.

    Returns:
        A ``pandas.DataFrame`` indexed by timestamp (ascending), containing
        at least a ``close`` column. Returns an empty DataFrame if
        ``candles`` is empty.
    """
    if not candles:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(candles)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _expected_raw_data_columns() -> List[str]:
    """Return the ordered column names for the raw expiry-week CSV output."""
    return [
        "Date",
        "Time",
        "NIFTY_Open",
        "NIFTY_High",
        "NIFTY_Low",
        "NIFTY_Close",
        "BANKNIFTY_Open",
        "BANKNIFTY_High",
        "BANKNIFTY_Low",
        "BANKNIFTY_Close",
        "NIFTY_FUT_Open",
        "NIFTY_FUT_High",
        "NIFTY_FUT_Low",
        "NIFTY_FUT_Close",
        "INDIA_VIX_Open",
        "INDIA_VIX_High",
        "INDIA_VIX_Low",
        "INDIA_VIX_Close",
    ]


def _build_session_frame(
    kite_helper: KiteHelper,
    session_date: date,
    session_close: time,
    instrument_tokens: Dict[str, Optional[int]],
) -> pd.DataFrame:
    """Create a single-session DataFrame with the required OHLC columns."""
    frames: List[pd.DataFrame] = []

    for instrument_name, instrument_token in instrument_tokens.items():
        if instrument_token is None:
            continue

        candles = fetch_candles_for_session(
            kite_helper,
            instrument_token,
            session_date,
            market_close=session_close,
        )
        if not candles:
            continue

        df = candles_to_dataframe(candles)
        if df.empty:
            continue

        df = df.copy()
        df["Date"] = df["date"].dt.strftime("%Y-%m-%d")
        df["Time"] = df["date"].dt.strftime("%H:%M")

        column_map = {
            "open": f"{instrument_name}_Open",
            "high": f"{instrument_name}_High",
            "low": f"{instrument_name}_Low",
            "close": f"{instrument_name}_Close",
        }
        df = df[["Date", "Time", "open", "high", "low", "close"]].rename(
            columns=column_map
        )
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=_expected_raw_data_columns())

    combined = frames[0]
    for frame in frames[1:]:
        combined = combined.merge(frame, on=["Date", "Time"], how="outer")

    combined = combined.sort_values(["Date", "Time"]).reset_index(drop=True)
    expected_columns = _expected_raw_data_columns()
    for column in expected_columns:
        if column not in combined.columns:
            combined[column] = pd.NA
    return combined[expected_columns]


def download_expiry_week_raw_data(
    kite_helper: KiteHelper,
    weekly_dates: Optional[List[date]] = None,
    output_dir: Optional[str] = None,
) -> List[str]:
    """Download Monday + expiry-day minute data for each expiry week and save it into one consolidated CSV file."""
    if weekly_dates is None:
        weekly_dates = generate_weekly_target_dates()

    output_dir = output_dir or config.RAW_DATA_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)

    instrument_tokens: Dict[str, Optional[int]] = {
        "NIFTY": kite_helper.get_token("NIFTY 50"),
        "BANKNIFTY": kite_helper.get_token("NIFTY BANK"),
        "NIFTY_FUT": kite_helper.get_nfo_future_token("NIFTY"),
        "INDIA_VIX": kite_helper.get_token("INDIA VIX"),
    }

    missing_tokens = [name for name, token in instrument_tokens.items() if token is None]
    if missing_tokens:
        logger.warning("Missing instrument token(s): %s", ", ".join(missing_tokens))

    primary_token = (
        instrument_tokens.get("NIFTY")
        or instrument_tokens.get("BANKNIFTY")
        or instrument_tokens.get("INDIA_VIX")
    )

    output_path = os.path.join(output_dir, "all_expiry_weeks_data.csv")
    if os.path.exists(output_path):
        os.remove(output_path)

    header_written = False
    written_files: List[str] = []
    for target_date in weekly_dates:
        week_monday = monday_of_week(target_date)
        logger.info(
            "Processing expiry week starting Monday %s (expiry target %s).",
            week_monday,
            target_date,
        )

        if primary_token is not None:
            expiry_actual_date, _ = get_trading_day_data(
                kite_helper,
                primary_token,
                target_date,
                market_close=config.EXPIRY_DAY_CLOSE,
            )
            monday_actual_date, _ = get_trading_day_data(
                kite_helper,
                primary_token,
                week_monday,
                market_close=config.MARKET_CLOSE,
            )
        else:
            expiry_actual_date = target_date
            monday_actual_date = week_monday

        if expiry_actual_date is None:
            logger.warning("Skipping week %s because no expiry-day data was found.", week_monday)
            continue

        monday_frame = _build_session_frame(
            kite_helper,
            monday_actual_date or week_monday,
            config.MARKET_CLOSE,
            instrument_tokens,
        )
        expiry_frame = _build_session_frame(
            kite_helper,
            expiry_actual_date,
            config.EXPIRY_DAY_CLOSE,
            instrument_tokens,
        )

        if monday_frame.empty and expiry_frame.empty:
            logger.warning("No raw data rows generated for week %s.", week_monday)
            continue

        monday_frame = monday_frame.copy()
        monday_frame.insert(0, "Expiry_Week", target_date.strftime("%Y-%m-%d"))
        monday_frame.insert(1, "Trading_Day", "Monday")

        expiry_frame = expiry_frame.copy()
        expiry_frame.insert(0, "Expiry_Week", target_date.strftime("%Y-%m-%d"))
        expiry_frame.insert(1, "Trading_Day", "Expiry")

        combined = pd.concat([monday_frame, expiry_frame], ignore_index=True)
        if combined.empty:
            logger.warning("No raw data rows generated for week %s.", week_monday)
            continue

        combined = combined.sort_values(["Date", "Time"]).reset_index(drop=True)
        combined.to_csv(
            output_path,
            mode="a",
            index=False,
            header=not header_written,
        )
        header_written = True
        written_files.append(output_path)
        logger.info(
            "Appended %d minute row(s) with raw OHLC data to %s",
            len(combined),
            output_path,
        )

    return written_files
