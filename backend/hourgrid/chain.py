"""Blockchain client: deploy-file loading, meter onboarding, interval commit + settlement,
gasless certificate retirement, and decoding of custom Solidity errors."""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from eth_abi import decode
from eth_account import Account
from eth_utils import function_signature_to_4byte_selector
from web3 import Web3
from web3.exceptions import ContractCustomError, ContractLogicError

from .config import ROOT, settings
from .neighbourhood import Home, meter_signer_key, wallet_key  # noqa: F401
from .signing import sign_retire

log = logging.getLogger("hourgrid.chain")
NAMES = ["SettlementToken", "MeterRegistry", "GreenHourPoints", "GranularCertificate", "HourGridMarket"]
KIND = {"consumer": 0, "prosumer": 1, "battery": 2}
SETTLE_CHUNK = 12


class ChainError(Exception):
    def __init__(self, name: str, args: tuple = (), raw: str = ""):
        self.name, self.args_, self.raw = name, args, raw
        super().__init__(f"{name}{args if args else ''}")


class Chain:
    def __init__(self) -> None:
        self.w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 60}))
        if not self.w3.is_connected():
            raise RuntimeError(f"cannot reach RPC {settings.rpc_url}")
        if not settings.operator_key:
            raise RuntimeError("OPERATOR_KEY is not set")
        self.chain_id = self.w3.eth.chain_id
        self.operator = Account.from_key(settings.operator_key)
        self.lock = threading.Lock()
        self.nonce = self.w3.eth.get_transaction_count(self.operator.address, "pending")
        dep_file = Path(settings.deployments_file) if settings.deployments_file else \
            ROOT / "contracts" / "deployments" / f"{self.chain_id}.json"
        if not dep_file.exists():
            raise RuntimeError(f"no deployment file {dep_file}; run the deploy script first")
        self.addresses = json.loads(dep_file.read_text())
        self.c = {}
        self.errors: dict[bytes, tuple[str, list[str]]] = {}
        for n in NAMES:
            from .deploy import _artifact
            abi = _artifact(n)["abi"]
            self.c[n] = self.w3.eth.contract(address=Web3.to_checksum_address(self.addresses[n]), abi=abi)
            for item in abi:
                if item.get("type") == "error":
                    types = [i["type"] for i in item["inputs"]]
                    sig = f"{item['name']}({','.join(types)})"
                    self.errors[function_signature_to_4byte_selector(sig)] = (item["name"], types)
        self.market = self.c["HourGridMarket"]
        self.certs = self.c["GranularCertificate"]
        log.info("chain %s connected, market %s", self.chain_id, self.market.address)

    # ---------------------------------------------------------------- tx plumbing
    def decode_error(self, e: Exception) -> ChainError:
        data = getattr(e, "data", None)
        if data is None and e.args and isinstance(e.args[0], str) and e.args[0].startswith("0x"):
            data = e.args[0]
        if isinstance(data, dict):
            data = data.get("data")
        if isinstance(data, str) and data.startswith("0x") and len(data) >= 10:
            raw = bytes.fromhex(data[2:])
            if raw[:4] in self.errors:
                name, types = self.errors[raw[:4]]
                try:
                    vals = decode(types, raw[4:])
                except Exception:  # noqa: BLE001
                    vals = ()
                return ChainError(name, tuple(v.hex() if isinstance(v, bytes) else v for v in vals), data)
        return ChainError(type(e).__name__, (str(e)[:200],))

    def _fees(self) -> dict:
        latest = self.w3.eth.get_block("latest")
        base = latest.get("baseFeePerGas")
        if base is None:
            return {"gasPrice": self.w3.eth.gas_price}
        try:
            tip = self.w3.eth.max_priority_fee
        except Exception:  # noqa: BLE001
            tip = Web3.to_wei(1, "gwei")
        if self.chain_id in (80002, 137):  # Polygon requires >= 25 gwei tip
            tip = max(tip, Web3.to_wei(30, "gwei"))
        return {"maxPriorityFeePerGas": tip, "maxFeePerGas": base * 2 + tip}

    def send(self, fn, gas: int | None = None) -> str:
        with self.lock:
            try:
                tx = fn.build_transaction({"from": self.operator.address, "nonce": self.nonce,
                                           "chainId": self.chain_id, **self._fees()})
                est = self.w3.eth.estimate_gas(tx)
            except (ContractCustomError, ContractLogicError) as e:
                raise self.decode_error(e) from None
            tx["gas"] = gas or int(est * 1.25)
            signed = self.operator.sign_transaction(tx)
            h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            self.nonce += 1
        rcpt = self.w3.eth.wait_for_transaction_receipt(h, timeout=180)
        if rcpt.status != 1:
            raise ChainError("TransactionReverted", (h.hex(),))
        return "0x" + h.hex().removeprefix("0x")

    # ---------------------------------------------------------------- setup
    def bootstrap(self, homes: list[Home], zone: bytes, deposit_micro: int) -> list[str]:
        reg, inr = self.c["MeterRegistry"], self.c["SettlementToken"]
        txs = []
        for h in homes:
            try:
                reg.functions.meter(h.meter_key).call()
                continue
            except (ContractCustomError, ContractLogicError):
                pass
            txs.append(self.send(reg.functions.register(
                h.meter_key, h.signer, h.wallet, h.capacity_w, KIND[h.role], zone)))
        need = 0
        todo = []
        for h in homes:
            if self.market.functions.balanceOf(h.wallet).call() == 0:
                todo.append(h)
                need += deposit_micro
        if todo:
            if inr.functions.balanceOf(self.operator.address).call() < need:
                txs.append(self.send(inr.functions.mint(self.operator.address, need * 4)))
            if inr.functions.allowance(self.operator.address, self.market.address).call() < need:
                txs.append(self.send(inr.functions.approve(self.market.address, 2**256 - 1)))
            for h in todo:
                txs.append(self.send(self.market.functions.depositFor(h.wallet, deposit_micro)))
        log.info("bootstrap done: %d txs", len(txs))
        return txs

    # ---------------------------------------------------------------- settlement
    def commit(self, interval_id: int, ob_hash: str, price: int, root: bytes, n: int) -> str:
        return self.send(self.market.functions.commitInterval(
            interval_id, bytes.fromhex(ob_hash[2:]), price, root, n))

    def settle_batch(self, items: list[dict]) -> list[str]:
        txs = []
        for i in range(0, len(items), SETTLE_CHUNK):
            chunk = items[i:i + SETTLE_CHUNK]
            txs.append(self.send(self.market.functions.settleBatch(
                [it["fill"] for it in chunk], [it["proof"] for it in chunk],
                [it["reading"] for it in chunk], [it["sig"] for it in chunk])))
        return txs

    # ---------------------------------------------------------------- certificates
    def _retire_args(self, h: Home, cert_id: int, amount: int, beneficiary: str):
        nonce = self.certs.functions.nonces(h.wallet).call()
        deadline = int(time.time()) + 3600
        sig = sign_retire(wallet_key(h), self.chain_id, self.certs.address, h.wallet, cert_id, amount,
                          beneficiary, nonce, deadline)
        return self.certs.functions.retireWithSig(h.wallet, cert_id, amount, beneficiary, deadline, sig)

    def simulate_retire(self, h: Home, cert_id: int, amount: int, beneficiary: str) -> ChainError | None:
        try:
            self._retire_args(h, cert_id, amount, beneficiary).call({"from": self.operator.address})
            return None
        except (ContractCustomError, ContractLogicError) as e:
            return self.decode_error(e)

    def retire(self, h: Home, cert_id: int, amount: int, beneficiary: str) -> str:
        return self.send(self._retire_args(h, cert_id, amount, beneficiary))

    # ---------------------------------------------------------------- reads
    def cert_onchain(self, cert_id: int, holder: str | None = None) -> dict:
        meter, hour, zone, minted, retired = self.certs.functions.info(cert_id).call()
        out = {"meter_id": "0x" + meter.hex(), "hour_start": hour, "minted_wh": minted, "retired_wh": retired}
        if holder:
            out["holder_balance_wh"] = self.certs.functions.balanceOf(holder, cert_id).call()
        return out

    def escrow(self, wallet: str) -> int:
        return self.market.functions.balanceOf(wallet).call()

    def info(self) -> dict:
        return {"chain_id": self.chain_id, "rpc": settings.rpc_url, "operator": self.operator.address,
                "contracts": {n: self.c[n].address for n in NAMES}, "explorer": settings.explorer_url,
                "block": self.w3.eth.block_number}
