"""Deploy the HourGrid contracts from Foundry build artifacts (contracts/out).

    python -m hourgrid.deploy        # uses RPC_URL and OPERATOR_KEY from .env

Equivalent to `forge script script/Deploy.s.sol --broadcast`; writes
contracts/deployments/<chainId>.json, which the backend reads at startup.
"""
from __future__ import annotations

import json
import logging

from eth_account import Account
from web3 import Web3

from . import tariffs
from .config import ROOT, settings

log = logging.getLogger("hourgrid.deploy")


def _artifact(name: str) -> dict:
    """Fresh `forge build` output if present, otherwise the prebuilt copy shipped in contracts/artifacts."""
    for p in (settings.contracts_out / f"{name}.sol" / f"{name}.json", ROOT / "contracts" / "artifacts" / f"{name}.json"):
        if p.exists():
            return json.loads(p.read_text())
    raise RuntimeError(f"no build artifact for {name}; run `forge build` in contracts/")


def deploy_all(profile=None) -> dict:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    profile = profile or tariffs.PROFILE
    w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 60}))
    acct = Account.from_key(settings.operator_key)
    chain_id = w3.eth.chain_id
    nonce = w3.eth.get_transaction_count(acct.address, "pending")

    def fees() -> dict:
        base = w3.eth.get_block("latest").get("baseFeePerGas")
        if base is None:
            return {"gasPrice": w3.eth.gas_price}
        tip = Web3.to_wei(30, "gwei") if chain_id in (80002, 137) else Web3.to_wei(1, "gwei")
        return {"maxPriorityFeePerGas": tip, "maxFeePerGas": base * 2 + tip}

    def send(tx: dict) -> dict:
        nonlocal nonce
        tx.update({"from": acct.address, "nonce": nonce, "chainId": chain_id, **fees()})
        tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
        h = w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
        nonce += 1
        r = w3.eth.wait_for_transaction_receipt(h, timeout=240)
        if r.status != 1:
            raise RuntimeError(f"deploy tx reverted {h.hex()}")
        return r

    def deploy(name: str, *args):
        a = _artifact(name)
        c = w3.eth.contract(abi=a["abi"], bytecode=a["bytecode"]["object"])
        r = send(c.constructor(*args).build_transaction({"from": acct.address}))
        log.info("deployed %s at %s", name, r.contractAddress)
        return w3.eth.contract(address=r.contractAddress, abi=a["abi"])

    admin = acct.address
    inr = deploy("SettlementToken", admin, profile.token_name, profile.token_symbol)
    registry = deploy("MeterRegistry", admin)
    points = deploy("GreenHourPoints", admin)
    certs = deploy("GranularCertificate", admin, points.address)
    market = deploy("HourGridMarket", admin, inr.address, registry.address, certs.address, points.address,
                    admin, tariffs.WHEELING_FEE, tariffs.TOTAL_FEE - tariffs.WHEELING_FEE,
                    int(datetime.now(ZoneInfo(profile.tz)).utcoffset().total_seconds()))
    minter_c = certs.functions.MINTER_ROLE().call()
    minter_p = points.functions.MINTER_ROLE().call()
    send(certs.functions.grantRole(minter_c, market.address).build_transaction({"from": admin}))
    send(points.functions.grantRole(minter_p, market.address).build_transaction({"from": admin}))
    send(points.functions.grantRole(minter_p, certs.address).build_transaction({"from": admin}))

    out = {"SettlementToken": inr.address, "country": profile.code, "currency": profile.token_symbol, "MeterRegistry": registry.address, "GreenHourPoints": points.address,
           "GranularCertificate": certs.address, "HourGridMarket": market.address,
           "chainId": chain_id, "deployBlock": w3.eth.block_number}
    d = ROOT / "contracts" / "deployments"
    d.mkdir(exist_ok=True)
    (d / f"{chain_id}.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(deploy_all(), indent=2))
