# =============================================================================
# nfo_downloader.py
# Download the NFO instrument dump from Kite Connect — maximum once per day.
# =============================================================================

import logging
import os
from datetime import date

import pandas as pd

import config

log = logging.getLogger(__name__)

_TODAY = date.today().isoformat()


def _read_last_download_date() -> str:
    """Return the date string of the last successful download, or ''."""
    if not os.path.exists(config.NFO_DATE_FILE):
        return ""
    with open(config.NFO_DATE_FILE) as fh:
        return fh.read().strip()


def _save_download_date() -> None:
    with open(config.NFO_DATE_FILE, "w") as fh:
        fh.write(_TODAY)


def ensure_nfo_instruments(kite, sheet_helper=None) -> bool:
    """
    Guarantee that a fresh (today's) NFO instruments CSV exists.

    Returns True if the file is ready to use, False on failure.
    """
    last_dl = _read_last_download_date()

    if last_dl == _TODAY and os.path.exists(config.NFO_CSV_PATH):
        log.info("NFO instruments file is current (downloaded today). Skipping download.")
        return True

    log.info("NFO instruments file is stale or missing. Downloading…")
    if sheet_helper:
        sheet_helper.set_status("Downloading NFO instruments…")

    try:
        instruments = kite.instruments("NFO")
    except Exception as exc:
        msg = f"NFO download failed: {exc}"
        log.error(msg)
        if sheet_helper:
            sheet_helper.set_status(msg)
        return False

    if not instruments:
        msg = "NFO download returned empty list."
        log.error(msg)
        if sheet_helper:
            sheet_helper.set_status(msg)
        return False

    df = pd.DataFrame(instruments)

    # --- normalise types immediately so downstream code is type-safe ---
    df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df = df.dropna(subset=["expiry", "strike", "instrument_type", "tradingsymbol", "name"])

    df.to_csv(config.NFO_CSV_PATH, index=False)
    _save_download_date()

    log.info("NFO instruments saved: %d rows → %s", len(df), config.NFO_CSV_PATH)
    if sheet_helper:
        sheet_helper.set_status(f"NFO download OK ({len(df)} rows)")

    return True


def load_nfo_dataframe() -> pd.DataFrame:
    """
    Load the NFO instruments CSV and return a normalised DataFrame.
    Raises FileNotFoundError if the file is missing.
    """
    if not os.path.exists(config.NFO_CSV_PATH):
        raise FileNotFoundError(
            f"NFO instruments file not found: {config.NFO_CSV_PATH}. "
            "Call ensure_nfo_instruments() first."
        )

    log.info("Loading NFO instruments from %s…", config.NFO_CSV_PATH)
    df = pd.read_csv(config.NFO_CSV_PATH)

    df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df = df.dropna(subset=["expiry", "strike", "instrument_type", "tradingsymbol", "name"])

    log.info("Loaded %d valid NFO rows.", len(df))
    return df
