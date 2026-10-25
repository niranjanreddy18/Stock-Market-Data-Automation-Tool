# =============================================================================
# analytics_cache.py
# Daily cache for 3-year weekly analytics.
# Reads/writes a local JSON file keyed by date so that historical API calls
# are made at most once per trading day.
# =============================================================================

import json
import logging
import os
from datetime import date

import config

log = logging.getLogger(__name__)

_TODAY = date.today().isoformat()


def _load_raw() -> dict:
    if not os.path.exists(config.ANALYTICS_CACHE_FILE):
        return {}
    try:
        with open(config.ANALYTICS_CACHE_FILE) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read analytics cache: %s", exc)
        return {}


def _save_raw(data: dict) -> None:
    try:
        with open(config.ANALYTICS_CACHE_FILE, "w") as fh:
            json.dump(data, fh, indent=2)
    except OSError as exc:
        log.error("Could not write analytics cache: %s", exc)


def get_cached(stock: str) -> dict | None:
    """
    Return today's cached analytics for *stock*, or None on a cache miss.
    """
    raw = _load_raw()
    entry = raw.get(stock)
    if entry and entry.get("date") == _TODAY:
        log.debug("[%s] Analytics cache HIT.", stock)
        return entry["analytics"]
    log.debug("[%s] Analytics cache MISS.", stock)
    return None


def set_cached(stock: str, analytics: dict) -> None:
    """Persist *analytics* for *stock* under today's date."""
    raw = _load_raw()
    raw[stock] = {"date": _TODAY, "analytics": analytics}
    _save_raw(raw)
    log.debug("[%s] Analytics cached for %s.", stock, _TODAY)


def cache_status() -> str:
    """Human-readable cache status for the status block."""
    raw = _load_raw()
    hits = sum(1 for v in raw.values() if v.get("date") == _TODAY)
    return f"{hits} stock(s) cached for {_TODAY}"
