"""Day-ahead forecasts of rooftop generation and household load.

Generation: hybrid model. pvlib turns the forecast irradiance into a physical estimate,
then a gradient-boosted model corrects it using hour of day, clear-sky irradiance and
temperature. Load: gradient-boosted model on calendar, weather and lagged consumption.
Both are trained on the HISTORY_DAYS before today and scored on a held-out window
against simple baselines, so the dashboard can show that the AI actually helps.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

from . import solar
from .neighbourhood import Home

log = logging.getLogger("hourgrid.forecast")


def forecast_irradiance(w: pd.DataFrame, seed: int = 5) -> pd.Series:
    """What a day-ahead weather forecast would have said: hourly resolution only,
    plus a per-day bias (forecasts miss cloudy days)."""
    rng = np.random.default_rng(seed)
    cs = solar.clearsky_ghi(w.index)
    k = solar.smooth_hourly(solar.cloud_index(w["ghi"]))
    days = w.index.normalize()
    bias = pd.Series(rng.normal(1.0, 0.08, len(days.unique())), index=days.unique())
    fc = (cs * (k * bias.reindex(days).values).clip(0, 1.1)).clip(lower=0)
    return fc


class Forecaster:
    def __init__(self) -> None:
        self.gen_model = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.08, random_state=0)
        self.load_model = HistGradientBoostingRegressor(max_iter=250, learning_rate=0.08, random_state=0)
        self.metrics: dict = {}
        self.gen_fc: pd.DataFrame | None = None
        self.load_fc: pd.DataFrame | None = None

    # ---------------------------------------------------------------- features
    def _gen_frame(self, homes, w, ghi_fc, gen_actual) -> pd.DataFrame:
        cs = solar.clearsky_ghi(w.index)
        _, phys = solar.poa_and_ac(ghi_fc, w["temp_air"])
        hr = w.index.hour + w.index.minute / 60
        rows = []
        for h in homes:
            if h.pv_kwp <= 0:
                continue
            rows.append(pd.DataFrame({
                "ts": w.index, "home_id": h.home_id, "kwp": h.pv_kwp,
                "hour": hr, "cs": cs.values, "ghi_fc": ghi_fc.values, "temp": w["temp_air"].values,
                "phys": phys.values * 250, "y": gen_actual[h.home_id].values / h.pv_kwp,
            }))
        return pd.concat(rows, ignore_index=True)

    def _load_frame(self, homes, w, load_actual) -> pd.DataFrame:
        hr = w.index.hour + w.index.minute / 60
        rows = []
        for h in homes:
            if h.role == "battery":
                continue
            y = load_actual[h.home_id]
            rows.append(pd.DataFrame({
                "ts": w.index, "home_id": h.home_id, "hour": hr, "dow": w.index.dayofweek,
                "temp": w["temp_air"].values, "occ": h.occupants, "ac": int(h.has_ac), "ev": int(h.has_ev),
                "base": h.base_load_kw, "lag_96": y.shift(96).values, "lag_672": y.shift(672).values,
                "y": y.values,
            }))
        return pd.concat(rows, ignore_index=True)

    GEN_X = ["hour", "cs", "ghi_fc", "temp", "phys"]
    LOAD_X = ["hour", "dow", "temp", "occ", "ac", "ev", "base", "lag_96", "lag_672"]

    # ---------------------------------------------------------------- train + predict
    def fit_predict(self, homes: list[Home], w: pd.DataFrame, profiles: dict, sim_start: pd.Timestamp) -> None:
        ghi_fc = forecast_irradiance(w)
        g = self._gen_frame(homes, w, ghi_fc, profiles["gen_wh"])
        l = self._load_frame(homes, w, profiles["load_wh"])

        hist_g, hist_l = g[g.ts < sim_start], l[l.ts < sim_start].dropna(subset=["lag_96"])
        holdout_start = sim_start - pd.Timedelta(days=2)
        tr_g, te_g = hist_g[hist_g.ts < holdout_start], hist_g[hist_g.ts >= holdout_start]
        tr_l, te_l = hist_l[hist_l.ts < holdout_start], hist_l[hist_l.ts >= holdout_start]

        if len(tr_g) < 500 or len(tr_l) < 500:
            raise ValueError("not enough history to train forecasts")

        # metrics on the held-out window
        self.gen_model.fit(tr_g[self.GEN_X], tr_g["y"])
        self.load_model.fit(tr_l[self.LOAD_X], tr_l["y"])
        day = te_g.hour.between(6, 18)
        gen_pred = np.clip(self.gen_model.predict(te_g[self.GEN_X]), 0, None) * te_g.kwp
        gen_true = te_g.y * te_g.kwp
        gen_persist = g.groupby("home_id")["y"].shift(96).loc[te_g.index] * te_g.kwp
        load_pred = np.clip(self.load_model.predict(te_l[self.LOAD_X]), 0, None)
        self.metrics = {
            "holdout_days": 2,
            "train_rows": int(len(tr_g) + len(tr_l)),
            "generation_mae_wh": {
                "hourgrid_ai": round(float(mean_absolute_error(gen_true[day], gen_pred[day])), 1),
                "physics_only": round(float(mean_absolute_error(gen_true[day], (te_g.phys * te_g.kwp)[day])), 1),
                "yesterday_same_time": round(float(mean_absolute_error(gen_true[day], gen_persist[day].fillna(0))), 1),
            },
            "load_mae_wh": {
                "hourgrid_ai": round(float(mean_absolute_error(te_l.y, load_pred)), 1),
                "yesterday_same_time": round(float(mean_absolute_error(te_l.y, te_l.lag_96)), 1),
            },
        }

        # refit on all history, predict the whole window
        self.gen_model.fit(hist_g[self.GEN_X], hist_g["y"])
        self.load_model.fit(hist_l[self.LOAD_X], hist_l["y"])
        g["pred"] = np.clip(self.gen_model.predict(g[self.GEN_X]), 0, None) * g.kwp
        g.loc[g.cs < 1, "pred"] = 0.0
        l["pred"] = np.clip(self.load_model.predict(l[self.LOAD_X].fillna(l["base"].mean() * 250)), 0, None)
        self.gen_fc = g.pivot(index="ts", columns="home_id", values="pred").reindex(w.index).fillna(0)
        self.load_fc = l.pivot(index="ts", columns="home_id", values="pred").reindex(w.index).fillna(0)
        for h in homes:  # consumers have no generation
            if h.role != "battery" and h.home_id not in self.gen_fc:
                self.gen_fc[h.home_id] = 0.0
        self.ghi_fc = ghi_fc
        log.info("forecast metrics: %s", self.metrics)
