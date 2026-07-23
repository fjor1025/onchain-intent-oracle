"""Shared ABI helpers used by both the calldata decoder and the log decoder.

Centralized here specifically because of a correctness bug this module fixes:
`source_resolver.py`'s original selector/topic0 computation built a type
string by reading each ABI input's `"type"` field directly. For a struct
(tuple) parameter, Etherscan-family ABI JSON represents that as
`{"type": "tuple", "components": [...]}` -- the literal string `"tuple"`,
*not* the expanded `(type1,type2,...)` Solidity actually hashes into the
selector/topic0. So any function or event with a struct argument (Morpho
Blue's `MarketParams`, Uniswap's `ExactInputSingleParams`, etc. -- extremely
common in real DeFi ABIs) would have had its selector/topic0 computed wrong,
silently. `abi_type_string()` below recurses through `components` to build
the correct canonical string; every selector/topic0 computation in this
codebase should go through it rather than reading `"type"` directly.
"""

from typing import Any, Dict, List


def abi_type_string(entry: Dict[str, Any]) -> str:
    """Canonical Solidity type string for a single ABI input/output entry,
    correctly expanding tuple (struct) types -- including nested tuples and
    tuple arrays (`tuple[]`, `tuple[3]`) -- via their `components`, per the
    ABI spec's own signature-encoding rules.
    """
    t = entry.get("type", "")
    if not t.startswith("tuple"):
        return t
    components = entry.get("components", []) or []
    inner = ",".join(abi_type_string(c) for c in components)
    suffix = t[len("tuple"):]  # "", "[]", "[3]", "[][]", etc.
    return f"({inner}){suffix}"


def split_top_level_types(types_str: str) -> List[str]:
    """Split a comma-joined type-string (e.g. from a resolved signature like
    `"exactInputSingle((address,address,uint24,address,uint256,uint256,
    uint256,uint160))"`'s inner `(...)`) on top-level commas only -- commas
    *inside* a nested tuple type must not be treated as argument separators.
    A naive `.split(",")` would incorrectly shred a single tuple-typed
    argument into several bogus ones.
    """
    parts: List[str] = []
    depth = 0
    current = ""
    for ch in types_str:
        if ch == "(":
            depth += 1
            current += ch
        elif ch == ")":
            depth -= 1
            current += ch
        elif ch == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    if current:
        parts.append(current)
    return [p for p in parts if p]


def normalize_decoded_value(value: Any) -> Any:
    """`eth_abi` returns raw `bytes` for `bytesN`/`bytes`/(non-address)
    binary types; make these JSON-serializable and human-legible as 0x-hex
    strings rather than letting `json.dumps(..., default=str)` fall back to
    a Python bytes repr. Recurses into lists/tuples (array-typed args,
    decoded structs)."""
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, (list, tuple)):
        return [normalize_decoded_value(v) for v in value]
    return value
