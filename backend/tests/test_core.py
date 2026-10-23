"""Fast unit tests: pytest backend/tests"""
import os

os.environ.setdefault("WEATHER_PROVIDER", "offline")
os.environ.setdefault("AUTOSTART", "0")
os.environ.setdefault("CHAIN_ENABLED", "0")
os.environ["HF_TOKEN"] = ""
os.environ.setdefault("DB_PATH", os.path.join(__import__("tempfile").gettempdir(), "hourgrid_test.db"))
os.environ.setdefault("COUNTRY", "IN")

from hourgrid import llm  # noqa: E402
from hourgrid.auction import Order, clear  # noqa: E402
from hourgrid.merkle import MerkleTree, fill_leaf  # noqa: E402


def test_auction_uniform_price_and_quantity():
    orders = [
        Order("S1", "sell", 300, 3_300_000), Order("S2", "sell", 500, 3_800_000),
        Order("B1", "buy", 400, 5_000_000), Order("B2", "buy", 600, 3_500_000),
    ]
    r = clear(orders, floor=3_000_000, ceiling=6_000_000)
    # S1(300@3.3) + 100 of S2(3.8) go to B1(5.0); B2(3.5) is below S2's ask
    assert r.volume_wh == 400
    assert r.price == int(0.5 * 5_000_000 + 0.5 * 3_800_000)
    assert all(f.price == r.price for f in r.fills)
    assert {(f.seller, f.buyer, f.wh) for f in r.fills} == {("S1", "B1", 300), ("S2", "B1", 100)}


def test_auction_no_cross():
    r = clear([Order("S", "sell", 100, 5_000_000), Order("B", "buy", 100, 4_000_000)], 0, 10**9)
    assert r.volume_wh == 0 and r.price is None


def test_auction_price_clamped_to_band():
    r = clear([Order("S", "sell", 100, 1_000_000), Order("B", "buy", 100, 9_000_000)], 3_000_000, 6_000_000)
    assert r.price == 5_000_000 or 3_000_000 <= r.price <= 6_000_000


def test_merkle_proofs_verify_for_every_size():
    for n in range(1, 18):
        leaves = [fill_leaf(1, i, b"\x01" * 32, "0x" + "11" * 20, "0x" + "22" * 20, 100 + i, 4_000_000) for i in range(n)]
        t = MerkleTree(leaves)
        for i, leaf in enumerate(leaves):
            assert MerkleTree.verify(t.proof(i), t.root, leaf)
        assert not MerkleTree.verify(t.proof(0), t.root, b"\x00" * 32)


def test_rules_fallback_parses_instructions():
    cur = {"participate": True, "min_sell_price": None, "max_buy_price": None, "sell_share": 1.0,
           "prefer_green": False, "aggressiveness": 0.5}
    home = {"name": "x", "role": "prosumer", "pv_kwp": 3, "has_ev": True, "home_id": "H01"}
    r = llm.instruct(home, "never sell below Rs 4.5 and prefer neighbour solar", cur)
    assert r["engine"] == "rules"
    assert r["prefs"]["min_sell_price"] == 4.5 and r["prefs"]["prefer_green"] is True
    assert llm.instruct(home, "stop trading", cur)["prefs"]["participate"] is False


def test_api_smoke():
    from fastapi.testclient import TestClient

    from hourgrid import api
    api.eng()
    c = TestClient(api.app)
    assert c.get("/api/state").json()["ready"]
    assert c.post("/api/sim/step?n=40").json()["stepped"] == 40
    k = c.get("/api/kpis").json()
    assert k["trades"] > 0 and k["traded_kwh"] > 0
    assert len(c.get("/api/homes").json()) == 25
    iv = c.get("/api/intervals?limit=1").json()[0]["id"]
    assert "orders" in c.get(f"/api/intervals/{iv}").json()
    certs = c.get("/api/certificates").json()
    assert certs
    v = c.get(f"/api/certificates/{certs[0]['cert_id']}").json()
    assert v["trades"] and v["producer"]["meter_id"]
    assert c.post("/api/agents/H01/instruct", json={"text": "never sell below Rs 4"}).json()["prefs"]["min_sell_price"] == 4
    assert c.get("/api/weather").json()["today"]
    assert c.post("/api/demo/tamper", json={"home_id": "H03", "export_wh": 3000}).status_code == 200


def test_country_profiles_are_consistent():
    from hourgrid import countries, tariffs
    from datetime import datetime
    from zoneinfo import ZoneInfo
    for p in countries.PROFILES.values():
        hours = sorted((per.start, per.end) for per in p.periods)
        assert hours[0][0] == 0 and hours[-1][1] == 24, p.code
        assert all(a[1] == b[0] for a, b in zip(hours, hours[1:])), f"{p.code} periods must tile the day"
        tariffs.set_profile(p)
        for h in range(24):
            lo, hi = tariffs.price_bounds(datetime(2026, 10, 21, h, tzinfo=ZoneInfo(p.tz)))
            assert 0 <= lo < hi, (p.code, h)
    tariffs.set_profile(countries.get("IN"))
