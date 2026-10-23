"""EIP-712 signatures that match the Solidity contracts.

Meters sign readings (HourGridMarket domain); holders sign certificate retirements
(GranularCertificate domain) so the DISCOM relayer can submit them gas-free.
"""
from __future__ import annotations

from eth_account import Account
from eth_account.messages import encode_typed_data


def sign_reading(key: str, chain_id: int, market: str, meter_id: bytes, interval_id: int,
                 export_wh: int, import_wh: int) -> bytes:
    data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"}, {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"},
            ],
            "Reading": [
                {"name": "meterId", "type": "bytes32"}, {"name": "intervalId", "type": "uint64"},
                {"name": "exportWh", "type": "uint32"}, {"name": "importWh", "type": "uint32"},
            ],
        },
        "primaryType": "Reading",
        "domain": {"name": "HourGrid", "version": "1", "chainId": chain_id, "verifyingContract": market},
        "message": {"meterId": meter_id, "intervalId": interval_id, "exportWh": export_wh, "importWh": import_wh},
    }
    return Account.sign_message(encode_typed_data(full_message=data), key).signature


def sign_retire(key: str, chain_id: int, cert_contract: str, holder: str, cert_id: int, amount: int,
                beneficiary: str, nonce: int, deadline: int) -> bytes:
    data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"}, {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"},
            ],
            "Retire": [
                {"name": "holder", "type": "address"}, {"name": "id", "type": "uint256"},
                {"name": "amount", "type": "uint256"}, {"name": "beneficiary", "type": "string"},
                {"name": "nonce", "type": "uint256"}, {"name": "deadline", "type": "uint256"},
            ],
        },
        "primaryType": "Retire",
        "domain": {"name": "HourGridCertificate", "version": "1", "chainId": chain_id,
                   "verifyingContract": cert_contract},
        "message": {"holder": holder, "id": cert_id, "amount": amount, "beneficiary": beneficiary,
                    "nonce": nonce, "deadline": deadline},
    }
    return Account.sign_message(encode_typed_data(full_message=data), key).signature
