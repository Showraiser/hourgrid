"""Weather for the neighbourhood.

Provider chain (WEATHER_PROVIDER=auto):
  1. Open-Meteo: live current conditions + hourly GHI/temperature for the last
     HISTORY_DAYS and the next 2 days. Free, no API key.
  2. NASA POWER: satellite hourly GHI/temperature (historical, ~1 week lag).
  3. Offline: pvlib clear-sky x stochastic cloud model (always works).

Everything is returned as a 15-minute DataFrame (in the site's time zone) with columns
ghi (W/m2), temp_air (C), cloud_cover (%).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from .timeutil import floor_local
import requests

from . import solar
from .config import settings

log = logging.getLogger("hourgrid.weather")
_lock = threading.Lock()
_cache: dict = {}
CACHE_SECONDS = 600


class WeatherBundle:
    def __init__(self, df: pd.DataFrame, source: str, current: dict | None, fetched_at: datetime):
        self.df = df
        self.source = source
        self.current = current
        self.fetched_at = fetched_at


# ---------------------------------------------------------------- providers
def _open_meteo() -> tuple[pd.DataFrame, dict]:
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": settings.lat, "longitude": settings.lon,
            "hourly": "shortwave_radiation,temperature_2m,cloud_cover",
            "current": "temperature_2m,shortwave_radiation,cloud_cover,is_day,weather_code",
            "past_days": settings.history_days, "forecast_days": 2,
            "timeformat": "unixtime", "timezone": settings.tz.key,
        },
        timeout=20,
    )
    r.raise_for_status()
    j = r.json()
    h = j["hourly"]
    # shortwave_radiation is the mean over the preceding hour: centre it on the half hour
    idx = pd.to_datetime(h["time"], unit="s", utc=True).tz_convert(settings.tz.key) - pd.Timedelta(minutes=30)
    df = pd.DataFrame(
        {"ghi": h["shortwave_radiation"], "temp_air": h["temperature_2m"], "cloud_cover": h["cloud_cover"]},
        index=idx,
    )
    c = j.get("current", {})
    current = {
        "time": datetime.fromtimestamp(c["time"]).astimezone(settings.tz).isoformat() if "time" in c else None,
        "temp_air": c.get("temperature_2m"), "ghi": c.get("shortwave_radiation"),
        "cloud_cover": c.get("cloud_cover"), "is_day": c.get("is_day"), "weather_code": c.get("weather_code"),
    }
    return df, current


def _nasa_power(start: datetime, end: datetime) -> pd.DataFrame:
    r = requests.get(
        "https://power.larc.nasa.gov/api/temporal/hourly/point",
        params={
            "parameters": "ALLSKY_SFC_SW_DWN,T2M,CLOUD_AMT", "community": "RE",
            "latitude": settings.lat, "longitude": settings.lon,
            "start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"),
            "format": "JSON", "time-standard": "UTC",
        },
        timeout=30,
    )
    r.raise_for_status()
    p = r.json()["properties"]["parameter"]
    idx = pd.to_datetime(list(p["T2M"].keys()), format="%Y%m%d%H").tz_localize("UTC").tz_convert(settings.tz.key) + pd.Timedelta(minutes=30)
    df = pd.DataFrame(
        {"ghi": list(p["ALLSKY_SFC_SW_DWN"].values()), "temp_air": list(p["T2M"].values()),
         "cloud_cover": list(p.get("CLOUD_AMT", p["T2M"]).values())},
        index=idx,
    ).replace(-999, np.nan)
    if df["ghi"].isna().mean() > 0.5:
        raise ValueError("NASA POWER has no data for these days yet")
    return df.interpolate(limit_direction="both")


def _offline(start: datetime, end: datetime, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(pd.Timestamp(start).tz_localize(None), pd.Timestamp(end).tz_localize(None), freq="h", tz=settings.tz.key)
    cs = solar.clearsky_ghi(idx)
    days = idx.normalize().unique()
    # each day gets a weather regime: clear, partly cloudy or monsoon-overcast
    regime = {d: rng.choice([0.93, 0.75, 0.45], p=[0.55, 0.3, 0.15]) for d in days}
    base = np.array([regime[d] for d in idx.normalize()])
    k = np.clip(base + solar.ar1_noise(len(idx), rng, 0.8, 0.07), 0.1, 1.05)
    hour = idx.hour.values
    temp = 28 + 6 * np.sin((hour - 9) / 24 * 2 * np.pi) - 5 * (1 - base) + rng.normal(0, 0.4, len(idx))
    return pd.DataFrame({"ghi": cs.values * k, "temp_air": temp, "cloud_cover": np.clip(1 - k, 0, 1) * 100}, index=idx)


def _to_15min(df: pd.DataFrame) -> pd.DataFrame:
    df = df[~df.index.duplicated()].sort_index()
    start = df.index[0].floor("h")
    end = df.index[-1].ceil("h")
    idx = pd.date_range(start, end, freq="15min")
    out = df.reindex(df.index.union(idx)).interpolate(method="time", limit_direction="both").reindex(idx)
    # night must be dark: zero out GHI when the sun is below the horizon
    cs = solar.clearsky_ghi(idx)
    out["ghi"] = out["ghi"].where(cs > 1, 0).clip(lower=0)
    return out


# ---------------------------------------------------------------- public API
def get_weather(force: bool = False) -> WeatherBundle:
    """Weather covering [today - HISTORY_DAYS, tomorrow end], cached for 10 minutes."""
    with _lock:
        b = _cache.get("bundle")
        if b and _cache.get("key") != (settings.lat, settings.lon):
            b = None
        if b and not force and time.time() - _cache["t"] < CACHE_SECONDS:
            return b
        now = datetime.now(settings.tz)
        start = (now - timedelta(days=settings.history_days)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = (now + timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)
        provider = settings.weather_provider
        df, current, source = None, None, "offline"

        if provider in ("auto", "openmeteo"):
            try:
                df, current = _open_meteo()
                source = "open-meteo (live)"
            except Exception as e:  # noqa: BLE001
                log.warning("Open-Meteo unavailable: %s", e)
        if df is None and provider in ("auto", "nasa"):
            try:
                # NASA lags by days; use the latest available window and shift it to today
                lag = timedelta(days=10)
                df = _nasa_power(start - lag, end - lag)
                df.index = df.index + lag
                source = "nasa-power (satellite, shifted 10 days)"
            except Exception as e:  # noqa: BLE001
                log.warning("NASA POWER unavailable: %s", e)
        if df is None:
            df = _offline(start, end)
            source = "offline (pvlib clear-sky + cloud model)"

        w = _to_15min(df)
        if current is None:
            row = w.iloc[w.index.get_indexer([floor_local(pd.Timestamp(now), "15min")], method="nearest")[0]]
            current = {"time": now.isoformat(), "temp_air": round(float(row.temp_air), 1),
                       "ghi": round(float(row.ghi)), "cloud_cover": round(float(row.cloud_cover)),
                       "is_day": int(row.ghi > 5), "weather_code": None}
        b = WeatherBundle(w, source, current, now)
        _cache.update(bundle=b, t=time.time(), key=(settings.lat, settings.lon))
        log.info("weather: %s, %d rows %s -> %s", source, len(w), w.index[0], w.index[-1])
        return b
