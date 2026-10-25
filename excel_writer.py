"""
excel_writer.py
===============

Builds and writes the final Excel workbook: one worksheet, one row per
(stock, weekly trading day), with Spot/RSI14/RSI10 columns for each minute
in the configured output window (14:55 - 15:15 inclusive by default).
"""

import logging
from datetime import date, datetime, time as dt_time, timedelta
from typing import Dict, List, Optional, Union

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

import config

logger = logging.getLogger("rsi_project")

#: Sentinel written to a cell whenever a value is unavailable/missing.
MISSING_VALUE = "N/A"

CellValue = Union[str, float, int]


def generate_output_time_slots(
    window_start: dt_time = config.OUTPUT_WINDOW_START,
    window_end: dt_time = config.OUTPUT_WINDOW_END,
) -> List[dt_time]:
    """Generate the list of minute-level time slots for the output window.

    Args:
        window_start: Inclusive start time of the output window.
        window_end: Inclusive end time of the output window.

    Returns:
        A chronologically ordered list of ``datetime.time`` objects, one
        per minute, from ``window_start`` to ``window_end`` inclusive.
    """
    base_date = date.today()
    start_dt = datetime.combine(base_date, window_start)
    end_dt = datetime.combine(base_date, window_end)

    slots: List[dt_time] = []
    current = start_dt
    while current <= end_dt:
        slots.append(current.time())
        current += timedelta(minutes=1)

    return slots


def format_time_label(t: dt_time) -> str:
    """Format a ``datetime.time`` as a short label like ``"2:55"``.

    Hours are converted from 24-hour to a leading-zero-free 12-hour style
    (e.g. 14 -> 2, 15 -> 3), matching the required Excel column header
    format for the afternoon market session.

    Args:
        t: The time to format.

    Returns:
        A string in the form ``"H:MM"``.
    """
    hour_12 = t.hour if t.hour <= 12 else t.hour - 12
    if hour_12 == 0:
        hour_12 = 12
    return f"{hour_12}:{t.minute:02d}"


class ExcelWriter:
    """Builds the output workbook incrementally, one row at a time.

    Args:
        output_path: File path where the workbook will be saved.
        time_slots: Ordered list of ``datetime.time`` objects representing
            each minute column to include in the output.
    """

    def __init__(
        self,
        output_path: str = config.OUTPUT_EXCEL,
        time_slots: Optional[List[dt_time]] = None,
    ) -> None:
        self.output_path = output_path
        self.time_slots = time_slots if time_slots is not None else generate_output_time_slots()

        self.workbook = Workbook()
        self.worksheet: Worksheet = self.workbook.active
        self.worksheet.title = "RSI Data"

        self._write_header()
        self._next_row = 2  # row 1 is the header

    def _write_header(self) -> None:
        """Write the header row: Stock, Date, then Spot/RSI14/RSI10 triples."""
        headers: List[str] = ["Stock", "Date"]

        for slot in self.time_slots:
            label = format_time_label(slot)
            headers.append(f"{label} Spot")
            headers.append(f"{label} RSI14")
            headers.append(f"{label} RSI10")

        bold_font = Font(bold=True)
        for col_idx, header in enumerate(headers, start=1):
            cell = self.worksheet.cell(row=1, column=col_idx, value=header)
            cell.font = bold_font

        # Freeze the header row and the first two identifying columns.
        self.worksheet.freeze_panes = "C2"

    def add_row(
        self,
        stock: str,
        trading_date: Optional[date],
        values_by_time: Dict[dt_time, Dict[str, CellValue]],
    ) -> None:
        """Append one row to the worksheet for a given stock and date.

        Args:
            stock: Trading symbol, e.g. ``"RELIANCE"``.
            trading_date: The actual trading date this row represents.
                If ``None`` (no data could be found at all for this week),
                the date cell and every value cell are written as
                ``MISSING_VALUE``.
            values_by_time: Mapping from each minute in ``self.time_slots``
                to a dict with keys ``"spot"``, ``"rsi14"``, ``"rsi10"``.
                Any minute missing from this mapping (or with a ``None``
                value for a given key) is written as ``MISSING_VALUE``.
        """
        row_values: List[CellValue] = [stock]
        row_values.append(
            trading_date.strftime("%Y-%m-%d") if trading_date is not None else MISSING_VALUE
        )

        for slot in self.time_slots:
            slot_values = values_by_time.get(slot, {})
            spot = slot_values.get("spot")
            rsi14 = slot_values.get("rsi14")
            rsi10 = slot_values.get("rsi10")

            row_values.append(spot if spot is not None else MISSING_VALUE)
            row_values.append(rsi14 if rsi14 is not None else MISSING_VALUE)
            row_values.append(rsi10 if rsi10 is not None else MISSING_VALUE)

        for col_idx, value in enumerate(row_values, start=1):
            self.worksheet.cell(row=self._next_row, column=col_idx, value=value)

        self._next_row += 1

    def auto_size_columns(self, max_width: int = 18) -> None:
        """Apply a reasonable fixed column width to every column.

        Args:
            max_width: Column width (in characters) to apply.
        """
        total_columns = 2 + len(self.time_slots) * 3
        for col_idx in range(1, total_columns + 1):
            letter = get_column_letter(col_idx)
            self.worksheet.column_dimensions[letter].width = max_width

    def save(self) -> None:
        """Save the workbook to ``self.output_path``.

        Raises:
            OSError: If the file cannot be written (e.g. permissions, open
                in another program).
        """
        self.auto_size_columns()
        try:
            self.workbook.save(self.output_path)
            logger.info("Excel workbook saved to '%s'.", self.output_path)
        except OSError as exc:
            logger.error("Failed to save Excel workbook to '%s': %s", self.output_path, exc)
            raise
