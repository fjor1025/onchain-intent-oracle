"""Tests for SourceResolver: ABI-based selector resolution and standards detection."""

import pytest
from eth_utils import keccak

from onchain_intent_oracle.ingestion.abi_utils import abi_type_string
from onchain_intent_oracle.ingestion.source_resolver import (
    SourceResolver,
    abi_to_function_map,
    abi_to_selector_map,
    detect_standards,
)

ERC20_ABI = [
    {"type": "function", "name": "totalSupply", "inputs": []},
    {"type": "function", "name": "balanceOf", "inputs": [{"type": "address"}]},
    {"type": "function", "name": "transfer", "inputs": [{"type": "address"}, {"type": "uint256"}]},
    {"type": "function", "name": "approve", "inputs": [{"type": "address"}, {"type": "uint256"}]},
    {"type": "event", "name": "Transfer", "inputs": []},  # non-function entries must be ignored
]

ERC721_ABI = [
    {"type": "function", "name": "ownerOf", "inputs": [{"type": "uint256"}]},
    {"type": "function", "name": "balanceOf", "inputs": [{"type": "address"}]},
    {"type": "function", "name": "safeTransferFrom", "inputs": [{"type": "address"}, {"type": "address"}, {"type": "uint256"}]},
]

# Morpho Blue-shaped ABI: a function taking a struct ("MarketParams") arg --
# real Etherscan/verified-source ABI JSON represents this as
# {"type": "tuple", "components": [...]}, NOT as an expanded type string.
MARKET_PARAMS_ABI = [
    {
        "type": "function",
        "name": "createMarket",
        "inputs": [
            {
                "name": "marketParams",
                "type": "tuple",
                "components": [
                    {"name": "loanToken", "type": "address"},
                    {"name": "collateralToken", "type": "address"},
                    {"name": "oracle", "type": "address"},
                    {"name": "irm", "type": "address"},
                    {"name": "lltv", "type": "uint256"},
                ],
            }
        ],
    },
]


class TestAbiTypeStringStructExpansion:
    """Regression coverage for a real bug: computing a selector/topic0 by
    reading an ABI input's "type" field directly gives "tuple" for a struct
    param, not the expanded (type1,type2,...) Solidity actually hashes --
    silently producing the WRONG selector for any function with a struct
    argument (e.g. Morpho Blue's `createMarket(MarketParams)`)."""

    def test_tuple_type_expands_via_components(self):
        entry = MARKET_PARAMS_ABI[0]["inputs"][0]
        assert abi_type_string(entry) == "(address,address,address,address,uint256)"

    def test_selector_matches_the_correctly_expanded_signature_not_the_naive_one(self):
        selectors = abi_to_selector_map(MARKET_PARAMS_ABI)
        correct_selector = "0x" + keccak(
            text="createMarket((address,address,address,address,uint256))"
        )[:4].hex()
        naive_wrong_selector = "0x" + keccak(text="createMarket(tuple)")[:4].hex()

        assert correct_selector in selectors
        assert naive_wrong_selector not in selectors
        assert selectors[correct_selector] == "createMarket"


class TestAbiToFunctionMap:
    def test_type_strings_expand_struct_args_for_eth_abi_decode(self):
        func_map = abi_to_function_map(MARKET_PARAMS_ABI)
        descriptor = next(iter(func_map.values()))
        assert descriptor["name"] == "createMarket"
        assert descriptor["type_strings"] == ["(address,address,address,address,uint256)"]
        assert descriptor["param_names"] == ["marketParams"]

    def test_flat_args_get_real_param_names(self):
        func_map = abi_to_function_map(ERC20_ABI)
        transfer = next(d for d in func_map.values() if d["name"] == "transfer")
        assert transfer["type_strings"] == ["address", "uint256"]

    def test_empty_abi(self):
        assert abi_to_function_map([]) == {}
        assert abi_to_function_map(None) == {}


class TestAbiToSelectorMap:
    def test_known_selectors(self):
        """Selectors must be computed correctly -- these are well-known, verifiable values."""
        selectors = abi_to_selector_map(ERC20_ABI)
        assert selectors["0xa9059cbb"] == "transfer"  # transfer(address,uint256)
        assert selectors["0x70a08231"] == "balanceOf"  # balanceOf(address)
        assert selectors["0x095ea7b3"] == "approve"  # approve(address,uint256)
        assert selectors["0x18160ddd"] == "totalSupply"  # totalSupply()

    def test_ignores_non_function_entries(self):
        selectors = abi_to_selector_map(ERC20_ABI)
        assert len(selectors) == 4  # not 5 -- the event entry must be skipped

    def test_empty_abi(self):
        assert abi_to_selector_map([]) == {}
        assert abi_to_selector_map(None) == {}


class TestDetectStandards:
    def test_erc20_detected(self):
        assert detect_standards(ERC20_ABI) == ["ERC-20"]

    def test_erc721_detected(self):
        assert detect_standards(ERC721_ABI) == ["ERC-721"]

    def test_no_standard_detected(self):
        abi = [{"type": "function", "name": "someCustomFunction", "inputs": []}]
        assert detect_standards(abi) == []

    def test_empty_abi(self):
        assert detect_standards([]) == []
        assert detect_standards(None) == []


class TestSourceResolver:
    @pytest.mark.asyncio
    async def test_get_abi_success(self, mocker):
        resolver = SourceResolver()
        fake_response = mocker.Mock()
        fake_response.json.return_value = {
            "status": "1",
            "result": '[{"type": "function", "name": "transfer", "inputs": []}]',
        }
        mocker.patch.object(resolver.client, "get", return_value=fake_response)

        abi = await resolver.get_abi("0xSomeContract", chain_id=1)
        assert abi == [{"type": "function", "name": "transfer", "inputs": []}]
        await resolver.close()

    @pytest.mark.asyncio
    async def test_get_abi_unverified_contract(self, mocker):
        """Etherscan returns status "0" for unverified contracts -- must not crash,
        just return None."""
        resolver = SourceResolver()
        fake_response = mocker.Mock()
        fake_response.json.return_value = {"status": "0", "message": "NOTOK", "result": "Contract source code not verified"}
        mocker.patch.object(resolver.client, "get", return_value=fake_response)

        abi = await resolver.get_abi("0xUnverified", chain_id=1)
        assert abi is None
        await resolver.close()

    @pytest.mark.asyncio
    async def test_get_abi_network_error_does_not_raise(self, mocker):
        resolver = SourceResolver()
        mocker.patch.object(resolver.client, "get", side_effect=ConnectionError("boom"))

        abi = await resolver.get_abi("0xSomeContract", chain_id=1)
        assert abi is None
        await resolver.close()

    @pytest.mark.asyncio
    async def test_get_abi_uses_v2_chainid_param(self, mocker):
        """Regression test: the explorer call must include chainid, since all
        chains now share the single unified V2 endpoint (V1's per-chain
        endpoints were deprecated 2025-08-15)."""
        resolver = SourceResolver()
        fake_response = mocker.Mock()
        fake_response.json.return_value = {"status": "1", "result": "[]"}
        mock_get = mocker.patch.object(resolver.client, "get", return_value=fake_response)

        await resolver.get_abi("0xSomeContract", chain_id=42161)
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["chainid"] == 42161
        await resolver.close()
