"""Physics oracle: is a meter reading physically possible?

1. Hard bound: export cannot exceed panel capacity x measured irradiance (plane of array)
   x 15 minutes x 115%. Irradiance comes from an independent source (weather data), not
   from the meter. Readings above the bound are rejected before the auction settles.
2. Soft signal: an IsolationForest trained on historical readings scores how unusual a
   reading looks (time of day, export per kWp, irradiance). Flagged, not rejected.
The smart contract enforces a third, coarser bound on-chain (capacity x 15 min x 115%).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from .solar import max_plausible_export_wh


class PhysicsOracle:
    def __init__(self) -> None:
        self.iforest = IsolationForest(n_estimators=150, contamination=0.01, random_state=0)
        self.fitted = False

    def fit(self, homes, profiles: dict, until: pd.Timestamp) -> None:
        idx = profiles["index"]
        mask = idx < until
        poa = profiles["poa_station"].values[mask]
        hr = (idx.hour + idx.minute / 60).values[mask]
        rows = []
        for h in homes:
            if h.pv_kwp <= 0:
                continue
            exp = np.clip(profiles["gen_wh"][h.home_id].values[mask] - profiles["load_wh"][h.home_id].values[mask], 0, None)
            rows.append(np.column_stack([hr, exp / h.pv_kwp, poa]))
        X = np.vstack(rows)
        self.iforest.fit(X)
        self.fitted = True

    def check(self, kwp: float, export_wh: float, poa_wm2: float, hour: float) -> dict:
        bound = max_plausible_export_wh(kwp, poa_wm2) if kwp > 0 else 0.0
        ok = export_wh <= bound + 1e-6
        score = None
        if self.fitted and kwp > 0:
            score = float(-self.iforest.score_samples([[hour, export_wh / kwp, poa_wm2]])[0])
        return {
            "accepted": bool(ok),
            "max_plausible_wh": round(bound, 1),
            "anomaly_score": None if score is None else round(score, 3),
            "anomalous": bool(score is not None and score > 0.70),
            "reason": None if ok else f"export {export_wh:.0f} Wh > physical max {bound:.0f} Wh at {poa_wm2:.0f} W/m2",
        }
