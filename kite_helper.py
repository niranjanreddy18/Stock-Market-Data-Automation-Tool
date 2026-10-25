"""
kite_helper.py
==============

Wraps the Zerodha ``kiteconnect`` client with:

* Instrument token lookup with on-disk caching (to avoid re-downloading the
  full instrument dump on every run).
* Rate limiting to respect Kite Connect's published API limits.
* Automatic retries with exponential backoff for transient failures.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException

import config

logger = logging.getLogger("rsi_project")


class KiteHelperError(Exception):
    """Raised when a Kite Connect operation fails after all retries."""


class KiteHelper:
    """High level helper around ``KiteConnect`` for this project's needs.

    Args:
        api_key: Kite Connect API key.
        api_secret: Kite Connect API secret (kept for completeness / future
            use, e.g. regenerating a session).
        access_token: A valid Kite Connect access token for the current
            trading day.
        cache_file: Path to the JSON file used to cache instrument tokens.
        cache_ttl_hours: Number of hours the instrument cache stays valid.
    """

    def __init__(
        self,
        api_key: str = config.API_KEY,
        api_secret: str = config.API_SECRET,
        access_token: str = config.ACCESS_TOKEN,
        cache_file: str = config.INSTRUMENT_CACHE_FILE,
        cache_ttl_hours: int = config.INSTRUMENT_CACHE_TTL_HOURS,
    ) -> None:
        if not api_key or not access_token:
            raise KiteHelperError(
                "API_KEY and ACCESS_TOKEN must be set in config.py (or via "
                "environment variables) before using KiteHelper."
            )

        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.cache_file = cache_file
        self.cache_ttl_hours = cache_ttl_hours

        self.kite = KiteConnect(api_key=self.api_key)
        self.kite.set_access_token(self.access_token)

        self._instrument_map: Dict[str, int] = {}
        self._last_call_time: float = 0.0

    # ------------------------------------------------------------------
    # Instrument token management
    # ------------------------------------------------------------------

    def _cache_is_fresh(self) -> bool:
        """Check whether the on-disk instrument cache file is still valid.

        Returns:
            True if the cache file exists and was written within the
            configured TTL window, False otherwise.
        """
        if not os.path.exists(self.cache_file):
            return False

        try:
            with open(self.cache_file, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return False

        cached_at_str = payload.get("cached_at")
        if not cached_at_str:
            return False

        try:
            cached_at = datetime.fromisoformat(cached_at_str)
        except ValueError:
            return False

        return datetime.now() - cached_at < timedelta(hours=self.cache_ttl_hours)

    def _load_cache(self) -> Dict[str, int]:
        """Load the instrument token map from the on-disk cache file.

        Returns:
            A mapping of trading symbol to instrument token. Returns an
            empty dict if the cache is missing or invalid.
        """
        try:
            with open(self.cache_file, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            return {str(k): int(v) for k, v in payload.get("tokens", {}).items()}
        except (json.JSONDecodeError, OSError, ValueError):
            return {}

    def _save_cache(self, tokens: Dict[str, int]) -> None:
        """Persist the instrument token map to the on-disk cache file.

        Args:
            tokens: Mapping of trading symbol to instrument token to save.
        """
        payload = {
            "cached_at": datetime.now().isoformat(),
            "tokens": tokens,
        }
        try:
            with open(self.cache_file, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
        except OSError as exc:
            logger.warning("Could not write instrument cache file: %s", exc)

    def load_instruments(self, exchange: str = config.DEFAULT_EXCHANGE) -> None:
        """Load instrument tokens for the given exchange, using the cache
        when possible, otherwise downloading a fresh instrument dump from
        Kite Connect exactly once.

        Args:
            exchange: Exchange to load instruments for (e.g. ``"NSE"``).

        Raises:
            KiteHelperError: If the instrument dump cannot be downloaded and
                no usable cache exists.
        """
        if self._instrument_map:
            return

        if self._cache_is_fresh():
            self._instrument_map = self._load_cache()
            if self._instrument_map:
                logger.info(
                    "Loaded %d instrument tokens from cache (%s).",
                    len(self._instrument_map),
                    self.cache_file,
                )
                return

        logger.info("Downloading instrument dump for exchange '%s'...", exchange)
        try:
            instruments: List[dict] = self._call_with_retry(
                self.kite.instruments, exchange
            )
        except Exception as exc:
            # Fall back to a stale cache if we have one, rather than failing
            # the whole run outright.
            stale = self._load_cache()
            if stale:
                logger.warning(
                    "Instrument download failed (%s); falling back to stale "
                    "cache with %d entries.",
                    exc,
                    len(stale),
                )
                self._instrument_map = stale
                return
            raise KiteHelperError(
                f"Failed to download instrument list for '{exchange}': {exc}"
            ) from exc

        token_map: Dict[str, int] = {}
        for instrument in instruments:
            symbol = instrument.get("tradingsymbol")
            token = instrument.get("instrument_token")
            if symbol and token is not None:
                token_map[str(symbol).upper()] = int(token)

        self._instrument_map = token_map
        self._save_cache(token_map)
        logger.info(
            "Downloaded and cached %d instrument tokens for exchange '%s'.",
            len(token_map),
            exchange,
        )

    def fetch_instruments(self, exchange: str = config.DEFAULT_EXCHANGE) -> List[dict]:
        """Fetch instrument definitions for an exchange with standard retries."""
        return self._call_with_retry(self.kite.instruments, exchange)

    def get_nfo_future_token(self, underlying_symbol: str = "NIFTY") -> Optional[int]:
        """Return a futures token for the given underlying from the NFO dump."""
        needle = underlying_symbol.upper()
        try:
            instruments = self.fetch_instruments("NFO")
        except KiteHelperError:
            return None

        for instrument in instruments:
            tradingsymbol = str(instrument.get("tradingsymbol", "")).upper()
            name = str(instrument.get("name", "")).upper()
            instrument_type = str(instrument.get("instrument_type", "")).upper()
            token = instrument.get("instrument_token")
            if (
                instrument_type == "FUT"
                and needle in name
                and "FUT" in tradingsymbol
                and token is not None
            ):
                return int(token)

        logger.warning(
            "Could not find a %s futures token in the NFO instrument dump.",
            underlying_symbol,
        )
        return None

    def get_token(self, trading_symbol: str) -> Optional[int]:
        """Return the instrument token for a given trading symbol.

        Args:
            trading_symbol: The NSE trading symbol, e.g. ``"RELIANCE"``.

        Returns:
            The instrument token as an int, or ``None`` if the symbol is
            not found in the loaded instrument map.
        """
        if not self._instrument_map:
            self.load_instruments()
        return self._instrument_map.get(trading_symbol.upper())

    # ------------------------------------------------------------------
    # Rate limiting + retry wrapper
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        """Sleep just long enough to respect the minimum API call interval."""
        elapsed = time.monotonic() - self._last_call_time
        min_interval = config.API_CALL_MIN_INTERVAL
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_call_time = time.monotonic()

    def _call_with_retry(self, func, *args, **kwargs):
        """Call ``func`` with retries, exponential backoff, and rate limiting.

        Args:
            func: Callable to invoke.
            *args: Positional arguments passed to ``func``.
            **kwargs: Keyword arguments passed to ``func``.

        Returns:
            Whatever ``func`` returns on success.

        Raises:
            KiteHelperError: If all retry attempts are exhausted.
        """
        last_exception: Optional[Exception] = None

        for attempt in range(1, config.MAX_RETRIES + 1):
            self._throttle()
            try:
                return func(*args, **kwargs)
            except KiteException as exc:
                last_exception = exc
                logger.warning(
                    "Kite API error on attempt %d/%d for %s: %s",
                    attempt,
                    config.MAX_RETRIES,
                    getattr(func, "__name__", str(func)),
                    exc,
                )
            except Exception as exc:  # network errors, timeouts, etc.
                last_exception = exc
                logger.warning(
                    "Unexpected error on attempt %d/%d for %s: %s",
                    attempt,
                    config.MAX_RETRIES,
                    getattr(func, "__name__", str(func)),
                    exc,
                )

            if attempt < config.MAX_RETRIES:
                backoff_seconds = config.RETRY_BACKOFF_BASE ** attempt
                time.sleep(backoff_seconds)

        raise KiteHelperError(
            f"Call to {getattr(func, '__name__', str(func))} failed after "
            f"{config.MAX_RETRIES} attempts: {last_exception}"
        )

    # ------------------------------------------------------------------
    # Historical data
    # ------------------------------------------------------------------

    def fetch_historical_data(
        self,
        instrument_token: int,
        from_dt: datetime,
        to_dt: datetime,
        interval: str = "minute",
    ) -> List[dict]:
        """Fetch historical candle data for an instrument, with retries.

        Args:
            instrument_token: The Kite instrument token to fetch data for.
            from_dt: Start of the date/time range (inclusive).
            to_dt: End of the date/time range (inclusive).
            interval: Candle interval, e.g. ``"minute"``.

        Returns:
            A list of candle dictionaries as returned by the Kite Connect
            API, each containing ``date``, ``open``, ``high``, ``low``,
            ``close``, and ``volume`` keys. Returns an empty list if no
            candles are available (e.g. market holiday).

        Raises:
            KiteHelperError: If the API call fails after all retries.
        """
        return self._call_with_retry(
            self.kite.historical_data,
            instrument_token,
            from_dt,
            to_dt,
            interval,
        )
