"""PV physics with pvlib: clear-sky irradiance, plane-of-array irradiance, AC output per kWp."""
import numpy as np
import pandas as pd
import pvlib

from .config import settings

TILT, AZIMUTH = 16, 180  # latitude tilt, south facing
SYSTEM_LOSSES = 0.86  # inverter, wiring, soiling


def location() -> pvlib.location.Location:
    return pvlib.location.Location(settings.lat, settings.lon, settings.tz.key)


def clearsky_ghi(index: pd.DatetimeIndex) -> pd.Series:
    return location().get_clearsky(index, model="ineichen")["ghi"]


def poa_and_ac(ghi: pd.Series, temp_air: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Returns (plane-of-array irradiance W/m2, AC output kW per kWp)."""
    sp = location().get_solarposition(ghi.index)
    dec = pvlib.irradiance.erbs(ghi, sp["zenith"], ghi.index)
    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=TILT, surface_azimuth=AZIMUTH,
        solar_zenith=sp["apparent_zenith"], solar_azimuth=sp["azimuth"],
        dni=dec["dni"], ghi=ghi, dhi=dec["dhi"],
    )["poa_global"].fillna(0).clip(lower=0)
    tcell = pvlib.temperature.faiman(poa, temp_air)
    dc = pvlib.pvsystem.pvwatts_dc(poa, tcell, pdc0=1.0, gamma_pdc=-0.004)
    ac = (dc * SYSTEM_LOSSES).clip(lower=0).fillna(0)
    return poa, ac


def max_plausible_export_wh(kwp: float, poa_wm2: float, margin: float = 1.15) -> float:
    """Physics-oracle bound for one 15-minute interval. A tiny floor tolerates
    meter noise at dawn/dusk."""
    return max(kwp * poa_wm2 / 1000.0 * 0.25 * 1000.0 * margin, 5.0 if kwp > 0 else 0.0)


def cloud_index(ghi: pd.Series) -> pd.Series:
    cs = clearsky_ghi(ghi.index)
    return (ghi / cs.where(cs > 20)).clip(0, 1.2).fillna(0)


def smooth_hourly(s: pd.Series) -> pd.Series:
    """What a day-ahead hourly forecast 'sees': hourly means, no 15-min variability."""
    return s.groupby(s.index.tz_convert("UTC").floor("h")).transform("mean")


def ar1_noise(n: int, rng: np.random.Generator, phi: float = 0.85, sigma: float = 0.06) -> np.ndarray:
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + rng.normal(0, sigma)
    return x
