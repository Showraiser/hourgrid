"""Real market data where a public source exists.

Türkiye  (EPİAŞ Transparency Platform, free account: EPIAS_USERNAME / EPIAS_PASSWORD)
  - hourly day-ahead market clearing price (PTF), TRY/MWh
  - real-time generation by fuel -> live grid carbon intensity
Germany  (Fraunhofer ISE Energy-Charts, no key)
  - day-ahead price for bidding zone DE-LU, EUR/MWh
  - grid CO2 intensity, g/kWh
India    no free real-time market API (IEX data is not open) -> tariff-based only

Every function returns (value, source, status) and never raises: the market always runs.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

from .countries import Profile

log = logging.getLogger("hourgrid.market_data")
UNIT = 1_000_000
_lock = threading.Lock()
_tgt: dict = {}

# lifecycle-free combustion factors, kg CO2 per kWh generated (typical values)
FUEL_EF = {"lignite": 1.10, "importCoal": 0.95, "blackCoal": 0.95, "asphaltiteCoal": 1.00, "naturalGas": 0.45,
           "lng": 0.45, "fueloil": 0.78, "fuelOil": 0.78, "naphta": 0.78}
NON_GEN = {"date", "hour", "total", "importExport", "id"}


# ---------------------------------------------------------------- EPİAŞ
def _epias_tgt() -> str | None:
    user, pw = os.getenv("EPIAS_USERNAME"), os.getenv("EPIAS_PASSWORD")
    if not user or not pw:
        return None
    with _lock:
        if _tgt.get("v") and _tgt["exp"] > time.time():
            return _tgt["v"]
        r = requests.post("https://giris.epias.com.tr/cas/v1/tickets",
                          data={"username": user, "password": pw},
                          headers={"Accept": "text/plain"}, timeout=15)
        r.raise_for_status()
        tgt = r.text.strip()
        if not tgt.startswith("TGT-"):
            raise ValueError("EPİAŞ login did not return a TGT")
        _tgt.update(v=tgt, exp=time.time() + 100 * 60)  # valid 2 h, refresh early
        return tgt


def _epias(path: str, start: datetime, end: datetime) -> list[dict]:
    tgt = _epias_tgt()
    if not tgt:
        raise PermissionError("set EPIAS_USERNAME and EPIAS_PASSWORD (free EPİAŞ transparency account)")
    body = {"startDate": start.strftime("%Y-%m-%dT00:00:00+03:00"), "endDate": end.strftime("%Y-%m-%dT00:00:00+03:00")}
    r = requests.post(f"https://seffaflik.epias.com.tr/electricity-service/v1/{path}", json=body,
                      headers={"TGT": tgt, "Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    return r.json().get("items", [])


def _epias_prices(start: datetime, end: datetime) -> pd.Series:
    items = _epias("markets/dam/data/mcp", start, end)
    idx = pd.to_datetime([i["date"] for i in items]).tz_convert("Europe/Istanbul")
    return pd.Series([float(i["price"]) * 1000 for i in items], index=idx)  # TRY/MWh -> micro-TRY/kWh


def _epias_intensity() -> tuple[float, str]:
    now = datetime.now()
    items = _epias("generation/data/realtime-generation", now - timedelta(days=1), now)
    if not items:
        raise ValueError("no realtime generation rows")
    last = items[-1]
    total = float(last.get("total") or sum(float(v) for k, v in last.items() if k not in NON_GEN and isinstance(v, (int, float))))
    co2 = sum(float(last.get(k) or 0) * f for k, f in FUEL_EF.items())
    renew = sum(float(last.get(k) or 0) for k in ("wind", "sun", "geothermal", "dammedHydro", "river", "biomass"))
    return co2 / total, f"EPİAŞ real-time generation mix {str(last.get('date', ''))[:16]} · {100 * renew / total:.0f}% renewable"


# ---------------------------------------------------------------- Energy-Charts
def _ec_prices(start: datetime, end: datetime) -> pd.Series:
    r = requests.get("https://api.energy-charts.info/price",
                     params={"bzn": "DE-LU", "start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d")},
                     timeout=25)
    r.raise_for_status()
    j = r.json()
    idx = pd.to_datetime(j["unix_seconds"], unit="s", utc=True).tz_convert("Europe/Berlin")
    s = pd.Series([float("nan") if v is None else float(v) * 1000 for v in j["price"]], index=idx).dropna()
    g = s.groupby(s.index.tz_convert("UTC").floor("h")).mean()
    g.index = g.index.tz_convert("Europe/Berlin")
    return g


def _ec_intensity() -> tuple[float, str]:
    r = requests.get("https://api.energy-charts.info/co2eq", params={"country": "de"}, timeout=25)
    r.raise_for_status()
    j = r.json()
    vals = [(t, v) for t, v in zip(j["unix_seconds"], j.get("co2eq") or []) if v is not None]
    t, v = vals[-1]
    return float(v) / 1000, f"Energy-Charts grid CO2 {datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M')}"


# ---------------------------------------------------------------- public
def reference_prices(p: Profile, start: datetime, end: datetime) -> tuple[pd.Series | None, str, str]:
    """Hourly wholesale price in micro-currency per kWh."""
    try:
        if p.market_price_provider == "epias":
            s = _epias_prices(start, end)
            return s, "EPİAŞ day-ahead PTF (real)", "live"
        if p.market_price_provider == "energy-charts":
            s = _ec_prices(start, end)
            return s, "Energy-Charts day-ahead DE-LU (real)", "live"
        return None, "No open real-time market price API; ToD tariff used", "n/a"
    except PermissionError as e:
        return None, str(e), "needs-credentials"
    except Exception as e:  # noqa: BLE001
        log.warning("reference prices unavailable for %s: %s", p.code, e)
        return None, f"{p.market_price_provider} unreachable ({type(e).__name__}); tariff used", "fallback"


def grid_intensity(p: Profile) -> tuple[float, str, str]:
    """Current grid CO2 intensity in kg/kWh."""
    try:
        if p.carbon_provider == "epias":
            v, src = _epias_intensity()
            return v, src, "live"
        if p.carbon_provider == "energy-charts":
            v, src = _ec_intensity()
            return v, src, "live"
    except PermissionError as e:
        return p.grid_ef, f"{p.grid_ef_source} · live mix {e}", "needs-credentials"
    except Exception as e:  # noqa: BLE001
        log.warning("grid intensity unavailable for %s: %s", p.code, e)
        return p.grid_ef, f"{p.grid_ef_source} (live source unreachable)", "fallback"
    return p.grid_ef, p.grid_ef_source, "static"
