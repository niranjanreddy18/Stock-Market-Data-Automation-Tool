# =============================================================================
# option_chain.py
# Option chain analysis — refactored from the original options_tracker.py.
# All original business logic is preserved.
# =============================================================================

import logging
import pandas as pd

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strike / expiry helpers
# ---------------------------------------------------------------------------

def get_nearest_expiry(df: pd.DataFrame, stock: str) -> str | None:
    """
    Return the nearest expiry date string ("YYYY-MM-DD") for *stock*.
    Returns None if no contracts exist.
    """
    stock_df = df[
        (df["name"] == stock) &
        (df["instrument_type"].isin(["CE", "PE"]))
    ]
    log.debug("[%s] get_nearest_expiry — %d rows found.", stock, len(stock_df))

    if stock_df.empty:
        log.warning(
            "[%s] No options found in instruments CSV. "
            "Check that the name column matches exactly.",
            stock,
        )
        return None

    expiries = pd.to_datetime(stock_df["expiry"], errors="coerce").dropna().sort_values()
    if expiries.empty:
        log.warning("[%s] Expiry column empty or unparseable.", stock)
        return None

    nearest = expiries.iloc[0].strftime("%Y-%m-%d")
    log.debug("[%s] Nearest expiry: %s", stock, nearest)
    return nearest


def get_strikes(df: pd.DataFrame, stock: str, expiry_str: str) -> list[float]:
    """Return sorted list of strike prices for *stock* + *expiry_str*."""
    stock_df = df[
        (df["name"] == stock) &
        (df["expiry"] == expiry_str) &
        (df["instrument_type"].isin(["CE", "PE"]))
    ]
    log.debug("[%s] get_strikes(%s) — %d rows.", stock, expiry_str, len(stock_df))

    if stock_df.empty:
        log.warning("[%s] No strikes found for expiry %s.", stock, expiry_str)
        return []

    return sorted(stock_df["strike"].dropna().unique().tolist())


def find_nearest_strike(target: float, strikes: list[float]) -> float | None:
    if not strikes:
        return None
    return min(strikes, key=lambda x: abs(x - target))


def build_strike_map(spot: float, strikes: list[float]) -> dict:
    return {
        "atm":    find_nearest_strike(spot,        strikes),
        "up_5":   find_nearest_strike(spot * 1.05, strikes),
        "down_5": find_nearest_strike(spot * 0.95, strikes),
        "up_10":  find_nearest_strike(spot * 1.10, strikes),
        "down_10":find_nearest_strike(spot * 0.90, strikes),
    }


def get_option_symbols(
    df: pd.DataFrame, stock: str, expiry_str: str, strike: float
) -> tuple[str | None, str | None]:
    """
    Return (ce_symbol, pe_symbol) for stock / expiry / strike.
    Returns (None, None) when contracts are missing.
    """
    if strike is None:
        log.warning("[%s] strike is None — skipping symbol lookup.", stock)
        return None, None

    option_df = df[
        (df["name"] == stock) &
        (df["expiry"] == expiry_str) &
        (df["strike"] == float(strike))
    ]
    log.debug(
        "[%s] get_option_symbols(expiry=%s, strike=%s) — %d rows.",
        stock, expiry_str, strike, len(option_df),
    )

    ce_df = option_df[option_df["instrument_type"] == "CE"]
    pe_df = option_df[option_df["instrument_type"] == "PE"]

    if ce_df.empty:
        log.warning("[%s] CE missing for strike=%s, expiry=%s.", stock, strike, expiry_str)
    if pe_df.empty:
        log.warning("[%s] PE missing for strike=%s, expiry=%s.", stock, strike, expiry_str)

    ce_sym = ce_df["tradingsymbol"].iloc[0] if not ce_df.empty else None
    pe_sym = pe_df["tradingsymbol"].iloc[0] if not pe_df.empty else None
    return ce_sym, pe_sym


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyse_stock(
    df: pd.DataFrame,
    stock: str,
    spot: float,
    option_quotes: dict,
) -> dict | None:
    """
    Run a full option chain analysis for *stock* given a pre-fetched
    *spot* price and a *option_quotes* dict (keyed "NFO:SYMBOL").

    Returns a result dict or None if the stock cannot be analysed.
    """
    expiry_str = get_nearest_expiry(df, stock)
    if expiry_str is None:
        return None

    strikes = get_strikes(df, stock, expiry_str)
    if not strikes:
        return None

    strike_map = build_strike_map(spot, strikes)

    days_to_expiry = (
        pd.Timestamp(expiry_str) - pd.Timestamp.today()
    ).days

    log.info(
        "[%s] spot=%.2f | expiry=%s | ATM=%s | UP5%%=%s | DOWN5%%=%s | "
        "UP10%%=%s | DOWN10%%=%s",
        stock, spot, expiry_str,
        strike_map["atm"], strike_map["up_5"], strike_map["down_5"],
        strike_map["up_10"], strike_map["down_10"],
    )

    symbol_map: dict[str, str] = {}
    for label, strike in strike_map.items():
        ce_sym, pe_sym = get_option_symbols(df, stock, expiry_str, strike)
        if label == "atm":
            if ce_sym:
                symbol_map["atm_ce"] = ce_sym
            if pe_sym:
                symbol_map["atm_pe"] = pe_sym
        elif label.startswith("up"):
            if ce_sym:
                symbol_map[f"{label}_ce"] = ce_sym
        elif label.startswith("down"):
            if pe_sym:
                symbol_map[f"{label}_pe"] = pe_sym

    valid_syms = {k: f"NFO:{v}" for k, v in symbol_map.items() if v}

    def _premium(key: str):
        nfo_sym = valid_syms.get(key)
        if nfo_sym is None:
            return "N/A"
        q = option_quotes.get(nfo_sym)
        if q is None:
            log.warning("No quote for %s", nfo_sym)
            return "N/A"
        return q.get("last_price", "N/A")

    return {
        "spot":               spot,
        "expiry":             days_to_expiry,
        "atm":                strike_map["atm"],
        "up_5":               strike_map["up_5"],
        "down_5":             strike_map["down_5"],
        "up_10":              strike_map["up_10"],
        "down_10":            strike_map["down_10"],
        "atm_ce_premium":     _premium("atm_ce"),
        "atm_pe_premium":     _premium("atm_pe"),
        "up_5_ce_premium":    _premium("up_5_ce"),
        "up_10_ce_premium":   _premium("up_10_ce"),
        "down_5_pe_premium":  _premium("down_5_pe"),
        "down_10_pe_premium": _premium("down_10_pe"),
        "valid_syms":         valid_syms,
    }


def collect_option_symbols(results: dict) -> list[str]:
    """Flatten all NFO option symbols from a results dict for batch quoting."""
    symbols = []
    for d in results.values():
        symbols.extend(d.get("valid_syms", {}).values())
    return list(set(symbols))
