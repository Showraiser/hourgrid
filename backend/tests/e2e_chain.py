"""End-to-end check against a running chain (anvil or a testnet).

    anvil &                       # in another terminal
    python tests/e2e_chain.py     # uses RPC_URL / OPERATOR_KEY from env (defaults: anvil)

Deploys fresh contracts, runs a simulated morning-to-evening market, then checks that the
on-chain state matches the backend ledger, that a forged meter reading is rejected,
and that a certificate cannot be retired twice.
"""
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHAIN_ENABLED", "1")
os.environ.setdefault("AUTOSTART", "0")
os.environ.setdefault("RPC_URL", "http://127.0.0.1:8545")
os.environ.setdefault("OPERATOR_KEY", "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")
os.environ.setdefault("DB_PATH", os.path.join(__import__("tempfile").gettempdir(), "hourgrid_e2e.db"))
os.environ.setdefault("WEATHER_PROVIDER", "auto")
os.environ.setdefault("COUNTRY", "TR")

from hourgrid.config import settings  # noqa: E402
from hourgrid.engine import Engine  # noqa: E402
from hourgrid.store import Store  # noqa: E402

logging.basicConfig(level=logging.WARNING)
STEPS = int(os.getenv("E2E_STEPS", "56"))  # 06:00 -> 20:00
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")


t0 = time.time()
e = Engine(Store(settings.db_path), fresh_chain=True)
while e.chain_status not in ("connected", "error"):
    time.sleep(0.5)
print(f"chain: {e.chain_status} {e.chain_error} ({time.time() - t0:.0f}s), weather: {e.weather.source}")
check("chain connected and meters onboarded", e.chain_status == "connected")
if e.chain is None:
    sys.exit(1)

for i in range(STEPS):
    if i == STEPS - 4:
        e.tamper("H03", 3000)
    e.step()
print(f"simulated to {e.clock}, waiting for settlement...")
check("all intervals settled on-chain", e.wait_chain_idle(600))

st, ch = e.store, e.chain
k = e.kpis()
print(f"  trades={k['trades']} traded={k['traded_kwh']} kWh, settled intervals={k['intervals_settled_onchain']}")
errs = st.all("SELECT id, error FROM intervals WHERE status='chain-error'")
check("no settlement errors", not errs, str(errs[:2]))

mism = [h.home_id for h in e.homes
        if ch.escrow(h.wallet) != st.one("SELECT escrow FROM balances WHERE home_id=?", (h.home_id,))["escrow"]]
check("escrow balances on-chain == backend ledger (25 accounts)", not mism, str(mism))

certs = st.all("SELECT * FROM certificates")
bad = [c["cert_id"] for c in certs if ch.cert_onchain(int(c["cert_id"], 16))["minted_wh"] != c["minted_wh"]]
check(f"certificates minted on-chain == ledger ({len(certs)} ids)", certs and not bad)

holdings = st.all("SELECT hd.*, c.home_id producer FROM holdings hd JOIN certificates c USING(cert_id) WHERE hd.wh>0")
bad = [h for h in holdings[:40]
       if ch.certs.functions.balanceOf(e.by_id[h["home_id"]].wallet, int(h["cert_id"], 16)).call() != h["wh"]]
check("certificate balances per holder match (sample of 40)", not bad)

rej = st.one("SELECT * FROM readings WHERE home_id='H03' AND tampered=1")
check("forged 3 kWh reading rejected by physics oracle", rej and rej["accepted"] == 0,
      f"(max plausible {rej['max_plausible_wh'] if rej else '?'} Wh)")
leak = st.one("SELECT COUNT(*) n FROM fills WHERE seller='H03' AND interval_id=?", (rej["interval_id"],))["n"]
check("no trade settled from the forged reading", leak == 0)

consumer = st.one("""SELECT hd.* FROM holdings hd JOIN certificates c USING(cert_id)
                     WHERE hd.home_id != 'BAT' AND hd.wh > 0 ORDER BY hd.wh DESC LIMIT 1""")
r1 = e.retire(consumer["home_id"], consumer["cert_id"], consumer["wh"], "EV charge, Amaravati")
check("retire certificate on-chain (gasless, signed by holder)", r1["ok"] and r1["tx"], r1.get("tx", ""))
onc = ch.cert_onchain(int(consumer["cert_id"], 16), e.by_id[consumer["home_id"]].wallet)
check("on-chain retired amount recorded", onc["retired_wh"] == consumer["wh"] and onc["holder_balance_wh"] == 0)
r2 = e.retire(consumer["home_id"], consumer["cert_id"], consumer["wh"], "same kWh again")
check("second retirement of same Wh rejected by smart contract",
      not r2["ok"] and r2["layer"] == "smart-contract", r2.get("error"))

pts = ch.c["GreenHourPoints"].functions.balanceOf(e.by_id[consumer["home_id"]].wallet).call()
dbp = st.one("SELECT points FROM balances WHERE home_id=?", (consumer["home_id"],))["points"]
check("soulbound Green Hour points on-chain == ledger", pts == dbp, f"({pts})")

print(f"\n{'ALL CHECKS PASSED' if ok else 'SOME CHECKS FAILED'} in {time.time() - t0:.0f}s")
sys.exit(0 if ok else 1)
