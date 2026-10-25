"""
main.py
=======

Main entry point and CLI orchestrator for the Stock Data Automation Tool.

Supported Pipelines:
    1. RSI Historical Analysis (--mode rsi):
       - Reads stock symbols from the configured Google Sheet.
       - Authenticates with Zerodha Kite Connect and loads instrument tokens.
       - Generates weekly target sampling dates spanning configured lookback years
         (dynamically switching between Thursday and Tuesday with holiday fallback).
       - Fetches 1-minute historical candles from Kite Connect.
       - Computes RSI(14) and RSI(10) over full daily trading sessions using
         Wilder's smoothing method.
       - Extracts the specified closing session window (Spot, RSI14, RSI10).
       - Writes and formats the output Excel workbook.

    2. Raw Expiry-Week Market Data Export (--mode raw-export):
       - Downloads raw 1-minute OHLC market data for key benchmark indices and
         derivatives (NIFTY 50, NIFTY BANK, NIFTY Futures, and INDIA VIX).
       - Consolidates Monday and weekly expiry sessions across configured lookback years.
       - Saves consolidated results to a structured CSV in the output directory.
"""

import argparse
import logging
from datetime import time as dt_time
import sys
from typing import Dict, List, Optional

import config
from excel_writer import ExcelWriter, generate_output_time_slots
from google_sheets import GoogleSheetsClient, GoogleSheetsError
from historical_data import (
    candles_to_dataframe,
    download_expiry_week_raw_data,
    generate_weekly_target_dates,
    get_trading_day_data,
)
from indicators import add_rsi_indicators
from kite_helper import KiteHelper, KiteHelperError
from logger import Timer, log_progress, setup_logger
from utils import safe_float

logger = setup_logger()


def build_values_by_time(day_df, time_slots) -> Dict[dt_time, Dict[str, Optional[float]]]:
    """Build a {time: {"spot": ..., "rsi14": ..., "rsi10": ...}} mapping for
    the rows of ``day_df`` that fall within the given time slots.

    Args:
        day_df: DataFrame for a single trading day, containing ``date``,
            ``close``, ``rsi_14``, and ``rsi_10`` columns, sorted ascending.
        time_slots: List of ``datetime.time`` objects representing the
            minutes to extract.

    Returns:
        A dict mapping each ``datetime.time`` present in ``day_df`` to its
        spot/RSI14/RSI10 values.
    """
    values_by_time: Dict[dt_time, Dict[str, Optional[float]]] = {}

    if day_df.empty:
        return values_by_time

    slot_set = set(time_slots)

    for _, row in day_df.iterrows():
        row_time = row["date"].time()
        if row_time not in slot_set:
            continue

        values_by_time[row_time] = {
            "spot": safe_float(row.get("close")),
            "rsi14": safe_float(row.get("rsi_14")),
            "rsi10": safe_float(row.get("rsi_10")),
        }

    return values_by_time


def process_stock(
    stock: str,
    kite_helper: KiteHelper,
    weekly_dates: list,
    excel_writer: ExcelWriter,
    time_slots: list,
    timer: Timer,
    stock_index: int,
    total_stocks: int,
) -> None:
    """Process a single stock across all configured weekly dates.

    Guarantees that a single stock's missing token or API failure does not abort
    the whole run, preserving column alignment with "N/A" placeholders.
    """
    logger.info(
        "=== Processing stock %d/%d: %s ===", stock_index, total_stocks, stock
    )

    try:
        token = kite_helper.get_token(stock)
    except KiteHelperError as exc:
        logger.error("Could not load instrument tokens: %s", exc)
        token = None

    if token is None:
        logger.error(
            "No instrument token found for '%s'. Writing N/A rows for all "
            "%d week(s) and skipping this stock.",
            stock,
            len(weekly_dates),
        )
        for _ in weekly_dates:
            excel_writer.add_row(stock, None, {})
        return

    total_weeks = len(weekly_dates)
    for week_index, target_date in enumerate(weekly_dates, start=1):
        logger.debug(
            "[%s] Week %d/%d - target date: %s",
            stock,
            week_index,
            total_weeks,
            target_date,
        )

        try:
            actual_date, candles = get_trading_day_data(kite_helper, token, target_date)
        except Exception as exc:  # defensive: never let one week abort the run
            logger.error(
                "[%s] Unexpected error fetching data for week of %s: %s",
                stock,
                target_date,
                exc,
            )
            actual_date, candles = None, []

        if actual_date is None or not candles:
            logger.warning(
                "[%s] No data available for week of %s; writing N/A row.",
                stock,
                target_date,
            )
            excel_writer.add_row(stock, None, {})
            continue

        try:
            day_df = candles_to_dataframe(candles)
            day_df = add_rsi_indicators(day_df, config.RSI_PERIODS)
            values_by_time = build_values_by_time(day_df, time_slots)
        except Exception as exc:
            logger.error(
                "[%s] Failed to compute indicators for %s: %s",
                stock,
                actual_date,
                exc,
            )
            values_by_time = {}

        excel_writer.add_row(stock, actual_date, values_by_time)

    log_progress(logger, stock_index, total_stocks, timer, label="Stocks processed")


def run_rsi_pipeline(custom_stocks: Optional[List[str]] = None) -> int:
    """Execute the full RSI historical analysis pipeline end-to-end."""
    timer = Timer()
    timer.start()

    logger.info("Starting RSI Historical Data pipeline.")

    # 1. Read stock list
    if custom_stocks:
        stocks = [s.strip().upper() for s in custom_stocks if s.strip()]
        logger.info("Using %d stock(s) specified via CLI: %s", len(stocks), ", ".join(stocks))
    else:
        try:
            sheets_client = GoogleSheetsClient()
            stocks = sheets_client.get_stock_names()
        except GoogleSheetsError as exc:
            logger.error("Failed to read stock names from Google Sheets: %s", exc)
            return 1

    if not stocks:
        logger.error("No stock names found to process. Aborting.")
        return 1

    logger.info("Stocks to process (%d): %s", len(stocks), ", ".join(stocks))

    # 2. Initialize Kite Connect helper and load instrument tokens
    try:
        kite_helper = KiteHelper()
        kite_helper.load_instruments()
    except KiteHelperError as exc:
        logger.error("Failed to initialize Kite Connect: %s", exc)
        return 1

    # 3. Generate weekly target dates and output time slots
    weekly_dates = generate_weekly_target_dates()
    time_slots = generate_output_time_slots()

    logger.info(
        "Processing %d weekly date(s) spanning the last %d year(s), from %s to %s.",
        len(weekly_dates),
        config.YEARS_BACK,
        weekly_dates[0] if weekly_dates else "N/A",
        weekly_dates[-1] if weekly_dates else "N/A",
    )

    # 4. Process each stock and populate Excel workbook
    excel_writer = ExcelWriter()
    total_stocks = len(stocks)

    for stock_index, stock in enumerate(stocks, start=1):
        try:
            process_stock(
                stock=stock,
                kite_helper=kite_helper,
                weekly_dates=weekly_dates,
                excel_writer=excel_writer,
                time_slots=time_slots,
                timer=timer,
                stock_index=stock_index,
                total_stocks=total_stocks,
            )
        except Exception as exc:
            logger.error("Unexpected error processing stock '%s': %s", stock, exc)
            for _ in weekly_dates:
                excel_writer.add_row(stock, None, {})

    # 5. Save the output workbook
    try:
        excel_writer.save()
    except OSError as exc:
        logger.error("Failed to save output workbook: %s", exc)
        return 1

    logger.info(
        "Pipeline complete. Processed %d stock(s) in %s. Saved to %s.",
        total_stocks,
        timer.elapsed_str(),
        config.OUTPUT_EXCEL,
    )
    return 0


def run_raw_export_pipeline() -> int:
    """Execute the raw expiry-week historical market data export pipeline."""
    timer = Timer()
    timer.start()

    logger.info("Starting raw expiry-week historical data pipeline.")

    try:
        kite_helper = KiteHelper()
        kite_helper.load_instruments()
    except KiteHelperError as exc:
        logger.error("Failed to initialize Kite Connect: %s", exc)
        return 1

    weekly_dates = generate_weekly_target_dates()
    logger.info(
        "Processing %d weekly expiry date(s) spanning the last %d year(s), from %s to %s.",
        len(weekly_dates),
        config.YEARS_BACK,
        weekly_dates[0] if weekly_dates else "N/A",
        weekly_dates[-1] if weekly_dates else "N/A",
    )

    try:
        output_files = download_expiry_week_raw_data(
            kite_helper,
            weekly_dates=weekly_dates,
            output_dir=config.RAW_DATA_OUTPUT_DIR,
        )
    except Exception as exc:
        logger.error("Unexpected error while exporting raw data: %s", exc)
        return 1

    logger.info(
        "Pipeline complete. Wrote %d consolidated CSV output file(s) to %s in %s.",
        len(output_files),
        config.RAW_DATA_OUTPUT_DIR,
        timer.elapsed_str(),
    )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Parse command line arguments and execute the chosen pipeline."""
    parser = argparse.ArgumentParser(
        description="Stock Data Automation Tool: Kite Connect market data retrieval & processing."
    )
    parser.add_argument(
        "--mode",
        choices=["rsi", "raw-export"],
        default="rsi",
        help="Pipeline mode to run: 'rsi' (Google Sheets + Kite Connect + RSI + Excel) "
        "or 'raw-export' (Monday + Expiry session OHLC CSV export for indices/derivatives). "
        "Default: 'rsi'.",
    )
    parser.add_argument(
        "--stocks",
        nargs="+",
        default=None,
        help="Optional list of stock symbols to process in 'rsi' mode, overriding Google Sheets "
        "(e.g. --stocks INFY RELIANCE TCS).",
    )

    args = parser.parse_args(argv)

    if args.mode == "raw-export":
        return run_raw_export_pipeline()
    return run_rsi_pipeline(custom_stocks=args.stocks)


if __name__ == "__main__":
    sys.exit(main())
