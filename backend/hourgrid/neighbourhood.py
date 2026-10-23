"""Simulated neighbourhood: homes, smart meters, keys, and 15-minute energy profiles."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
from eth_account import Account
from eth_utils import keccak

from . import solar
from .config import settings



@dataclass
class Home:
    home_id: str
    name: str
    role: str  # prosumer | consumer | battery
    meter_id: str
    pv_kwp: float
    base_load_kw: float
    occupants: int
    has_ac: bool
    has_ev: bool
    soiling: float
    kind: str = "home"  # home | business
    wallet: str = ""
    signer: str = ""
    capacity_w: int = 0
    prefs: dict = field(default_factory=dict)

    @property
    def meter_key(self) -> bytes:
        return keccak(text=self.meter_id)

    def public(self) -> dict:
        d = asdict(self)
        d["meter_key"] = "0x" + self.meter_key.hex()
        return d


def default_prefs(role: str, rng: np.random.Generator) -> dict:
    return {
        "participate": True,
        "min_sell_price": None,  # Rs/kWh; None = agent decides
        "max_buy_price": None,
        "sell_share": 1.0,  # fraction of forecast surplus offered
        "prefer_green": bool(rng.random() < 0.5),  # buyer will pay up to the grid price for solar
        "aggressiveness": round(float(rng.uniform(0.3, 0.7)), 2),
    }


def _key(seed: str, label: str) -> str:
    return "0x" + keccak(text=f"{seed}:{label}").hex()


def make_homes() -> list[Home]:
    from . import tariffs
    prof = tariffs.PROFILE
    rng = np.random.default_rng(2026)
    n = settings.n_homes
    n_pro = int(round(n * settings.prosumer_share))
    commercial = prof.prosumer_kind == "commercial"
    homes: list[Home] = []
    for i in range(n):
        pro = i < n_pro
        biz = pro and commercial
        h = Home(
            home_id=f"H{i + 1:02d}",
            name=prof.business_names[i % len(prof.business_names)] if biz else f"{prof.names[i % len(prof.names)]}'s home",
            role="prosumer" if pro else "consumer",
            meter_id=f"MTR-{prof.code}-{100200 + i}",
            pv_kwp=float(rng.choice([8, 10, 10, 12, 15])) if biz else (float(rng.choice([2, 3, 3, 4, 5])) if pro else 0.0),
            base_load_kw=round(float(rng.uniform(0.9, 2.2)), 2) if biz else round(float(rng.uniform(0.15, 0.35)), 2),
            occupants=int(rng.integers(3, 12)) if biz else int(rng.integers(2, 6)),
            has_ac=bool(rng.random() < (0.5 if prof.code == "DE" else 0.6)),
            has_ev=bool(rng.random() < 0.2),
            soiling=round(float(rng.uniform(0.92, 1.0)), 3),
            kind="business" if biz else "home",
        )
        h.capacity_w = int(h.pv_kwp * 1000)
        h.prefs = default_prefs(h.role, rng)
        homes.append(h)
    bat = Home(
        home_id="BAT", name="Community battery", role="battery", meter_id=f"MTR-{tariffs.PROFILE.code}-BAT-01",
        pv_kwp=0.0, base_load_kw=0.0, occupants=0, has_ac=False, has_ev=False, soiling=1.0,
    )
    from .agents import battery_spec
    bat.capacity_w = int(battery_spec()[1] * 1000)
    bat.prefs = {"participate": True}
    homes.append(bat)
    for h in homes:
        h.wallet = Account.from_key(wallet_key(h)).address
        h.signer = Account.from_key(meter_signer_key(h)).address
    return homes


def wallet_key(h: Home) -> str:
    return _key(settings.demo_seed, f"wallet:{h.home_id}")


def meter_signer_key(h: Home) -> str:
    return _key(settings.demo_seed, f"meter:{h.meter_id}")


# ---------------------------------------------------------------- profiles
def load_kw(h: Home, idx: pd.DatetimeIndex, temp: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    hr = idx.hour.values + idx.minute.values / 60
    weekend = idx.dayofweek.values >= 5
    if h.kind == "business":
        # workshop / shop: plateau 08-18 on working days, Saturday half day, Sunday closed
        open_ = np.clip((hr - 7.5) * 2, 0, 1) * np.clip((18.5 - hr) * 2, 0, 1)
        sat = idx.dayofweek.values == 5
        sun = idx.dayofweek.values == 6
        level = np.where(sun, 0.05, np.where(sat, np.where(hr < 13, 1.0, 0.1), 1.0))
        load = h.base_load_kw * (0.15 + 0.85 * open_ * level) * (1 + 0.15 * np.sin(hr / 3))
        return load * np.clip(rng.normal(1, 0.08, len(idx)), 0.8, 1.3)
    morning = 0.6 * np.exp(-((hr - 7.0) ** 2) / 1.5)
    evening = 1.1 * np.exp(-((hr - 20.0) ** 2) / 3.0)
    midday = np.where(weekend, 0.35 * np.exp(-((hr - 13.0) ** 2) / 4.0), 0.0)  # people at home
    scale = 0.7 + 0.12 * h.occupants
    load = h.base_load_kw + scale * (morning + evening + midday)
    if h.has_ac:
        hot = temp > 29
        ac_on = (hot & (hr >= 13) & (hr <= 16)) | (hr >= 22) | (hr < 5)
        load = load + np.where(ac_on, 1.1 + 0.05 * np.clip(temp - 29, 0, 8), 0)
    if h.has_ev:
        load = load + np.where((hr >= 19) & (hr < 22), 1.8, 0)
    return load * np.clip(rng.normal(1, 0.1, len(idx)), 0.75, 1.35)


def build_profiles(homes: list[Home], w: pd.DataFrame) -> dict:
    """Actual 15-minute generation/load per home plus physics fields, for the whole
    weather window. Deterministic for a given weather frame."""
    rng = np.random.default_rng(11)
    idx = w.index
    # house-level passing clouds: station GHI x small AR(1) perturbation (capped at +8%)
    local_k = 1 + np.clip(solar.ar1_noise(len(idx), rng, 0.7, 0.05), -0.5, 0.08)
    ghi_local = (w["ghi"] * local_k).clip(lower=0)
    _, ac_local = solar.poa_and_ac(ghi_local, w["temp_air"])
    poa_station, _ = solar.poa_and_ac(w["ghi"], w["temp_air"])
    temp = w["temp_air"].values
    gen, load = {}, {}
    for h in homes:
        if h.role == "battery":
            continue
        gen[h.home_id] = (ac_local.values * h.pv_kwp * h.soiling * 250).round(1)  # Wh per 15 min
        load[h.home_id] = (load_kw(h, idx, temp, rng) * 250).round(1)
    return {
        "index": idx,
        "gen_wh": pd.DataFrame(gen, index=idx),
        "load_wh": pd.DataFrame(load, index=idx),
        "poa_station": poa_station,
    }
