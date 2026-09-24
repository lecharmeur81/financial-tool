"""Address validation: checksums catch mistyped addresses before they are stored or matched."""

from __future__ import annotations

import pytest

from cfi.core.addresses import InvalidAddressError, canonical_address, is_valid_address
from tests.whale_fakes import btc_address


@pytest.mark.parametrize(
    ("address", "canonical"),
    [
        ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"),  # P2PKH
        ("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy", "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"),  # P2SH
        # BIP-173 test vector (upper case is valid Bech32 and stored lower case)
        (
            "BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4",
            "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
        ),
        # BIP-350 test vector (taproot, Bech32m)
        (
            "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0",
            "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0",
        ),
        ("  1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa ", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"),
    ],
)
def test_valid_bitcoin_addresses(address: str, canonical: str) -> None:
    assert canonical_address("bitcoin", address) == canonical


@pytest.mark.parametrize(
    "address",
    [
        "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb",  # one character changed: checksum fails
        "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfN",  # truncated
        "0A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",  # '0' is not Base58
        "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5",  # Bech32 checksum
        "bc1qW508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",  # mixed case
        "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx",  # testnet
        # v1 witness with a Bech32 (not Bech32m) checksum: invalid since BIP-350
        "bc1pw508d6qejxtdg4y5r3zarvary0c5xw7kw508d6qejxtdg4y5r3zarvary0c5xw7k7grplx",
        "mipcBbFg9gMiCh81Kj8tqqdgoZub1ZJRfn",  # testnet P2PKH (version 0x6f)
        "",
    ],
)
def test_invalid_bitcoin_addresses(address: str) -> None:
    assert not is_valid_address("bitcoin", address)
    with pytest.raises(InvalidAddressError):
        canonical_address("bitcoin", address)


def test_ethereum_addresses_are_lower_cased_hex() -> None:
    mixed = "0x00000000219ab540356cBB839Cbe05303d7705Fa"
    assert canonical_address("ethereum", mixed) == mixed.lower()
    for bad in ("0x1234", "00000000219ab540356cbb839cbe05303d7705fa00", "0x" + "g" * 40):
        assert not is_valid_address("ethereum", bad)


def test_unsupported_chain_is_rejected() -> None:
    with pytest.raises(InvalidAddressError, match="unsupported chain"):
        canonical_address("solana", "anything")


def test_synthetic_test_addresses_are_valid() -> None:
    addresses = {btc_address(i) for i in range(50)}
    assert len(addresses) == 50
    assert all(is_valid_address("bitcoin", a) for a in addresses)
