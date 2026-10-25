# =============================================================================
# futures.py
# Futures price fetch for each stock — nearest month contract.
# =============================================================================

import logging
import pandas as pd

log = logging.getLogger(__name__)


def get_nearest_futures_symbol(df: pd.DataFrame, stock: str) -> str | None:
    """
    Return the tradingsymbol of the nearest-month futures contract for *stock*.
    Returns None if no FUT contract exists.
    """
    fut_df = df[
        (df["name"] == stock) &
        (df["instrument_type"] == "FUT")
    ].copy()

    if fut_df.empty:
        log.warning("[%s] No futures contract found in instruments CSV.", stock)
        return None

    fut_df["_expiry_dt"] = pd.to_datetime(fut_df["expiry"], errors="coerce")
    fut_df = fut_df.dropna(subset=["_expiry_dt"])
    fut_df = fut_df.sort_values("_expiry_dt")

    symbol = fut_df["tradingsymbol"].iloc[0]
    log.debug("[%s] Nearest futures symbol: %s", stock, symbol)
    return symbol


def fetch_futures_prices(
    kite,
    df: pd.DataFrame,
    stocks: list[str],
) -> dict[str, float | str]:
    """
    Batch-fetch current futures prices for all *stocks*.

    Returns a dict  {stock: last_price | "N/A"}.
    """
    symbol_map: dict[str, str] = {}   # stock → NFO:SYMBOL
    for stock in stocks:
        sym = get_nearest_futures_symbol(df, stock)
        if sym:
            symbol_map[stock] = f"NFO:{sym}"

    if not symbol_map:
        log.warning("No futures symbols found for any stock.")
        return {s: "N/A" for s in stocks}

    # Batch quote (Kite limit 500 per call)
    nfo_symbols = list(symbol_map.values())
    quotes: dict = {}
    for i in range(0, len(nfo_symbols), 500):
        batch = nfo_symbols[i: i + 500]
        try:
            quotes.update(kite.quote(batch))
        except Exception as exc:
            log.error("Kite quote() failed for futures batch: %s", exc)

    result: dict[str, float | str] = {}
    for stock in stocks:
        nfo_sym = symbol_map.get(stock)
        if nfo_sym is None:
            result[stock] = "N/A"
            continue
        q = quotes.get(nfo_sym)
        if q is None:
            log.warning("[%s] No futures quote returned for %s.", stock, nfo_sym)
            result[stock] = "N/A"
        else:
            result[stock] = q.get("last_price", "N/A")

    return result
