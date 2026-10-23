"""Merkle tree compatible with OpenZeppelin MerkleProof (sorted-pair keccak256, and the
double-hashed leaf used by HourGridMarket.fillLeaf)."""
from __future__ import annotations

from eth_abi import encode
from eth_utils import keccak

FILL_TYPES = ["uint64", "uint32", "bytes32", "address", "address", "uint32", "uint128"]


def fill_leaf(interval_id: int, index: int, seller_meter: bytes, seller: str, buyer: str, wh: int, price: int) -> bytes:
    inner = keccak(encode(FILL_TYPES, [interval_id, index, seller_meter, seller, buyer, wh, price]))
    return keccak(inner)


def _hash_pair(a: bytes, b: bytes) -> bytes:
    return keccak(a + b) if a < b else keccak(b + a)


class MerkleTree:
    def __init__(self, leaves: list[bytes]):
        if not leaves:
            raise ValueError("empty tree")
        self.layers = [list(leaves)]
        while len(self.layers[-1]) > 1:
            cur = self.layers[-1]
            nxt = []
            for i in range(0, len(cur), 2):
                nxt.append(_hash_pair(cur[i], cur[i + 1]) if i + 1 < len(cur) else cur[i])
            self.layers.append(nxt)

    @property
    def root(self) -> bytes:
        return self.layers[-1][0]

    def proof(self, index: int) -> list[bytes]:
        out = []
        for layer in self.layers[:-1]:
            sib = index ^ 1
            if sib < len(layer):
                out.append(layer[sib])
            index //= 2
        return out

    @staticmethod
    def verify(proof: list[bytes], root: bytes, leaf: bytes) -> bool:
        h = leaf
        for p in proof:
            h = _hash_pair(h, p)
        return h == root
