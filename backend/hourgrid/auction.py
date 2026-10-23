"""Uniform-price k-double auction for one 15-minute interval.

Bids (buy) sorted by price descending, asks (sell) ascending. The traded quantity is
where the curves cross. Every trade clears at one price: k * marginal bid +
(1 - k) * marginal ask (k = 0.5), clamped to the regulatory price band. Fills pair
asks with bids in merit order, so each fill is (seller, buyer, Wh) at that price.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass
class Order:
    agent: str  # home_id
    side: str  # "buy" | "sell"
    wh: int
    price: int  # micro-INR per kWh (limit price)
    reason: str = ""


@dataclass
class Fill:
    seller: str
    buyer: str
    wh: int
    price: int


@dataclass
class ClearingResult:
    price: int | None
    volume_wh: int
    fills: list[Fill]
    marginal_bid: int | None
    marginal_ask: int | None


def clear(orders: list[Order], floor: int, ceiling: int, k: float = 0.5) -> ClearingResult:
    bids = sorted([o for o in orders if o.side == "buy" and o.wh > 0], key=lambda o: (-o.price, o.agent))
    asks = sorted([o for o in orders if o.side == "sell" and o.wh > 0], key=lambda o: (o.price, o.agent))
    bi = ai = 0
    brem = bids[0].wh if bids else 0
    arem = asks[0].wh if asks else 0
    pairs: list[tuple[str, str, int]] = []
    last_bid = last_ask = None
    while bi < len(bids) and ai < len(asks) and bids[bi].price >= asks[ai].price:
        q = min(brem, arem)
        pairs.append((asks[ai].agent, bids[bi].agent, q))
        last_bid, last_ask = bids[bi].price, asks[ai].price
        brem -= q
        arem -= q
        if brem == 0:
            bi += 1
            brem = bids[bi].wh if bi < len(bids) else 0
        if arem == 0:
            ai += 1
            arem = asks[ai].wh if ai < len(asks) else 0

    if not pairs:
        return ClearingResult(None, 0, [], None, None)
    price = int(round(k * last_bid + (1 - k) * last_ask))
    price = max(floor, min(ceiling, price))
    # merge duplicate seller/buyer pairs
    merged: dict[tuple[str, str], int] = {}
    for s, b, q in pairs:
        if s != b:
            merged[(s, b)] = merged.get((s, b), 0) + q
    fills = [Fill(s, b, q, price) for (s, b), q in merged.items() if q > 0]
    return ClearingResult(price, sum(f.wh for f in fills), fills, last_bid, last_ask)


def orderbook_hash(interval_id: int, orders: list[Order]) -> str:
    """Hash of the full order book, committed on-chain so anyone can re-run the clearing."""
    canon = json.dumps(
        {"interval": interval_id,
         "orders": sorted([asdict(o) | {"reason": ""} for o in orders], key=lambda d: (d["side"], d["agent"]))},
        sort_keys=True, separators=(",", ":"),
    )
    return "0x" + hashlib.sha3_256(canon.encode()).hexdigest()


def supply_demand_curves(orders: list[Order]) -> dict:
    """Step curves for the order-book chart (cumulative Wh vs price per kWh)."""
    def curve(side, reverse):
        cum, pts = 0, []
        for o in sorted([o for o in orders if o.side == side], key=lambda o: o.price, reverse=reverse):
            pts.append({"wh": cum, "price": o.price / 1e6})
            cum += o.wh
            pts.append({"wh": cum, "price": o.price / 1e6})
        return pts
    return {"demand": curve("buy", True), "supply": curve("sell", False)}
