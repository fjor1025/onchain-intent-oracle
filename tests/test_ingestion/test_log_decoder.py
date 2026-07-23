"""Tests for ingestion/log_decoder.py."""

import pytest
from eth_abi import encode
from eth_utils import keccak

from onchain_intent_oracle.ingestion.log_decoder import LogDecoder
from onchain_intent_oracle.ingestion.source_resolver import abi_to_event_map


def _addr_topic(addr_hex: str) -> str:
    """Left-pad a 20-byte address into a 32-byte topic word."""
    return "0x" + "00" * 12 + addr_hex.replace("0x", "")


def _topic0(signature: str) -> str:
    return "0x" + keccak(text=signature).hex()


FROM_ADDR = "0x1111111111111111111111111111111111111111"
TO_ADDR = "0x2222222222222222222222222222222222222222"


def _erc20_transfer_log(value: int, tx_hash="0xaaa", log_index=0, block_number=100):
    return {
        "address": "0xContract",
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
        "blockNumber": hex(block_number),
        "topics": [
            _topic0("Transfer(address,address,uint256)"),
            _addr_topic(FROM_ADDR),
            _addr_topic(TO_ADDR),
        ],
        "data": "0x" + encode(["uint256"], [value]).hex(),
    }


class TestBuiltinResolution:
    def test_erc20_transfer_decodes_via_builtin_table(self):
        decoder = LogDecoder()
        log = _erc20_transfer_log(1000)
        decoded = decoder.decode_log(log)

        assert decoded.confidence == "builtin_table"
        assert decoded.event_name == "Transfer"
        assert decoded.args["from"] == FROM_ADDR.lower()
        assert decoded.args["to"] == TO_ADDR.lower()
        assert decoded.args["value"] == 1000
        assert decoded.decode_error is None

    def test_erc721_transfer_disambiguated_by_topic_count(self):
        """Same topic0 as ERC-20 Transfer (indexed-ness doesn't affect the
        signature hash), but 4 topics instead of 3 -- tokenId indexed too.
        Must resolve to the ERC-721-shaped candidate, not the ERC-20 one."""
        decoder = LogDecoder()
        log = {
            "address": "0xNFT",
            "transactionHash": "0xbbb",
            "logIndex": "0x0",
            "blockNumber": "0x64",
            "topics": [
                _topic0("Transfer(address,address,uint256)"),
                _addr_topic(FROM_ADDR),
                _addr_topic(TO_ADDR),
                "0x" + (42).to_bytes(32, "big").hex(),
            ],
            "data": "0x",
        }
        decoded = decoder.decode_log(log)
        assert decoded.confidence == "builtin_table"
        assert decoded.args["tokenId"] == 42
        assert "value" not in decoded.args

    def test_unresolved_topic0_never_fabricates_a_name(self):
        decoder = LogDecoder()
        log = {
            "address": "0xContract",
            "transactionHash": "0xccc",
            "logIndex": "0x0",
            "blockNumber": "0x64",
            "topics": ["0x" + "ab" * 32],
            "data": "0x",
        }
        decoded = decoder.decode_log(log)
        assert decoded.confidence == "unresolved"
        assert decoded.event_name is None
        assert decoded.args == {}


class TestVerifiedAbiResolution:
    def test_verified_abi_takes_priority_over_builtin_table(self):
        """A custom event with its own real ABI entry must resolve via
        abi_event_map (authoritative), even if it happens to share a name
        with something in the builtin table."""
        abi = [
            {
                "type": "event",
                "name": "MarketCreated",
                "inputs": [
                    {"name": "id", "type": "bytes32", "indexed": True},
                    {"name": "loanToken", "type": "address", "indexed": False},
                    {"name": "collateral", "type": "address", "indexed": False},
                ],
            }
        ]
        event_map = abi_to_event_map(abi)
        decoder = LogDecoder(abi_event_map=event_map)

        market_id = b"\x01" * 32
        log = {
            "address": "0xMarket",
            "transactionHash": "0xddd",
            "logIndex": "0x0",
            "blockNumber": "0x64",
            "topics": [
                _topic0("MarketCreated(bytes32,address,address)"),
                "0x" + market_id.hex(),
            ],
            "data": "0x" + encode(["address", "address"], [FROM_ADDR, TO_ADDR]).hex(),
        }
        decoded = decoder.decode_log(log)
        assert decoded.confidence == "verified_abi"
        assert decoded.event_name == "MarketCreated"
        assert decoded.args["id"] == "0x" + market_id.hex()
        assert decoded.args["loanToken"] == FROM_ADDR.lower()
        assert decoded.args["collateral"] == TO_ADDR.lower()

    def test_dynamic_indexed_arg_surfaces_as_hash_only(self):
        """A `string`/`bytes`/array param that's indexed can only ever be
        recovered as its keccak256 hash on-chain -- must be flagged, never
        presented as if it were the real value."""
        abi = [
            {
                "type": "event",
                "name": "Tagged",
                "inputs": [{"name": "label", "type": "string", "indexed": True}],
            }
        ]
        decoder = LogDecoder(abi_event_map=abi_to_event_map(abi))
        label_hash = keccak(text="hello")
        log = {
            "address": "0xC",
            "transactionHash": "0xeee",
            "logIndex": "0x0",
            "blockNumber": "0x64",
            "topics": [_topic0("Tagged(string)"), "0x" + label_hash.hex()],
            "data": "0x",
        }
        decoded = decoder.decode_log(log)
        assert decoded.confidence == "verified_abi"
        assert "label" in decoded.indexed_hash_only
        assert decoded.args["label"] == "0x" + label_hash.hex()


class TestArgDecodeFailureIsDistinctFromUnresolved:
    def test_malformed_data_flags_decode_error_but_keeps_event_name(self):
        abi = [
            {
                "type": "event",
                "name": "Borrow",
                "inputs": [
                    {"name": "id", "type": "bytes32", "indexed": True},
                    {"name": "amount", "type": "uint256", "indexed": False},
                ],
            }
        ]
        decoder = LogDecoder(abi_event_map=abi_to_event_map(abi))
        log = {
            "address": "0xC",
            "transactionHash": "0xfff",
            "logIndex": "0x0",
            "blockNumber": "0x64",
            "topics": [
                _topic0("Borrow(bytes32,uint256)"), "0x" + (b"\x02" * 32).hex()
            ],
            # Truncated / malformed data -- not a valid uint256 word.
            "data": "0x01",
        }
        decoded = decoder.decode_log(log)
        assert decoded.confidence == "verified_abi"
        assert decoded.event_name == "Borrow"
        assert decoded.decode_error is not None
        assert decoded.args == {}


class TestBatchDecoding:
    def test_decode_logs_preserves_order(self):
        decoder = LogDecoder()
        logs = [_erc20_transfer_log(1), _erc20_transfer_log(2, tx_hash="0xbbb")]
        decoded = decoder.decode_logs(logs)
        assert [d.args["value"] for d in decoded] == [1, 2]
