"""The market engine: one tick = one 15-minute interval.

  forecast -> agent orders -> double auction (schedule) -> meter readings arrive ->
  physics oracle -> delivery reconciliation -> payments, certificates, points ->
  Merkle commit + settlement on-chain (background worker)
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from .timeutil import floor_local
from eth_abi import encode
from eth_utils import keccak

from . import market_data, tariffs
from .agents import BatteryState, battery_orders, battery_spec, home_orders, new_battery
from .auction import Order, clear, orderbook_hash, supply_demand_curves
from .config import apply_country, settings
from .forecasting import Forecaster
from .merkle import MerkleTree, fill_leaf
from .neighbourhood import Home, build_profiles, make_homes, meter_signer_key
from .oracle import PhysicsOracle
from .signing import sign_reading
from .store import Store, dumps
from .weather import get_weather

log = logging.getLogger("hourgrid.engine")
RS = tariffs.RS
ZERO = "0x0000000000000000000000000000000000000000"


def interval_id(ts: pd.Timestamp) -> int:
    return int(ts.timestamp()) // 900


def local_hour_start(ts: pd.Timestamp) -> int:
    return int(floor_local(ts, "h").timestamp())


def cert_id_for(meter_key: bytes, hour_start: int) -> str:
    return "0x" + keccak(encode(["bytes32", "uint64"], [meter_key, hour_start])).hex()


class Engine:
    def __init__(self, store: Store, fresh_chain: bool = False):
        self.store = store
        self.lock = threading.RLock()
        self.running = False
        self.thread: threading.Thread | None = None
        self.pending_tamper: dict[str, float] = {}
        self.chain = None
        self.chain_status = "disabled"
        self.chain_error = ""
        self.jobs: queue.Queue = queue.Queue()
        self.worker = threading.Thread(target=self._chain_worker, daemon=True)
        self.worker.start()
        self.ready = False
        self.status_msg = "starting"
        self.reset(fresh_chain=fresh_chain)

    # ---------------------------------------------------------------- setup
    def reset(self, fresh_chain: bool = False, country: str | None = None, site: str | None = None) -> None:
        with self.lock:
            self.running = False
            self.ready = False
            if country or site:
                apply_country(country or settings.country, site)
                fresh_chain = True  # new currency / fees / time zone -> fresh market contracts
            self.profile = tariffs.PROFILE
            self.homes: list[Home] = make_homes()
            self.by_id = {h.home_id: h for h in self.homes}
            self.by_wallet = {h.wallet.lower(): h for h in self.homes}
            self.chain = None
            self.chain_status = "disabled"
            self.status_msg = "loading weather"
            self.weather = get_weather(force=True)
            w = self.weather.df
            now = pd.Timestamp(datetime.now(settings.tz))
            self.day_start = now.normalize()
            self.status_msg = "fetching market data"
            rp, rp_src, rp_status = market_data.reference_prices(
                self.profile, (self.day_start - pd.Timedelta(days=1)).to_pydatetime(),
                (self.day_start + pd.Timedelta(days=2)).to_pydatetime())
            self.ref_prices = rp
            self.data_sources = {
                "weather": {"source": self.weather.source,
                            "status": "live" if "live" in self.weather.source or "nasa" in self.weather.source else "fallback"},
                "market_price": {"source": rp_src, "status": rp_status},
                "grid_carbon": {"source": self.profile.grid_ef_source, "status": "pending"},
            }
            tariffs.set_dynamic_prices(rp)
            self.intensity = self.profile.grid_ef
            threading.Thread(target=self._fetch_intensity, daemon=True).start()
            self.profiles = build_profiles(self.homes, w)
            self.status_msg = "training forecasts"
            self.forecaster = Forecaster()
            self.forecaster.fit_predict(self.homes, w, self.profiles, self.day_start)
            self.oracle = PhysicsOracle()
            self.oracle.fit(self.homes, self.profiles, self.day_start)
            self.battery: BatteryState = new_battery()
            if settings.clock_mode == "live":
                self.clock = floor_local(now, "15min") - pd.Timedelta(minutes=15)
            else:
                self.clock = self.day_start + pd.Timedelta(hours=settings.demo_start_hour)
            self.end = w.index[-1]
            self.store.reset()
            deposit = int(self.profile.deposit * RS)
            self.store.executemany(
                "INSERT INTO balances(home_id, escrow) VALUES (?,?)",
                [(h.home_id, deposit * (10 if h.role == "battery" else 1)) for h in self.homes],
            )
            self.chain_id, self.market_addr = 31337, ZERO
            self.status_msg = "ready"
            self.ready = True
        if settings.chain_enabled:
            threading.Thread(target=self._connect_chain, args=(fresh_chain,), daemon=True).start()
        if settings.autostart:
            self.start()

    def _fetch_intensity(self) -> None:
        v, src, status = market_data.grid_intensity(self.profile)
        self.intensity = v
        self.data_sources["grid_carbon"] = {"source": src, "status": status, "kg_per_kwh": round(v, 3)}

    def _connect_chain(self, fresh: bool) -> None:
        from .chain import Chain
        from .deploy import deploy_all
        try:
            self.chain_status = "connecting"
            if fresh:
                self.chain_status = "deploying contracts"
                deploy_all(self.profile)
            try:
                ch = Chain()
            except RuntimeError as e:
                if "no deployment file" not in str(e):
                    raise
                self.chain_status = "deploying contracts"
                deploy_all(self.profile)
                ch = Chain()
            # a previous run may already have committed these intervals: start a fresh market
            n = ch.market.functions.intervalCount().call()
            first = interval_id(self.clock + pd.Timedelta(minutes=15))
            wrong_ccy = ch.c["SettlementToken"].functions.symbol().call() != self.profile.token_symbol
            if wrong_ccy or (n and ch.market.functions.intervalIds(n - 1).call() >= first):
                self.chain_status = "deploying fresh market"
                deploy_all(self.profile)
                ch = Chain()
            self.chain_status = "onboarding meters"
            ch.bootstrap(self.homes, keccak(text=settings.zone), int(self.profile.deposit * RS))
            for h in self.homes:
                self.store.execute("UPDATE balances SET escrow=? WHERE home_id=?", (ch.escrow(h.wallet), h.home_id))
            self.chain_id, self.market_addr = ch.chain_id, ch.market.address
            self.chain = ch
            self.chain_status = "connected"
            self.chain_error = ""
        except Exception as e:  # noqa: BLE001
            log.exception("chain unavailable")
            self.chain_status = "error"
            self.chain_error = str(e)[:300]
            self.store.alert("warn", "chain", f"Blockchain unavailable, settling off-chain: {self.chain_error}")

    # ---------------------------------------------------------------- clock
    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def pause(self) -> None:
        self.running = False

    def _loop(self) -> None:
        while self.running:
            if settings.chain_enabled and self.chain_status not in ("connected", "error"):
                time.sleep(0.5)  # wait for meters to be onboarded before trading
                continue
            if settings.clock_mode == "live":
                nxt = self.clock + pd.Timedelta(minutes=30)  # interval [clock+15, +30) closes at +30
                wait = (nxt - pd.Timestamp(datetime.now(settings.tz))).total_seconds()
                if wait > 0:
                    time.sleep(min(wait, 5))
                    continue
            try:
                if not self.step():
                    self.running = False
            except Exception:  # noqa: BLE001
                log.exception("tick failed")
                self.running = False
            if settings.clock_mode != "live":
                time.sleep(settings.seconds_per_interval)

    # ---------------------------------------------------------------- one interval
    def step(self) -> bool:
        with self.lock:
            t = self.clock + pd.Timedelta(minutes=15)
            if t > self.end:
                self.status_msg = "end of weather window"
                return False
            self.clock = t
            self._tick(t)
            return True

    def _tick(self, t: pd.Timestamp) -> None:
        w = self.weather.df
        iv = interval_id(t)
        i = w.index.get_loc(t)
        poa = float(self.profiles["poa_station"].iloc[i])
        hour_f = t.hour + t.minute / 60
        lo, hi = tariffs.price_bounds(t)
        gp = tariffs.grid_price(t)
        period = tariffs.period(t)

        # 1-2. forecasts -> orders (placed before the interval)
        orders: list[Order] = []
        fc = {}
        for h in self.homes:
            if h.role == "battery":
                continue
            g, l = float(self.forecaster.gen_fc[h.home_id].iloc[i]), float(self.forecaster.load_fc[h.home_id].iloc[i])
            fc[h.home_id] = (g, l)
            orders += home_orders(h, t, g, l)
        orders += battery_orders(self.battery, t)

        # 3. clear
        res = clear(orders, lo, hi)
        ob_hash = orderbook_hash(iv, orders)

        # 4. actual meter readings
        readings = {}
        for h in self.homes:
            if h.role == "battery":
                continue
            gen = float(self.profiles["gen_wh"][h.home_id].iloc[i])
            load = float(self.profiles["load_wh"][h.home_id].iloc[i])
            exp, imp = max(0.0, gen - load), max(0.0, load - gen)
            tampered = False
            if h.home_id in self.pending_tamper:
                exp, imp, tampered = self.pending_tamper.pop(h.home_id), 0.0, True
            chk = self.oracle.check(h.pv_kwp, exp, poa, hour_f)
            readings[h.home_id] = dict(gen=gen, load=load, exp=int(round(exp)), imp=int(round(imp)),
                                       tampered=tampered, **chk)
            if not chk["accepted"]:
                self.store.alert("critical", "oracle", f"{h.name} ({h.meter_id}) reading rejected: {chk['reason']}",
                                 t.isoformat(), iv, h.home_id)
            elif chk["anomalous"] and exp > 0:
                self.store.alert("info", "anomaly", f"{h.name}: unusual reading (score {chk['anomaly_score']})",
                                 t.isoformat(), iv, h.home_id)

        # 5-6. reconcile scheduled fills against what was actually metered
        sell_cap = {hid: (r["exp"] if r["accepted"] else 0) for hid, r in readings.items()}
        buy_cap = {hid: r["imp"] for hid, r in readings.items()}
        sell_cap["BAT"] = int(self.battery.available_wh())
        buy_cap["BAT"] = int(self.battery.headroom_wh())
        fills = [dict(seller=f.seller, buyer=f.buyer, scheduled=f.wh, wh=float(f.wh), price=f.price) for f in res.fills]
        for side, cap in (("seller", sell_cap), ("buyer", buy_cap)):
            tot: dict[str, float] = {}
            for f in fills:
                tot[f[side]] = tot.get(f[side], 0) + f["wh"]
            for f in fills:
                if tot[f[side]] > cap.get(f[side], 0):
                    f["wh"] = f["wh"] * cap.get(f[side], 0) / tot[f[side]]
        # buyer must be able to pay (escrow)
        bal = {r["home_id"]: r for r in self.store.all("SELECT * FROM balances")}
        delivered = []
        for f in fills:
            f["wh"] = int(f["wh"])
            if f["wh"] <= 0:
                continue
            gross = f["wh"] * f["price"] // 1000
            fee = f["wh"] * tariffs.TOTAL_FEE // 1000
            half = fee // 2
            pay = gross + (fee - half)
            if bal[f["buyer"]]["escrow"] < pay:
                self.store.alert("warn", "funds", f"{self.by_id[f['buyer']].name} has insufficient balance",
                                 t.isoformat(), iv, f["buyer"])
                continue
            bal[f["buyer"]]["escrow"] -= pay
            bal[f["seller"]]["escrow"] += gross - half
            f.update(gross=gross, fee=fee, half=half, pay=pay)
            delivered.append(f)

        # battery state of charge
        for f in delivered:
            if f["buyer"] == "BAT":
                self.battery.soc_wh += f["wh"] * self.battery.efficiency
            if f["seller"] == "BAT":
                self.battery.soc_wh -= f["wh"] / self.battery.efficiency
        bat_exp = sum(f["wh"] for f in delivered if f["seller"] == "BAT")
        bat_imp = sum(f["wh"] for f in delivered if f["buyer"] == "BAT")
        readings["BAT"] = dict(gen=0, load=0, exp=bat_exp, imp=bat_imp, tampered=False, accepted=True,
                               max_plausible_wh=battery_spec()[1] * 250, anomaly_score=None, anomalous=False)

        # 7. sign readings (EIP-712, as the meter would)
        sigs = {}
        for hid, r in readings.items():
            h = self.by_id[hid]
            sigs[hid] = sign_reading(meter_signer_key(h), self.chain_id, self.market_addr, h.meter_key, iv,
                                     r["exp"], r["imp"])

        # 8. Merkle commitment over delivered fills
        hour_start = local_hour_start(t)
        leaves, items = [], []
        for idx, f in enumerate(delivered):
            s, b = self.by_id[f["seller"]], self.by_id[f["buyer"]]
            f["idx"] = idx
            f["cert_id"] = cert_id_for(s.meter_key, hour_start) if s.role == "prosumer" else None
            leaves.append(fill_leaf(iv, idx, s.meter_key, s.wallet, b.wallet, f["wh"], f["price"]))
        root = MerkleTree(leaves).root if leaves else b"\x00" * 32
        if leaves:
            tree = MerkleTree(leaves)
            for idx, f in enumerate(delivered):
                s, b = self.by_id[f["seller"]], self.by_id[f["buyer"]]
                r = readings[f["seller"]]
                items.append({
                    "fill": (iv, idx, s.meter_key, s.wallet, b.wallet, f["wh"], f["price"]),
                    "proof": tree.proof(idx),
                    "reading": (s.meter_key, iv, r["exp"], r["imp"]),
                    "sig": sigs[f["seller"]],
                })

        # 9. persist
        self._persist(t, iv, period, gp, lo, hi, poa, res, orders, delivered, readings, sigs, fc, ob_hash, root, bal)

        # 10. on-chain settlement in the background
        status = "pending" if self.chain is not None else ("offchain" if not settings.chain_enabled else "chain-error")
        if not delivered:
            status = "no-trades"
        self.store.execute("UPDATE intervals SET status=? WHERE id=?", (status, iv))
        if status == "offchain":
            self.store.execute("UPDATE fills SET status='offchain' WHERE interval_id=?", (iv,))
        if self.chain is not None and delivered:
            self.jobs.put(dict(iv=iv, ob_hash=ob_hash, price=res.price or 0, root=root, n=len(delivered), items=items))

    def _ref_price(self, t: pd.Timestamp) -> int | None:
        if self.ref_prices is None or not len(self.ref_prices):
            return None
        v = self.ref_prices.get(floor_local(t, "h"))
        return None if v is None or pd.isna(v) else int(v)

    def _persist(self, t, iv, period, gp, lo, hi, poa, res, orders, delivered, readings, sigs, fc, ob_hash, root, bal):
        st = self.store
        w = self.weather.df.loc[t]
        volume = sum(f["wh"] for f in delivered)
        totals = {
            "solar_wh": sum(r["gen"] for r in readings.values()),
            "load_wh": sum(r["load"] for r in readings.values()),
            "export_wh": sum(r["exp"] for k, r in readings.items() if k != "BAT" and r["accepted"]),
            "import_wh": sum(r["imp"] for k, r in readings.items() if k != "BAT"),
            "battery_soc": self.battery.soc_wh / self.battery.capacity_wh,
        }
        st.execute(
            """INSERT OR REPLACE INTO intervals(id,start_ts,period,clearing_price,volume_wh,scheduled_wh,n_bids,n_asks,
               n_fills,orderbook_hash,fills_root,ghi,temp,grid_price,floor,ceiling,battery_soc,status,curves,totals,
               ref_price,period_label)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (iv, t.isoformat(), period, res.price if delivered else None, volume, res.volume_wh,
             sum(o.side == "buy" for o in orders), sum(o.side == "sell" for o in orders), len(delivered),
             ob_hash, "0x" + root.hex(), float(w.ghi), float(w.temp_air), gp, lo, hi,
             totals["battery_soc"], "processing", dumps(supply_demand_curves(orders)), dumps(totals),
             self._ref_price(t), tariffs.period_label(t)),
        )
        st.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?)",
                       [(iv, o.agent, o.side, o.wh, o.price, o.reason) for o in orders])
        st.executemany(
            "INSERT OR REPLACE INTO fills VALUES (?,?,?,?,?,?,?,?,?)",
            [(iv, f["idx"], f["seller"], f["buyer"], f["wh"], f["scheduled"], f["price"], f["cert_id"], "pending")
             for f in delivered],
        )
        st.executemany(
            "INSERT OR REPLACE INTO readings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(iv, hid, r["gen"], r["load"], r["exp"], r["imp"], fc.get(hid, (0, 0))[0], fc.get(hid, (0, 0))[1],
              r["max_plausible_wh"], r["anomaly_score"], int(r["accepted"]), int(r["tampered"]),
              "0x" + sigs[hid].hex()) for hid, r in readings.items()],
        )
        hour_start = local_hour_start(t)
        for f in delivered:
            s = self.by_id[f["seller"]]
            st.execute(
                """UPDATE balances SET escrow=?, earned=earned+?, sold_wh=sold_wh+?, netmeter_value=netmeter_value+?
                   WHERE home_id=?""",
                (bal[f["seller"]]["escrow"], f["gross"] - f["half"], f["wh"], f["wh"] * tariffs.FEED_IN // 1000, f["seller"]),
            )
            st.execute(
                """UPDATE balances SET escrow=?, spent=spent+?, bought_wh=bought_wh+?, grid_cost_avoided=grid_cost_avoided+?,
                   points=points+? WHERE home_id=?""",
                (bal[f["buyer"]]["escrow"], f["pay"], f["wh"], f["wh"] * gp // 1000,
                 f["wh"] if f["cert_id"] else 0, f["buyer"]),
            )
            if f["cert_id"]:
                st.execute(
                    """INSERT INTO certificates(cert_id, meter_id, home_id, hour_start, zone, minted_wh) VALUES (?,?,?,?,?,?)
                       ON CONFLICT(cert_id) DO UPDATE SET minted_wh = minted_wh + excluded.minted_wh""",
                    (f["cert_id"], s.meter_id, s.home_id,
                     datetime.fromtimestamp(hour_start, settings.tz).isoformat(), settings.zone, f["wh"]),
                )
                st.execute(
                    """INSERT INTO holdings VALUES (?,?,?) ON CONFLICT(cert_id, home_id) DO UPDATE SET wh = wh + excluded.wh""",
                    (f["cert_id"], f["buyer"], f["wh"]),
                )

    # ---------------------------------------------------------------- chain worker
    def _chain_worker(self) -> None:
        while True:
            job = self.jobs.get()
            iv = job["iv"]
            try:
                commit_tx = self.chain.commit(iv, job["ob_hash"], job["price"], job["root"], job["n"])
                self.store.execute("UPDATE intervals SET commit_tx=?, status='committed' WHERE id=?", (commit_tx, iv))
                txs = self.chain.settle_batch(job["items"])
                self.store.execute("UPDATE intervals SET settle_tx=?, status='settled' WHERE id=?", (",".join(txs), iv))
                self.store.execute("UPDATE fills SET status='settled' WHERE interval_id=?", (iv,))
            except Exception as e:  # noqa: BLE001
                msg = str(e)[:300]
                log.error("settlement of %s failed: %s", iv, msg)
                self.store.execute("UPDATE intervals SET status='chain-error', error=? WHERE id=?", (msg, iv))
                self.store.execute("UPDATE fills SET status='chain-error' WHERE interval_id=?", (iv,))
                self.store.alert("critical", "chain", f"Settlement failed for interval {iv}: {msg}", interval_id=iv)

    def wait_chain_idle(self, timeout: float = 120) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.jobs.unfinished_tasks == 0 or self.jobs.empty():
                pending = self.store.one("SELECT COUNT(*) n FROM intervals WHERE status IN ('pending','committed')")
                if pending["n"] == 0:
                    return True
            time.sleep(0.3)
        return False

    # ---------------------------------------------------------------- certificates
    def retire(self, home_id: str, cert_id: str, wh: int, beneficiary: str) -> dict:
        h = self.by_id[home_id]
        held = self.store.one("SELECT wh FROM holdings WHERE cert_id=? AND home_id=?", (cert_id, home_id))
        held_wh = held["wh"] if held else 0
        if wh <= 0:
            return {"ok": False, "layer": "api", "error": "amount must be positive"}
        if self.chain is not None:
            unsettled = self.store.one(
                "SELECT COUNT(*) n FROM fills WHERE cert_id=? AND buyer=? AND status NOT IN ('settled')", (cert_id, home_id))["n"]
            if unsettled and held_wh >= wh:
                return {"ok": False, "layer": "pending", "error": "StillSettling",
                        "message": "This certificate's trade is still being settled on-chain. Try again in a few seconds."}
            err = self.chain.simulate_retire(h, int(cert_id, 16), wh, beneficiary)
            if err:
                return {"ok": False, "layer": "smart-contract", "error": err.name, "args": [str(a) for a in err.args_],
                        "message": f"Rejected by GranularCertificate: {err.name}. "
                                   f"{h.name} holds {held_wh} Wh of this certificate, tried to retire {wh} Wh."}
            tx = self.chain.retire(h, int(cert_id, 16), wh, beneficiary)
        else:
            if held_wh < wh:
                return {"ok": False, "layer": "ledger", "error": "ERC1155InsufficientBalance",
                        "message": f"{h.name} holds {held_wh} Wh of this certificate, tried to retire {wh} Wh. "
                                   "Each Wh can only be claimed once."}
            tx = None
        self.store.execute("UPDATE holdings SET wh = wh - ? WHERE cert_id=? AND home_id=?", (wh, cert_id, home_id))
        self.store.execute("UPDATE certificates SET retired_wh = retired_wh + ? WHERE cert_id=?", (wh, cert_id))
        self.store.execute("UPDATE balances SET points = points + ? WHERE home_id=?", (wh, home_id))
        cur = self.store.execute(
            "INSERT INTO retirements(cert_id, home_id, wh, beneficiary, ts, tx, status) VALUES (?,?,?,?,?,?,?)",
            (cert_id, home_id, wh, beneficiary, datetime.now(settings.tz).isoformat(timespec="seconds"), tx,
             "on-chain" if tx else "off-chain"),
        )
        return {"ok": True, "retirement_id": cur.lastrowid, "tx": tx}

    # ---------------------------------------------------------------- demo
    def tamper(self, home_id: str = "H03", export_wh: float = 3000) -> dict:
        h = self.by_id[home_id]
        self.pending_tamper[home_id] = export_wh
        return {"home_id": home_id, "meter_id": h.meter_id, "claimed_export_wh": export_wh,
                "applies_to": (self.clock + pd.Timedelta(minutes=15)).isoformat()}

    # ---------------------------------------------------------------- KPIs
    def kpis(self) -> dict:
        st = self.store
        f = st.one("""SELECT COUNT(*) n, COALESCE(SUM(f.wh),0) wh, COALESCE(SUM(f.scheduled_wh),0) sched FROM fills f""")
        solar_f = st.one("""SELECT COALESCE(SUM(f.wh),0) wh FROM fills f WHERE f.seller != 'BAT'""")
        bat = st.one("""SELECT COALESCE(SUM(CASE WHEN buyer='BAT' THEN wh END),0) charged,
                               COALESCE(SUM(CASE WHEN seller='BAT' THEN wh END),0) discharged FROM fills""")
        ex = st.one("""SELECT COALESCE(SUM(r.export_wh),0) exp, COALESCE(SUM(r.gen_wh),0) gen, COALESCE(SUM(r.load_wh),0) load
                       FROM readings r WHERE r.home_id != 'BAT' AND r.accepted = 1""")
        uplift = st.one(f"""SELECT COALESCE(SUM(f.wh * (f.price - {tariffs.HALF_FEE} - {tariffs.FEED_IN})),0)/1000 v
                            FROM fills f WHERE f.seller != 'BAT'""")["v"]
        savings = st.one(f"""SELECT COALESCE(SUM(f.wh * (i.grid_price - f.price - {tariffs.TOTAL_FEE - tariffs.HALF_FEE})),0)/1000 v
                             FROM fills f JOIN intervals i ON i.id=f.interval_id WHERE f.buyer != 'BAT'""")["v"]
        cfe = st.one("""
            WITH certs AS (SELECT f.buyer, i.start_ts, f.interval_id, SUM(f.wh) wh FROM fills f
                           JOIN intervals i ON i.id=f.interval_id WHERE f.seller != 'BAT' AND f.buyer != 'BAT'
                           GROUP BY f.buyer, substr(i.start_ts,1,13)),
                 use AS (SELECT r.home_id, substr(i.start_ts,1,13) hr, SUM(r.load_wh) load FROM readings r
                         JOIN intervals i ON i.id=r.interval_id WHERE r.home_id != 'BAT' GROUP BY r.home_id, hr)
            SELECT COALESCE(SUM(MIN(c.wh, u.load)),0) matched, (SELECT SUM(load_wh) FROM readings WHERE home_id!='BAT') total
            FROM certs c JOIN use u ON u.home_id=c.buyer AND u.hr=substr(c.start_ts,1,13)""")
        rej = st.one("SELECT COUNT(*) n FROM readings WHERE accepted=0")["n"]
        live = st.one("""SELECT COALESCE(AVG(ABS(gen_fc-gen_wh)),0) gen_mae, COALESCE(AVG(ABS(load_fc-load_wh)),0) load_mae
                         FROM readings r JOIN (SELECT id FROM intervals) i ON i.id=r.interval_id
                         WHERE r.home_id!='BAT' AND (r.gen_wh>0 OR r.gen_fc>0)""")
        ivs = st.one("SELECT COUNT(*) n, SUM(status='settled') settled FROM intervals")
        surplus = ex["exp"] or 0
        return {
            "intervals": ivs["n"], "intervals_settled_onchain": ivs["settled"] or 0,
            "trades": f["n"], "traded_kwh": round(f["wh"] / 1000, 2),
            "solar_traded_kwh": round(solar_f["wh"] / 1000, 2),
            "solar_generated_kwh": round(ex["gen"] / 1000, 2), "surplus_kwh": round(surplus / 1000, 2),
            "local_use_of_surplus_pct": round(100 * (solar_f["wh"]) / surplus, 1) if surplus else 0,
            "battery_charged_kwh": round(bat["charged"] / 1000, 2), "battery_discharged_kwh": round(bat["discharged"] / 1000, 2),
            "battery_soc_pct": round(100 * self.battery.soc_wh / self.battery.capacity_wh, 1),
            "prosumer_extra_earnings": round(uplift / RS, 2),
            "consumer_savings": round(savings / RS, 2),
            "hourly_cfe_pct": round(100 * cfe["matched"] / cfe["total"], 2) if cfe["total"] else 0,
            "co2_displaced_kg": round(solar_f["wh"] / 1000 * self.intensity, 2),
            "grid_intensity_kg_per_kwh": round(self.intensity, 3),
            "delivery_shortfall_pct": round(100 * (f["sched"] - f["wh"]) / f["sched"], 1) if f["sched"] else 0,
            "oracle_rejections": rej,
            "forecast": {"holdout": self.forecaster.metrics,
                         "live_mae_wh": {"generation": round(live["gen_mae"], 1), "load": round(live["load_mae"], 1)}},
        }

    def state(self) -> dict:
        last = self.store.one("SELECT * FROM intervals ORDER BY id DESC LIMIT 1")
        return {
            "ready": self.ready, "status": self.status_msg, "running": self.running,
            "clock": self.clock.isoformat(), "clock_mode": settings.clock_mode,
            "seconds_per_interval": settings.seconds_per_interval,
            "period": tariffs.period(self.clock + pd.Timedelta(minutes=15)),
            "period_label": tariffs.period_label(self.clock + pd.Timedelta(minutes=15)),
            "site": {"id": settings.site_id, "name": settings.site_name, "lat": settings.lat, "lon": settings.lon,
                     "zone": settings.zone, "landmark": settings.landmark, "tz": settings.tz.key},
            "country": self.profile.public(),
            "data_sources": self.data_sources,
            "weather_source": self.weather.source,
            "chain": {"enabled": settings.chain_enabled, "status": self.chain_status, "error": self.chain_error,
                      **(self.chain.info() if self.chain else {})},
            "last_interval": _interval_public(last) if last else None,
            "tariffs": tariffs.as_dict(),
        }


def _interval_public(r: dict) -> dict:
    import json
    d = dict(r)
    for k in ("clearing_price", "grid_price", "floor", "ceiling", "ref_price"):
        d[k] = None if d.get(k) is None else d[k] / RS
    d["curves"] = json.loads(d["curves"]) if d.get("curves") else None
    d["totals"] = json.loads(d["totals"]) if d.get("totals") else None
    return d
