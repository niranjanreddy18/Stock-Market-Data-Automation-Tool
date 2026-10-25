# =============================================================================
# historical_analysis.py
# 3-year weekly analytics using Kite Connect historical_data API.
# Results are cached daily via analytics_cache.py.
# =============================================================================

import logging
from datetime import date, timedelta

import pandas as pd

import analytics_cache
import config

log = logging.getLogger(__name__)

_EMPTY = {
    "min_up":  "N/A",
    "avg_up":  "N/A",
    "max_up":  "N/A",
    "min_dn":  "N/A",
    "avg_dn":  "N/A",
    "max_dn":  "N/A",
}


def _instrument_token(df: pd.DataFrame, stock: str) -> int | None:
    """Return the NSE equity instrument token for *stock*."""
    # Historical data is fetched from NSE equities, not NFO
    row = df[
        (df["name"] == stock) &
        (df["instrument_type"] == "EQ")
    ]
    if row.empty:
        log.warning("[%s] No EQ instrument token found.", stock)
        return None
    return int(row["instrument_token"].iloc[0])


def _daily_to_weekly(daily_df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate daily OHLC candles into weekly candles.

    week_open  = first trading day's open
    week_high  = max high of the week
    week_low   = min low  of the week
    """
    daily_df = daily_df.copy()
    daily_df.index = pd.to_datetime(daily_df["date"])
    daily_df = daily_df.sort_index()

    weekly = daily_df.resample("W-FRI").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    ).dropna()

    return weekly


def _calc_analytics(weekly: pd.DataFrame) -> dict:
    """
    Calculate min / avg / max weekly up-move and down-move percentages.

    up_move  (%) = (week_high  - week_open) / week_open * 100
    down_move(%) = (week_open  - week_low)  / week_open * 100
    """
    weekly = weekly[weekly["open"] > 0].copy()

    weekly["up_pct"]   = (weekly["high"]  - weekly["open"]) / weekly["open"] * 100
    weekly["down_pct"] = (weekly["open"]  - weekly["low"])  / weekly["open"] * 100

    def _r(series, fn):
        try:
            return round(float(fn(series)), 2)
        except Exception:
            return "N/A"

    return {
        "min_up":  _r(weekly["up_pct"],   lambda s: s.min()),
        "avg_up":  _r(weekly["up_pct"],   lambda s: s.mean()),
        "max_up":  _r(weekly["up_pct"],   lambda s: s.max()),
        "min_dn":  _r(weekly["down_pct"], lambda s: s.min()),
        "avg_dn":  _r(weekly["down_pct"], lambda s: s.mean()),
        "max_dn":  _r(weekly["down_pct"], lambda s: s.max()),
    }


def get_analytics(
    kite,
    nse_df: pd.DataFrame,
    stock: str,
) -> dict:
    """
    Return the 3-year weekly analytics dict for *stock*.

    Uses the daily cache; fetches from Kite only on a cache miss.
    *nse_df* should be the NSE (equity) instruments DataFrame.
    """
    # --- cache check ---
    cached = analytics_cache.get_cached(stock)
    if cached is not None:
        log.info("[%s] Using cached historical analytics.", stock)
        return cached

    log.info("[%s] Fetching 3-year historical data from Kite…", stock)

    token = _instrument_token(nse_df, stock)
    if token is None:
        return _EMPTY

    today = date.today()
    from_date = today - timedelta(days=config.HISTORICAL_YEARS * 365)

    try:
        candles = kite.historical_data(
            instrument_token=token,
            from_date=from_date.isoformat(),
            to_date=today.isoformat(),
            interval=config.HISTORICAL_INTERVAL,
            continuous=False,
        )
    except Exception as exc:
        log.error("[%s] historical_data() failed: %s", stock, exc)
        return _EMPTY

    if not candles:
        log.warning("[%s] historical_data() returned no candles.", stock)
        return _EMPTY

    daily_df = pd.DataFrame(candles)
    weekly   = _daily_to_weekly(daily_df)

    if weekly.empty:
        log.warning("[%s] Weekly aggregation produced no rows.", stock)
        return _EMPTY

    analytics = _calc_analytics(weekly)
    analytics_cache.set_cached(stock, analytics)

    log.info(
        "[%s] Analytics: up(min=%.2f avg=%.2f max=%.2f) "
        "dn(min=%.2f avg=%.2f max=%.2f)",
        stock,
        analytics.get("min_up", 0), analytics.get("avg_up", 0), analytics.get("max_up", 0),
        analytics.get("min_dn", 0), analytics.get("avg_dn", 0), analytics.get("max_dn", 0),
    )
    return analytics


def load_nse_instruments(kite) -> pd.DataFrame:
    """
    Fetch and return the NSE equity instruments as a DataFrame.
    Used exclusively to resolve instrument tokens for historical data.
    """
    try:
        instruments = kite.instruments("NSE")
        df = pd.DataFrame(instruments)
        log.info("Loaded %d NSE instruments.", len(df))
        return df
    except Exception as exc:
        log.error("Failed to load NSE instruments: %s", exc)
        return pd.DataFrame()
