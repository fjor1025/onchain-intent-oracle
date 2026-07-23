"""Decoded event-log models.

Event logs are a distinct evidence channel from traces/state-diffs: they're
available on every RPC tier via plain `eth_getLogs` (no `debug_*`/`trace_*`
support needed), and for most DeFi contracts they carry the richest
"who did what, to what, how much" signal of anything this pipeline can fetch.

See `ingestion/log_decoder.py` for how these are produced and
`analysis/state_machine.py` / `analysis/invariant_miner.py` for how they're
consumed as evidence.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Confidence provenance for a decoded log, ordered roughly by trust.
# - "verified_abi": topic0 matched an event in a verified, explorer-fetched
#   ABI for this exact contract. Authoritative -- the contract's own code
#   defines this event.
# - "builtin_table": topic0 matched a small built-in table of extremely
#   common, well-known event signatures (ERC-20/721/4626-shaped, etc).
#   Usually correct, but not verified against *this* contract's own source.
# - "signature_directory": topic0 resolved via an open signature-hash
#   directory (analogous to 4byte.directory for function selectors). Best
#   effort; hash collisions/homonyms are possible.
# - "unresolved": topic0 could not be resolved by any of the above. The log
#   is still evidence that *something* happened -- just not evidence of a
#   named claim. Never silently treat this as "no activity".
LOG_CONFIDENCE_LEVELS = (
    "verified_abi",
    "builtin_table",
    "signature_directory",
    "unresolved",
)


@dataclass
class DecodedLog:
    """A single decoded (or decode-attempted) event log."""

    address: str
    tx_hash: str
    log_index: int
    block_number: int
    topic0: str
    confidence: str  # one of LOG_CONFIDENCE_LEVELS
    event_name: Optional[str] = None
    signature: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)
    # ABI type string per arg name (e.g. {"id": "bytes32", "amount":
    # "uint256"}) -- lets a consumer (e.g. analysis/entity_key.py) filter
    # args by type without re-deriving it from `descriptor`/ABI itself.
    arg_types: Dict[str, str] = field(default_factory=dict)
    # Indexed args whose ABI type is dynamic (string/bytes/array) are only
    # available on-chain as their keccak256 hash, not the original value --
    # the EVM itself discards the preimage. Names of args affected by this go
    # here so a consumer never mistakes a hash for the real value.
    indexed_hash_only: List[str] = field(default_factory=list)
    # Set when the event name/signature resolved but argument decoding itself
    # failed (malformed data, ambiguous indexed-arg layout, etc). Distinct
    # from an unresolved topic0 -- this means "we know what event this claims
    # to be, but couldn't safely extract its argument values", so a consumer
    # should treat `args` as empty/untrustworthy without discarding the
    # confirmed fact that this event fired.
    decode_error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "tx_hash": self.tx_hash,
            "log_index": self.log_index,
            "block_number": self.block_number,
            "topic0": self.topic0,
            "confidence": self.confidence,
            "event_name": self.event_name,
            "signature": self.signature,
            "args": self.args,
            "arg_types": self.arg_types,
            "indexed_hash_only": self.indexed_hash_only,
            "decode_error": self.decode_error,
        }
