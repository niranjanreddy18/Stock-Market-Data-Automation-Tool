"""
utils.py
========

Small, generic helper functions shared across multiple modules: weekday
name resolution, weekly target-date computation (implementing the
Thursday -> Tuesday weekly-day switch), weekend checks, and safe numeric
conversion used when reading pandas values that may be ``NaN``.

Keeping these helpers in one place avoids duplicating the same logic in
``historical_data.py``, ``main.py``, and ``excel_writer.py``.
"""

import math
from datetime import date, timedelta
from typing import Optional

#: Maps weekday names (as used in config.py) to Python's Monday=0..Sunday=6
#: weekday index convention.
WEEKDAY_NAME_TO_INDEX = {
    "MONDAY": 0,
    "TUESDAY": 1,
    "WEDNESDAY": 2,
    "THURSDAY": 3,
    "FRIDAY": 4,
    "SATURDAY": 5,
    "SUNDAY": 6,
}


class InvalidWeekdayNameError(ValueError):
    """Raised when a configured weekday name is not recognized."""


def weekday_name_to_index(weekday_name: str) -> int:
    """Convert a weekday name (e.g. ``"THURSDAY"``) to its index (0-6).

    Args:
        weekday_name: Weekday name, case-insensitive (e.g. ``"tuesday"``,
            ``"THURSDAY"``).

    Returns:
        The corresponding weekday index using Python's convention
        (Monday=0 ... Sunday=6).

    Raises:
        InvalidWeekdayNameError: If ``weekday_name`` is not a recognized
            weekday name.
    """
    key = weekday_name.strip().upper()
    if key not in WEEKDAY_NAME_TO_INDEX:
        raise InvalidWeekdayNameError(
            f"Unrecognized weekday name '{weekday_name}'. Expected one of: "
            f"{', '.join(WEEKDAY_NAME_TO_INDEX.keys())}."
        )
    return WEEKDAY_NAME_TO_INDEX[key]


def monday_of_week(any_date: date) -> date:
    """Return the Monday date of the ISO week containing ``any_date``.

    Args:
        any_date: Any date within the week of interest.

    Returns:
        The ``datetime.date`` corresponding to the Monday of that week.
    """
    return any_date - timedelta(days=any_date.weekday())


def is_weekend(target_date: date) -> bool:
    """Return True if ``target_date`` falls on a Saturday or Sunday.

    Args:
        target_date: The date to check.

    Returns:
        True if the date is a Saturday or Sunday, False otherwise.
    """
    return target_date.weekday() >= 5


def resolve_weekly_target_date(
    week_monday: date,
    change_date: date,
    old_weekly_day: str,
    new_weekly_day: str,
) -> date:
    """Determine the target sampling date for a given week.

    Implements the dynamic weekly-day switch rule: weeks starting strictly
    before ``change_date`` use ``old_weekly_day``; weeks starting on/after
    ``change_date`` use ``new_weekly_day``. No calendar dates are
    hardcoded -- everything is derived from ``week_monday`` and the
    supplied configuration values.

    Args:
        week_monday: The Monday date that begins the week in question.
        change_date: The date on which the weekly sampling day switches
            from ``old_weekly_day`` to ``new_weekly_day``.
        old_weekly_day: Weekday name to use for weeks before ``change_date``.
        new_weekly_day: Weekday name to use for weeks on/after
            ``change_date``.

    Returns:
        The ``datetime.date`` within the given week that should be used as
        the weekly sampling target (before any holiday fallback is applied).
    """
    if week_monday >= change_date:
        weekday_name = new_weekly_day
    else:
        weekday_name = old_weekly_day

    weekday_index = weekday_name_to_index(weekday_name)
    return week_monday + timedelta(days=weekday_index)


def safe_float(value: object) -> Optional[float]:
    """Safely convert a value (which may be ``None``, ``NaN``, or numeric)
    to a plain Python ``float``.

    Args:
        value: The value to convert. Typically a pandas/numpy scalar that
            may be ``NaN`` to represent a missing value.

    Returns:
        A ``float`` if ``value`` is a valid, finite number; otherwise
        ``None``.
    """
    if value is None:
        return None
    try:
        float_value = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(float_value) or math.isinf(float_value):
        return None
    return float_value


def format_seconds_as_hms(total_seconds: float) -> str:
    """Format a duration in seconds as ``HH:MM:SS``.

    Args:
        total_seconds: Duration in seconds.

    Returns:
        A string formatted as ``HH:MM:SS``.
    """
    seconds_int = int(total_seconds)
    hours, remainder = divmod(seconds_int, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
