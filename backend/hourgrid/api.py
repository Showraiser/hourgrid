"""HTTP API for the HourGrid dashboard.   uvicorn hourgrid.api:app --port 8000"""
from __future__ import annotations

import json
import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import countries, llm, tariffs
from .config import settings
from .engine import Engine, _interval_public
from .store import Store, dumps

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
RS = tariffs.RS

@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=eng, daemon=True).start()  # load weather + train models in background
    yield


app = FastAPI(title="HourGrid API", version="1.0", lifespan=lifespan,
              description="P2P solar trading with hourly clean-energy certificates")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_methods=["*"],
                   allow_headers=["*"])

store = Store(settings.db_path)
engine: Engine | None = None
_boot_lock = threading.Lock()


def eng() -> Engine:
    global engine
    with _boot_lock:
        if engine is None:
            engine = Engine(store)
    return engine


def _ready() -> Engine:
    if engine is None or not engine.ready:
        raise HTTPException(503, "engine starting (loading weather, training forecasts)")
    return engine


def _rs(v):
    return None if v is None else round(v / RS, 2)


# ---------------------------------------------------------------- countries
@app.get("/api/countries")
def list_countries():
    return {"active": {"country": settings.country, "site": settings.site_id},
            "countries": [p.public() for p in countries.PROFILES.values()]}


class CountryBody(BaseModel):
    country: str
    site: str | None = None


@app.post("/api/country")
def set_country(body: CountryBody):
    if body.country.upper() not in countries.PROFILES:
        raise HTTPException(404, "unknown country")
    e = _ready()
    e.pause()
    threading.Thread(target=e.reset, kwargs={"country": body.country.upper(), "site": body.site}, daemon=True).start()
    return {"switching": True, "country": body.country.upper(), "site": body.site}


# ---------------------------------------------------------------- overview
@app.get("/api/health")
def health():
    return {"ok": True, "engine": engine.status_msg if engine else "starting"}


@app.get("/api/state")
def state():
    return _ready().state()


@app.get("/api/kpis")
def kpis():
    return _ready().kpis()


@app.get("/api/weather")
def weather():
    e = _ready()
    w = e.weather.df
    day = w[(w.index >= e.day_start) & (w.index < e.day_start + pd.Timedelta(days=1))]
    fc = e.forecaster.ghi_fc.reindex(day.index)
    return {
        "source": e.weather.source, "fetched_at": e.weather.fetched_at.isoformat(), "current": e.weather.current,
        "site": {"name": settings.site_name, "lat": settings.lat, "lon": settings.lon},
        "today": [{"ts": t.isoformat(), "ghi": round(float(r.ghi), 1), "ghi_forecast": round(float(fc.loc[t]), 1),
                   "temp": round(float(r.temp_air), 1), "cloud_cover": round(float(r.cloud_cover), 0)}
                  for t, r in day.iterrows()],
    }


@app.get("/api/series")
def series(limit: int = 192):
    """Per-interval market + energy series for charts."""
    rows = store.all("SELECT * FROM intervals ORDER BY id DESC LIMIT ?", (limit,))[::-1]
    out = []
    for r in rows:
        t = json.loads(r["totals"]) if r["totals"] else {}
        out.append({
            "id": r["id"], "ts": r["start_ts"], "period": r["period"], "price": _rs(r["clearing_price"]),
            "ref_price": _rs(r.get("ref_price")), "period_label": r.get("period_label"),
            "grid_price": _rs(r["grid_price"]), "feed_in": tariffs.FEED_IN / RS,
            "volume_wh": r["volume_wh"], "scheduled_wh": r["scheduled_wh"], "fills": r["n_fills"],
            "solar_wh": round(t.get("solar_wh", 0)), "load_wh": round(t.get("load_wh", 0)),
            "export_wh": t.get("export_wh", 0), "battery_soc": round(100 * (r["battery_soc"] or 0), 1),
            "ghi": r["ghi"], "status": r["status"],
        })
    return out


# ---------------------------------------------------------------- market
@app.get("/api/intervals")
def intervals(limit: int = 50):
    rows = store.all("SELECT * FROM intervals ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        r.pop("curves", None)
        r["totals"] = json.loads(r["totals"]) if r["totals"] else None
        for k in ("clearing_price", "grid_price", "floor", "ceiling", "ref_price"):
            r[k] = _rs(r.get(k))
    return rows


@app.get("/api/intervals/{iv}")
def interval(iv: int):
    e = _ready()
    r = store.one("SELECT * FROM intervals WHERE id=?", (iv,))
    if not r:
        raise HTTPException(404, "unknown interval")
    out = _interval_public(r)
    names = {h.home_id: h.name for h in e.homes}
    out["orders"] = [dict(o, price=_rs(o["price"]), name=names.get(o["agent"]))
                     for o in store.all("SELECT * FROM orders WHERE interval_id=? ORDER BY side, price DESC", (iv,))]
    out["fills"] = [dict(f, price=_rs(f["price"]), seller_name=names.get(f["seller"]), buyer_name=names.get(f["buyer"]))
                    for f in store.all("SELECT * FROM fills WHERE interval_id=? ORDER BY idx", (iv,))]
    out["readings"] = store.all("SELECT * FROM readings WHERE interval_id=?", (iv,))
    out["explorer"] = settings.explorer_url or None
    return out


# ---------------------------------------------------------------- homes / agents
def _home_row(e: Engine, h, bal, last):
    d = h.public()
    d.update(balance=_rs(bal["escrow"]), earned=_rs(bal["earned"]), spent=_rs(bal["spent"]),
             sold_wh=bal["sold_wh"], bought_wh=bal["bought_wh"], points=bal["points"],
             extra_vs_feed_in=_rs(bal["earned"] - bal["netmeter_value"]),
             saved_vs_grid=_rs(bal["grid_cost_avoided"] - bal["spent"]),
             last_reading=last.get(h.home_id))
    if h.role == "battery":
        d["soc_pct"] = round(100 * e.battery.soc_wh / e.battery.capacity_wh, 1)
        d["capacity_kwh"] = e.battery.capacity_wh / 1000
    return d


@app.get("/api/homes")
def homes():
    e = _ready()
    bal = {b["home_id"]: b for b in store.all("SELECT * FROM balances")}
    li = store.one("SELECT MAX(id) id FROM intervals")["id"]
    last = {r["home_id"]: r for r in store.all("SELECT * FROM readings WHERE interval_id=?", (li,))} if li else {}
    return [_home_row(e, h, bal[h.home_id], last) for h in e.homes]


@app.get("/api/homes/{home_id}")
def home(home_id: str):
    e = _ready()
    h = e.by_id.get(home_id)
    if not h:
        raise HTTPException(404, "unknown home")
    bal = store.one("SELECT * FROM balances WHERE home_id=?", (home_id,))
    li = store.one("SELECT MAX(id) id FROM intervals")["id"]
    last = {r["home_id"]: r for r in store.all("SELECT * FROM readings WHERE interval_id=? AND home_id=?", (li, home_id))}
    d = _home_row(e, h, bal, last)
    d["series"] = store.all(
        """SELECT i.start_ts ts, r.gen_wh, r.load_wh, r.gen_fc, r.load_fc, r.export_wh, r.import_wh, r.accepted
           FROM readings r JOIN intervals i ON i.id=r.interval_id WHERE r.home_id=? ORDER BY r.interval_id""",
        (home_id,))
    d["orders"] = [dict(o, price=_rs(o["price"])) for o in store.all(
        """SELECT o.*, i.start_ts ts FROM orders o JOIN intervals i ON i.id=o.interval_id WHERE o.agent=?
           ORDER BY o.interval_id DESC LIMIT 30""", (home_id,))]
    d["trades"] = [dict(f, price=_rs(f["price"])) for f in store.all(
        """SELECT f.*, i.start_ts ts FROM fills f JOIN intervals i ON i.id=f.interval_id
           WHERE f.seller=? OR f.buyer=? ORDER BY f.interval_id DESC LIMIT 50""", (home_id, home_id))]
    d["certificates"] = store.all(
        """SELECT c.*, hd.wh held_wh, (SELECT COUNT(*) FROM fills f WHERE f.cert_id=c.cert_id AND f.status NOT IN ('settled','offchain')) = 0 AS settled FROM holdings hd JOIN certificates c ON c.cert_id=hd.cert_id
           WHERE hd.home_id=? AND hd.wh > 0 ORDER BY c.hour_start DESC""", (home_id,))
    d["agent_log"] = store.all("SELECT * FROM agent_log WHERE home_id=? ORDER BY id DESC LIMIT 10", (home_id,))
    return d


class Instruction(BaseModel):
    text: str = Field(..., max_length=500)


@app.post("/api/agents/{home_id}/instruct")
def instruct(home_id: str, body: Instruction):
    e = _ready()
    h = e.by_id.get(home_id)
    if not h or h.role == "battery":
        raise HTTPException(404, "unknown home")
    res = llm.instruct(h.public(), body.text, h.prefs)
    h.prefs = res["prefs"]
    store.execute("INSERT INTO agent_log(ts, home_id, instruction, prefs, explanation, engine) VALUES (?,?,?,?,?,?)",
                  (datetime.now().isoformat(timespec="seconds"), home_id, body.text, dumps(h.prefs), res["reply"],
                   res["engine"]))
    return res


@app.post("/api/agents/{home_id}/ask")
def ask(home_id: str, body: Instruction):
    e = _ready()
    h = e.by_id.get(home_id)
    if not h:
        raise HTTPException(404, "unknown home")
    ctx = {
        "recent_orders": [dict(time=o["ts"], side=o["side"], wh=o["wh"], price=_rs(o["price"]), reason=o["reason"])
                          for o in store.all("""SELECT o.*, i.start_ts ts FROM orders o JOIN intervals i ON i.id=o.interval_id
                                                WHERE o.agent=? ORDER BY o.interval_id DESC LIMIT 12""", (home_id,))],
        "recent_fills": [dict(time=f["ts"], seller=f["seller"], buyer=f["buyer"], wh=f["wh"], price=_rs(f["price"]))
                         for f in store.all("""SELECT f.*, i.start_ts ts FROM fills f JOIN intervals i ON i.id=f.interval_id
                                               WHERE f.seller=? OR f.buyer=? ORDER BY f.interval_id DESC LIMIT 12""",
                                            (home_id, home_id))],
        "balance": store.one("SELECT sold_wh, bought_wh, points FROM balances WHERE home_id=?", (home_id,)),
        "prefs": h.prefs, "tariffs": tariffs.as_dict(),
    }
    return llm.ask(h.public(), body.text, ctx)


# ---------------------------------------------------------------- certificates
@app.get("/api/certificates")
def certificates(limit: int = 100):
    e = _ready()
    names = {h.home_id: h.name for h in e.homes}
    rows = store.all("SELECT c.*, (SELECT COUNT(*) FROM fills f WHERE f.cert_id=c.cert_id AND f.status NOT IN ('settled','offchain')) = 0 AS settled FROM certificates c ORDER BY hour_start DESC, minted_wh DESC LIMIT ?", (limit,))
    for r in rows:
        r["producer"] = names.get(r["home_id"])
        r["holders"] = store.all("SELECT home_id, wh FROM holdings WHERE cert_id=? AND wh>0", (r["cert_id"],))
    return rows


@app.get("/api/certificates/{cert_id}")
def verify(cert_id: str):
    """Public verifier: certificate -> producer meter -> hour -> trades -> signed readings -> retirements."""
    e = _ready()
    c = store.one("SELECT * FROM certificates WHERE cert_id=?", (cert_id.lower(),))
    if not c:
        raise HTTPException(404, "certificate not found")
    names = {h.home_id: h.name for h in e.homes}
    h = e.by_id[c["home_id"]]
    trades = store.all(
        """SELECT f.*, i.start_ts ts, i.commit_tx, i.settle_tx, i.fills_root, i.orderbook_hash, i.status interval_status,
                  r.export_wh, r.max_plausible_wh, r.signature
           FROM fills f JOIN intervals i ON i.id=f.interval_id
           LEFT JOIN readings r ON r.interval_id=f.interval_id AND r.home_id=f.seller
           WHERE f.cert_id=? ORDER BY f.interval_id, f.idx""", (c["cert_id"],))
    for t in trades:
        t["price"] = _rs(t["price"])
        t["buyer_name"] = names.get(t["buyer"])
    out = {
        "certificate": c, "producer": {"home_id": h.home_id, "name": h.name, "meter_id": h.meter_id,
                                        "meter_key": "0x" + h.meter_key.hex(), "signer": h.signer,
                                        "pv_kwp": h.pv_kwp, "zone": settings.zone},
        "trades": trades,
        "holders": [dict(x, name=names.get(x["home_id"])) for x in
                    store.all("SELECT home_id, wh FROM holdings WHERE cert_id=? AND wh>0", (c["cert_id"],))],
        "retirements": [dict(x, name=names.get(x["home_id"])) for x in
                        store.all("SELECT * FROM retirements WHERE cert_id=? ORDER BY id", (c["cert_id"],))],
        "onchain": None, "explorer": settings.explorer_url or None,
    }
    if e.chain is not None:
        try:
            out["onchain"] = e.chain.cert_onchain(int(c["cert_id"], 16))
            out["onchain"]["contract"] = e.chain.certs.address
        except Exception as ex:  # noqa: BLE001
            out["onchain"] = {"error": str(ex)[:200]}
    return out


class RetireBody(BaseModel):
    home_id: str
    cert_id: str
    wh: int
    beneficiary: str = Field(..., max_length=120)


@app.post("/api/certificates/retire")
def retire(body: RetireBody):
    e = _ready()
    if body.home_id not in e.by_id:
        raise HTTPException(404, "unknown home")
    res = e.retire(body.home_id, body.cert_id.lower(), body.wh, body.beneficiary)
    if not res["ok"]:
        store.alert("critical", "double-claim", res.get("message", res["error"]), home_id=body.home_id)
    return res


@app.get("/api/retirements")
def retirements(limit: int = 50):
    e = _ready()
    names = {h.home_id: h.name for h in e.homes}
    return [dict(r, name=names.get(r["home_id"])) for r in
            store.all("SELECT * FROM retirements ORDER BY id DESC LIMIT ?", (limit,))]


# ---------------------------------------------------------------- alerts / forecast
@app.get("/api/alerts")
def alerts(limit: int = 50):
    return store.all("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))


@app.get("/api/forecast")
def forecast():
    return _ready().forecaster.metrics


# ---------------------------------------------------------------- simulation control
class Speed(BaseModel):
    seconds_per_interval: float = Field(..., ge=0.2, le=120)


@app.post("/api/sim/start")
def sim_start():
    _ready().start()
    return {"running": True}


@app.post("/api/sim/pause")
def sim_pause():
    _ready().pause()
    return {"running": False}


@app.post("/api/sim/step")
def sim_step(n: int = 1):
    e = _ready()
    done = 0
    for _ in range(max(1, min(n, 96))):
        if not e.step():
            break
        done += 1
    return {"stepped": done, "clock": e.clock.isoformat()}


@app.post("/api/sim/speed")
def sim_speed(body: Speed):
    settings.seconds_per_interval = body.seconds_per_interval
    return {"seconds_per_interval": settings.seconds_per_interval}


@app.post("/api/sim/reset")
def sim_reset(fresh_chain: bool = False):
    e = _ready()
    e.pause()
    threading.Thread(target=e.reset, kwargs={"fresh_chain": fresh_chain}, daemon=True).start()
    return {"resetting": True}


class Tamper(BaseModel):
    home_id: str = "H03"
    export_wh: float = 3000


@app.post("/api/demo/tamper")
def demo_tamper(body: Tamper = Tamper()):
    e = _ready()
    if body.home_id not in e.by_id or e.by_id[body.home_id].role == "battery":
        raise HTTPException(404, "unknown home")
    return e.tamper(body.home_id, body.export_wh)
