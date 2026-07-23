"""Decode function-call calldata: resolve a selector to a function name *and*
ABI-decode its argument values, not just the name (that's all
`SignatureDecoder` ever did).

Resolution priority mirrors `log_decoder.py`'s philosophy:
  1. `abi_function_map` -- computed directly from a verified ABI via
     `source_resolver.abi_to_function_map()`. Authoritative for *this*
     contract, including correctly-expanded struct (tuple) parameter types.
  2. A resolved signature string from `SignatureDecoder` (builtin table or
     4byte.directory) that includes full parameter type info, e.g.
     `"transfer(address,uint256)"`. Many (not all) 4byte.directory entries
     and all of `SignatureDecoder.BUILTIN_SIGNATURES` have this shape, so
     args can still be decoded positionally -- just without real parameter
     *names*, and without verification that this selector really belongs to
     *this* contract (selector collisions across unrelated functions are
     possible, if rare).
  3. Unresolved -- keep the raw hex, never fabricate argument values.
"""

from typing import Any, Dict, Optional

import structlog
from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import keccak

from onchain_intent_oracle.ingestion.abi_utils import (
    normalize_decoded_value,
    split_top_level_types,
)

logger = structlog.get_logger()

CALLDATA_CONFIDENCE_LEVELS = ("verified_abi", "selector_signature_only", "unresolved")


class CalldataDecoder:
    """Decodes raw transaction `input` calldata into a method name plus
    typed argument values."""

    def __init__(self, abi_function_map: Optional[Dict[str, Dict[str, Any]]] = None):
        # Authoritative, per-contract map from source_resolver.abi_to_function_map().
        self.abi_function_map = abi_function_map or {}

    def decode(self, input_data: str, resolved_signature: Optional[str] = None) -> Dict[str, Any]:
        """`input_data`: full "0x..." calldata (4-byte selector + args).
        `resolved_signature`: a signature string already resolved by
        `SignatureDecoder` (e.g. `"transfer(address,uint256)"`), used as the
        fallback source when no verified ABI entry matches this selector.
        Passing the already-resolved signature in, rather than re-deriving
        it here, avoids duplicating `SignatureDecoder`'s own builtin-table/
        4byte-directory lookup logic (and its caching / async handling).

        Returns `{"method_name", "args", "arg_types", "confidence",
        "decode_error", "struct_hash"}`. `args`/`arg_types` are `{}` (never
        fabricated placeholder values) whenever confidence is
        `"unresolved"` or a decode actually failed.

        `struct_hash` is set only when the entire call takes exactly one
        top-level struct (tuple) argument -- e.g. Morpho Blue's
        `createMarket(MarketParams)` -- and is `keccak256(abi.encode(that
        struct))`, i.e. exactly what a contract computes internally when it
        derives an id from a params struct (Morpho's `Id.wrap(keccak256(
        abi.encode(marketParams)))` idiom). This is a *candidate*, not a
        claim: `analysis/entity_key.py` only promotes it to an actual entity
        key when it's cross-checked against an id value observed elsewhere
        in the same run (see that module's docstring) -- never used alone.
        """
        if not input_data or input_data == "0x":
            return {"method_name": "fallback", "args": {}, "arg_types": {}, "confidence": "unresolved", "decode_error": None, "struct_hash": None}

        selector = input_data[:10].lower()
        data_hex = input_data[10:]
        try:
            data_bytes = bytes.fromhex(data_hex) if data_hex else b""
        except ValueError:
            data_bytes = b""

        descriptor = self.abi_function_map.get(selector)
        if descriptor:
            confidence = "verified_abi"
            name = descriptor["name"]
            type_strings = descriptor["type_strings"]
            param_names = descriptor["param_names"]
        elif resolved_signature and "(" in resolved_signature:
            confidence = "selector_signature_only"
            name = resolved_signature.split("(")[0]
            inner = resolved_signature[resolved_signature.index("(") + 1: resolved_signature.rindex(")")]
            type_strings = split_top_level_types(inner) if inner else []
            # 4byte.directory / the builtin table give us types, not names.
            param_names = [f"arg{i}" for i in range(len(type_strings))]
        else:
            return {"method_name": "unknown", "args": {}, "arg_types": {}, "confidence": "unresolved", "decode_error": None, "struct_hash": None}

        if not type_strings:
            return {"method_name": name, "args": {}, "arg_types": {}, "confidence": confidence, "decode_error": None, "struct_hash": None}

        try:
            values = abi_decode(type_strings, data_bytes)
            args = {
                pname: normalize_decoded_value(v)
                for pname, v in zip(param_names, values)
            }
            arg_types = dict(zip(param_names, type_strings))
            struct_hash = self._struct_hash(type_strings, values)
            return {"method_name": name, "args": args, "arg_types": arg_types, "confidence": confidence, "decode_error": None, "struct_hash": struct_hash}
        except Exception as e:
            # Name resolved, but we couldn't safely pull argument values out
            # (malformed/truncated calldata, a proxy-forwarded call whose
            # calldata doesn't actually match the target's own ABI, a
            # selector collision against `resolved_signature`, etc). Keep
            # the confirmed method-name claim; do not fabricate args.
            logger.debug("calldata_arg_decode_failed", selector=selector, error=str(e))
            return {"method_name": name, "args": {}, "arg_types": {}, "confidence": confidence, "decode_error": str(e), "struct_hash": None}

    @staticmethod
    def _struct_hash(type_strings, values) -> Optional[str]:
        if len(type_strings) != 1 or not type_strings[0].startswith("("):
            return None
        try:
            return "0x" + keccak(abi_encode(type_strings, values)).hex()
        except Exception:
            return None
