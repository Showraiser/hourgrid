"""DST-safe rounding for tz-aware timestamps.

pandas' own .floor()/.ceil() on a tz-aware value converts to local wall-clock time and back,
and raises when that wall-clock time is ambiguous (the repeated hour when clocks go back,
e.g. Europe/Berlin on the last Sunday of October). These helpers subtract the wall-clock
remainder in absolute time instead, so they never raise and give the same result as
.floor() everywhere else.
"""
from __future__ import annotations

import pandas as pd


def floor_local(x, freq: str = "h"):
    """Floor a Timestamp or DatetimeIndex to `freq` in local wall-clock time, DST-safe."""
    tz = getattr(x, "tz", None) if isinstance(x, pd.DatetimeIndex) else getattr(x, "tzinfo", None)
    if tz is None:
        return x.floor(freq)
    wall = x.tz_localize(None)
    return x - (wall - wall.floor(freq))
