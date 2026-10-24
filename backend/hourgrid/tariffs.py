"""Retail tariffs, feed-in and local-trading charges for the active country profile.

All prices are integers in micro-units of the profile currency per kWh
(1 INR / TRY / EUR = 1_000_000). Module-level values are rebound by set_profile(),
so other modules must read them as tariffs.X (not `from tariffs import X`).
Environment overrides: TARIFF_FEED_IN, P2P_WHEELING_FEE, P2P_TRANSACTION_FEE, and
TARIFF_<KIND> (e.g. TARIFF_PEAK) to override every period of that kind.
"""
from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
from .timeutil import floor_local

from .countries import Profile, get

RS = 1_000_000  # micro-units per currency unit (name kept for backwards compatibility)
UNIT = RS

PROFILE: Profile = get(None)
PERIODS: list = []
FEED_IN = WHEELING_FEE = TRANSACTION_FEE = TOTAL_FEE = HALF_FEE = 0
SOLAR_HOURS = (9, 17)
PEAK_HOURS = (18, 22)
_dynamic: dict = {}  # local hour (Timestamp) -> retail micro/kWh (dynamic-tariff countries)


def _env(name: str, default: float) -> int:
    return int(round(float(os.getenv(name, default)) * UNIT))


def set_profile(p: Profile) -> None:
    global PROFILE, PERIODS, FEED_IN, WHEELING_FEE, TRANSACTION_FEE, TOTAL_FEE, HALF_FEE, SOLAR_HOURS, PEAK_HOURS
    PROFILE = p
    PERIODS = [(per.kind, per.label, per.start, per.end, _env(f"TARIFF_{per.kind.upper()}", per.price)) for per in p.periods]
    FEED_IN = _env("TARIFF_FEED_IN", p.feed_in)
    WHEELING_FEE = _env("P2P_WHEELING_FEE", p.wheeling_fee)
    TRANSACTION_FEE = _env("P2P_TRANSACTION_FEE", p.transaction_fee)
    TOTAL_FEE = WHEELING_FEE + TRANSACTION_FEE
    HALF_FEE = TOTAL_FEE // 2
    solar = [x for x in PERIODS if x[0] == "solar"]
    peak = [x for x in PERIODS if x[0] == "peak"]
    SOLAR_HOURS = (solar[0][2], solar[0][3]) if solar else (9, 17)
    PEAK_HOURS = (peak[0][2], peak[0][3]) if peak else (18, 22)
    _dynamic.clear()


def set_dynamic_prices(hourly_wholesale: pd.Series | None) -> None:
    """For dynamic-tariff countries: retail = day-ahead wholesale + fixed adder."""
    _dynamic.clear()
    if hourly_wholesale is None or PROFILE.dynamic_retail_adder is None:
        return
    adder = int(PROFILE.dynamic_retail_adder * UNIT)
    for ts, v in hourly_wholesale.items():
        _dynamic[floor_local(pd.Timestamp(ts), "h")] = max(int(v) + adder, int(0.05 * UNIT))


def _period(ts: datetime):
    h = ts.hour
    for p in PERIODS:
        if p[2] <= h < p[3]:
            return p
    return PERIODS[-1]


def period(ts: datetime) -> str:
    return _period(ts)[0]


def period_label(ts: datetime) -> str:
    return _period(ts)[1]


def grid_price(ts: datetime) -> int:
    if _dynamic:
        v = _dynamic.get(floor_local(pd.Timestamp(ts), "h"))
        if v is not None:
            return v
    return _period(ts)[4]


def price_bounds(ts: datetime) -> tuple[int, int]:
    """Auction clamp. A seller never accepts less than feed-in + their fee share;
    a buyer never pays more than the grid tariff minus their fee share."""
    lo = FEED_IN + HALF_FEE
    hi = grid_price(ts) - (TOTAL_FEE - HALF_FEE)
    return lo, max(hi, lo + int(0.01 * UNIT))


def fmt(micro: int | float) -> str:
    return f"{PROFILE.symbol}{micro / UNIT:.2f}"


def as_dict() -> dict:
    p = PROFILE
    return {
        "currency": p.currency, "symbol": p.symbol,
        "periods": [{"kind": k, "label": l, "start": s, "end": e, "price": v / UNIT} for k, l, s, e, v in PERIODS],
        "feed_in": FEED_IN / UNIT, "wheeling_fee": WHEELING_FEE / UNIT, "transaction_fee": TRANSACTION_FEE / UNIT,
        "solar_hours": SOLAR_HOURS, "peak_hours": PEAK_HOURS, "dynamic": bool(_dynamic),
        "tariff_source": p.tariff_source, "fee_source": p.fee_source,
    }


set_profile(PROFILE)
