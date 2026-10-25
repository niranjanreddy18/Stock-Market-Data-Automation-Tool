"""
logger.py
=========

Centralized logging configuration and small utility helpers for tracking
elapsed time and reporting progress percentage during the data pipeline run.
"""

import logging
import sys
import time
from typing import Optional

import config
from utils import format_seconds_as_hms


def setup_logger(name: str = "rsi_project") -> logging.Logger:
    """Create and configure a logger that writes to both console and file.

    The logger is configured only once per process. Calling this function
    multiple times with the same ``name`` will return the same configured
    logger instance without duplicating handlers.

    Args:
        name: Name of the logger to create/retrieve.

    Returns:
        A fully configured ``logging.Logger`` instance.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        # Already configured -- avoid attaching duplicate handlers if this
        # function is called more than once.
        return logger

    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    try:
        file_handler = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:  # pragma: no cover - defensive, e.g. read-only FS
        logger.warning("Could not attach file log handler: %s", exc)

    logger.propagate = False
    return logger


class Timer:
    """Simple elapsed-time tracker usable as a context manager or directly.

    Example:
        >>> timer = Timer()
        >>> timer.start()
        >>> # ... do work ...
        >>> elapsed_seconds = timer.elapsed()
    """

    def __init__(self) -> None:
        self._start_time: Optional[float] = None

    def start(self) -> None:
        """Start (or restart) the timer."""
        self._start_time = time.monotonic()

    def elapsed(self) -> float:
        """Return elapsed seconds since ``start()`` was called.

        Returns:
            Elapsed time in seconds. Returns ``0.0`` if the timer was never
            started.
        """
        if self._start_time is None:
            return 0.0
        return time.monotonic() - self._start_time

    def elapsed_str(self) -> str:
        """Return a human readable elapsed time string ``HH:MM:SS``."""
        return format_seconds_as_hms(self.elapsed())

    def __enter__(self) -> "Timer":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


def log_progress(
    logger: logging.Logger,
    current: int,
    total: int,
    timer: Optional[Timer] = None,
    label: str = "Overall progress",
) -> None:
    """Log a standardized progress message with percentage complete.

    Args:
        logger: Logger instance to write the message to.
        current: Number of items completed so far (1-indexed for display).
        total: Total number of items to process.
        timer: Optional ``Timer`` instance to include elapsed time in the log.
        label: A short label describing what is being tracked.
    """
    if total <= 0:
        percentage = 100.0
    else:
        percentage = (current / total) * 100.0

    elapsed_part = f" | Elapsed: {timer.elapsed_str()}" if timer is not None else ""
    logger.info(
        "%s: %d/%d (%.1f%%)%s", label, current, total, percentage, elapsed_part
    )
