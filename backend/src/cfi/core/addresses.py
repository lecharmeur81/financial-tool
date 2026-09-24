"""On-chain address validation and canonical forms.

Addresses copied from any source (a provider, a web page, a label file) are checked here before
they are stored, so a mistyped address can never silently match nothing — or the wrong wallet.

- Bitcoin: legacy/P2SH Base58Check (version byte 0x00 or 0x05, double-SHA-256 checksum) and
  SegWit Bech32 (witness v0, BIP-173) / Bech32m (v1+, BIP-350) on mainnet (``bc``). Bech32 is
  case-insensitive and stored in lower case; Base58 is case-sensitive and stored as given.
- Ethereum: ``0x`` + 40 hex digits, stored in lower case. (EIP-55 mixed-case checksums are not
  verified here: that needs Keccak-256, which the standard library does not provide.)
"""

from __future__ import annotations

import hashlib
from typing import Literal

Chain = Literal["bitcoin", "ethereum"]
CHAINS: tuple[Chain, ...] = ("bitcoin", "ethereum")

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_CONST = 1
_BECH32M_CONST = 0x2BC830A3


class InvalidAddressError(ValueError):
    """The text is not a valid address for the chain."""


def _b58decode(text: str) -> bytes:
    number = 0
    for char in text:
        index = _B58.find(char)
        if index < 0:
            raise InvalidAddressError(f"invalid Base58 character {char!r}")
        number = number * 58 + index
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading = len(text) - len(text.lstrip("1"))
    return b"\x00" * leading + body


def _polymod(values: list[int]) -> int:
    generator = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = (checksum & 0x1FFFFFF) << 5 ^ value
        for i in range(5):
            checksum ^= generator[i] if (top >> i) & 1 else 0
    return checksum


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convertbits(data: list[int], frombits: int, tobits: int) -> list[int]:
    acc, bits, out = 0, 0, []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            out.append((acc >> bits) & maxv)
    if bits >= frombits or ((acc << (tobits - bits)) & maxv):
        raise InvalidAddressError("invalid Bech32 padding")
    return out


def _bitcoin_bech32(address: str) -> str:
    if address.lower() != address and address.upper() != address:
        raise InvalidAddressError("mixed-case Bech32 address")
    address = address.lower()
    hrp, sep, data_part = address.rpartition("1")
    if not sep or hrp != "bc" or len(data_part) < 7:
        raise InvalidAddressError("not a mainnet Bech32 address (bc1…)")
    try:
        data = [_BECH32.index(c) for c in data_part]
    except ValueError as exc:
        raise InvalidAddressError("invalid Bech32 character") from exc
    const = _polymod(_hrp_expand(hrp) + data)
    version = data[0]
    if const not in (_BECH32_CONST, _BECH32M_CONST):
        raise InvalidAddressError("Bech32 checksum mismatch")
    if (version == 0) != (const == _BECH32_CONST):
        raise InvalidAddressError("wrong Bech32 variant for the witness version")
    program = _convertbits(data[1:-6], 5, 8)
    if version > 16 or not 2 <= len(program) <= 40:
        raise InvalidAddressError("invalid witness program")
    if version == 0 and len(program) not in (20, 32):
        raise InvalidAddressError("invalid v0 witness program length")
    return address


def _bitcoin_base58(address: str) -> str:
    raw = _b58decode(address)
    if len(raw) != 25:
        raise InvalidAddressError("Base58 address must decode to 25 bytes")
    payload, checksum = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != checksum:
        raise InvalidAddressError("Base58Check checksum mismatch")
    if payload[0] not in (0x00, 0x05):
        raise InvalidAddressError("not a mainnet P2PKH/P2SH address")
    return address


def canonical_address(chain: str, address: str) -> str:
    """The validated, canonical form of ``address`` on ``chain``; raises InvalidAddressError."""
    text = address.strip()
    if chain == "bitcoin":
        if text.lower().startswith("bc1"):
            return _bitcoin_bech32(text)
        return _bitcoin_base58(text)
    if chain == "ethereum":
        if len(text) != 42 or not text.lower().startswith("0x"):
            raise InvalidAddressError("Ethereum address must be 0x + 40 hex digits")
        body = text[2:].lower()
        if any(c not in "0123456789abcdef" for c in body):
            raise InvalidAddressError("Ethereum address must be hexadecimal")
        return "0x" + body
    raise InvalidAddressError(f"unsupported chain {chain!r}")


def is_valid_address(chain: str, address: str) -> bool:
    try:
        canonical_address(chain, address)
    except InvalidAddressError:
        return False
    return True
