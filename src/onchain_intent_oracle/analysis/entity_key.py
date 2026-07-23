"""Entity-key extraction and per-entity bucketing for singleton-multiplexed
contracts (Fix 3 of the accuracy-remediation spec).

Problem this solves: `StateMachineInference`/`InvariantMiner` treat "the
contract address" as one behavioral entity. That's wrong for any contract
that multiplexes many independent logical entities behind one address and
one set of function selectors -- Morpho Blue's markets, Uniswap V3's
per-tokenId positions, any vault factory's per-vault state, etc. Without
this, a state machine built across many markets' calls blends unrelated
state spaces into one meaningless chain.

Two resolution strategies, applied in order, generic and not hardcoded to
any one protocol's shape:

1. **Name+type heuristic**: an argument (from a decoded call or a decoded
   log -- see `ingestion/calldata_decoder.py` / `ingestion/log_decoder.py`)
   whose ABI type is `bytes32` or `uint256` and whose name looks like an
   entity identifier (`id`, `marketId`, `poolId`, `vaultId`, `tokenId`,
   `trancheId`, or anything else matching `*Id`/`*_id`). This alone covers
   Morpho Blue in practice: even though `supply`/`borrow`/`withdraw`/`repay`
   take a `MarketParams` struct rather than a bare `id` on the *call* side,
   the corresponding `Supply`/`Borrow`/`Withdraw`/`Repay` *events* all carry
   `Id indexed id` directly.

2. **Struct-hash heuristic**: for a call whose single argument is a struct
   (see `CalldataDecoder._struct_hash`), `keccak256(abi.encode(that
   struct))` is a *candidate* entity key -- but only promoted to a real one
   when it's cross-checked against an id-value actually observed elsewhere
   in the same run via strategy 1. This is deliberately evidence-gated
   rather than a blind guess: a bare "we hashed a struct" claim has no
   grounds to assert *this contract* actually derives its entity id that
   way; a hash that matches something the contract itself emitted as `id`
   somewhere else in the same dataset does.

Flat, non-multiplexed contracts (a plain ERC-20, a single-purpose vault) are
expected to produce **no** entity-key candidates at all -- every tx lands in
the `None` bucket, which callers should treat identically to "no bucketing
happened" (see `cli.py`'s use of `bucket_by_entity`). This must be the
overwhelmingly common case and is the pass-through/regression-safe default.
"""

from typing import Any, Dict, List, Optional, Set, Tuple

ENTITY_ID_TYPES = ("bytes32", "uint256")

_RESOLVED_CALL_CONFIDENCE = ("verified_abi", "selector_signature_only")
_RESOLVED_LOG_CONFIDENCE = ("verified_abi", "builtin_table", "signature_directory")


def looks_like_entity_id_name(name: str) -> bool:
    """True for arg names that read as an entity identifier: `id`,
    `marketId`, `poolId`, `vaultId`, `tokenId`, `trancheId`, or generically
    anything ending in `Id`/containing `_id` (case-insensitive)."""
    if not name:
        return False
    n = name.lower()
    if n in {"id", "marketid", "poolid", "vaultid", "tokenid", "trancheid"}:
        return True
    if n.endswith("id") and len(n) > 2:
        return True
    if "_id" in n:
        return True
    return False


def _stringify(value: Any) -> str:
    return value if isinstance(value, str) else str(value)


def _tx_get(tx: Any, key: str, default=None):
    if isinstance(tx, dict):
        return tx.get(key, default)
    return getattr(tx, key, default)


def extract_name_matched_candidates(tx: Any, forced_arg_name: Optional[str] = None) -> List[Tuple[str, str, Any]]:
    """Returns a list of `(source, arg_name, value)` candidates from a
    single tx's decoded call and decoded logs -- `source` is `"call"` or
    `"log"`. Does not apply the struct-hash heuristic (that needs
    cross-tx visibility; see `bucket_by_entity`).

    Only considers args from a *resolved* call/log with no decode error --
    an unresolved topic0 or a failed decode carries no argument evidence to
    extract a key from in the first place.
    """
    candidates: List[Tuple[str, str, Any]] = []

    call = _tx_get(tx, "decoded_args", None) or _tx_get(tx, "decoded_input", None) or {}
    if call.get("confidence") in _RESOLVED_CALL_CONFIDENCE and not call.get("decode_error"):
        arg_types = call.get("arg_types", {})
        for name, value in (call.get("args") or {}).items():
            if forced_arg_name:
                if name.lower() == forced_arg_name.lower():
                    candidates.append(("call", name, value))
                continue
            if arg_types.get(name) in ENTITY_ID_TYPES and looks_like_entity_id_name(name):
                candidates.append(("call", name, value))

    logs = _tx_get(tx, "decoded_logs", None) or _tx_get(tx, "decoded_events", None) or []
    for log in logs:
        if not isinstance(log, dict) or log.get("decode_error"):
            continue
        if log.get("confidence") not in _RESOLVED_LOG_CONFIDENCE:
            continue
        arg_types = log.get("arg_types", {})
        hash_only = set(log.get("indexed_hash_only") or [])
        for name, value in (log.get("args") or {}).items():
            if name in hash_only:
                continue  # a keccak hash of a dynamic value, not the value itself
            if forced_arg_name:
                if name.lower() == forced_arg_name.lower():
                    candidates.append(("log", name, value))
                continue
            if arg_types.get(name) in ENTITY_ID_TYPES and looks_like_entity_id_name(name):
                candidates.append(("log", name, value))

    return candidates


def bucket_by_entity(
    txs: List[Any], forced_arg_name: Optional[str] = None
) -> Tuple[Dict[Optional[str], List[Any]], str]:
    """Groups transactions by inferred entity key.

    Returns `(buckets, entity_key_source)`:
    - `buckets`: `{entity_key_or_None: [tx, ...]}`. The `None` bucket holds
      every tx with no discoverable entity key -- contract-wide admin calls
      (Morpho Blue's `enableIrm`/`enableLltv`/`setOwner`, none of which are
      about any one market) belong here even when other txs *do* bucket by
      entity; they're real evidence about the contract as a whole, not about
      any single entity, and must not be silently dropped or force-fit into
      one.
    - `entity_key_source`: `"user_specified"` (a `--entity-key` flag was
      given and matched at least one tx), `"heuristic"` (name+type and/or
      struct-hash heuristics found candidates), or `"none"` (every tx landed
      in the `None` bucket -- the flat-contract, pass-through case).

    Mutates each tx in place, attaching `_entity_key`/`_entity_key_source`
    for the same tx (best-effort: dict-shape txs get real keys set; objects
    without a settable `__dict__`-style attribute are left alone -- this is
    purely informational bookkeeping, not required for the bucketing
    result itself).
    """
    buckets: Dict[Optional[str], List[Any]] = {}
    sources_seen: Set[str] = set()
    struct_hash_pending: List[Tuple[Any, str]] = []
    known_id_values: Set[str] = set()

    def _tag(tx, key, source):
        if isinstance(tx, dict):
            tx["_entity_key"] = key
            tx["_entity_key_source"] = source

    for tx in txs:
        candidates = extract_name_matched_candidates(tx, forced_arg_name=forced_arg_name)
        if candidates:
            # Prefer a call-side match (the tx's own direct argument) over a
            # log-side one when both exist, for a deterministic,
            # non-arbitrary choice; otherwise take the first log candidate.
            chosen = next((c for c in candidates if c[0] == "call"), candidates[0])
            key = _stringify(chosen[2])
            source = "user_specified" if forced_arg_name else "heuristic"
            buckets.setdefault(key, []).append(tx)
            _tag(tx, key, source)
            sources_seen.add(source)
            known_id_values.add(key)
            continue

        if forced_arg_name:
            # Nothing matched the user-forced arg name for this tx -- no
            # heuristic fallback when the user has explicitly told us what
            # to key on; falling back would silently ignore their choice.
            buckets.setdefault(None, []).append(tx)
            _tag(tx, None, None)
            continue

        struct_hash = ((_tx_get(tx, "decoded_args", None) or {}).get("struct_hash"))
        if struct_hash:
            struct_hash_pending.append((tx, struct_hash))
        else:
            buckets.setdefault(None, []).append(tx)
            _tag(tx, None, None)

    # Second pass: a struct_hash is only promoted to a real entity key when
    # it matches an id-value actually observed elsewhere in this run -- see
    # module docstring for why this isn't a blind guess.
    for tx, struct_hash in struct_hash_pending:
        if struct_hash in known_id_values:
            buckets.setdefault(struct_hash, []).append(tx)
            _tag(tx, struct_hash, "heuristic")
            sources_seen.add("heuristic")
        else:
            buckets.setdefault(None, []).append(tx)
            _tag(tx, None, None)

    if forced_arg_name:
        source_summary = "user_specified" if "user_specified" in sources_seen else "none"
    elif sources_seen:
        source_summary = "heuristic"
    else:
        source_summary = "none"

    return buckets, source_summary
