"""Tests for ingestion/calldata_decoder.py."""

from eth_abi import encode
from eth_utils import keccak

from onchain_intent_oracle.ingestion.calldata_decoder import CalldataDecoder
from onchain_intent_oracle.ingestion.source_resolver import abi_to_function_map

FROM_ADDR = "0x1111111111111111111111111111111111111111"
TO_ADDR = "0x2222222222222222222222222222222222222222"

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

TRANSFER_ABI = [
    {
        "type": "function",
        "name": "transfer",
        "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
    }
]


def _calldata(selector: str, encoded_args: bytes) -> str:
    return selector + encoded_args.hex()


class TestVerifiedAbiDecoding:
    def test_flat_args_decode_with_real_param_names(self):
        func_map = abi_to_function_map(TRANSFER_ABI)
        selector = next(iter(func_map.keys()))
        decoder = CalldataDecoder(abi_function_map=func_map)

        data = encode(["address", "uint256"], [TO_ADDR, 5000])
        decoded = decoder.decode(_calldata(selector, data))

        assert decoded["confidence"] == "verified_abi"
        assert decoded["method_name"] == "transfer"
        assert decoded["args"] == {"to": TO_ADDR.lower(), "amount": 5000}
        assert decoded["decode_error"] is None

    def test_struct_typed_arg_decodes_correctly(self):
        """The Morpho Blue case: a single struct (MarketParams) argument.
        This is exactly the shape that was previously broken -- the ABI's
        "type": "tuple" doesn't tell eth_abi.decode() what's inside without
        the components-aware type-string expansion from abi_to_function_map."""
        func_map = abi_to_function_map(MARKET_PARAMS_ABI)
        selector = next(iter(func_map.keys()))
        decoder = CalldataDecoder(abi_function_map=func_map)

        loan_token = FROM_ADDR
        collateral_token = TO_ADDR
        oracle = "0x3333333333333333333333333333333333333333"
        irm = "0x4444444444444444444444444444444444444444"
        lltv = 860000000000000000  # 0.86e18, a real Morpho LLTV shape

        data = encode(
            ["(address,address,address,address,uint256)"],
            [(loan_token, collateral_token, oracle, irm, lltv)],
        )
        decoded = decoder.decode(_calldata(selector, data))

        assert decoded["confidence"] == "verified_abi"
        assert decoded["method_name"] == "createMarket"
        assert decoded["decode_error"] is None
        market_params = decoded["args"]["marketParams"]
        assert market_params[0] == loan_token.lower()
        assert market_params[4] == lltv


class TestSelectorSignatureOnlyFallback:
    def test_decodes_positionally_from_a_resolved_signature_string(self):
        """No verified ABI -- but SignatureDecoder resolved a full signature
        (builtin table or 4byte.directory) that includes types. Still
        decodable, just with positional arg{i} names instead of real ones."""
        decoder = CalldataDecoder()  # no abi_function_map
        selector = "0xa9059cbb"  # transfer(address,uint256)
        data = encode(["address", "uint256"], [TO_ADDR, 777])

        decoded = decoder.decode(
            _calldata(selector, data),
            resolved_signature="transfer(address,uint256)",
        )
        assert decoded["confidence"] == "selector_signature_only"
        assert decoded["method_name"] == "transfer"
        assert decoded["args"] == {"arg0": TO_ADDR.lower(), "arg1": 777}

    def test_nested_tuple_signature_not_shredded_by_naive_comma_split(self):
        """A single tuple-typed arg (Uniswap-style
        exactInputSingle((address,...))) must decode as ONE argument, not be
        incorrectly split into several bogus ones by a naive comma-split."""
        decoder = CalldataDecoder()
        signature = "exactInputSingle((address,address,uint24,address,uint256,uint256,uint256,uint160))"
        selector = "0x" + keccak(text=signature)[:4].hex()
        params = (FROM_ADDR, TO_ADDR, 3000, FROM_ADDR, 100, 0, 0, 0)
        data = encode(
            ["(address,address,uint24,address,uint256,uint256,uint256,uint160)"],
            [params],
        )
        decoded = decoder.decode(_calldata(selector, data), resolved_signature=signature)
        assert decoded["decode_error"] is None
        assert len(decoded["args"]) == 1
        assert decoded["args"]["arg0"][0] == FROM_ADDR.lower()


class TestUnresolvedAndFailureModes:
    def test_no_abi_and_no_resolved_signature_is_unresolved(self):
        decoder = CalldataDecoder()
        decoded = decoder.decode("0xdeadbeef" + "00" * 32)
        assert decoded["confidence"] == "unresolved"
        assert decoded["method_name"] == "unknown"
        assert decoded["args"] == {}

    def test_empty_calldata_is_fallback_not_unknown(self):
        decoder = CalldataDecoder()
        decoded = decoder.decode("0x")
        assert decoded["method_name"] == "fallback"
        assert decoded["confidence"] == "unresolved"

    def test_malformed_data_flags_decode_error_but_keeps_method_name(self):
        func_map = abi_to_function_map(TRANSFER_ABI)
        selector = next(iter(func_map.keys()))
        decoder = CalldataDecoder(abi_function_map=func_map)

        # Truncated -- not enough bytes for (address, uint256).
        decoded = decoder.decode(selector + "01")
        assert decoded["method_name"] == "transfer"
        assert decoded["confidence"] == "verified_abi"
        assert decoded["decode_error"] is not None
        assert decoded["args"] == {}

    def test_no_args_function_decodes_cleanly(self):
        abi = [{"type": "function", "name": "totalSupply", "inputs": []}]
        func_map = abi_to_function_map(abi)
        selector = next(iter(func_map.keys()))
        decoder = CalldataDecoder(abi_function_map=func_map)

        decoded = decoder.decode(selector)
        assert decoded["method_name"] == "totalSupply"
        assert decoded["args"] == {}
        assert decoded["decode_error"] is None
