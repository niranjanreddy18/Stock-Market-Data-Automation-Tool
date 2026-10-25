"""
google_sheets.py
================

Handles all interaction with Google Sheets via the ``gspread`` library and
a Google Service Account credential, to read the list of stock symbols from
column A of the configured spreadsheet.
"""

import logging
from typing import List, Optional

import gspread
from google.oauth2.service_account import Credentials

import config

logger = logging.getLogger("rsi_project")

#: OAuth scopes required for read-only access to Google Sheets and Drive
#: metadata (Drive scope is required by gspread to open sheets by name).
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


class GoogleSheetsError(Exception):
    """Raised when the Google Sheets client encounters an unrecoverable error."""


class GoogleSheetsClient:
    """Thin wrapper around ``gspread`` for reading stock names from a sheet.

    Args:
        service_account_json: Path to the Google service account JSON key
            file.
        spreadsheet_name: Name of the Google Spreadsheet to open.
        worksheet_name: Optional worksheet/tab name. If not provided, the
            first worksheet in the spreadsheet is used.
    """

    def __init__(
        self,
        service_account_json: str = config.GOOGLE_SERVICE_ACCOUNT_JSON,
        spreadsheet_name: str = config.SPREADSHEET_NAME,
        worksheet_name: str = config.WORKSHEET_NAME,
    ) -> None:
        self.service_account_json = service_account_json
        self.spreadsheet_name = spreadsheet_name
        self.worksheet_name = worksheet_name
        self._client: Optional[gspread.Client] = None

    def _get_client(self) -> gspread.Client:
        """Lazily create and cache an authorized ``gspread`` client.

        Returns:
            An authorized ``gspread.Client`` instance.

        Raises:
            GoogleSheetsError: If the credentials file cannot be loaded or
                authorization fails.
        """
        if self._client is not None:
            return self._client

        try:
            credentials = Credentials.from_service_account_file(
                self.service_account_json, scopes=_SCOPES
            )
            self._client = gspread.authorize(credentials)
        except FileNotFoundError as exc:
            raise GoogleSheetsError(
                f"Service account JSON file not found: {self.service_account_json}"
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive catch-all
            raise GoogleSheetsError(
                f"Failed to authorize Google Sheets client: {exc}"
            ) from exc

        return self._client

    def get_stock_names(self) -> List[str]:
        """Read stock names from column A of the configured spreadsheet.

        Blank rows/cells are ignored. Leading/trailing whitespace is
        stripped from each value, and values are upper-cased since Kite
        trading symbols are conventionally upper-case.

        Returns:
            A list of non-empty stock name strings, in the order they
            appear in the sheet.

        Raises:
            GoogleSheetsError: If the spreadsheet or worksheet cannot be
                opened, or if reading values fails.
        """
        client = self._get_client()

        try:
            spreadsheet = client.open(self.spreadsheet_name)
        except gspread.exceptions.SpreadsheetNotFound as exc:
            raise GoogleSheetsError(
                f"Spreadsheet '{self.spreadsheet_name}' not found or not "
                "shared with the service account email."
            ) from exc
        except Exception as exc:
            raise GoogleSheetsError(f"Failed to open spreadsheet: {exc}") from exc

        try:
            if self.worksheet_name:
                worksheet = spreadsheet.worksheet(self.worksheet_name)
            else:
                worksheet = spreadsheet.get_worksheet(0)
        except gspread.exceptions.WorksheetNotFound as exc:
            raise GoogleSheetsError(
                f"Worksheet '{self.worksheet_name}' not found in spreadsheet "
                f"'{self.spreadsheet_name}'."
            ) from exc
        except Exception as exc:
            raise GoogleSheetsError(f"Failed to open worksheet: {exc}") from exc

        try:
            column_values = worksheet.col_values(1)
        except Exception as exc:
            raise GoogleSheetsError(f"Failed to read column A values: {exc}") from exc

        stock_names: List[str] = []
        for raw_value in column_values:
            value = (raw_value or "").strip()
            if not value:
                continue
            stock_names.append(value.upper())

        logger.info("Read %d stock name(s) from Google Sheet.", len(stock_names))
        return stock_names


def connect(
    service_account_json: str = config.GOOGLE_SERVICE_ACCOUNT_JSON,
) -> gspread.Client:
    """Convenience helper to authorize and return a ``gspread.Client`` instance.

    Args:
        service_account_json: Path to the service account JSON key file.

    Returns:
        An authorized ``gspread.Client`` instance.
    """
    client = GoogleSheetsClient(service_account_json=service_account_json)
    return client._get_client()

