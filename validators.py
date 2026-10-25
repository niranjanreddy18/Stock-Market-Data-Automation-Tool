# =============================================================================
# validators.py
# Startup validation — checks every external dependency before processing.
# Returns precise error messages; never raises.
# =============================================================================

import logging
import os
from dataclasses import dataclass, field

import config

log = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)
        log.error("Validation FAILED: %s", msg)

    def warn(self, msg: str) -> None:
        log.warning("Validation WARNING: %s", msg)

    def summary(self) -> str:
        return "OK" if self.ok else " | ".join(self.errors)


def validate_all(sheet_helper=None) -> ValidationResult:
    """
    Run every validation check.
    Writes precise error messages to Google Sheets when *sheet_helper* is provided.
    Returns a ValidationResult; caller should stop execution when result.ok is False.
    """
    result = ValidationResult()

    # A. API Key
    if not config.API_KEY:
        result.fail("Invalid API Key — KITE_API_KEY is not set")

    # B. API Secret
    if not config.API_SECRET:
        result.fail("API Secret missing — KITE_API_SECRET is not set")

    # C. Access Token
    _check_access_token(result)

    # D. credentials.json
    if not os.path.exists(config.GOOGLE_CREDENTIALS_FILE):
        result.fail(f"Google credentials file missing: {config.GOOGLE_CREDENTIALS_FILE}")

    # E & F. Google auth + sheet accessibility
    if os.path.exists(config.GOOGLE_CREDENTIALS_FILE):
        _check_google_sheet(result)

    # G. NFO instruments file (existence; freshness is handled by nfo_downloader)
    _check_nfo_file(result)

    # H. Required configuration
    _check_required_config(result)

    # Write to sheet if something failed
    if not result.ok and sheet_helper:
        try:
            sheet_helper.set_status(result.summary())
        except Exception:
            pass   # sheet may itself be broken

    if result.ok:
        log.info("All startup validations passed.")
    else:
        log.error("Startup validation errors: %s", result.summary())

    return result


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_access_token(result: ValidationResult) -> None:
    from token_manager import load_access_token
    token = load_access_token()
    if not token:
        result.fail("Access Token missing — run Kite login flow and save token")
    else:
        log.info("Access token file present.")


def _check_google_sheet(result: ValidationResult) -> None:
    try:
        import google_sheets
        google_sheets.connect()
        log.info("Google Sheet accessible.")
    except FileNotFoundError:
        result.fail("Google credentials file missing")
    except Exception as exc:
        result.fail(f"Google Sheet not accessible: {exc}")


def _check_nfo_file(result: ValidationResult) -> None:
    if not os.path.exists(config.NFO_CSV_PATH):
        result.warn(
            f"NFO instruments file not found at {config.NFO_CSV_PATH} — "
            "nfo_downloader will attempt download on startup."
        )
    else:
        log.info("NFO instruments file found: %s", config.NFO_CSV_PATH)


def _check_required_config(result: ValidationResult) -> None:
    if not config.SHEET_KEY:
        result.fail("Configuration missing: SHEET_KEY is empty")
