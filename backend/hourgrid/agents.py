"""Trading agents. Each home's agent posts orders before the interval starts, using the
AI forecast, the Time-of-Day tariff and the owner's preferences. Rules are deliberately
transparent so every order comes with a plain-language reason.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import tariffs
from .auction import Order
from .config import settings
from .neighbourhood import Home

RS = tariffs.RS
FORECAST_HAIRCUT = 0.9  # offer 90% of forecast surplus to limit delivery shortfalls


def _rs(x: int) -> str:
    return tariffs.fmt(x)


def home_orders(h: Home, ts, gen_fc: float, load_fc: float) -> list[Order]:
    p = h.prefs
    if not p.get("participate", True):
        return []
    lo, hi = tariffs.price_bounds(ts)
    agg = float(p.get("aggressiveness", 0.5))
    net = gen_fc - load_fc
    period = tariffs.period_label(ts)
    orders: list[Order] = []
    if net > 20:
        wh = int(net * FORECAST_HAIRCUT * float(p.get("sell_share", 1.0)))
        price = int(lo + agg * (hi - lo) * 0.5)
        if p.get("min_sell_price") is not None:
            price = max(price, int(float(p["min_sell_price"]) * RS))
        if wh > 0:
            orders.append(Order(h.home_id, "sell", wh, price,
                                f"Forecast surplus {net:.0f} Wh ({gen_fc:.0f} solar - {load_fc:.0f} use); "
                                f"offering {wh} Wh at {_rs(price)}/kWh, above the {_rs(tariffs.FEED_IN)} the grid pays for surplus."))
    elif net < -20:
        wh = int(-net)
        if p.get("prefer_green"):
            price = hi
            why = "prefers neighbour solar, bids up to the grid-equivalent price"
        else:
            price = int(hi - agg * (hi - lo) * 0.5)
            why = f"bids below the {period} grid tariff of {_rs(tariffs.grid_price(ts))}"
        if p.get("max_buy_price") is not None:
            price = min(price, int(float(p["max_buy_price"]) * RS))
        if price >= lo:
            orders.append(Order(h.home_id, "buy", wh, price,
                                f"Forecast need {wh} Wh; {why}: {_rs(price)}/kWh."))
    return orders


@dataclass
class BatteryState:
    soc_wh: float
    capacity_wh: float
    power_w: float
    efficiency: float = 0.92  # one-way
    min_soc: float = 0.1

    def headroom_wh(self) -> float:
        return max(0.0, (self.capacity_wh * 0.98 - self.soc_wh) / self.efficiency)

    def available_wh(self) -> float:
        return max(0.0, (self.soc_wh - self.capacity_wh * self.min_soc) * self.efficiency)


def battery_orders(b: BatteryState, ts) -> list[Order]:
    """Community battery: soak up cheap midday surplus, sell into the evening peak."""
    lo, hi = tariffs.price_bounds(ts)
    max_step = b.power_w * 0.25
    period = tariffs.period(ts)
    orders: list[Order] = []
    if period == "solar":
        wh = int(min(max_step, b.headroom_wh()))
        if wh > 0:
            price = lo + int(0.35 * (hi - lo))
            orders.append(Order("BAT", "buy", wh, price,
                                f"Solar hours: charging from neighbour surplus at {_rs(price)}/kWh "
                                f"(SoC {b.soc_wh / b.capacity_wh:.0%}). Homes outbid it, so it only takes what's left."))
    elif period == "peak":
        remaining = max(1, (tariffs.PEAK_HOURS[1] - ts.hour) * 4 - ts.minute // 15)
        wh = int(min(max_step, b.available_wh(), b.available_wh() / remaining * 1.3))
        price = max(lo, hi - int(0.25 * (hi - lo)))
        if wh > 0:
            orders.append(Order("BAT", "sell", wh, price,
                                f"Evening peak: discharging stored solar at {_rs(price)}/kWh, "
                                f"well under the {_rs(tariffs.grid_price(ts))} peak tariff (SoC {b.soc_wh / b.capacity_wh:.0%})."))
    return orders


def battery_spec() -> tuple[float, float]:
    """(kWh, kW). Commercial districts get a bigger shared battery."""
    scale = 5 if tariffs.PROFILE.prosumer_kind == "commercial" else 1
    return settings.battery_kwh * scale, settings.battery_kw * scale


def new_battery() -> BatteryState:
    kwh, kw = battery_spec()
    cap = kwh * 1000
    return BatteryState(soc_wh=cap * 0.3, capacity_wh=cap, power_w=kw * 1000)
