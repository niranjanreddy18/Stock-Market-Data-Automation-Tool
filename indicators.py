"""
indicators.py
=============

Technical indicator calculations. RSI is implemented manually using
Wilder's smoothing method (the standard, original RSI formula), so the
project has no hard dependency on ``pandas_ta``.
"""

from typing import Iterable

import numpy as np
import pandas as pd


def calculate_rsi(close: pd.Series, period: int) -> pd.Series:
    """Calculate the Relative Strength Index (RSI) using Wilder's smoothing.

    This mirrors the classic RSI formula popularized by J. Welles Wilder:
    the average gain and average loss are first computed as a simple mean
    over the initial ``period`` observations, and then smoothed using
    Wilder's exponential moving average for all subsequent observations.

    Args:
        close: A pandas Series of closing prices, ordered chronologically
            (ascending by time).
        period: The RSI lookback period (e.g. 14 or 10).

    Returns:
        A pandas Series of RSI values (0-100), aligned with the input
        index. The first ``period`` values will be ``NaN`` since there is
        not yet enough data to compute a stable RSI.

    Raises:
        ValueError: If ``period`` is not a positive integer.
    """
    if period <= 0:
        raise ValueError("RSI period must be a positive integer.")

    close = close.astype(float)
    delta = close.diff()

    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = pd.Series(np.nan, index=close.index)
    avg_loss = pd.Series(np.nan, index=close.index)

    if len(close) <= period:
        # Not enough data to compute even the first RSI value.
        return pd.Series(np.nan, index=close.index)

    # Wilder's initial average is a simple mean of the first `period` gains/losses.
    first_avg_gain = gain.iloc[1 : period + 1].mean()
    first_avg_loss = loss.iloc[1 : period + 1].mean()

    avg_gain.iloc[period] = first_avg_gain
    avg_loss.iloc[period] = first_avg_loss

    # Wilder's smoothing (a form of exponential moving average) for the rest.
    for i in range(period + 1, len(close)):
        avg_gain.iloc[i] = (
            avg_gain.iloc[i - 1] * (period - 1) + gain.iloc[i]
        ) / period
        avg_loss.iloc[i] = (
            avg_loss.iloc[i - 1] * (period - 1) + loss.iloc[i]
        ) / period

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    # Where avg_loss is 0 (and avg_gain > 0), RSI is defined as 100.
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain > 0)), other=100.0)
    # Where both avg_gain and avg_loss are 0 (flat price), RSI is defined as 50.
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain == 0)), other=50.0)

    return rsi


def add_rsi_indicators(df: pd.DataFrame, periods: Iterable[int]) -> pd.DataFrame:
    """Add one RSI column per requested period to a DataFrame of candles.

    Args:
        df: DataFrame containing at least a ``close`` column, sorted in
            ascending chronological order.
        periods: An iterable of RSI periods to calculate, e.g. ``(14, 10)``.
            A column named ``rsi_{period}`` is added for each.

    Returns:
        A new DataFrame (copy of ``df``) with the additional RSI columns.
    """
    result = df.copy()

    if result.empty or "close" not in result.columns:
        for period in periods:
            result[f"rsi_{period}"] = pd.Series(dtype=float)
        return result

    for period in periods:
        result[f"rsi_{period}"] = calculate_rsi(result["close"], period)

    return result
