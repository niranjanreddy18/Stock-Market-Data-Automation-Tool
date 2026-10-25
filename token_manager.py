# =============================================================================
# token_manager.py
# Centralised Kite Connect token management.
#
# IMPORTANT: Kite Connect does NOT support refresh tokens.
# When an access token expires the user must supply a fresh request_token
# obtained by completing the Kite login flow manually.
# =============================================================================

import logging
import os
from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException

import config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def load_access_token() -> str | None:
    """Read saved access token from disk or config. Returns None if missing."""
    if os.path.exists(config.ACCESS_TOKEN_FILE):
        try:
            with open(config.ACCESS_TOKEN_FILE, encoding="utf-8") as fh:
                token = fh.read().strip()
            if token:
                return token
        except OSError as exc:
            log.warning("Could not read access token file: %s", exc)
    return config.ACCESS_TOKEN or None



def save_access_token(token: str) -> None:
    """Persist access token to disk."""
    with open(config.ACCESS_TOKEN_FILE, "w") as fh:
        fh.write(token.strip())
    log.info("Access token saved to %s", config.ACCESS_TOKEN_FILE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_kite(access_token: str | None = None) -> KiteConnect:
    """
    Create and return a KiteConnect instance.

    If *access_token* is provided it is used; otherwise the saved token is
    loaded from disk.  Raises RuntimeError if no token is available.
    """
    if not config.API_KEY:
        raise RuntimeError("KITE_API_KEY is not set in environment / config.")

    kite = KiteConnect(api_key=config.API_KEY)

    token = access_token or load_access_token()
    if not token:
        raise RuntimeError(
            "No access token found.  Run the Kite login flow and save the "
            f"token to {config.ACCESS_TOKEN_FILE}."
        )

    kite.set_access_token(token)
    return kite


def is_token_exception(exc: Exception) -> bool:
    """Return True when *exc* represents an expired / invalid access token."""
    return isinstance(exc, TokenException) or "token" in str(exc).lower()


def generate_new_token(request_token: str) -> str:
    """
    Exchange *request_token* for a fresh access token using api_secret.

    Returns the new access token string and saves it to disk.
    Raises RuntimeError if API_SECRET is missing or generation fails.
    """
    if not config.API_SECRET:
        raise RuntimeError(
            "KITE_API_SECRET is not set — cannot generate a new session."
        )

    kite = KiteConnect(api_key=config.API_KEY)
    try:
        data = kite.generate_session(request_token, api_secret=config.API_SECRET)
    except Exception as exc:
        raise RuntimeError(f"generate_session() failed: {exc}") from exc

    new_token = data["access_token"]
    kite.set_access_token(new_token)
    save_access_token(new_token)
    log.info("New access token generated successfully.")
    return new_token


def interactive_token_refresh(sheet_helper=None) -> KiteConnect:
    """
    Prompt the user for a fresh request_token, generate a new access token,
    and return a ready-to-use KiteConnect instance.

    Optionally writes status updates to Google Sheets via *sheet_helper*
    (expected to have a ``set_status(msg)`` method).
    """
    msg = "Access Token Expired — please complete the Kite login flow."
    log.warning(msg)
    if sheet_helper:
        sheet_helper.set_status(msg)

    print("\n" + "=" * 60)
    print(msg)
    print(
        f"Open:  https://kite.trade/connect/login?api_key={config.API_KEY}"
    )
    print("Complete login, then paste the request_token from the redirect URL.")
    request_token = input("Enter request_token: ").strip()

    try:
        new_token = generate_new_token(request_token)
    except RuntimeError as exc:
        log.error("Token refresh failed: %s", exc)
        if sheet_helper:
            sheet_helper.set_status(f"Token refresh failed: {exc}")
        raise

    return build_kite(new_token)
