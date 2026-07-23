"""Decode EVM event logs: resolve topic0 -> event name, ABI-decode args.

This is the event-log analog of `signature_decoder.py` (which only resolves
4-byte *function* selectors). Event logs are fetched via
`RPCManager.get_logs()` -- see `cli.py`'s `_run_analysis` for where this is
wired into the pipeline.

Resolution priority (mirrors the function-selector decoder's philosophy: an
authoritative source beats a guess beats nothing):
  1. `abi_event_map` -- computed directly from a verified ABI via
     `source_resolver.abi_to_event_map()`. Authoritative for *this* contract.
  2. `BUILTIN_EVENTS` -- a small table of extremely common, well-known event
     shapes (ERC-20/721/4626-ish). Not verified against this specific
     contract's source, so labeled with lower confidence.
  3. An open event-signature-hash directory (analogous to 4byte.directory for
     function selectors). Best-effort; label accordingly.
  4. Unresolved -- never fabricate a name. The log is still evidence that
     *something* happened at this address in this tx; see `models/log.py`
     for why "unresolved" is a distinct third state, not folded into
     "no evidence" or "confirmed transition".

IMPORTANT AMBIGUITY NOTE: topic0 is keccak256(name(type1,type2,...)) over the
type list *only* -- indexed-ness does not change the hash. So two events with
the same name and types but different indexed-flag layouts (e.g. ERC-20
`Transfer(address,address,uint256)` with `value` non-indexed, vs. ERC-721's
same-named/typed event with `tokenId` indexed) hash identically. This module
resolves that ambiguity for BUILTIN_EVENTS by preferring whichever registered
candidate's expected topic count (`1 + indexed_param_count`) matches the
*actual* number of topics on the observed log -- never by assuming one shape.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from eth_abi import decode as abi_decode
from eth_utils import keccak

from onchain_intent_oracle.models.log import DecodedLog
from onchain_intent_oracle.ingestion.abi_utils import normalize_decoded_value

logger = structlog.get_logger()


def _sig_to_topic0(name: str, types: List[str]) -> str:
    return "0x" + keccak(text=f"{name}({','.join(types)})").hex()


def _descriptor(name: str, params: List[tuple]) -> Dict[str, Any]:
    """params: list of (name, type, indexed) tuples, in declaration order."""
    types = [t for _, t, _ in params]
    return {
        "name": name,
        "signature": f"{name}({','.join(types)})",
        "anonymous": False,
        "inputs": [{"name": n, "type": t, "indexed": ix} for n, t, ix in params],
    }


def _register(table: Dict[str, List[Dict[str, Any]]], name: str, params: List[tuple]) -> None:
    topic0 = _sig_to_topic0(name, [t for _, t, _ in params])
    table.setdefault(topic0, []).append(_descriptor(name, params))


# Built-in table of common event shapes. Multiple candidates per topic0 are
# stored where indexed-ness is genuinely ambiguous from the signature alone
# (see module docstring) -- `_pick_candidate` below disambiguates using the
# observed log's actual topic count.
BUILTIN_EVENTS: Dict[str, List[Dict[str, Any]]] = {}

# ERC-20-shaped Transfer/Approval: value/allowance NOT indexed.
_register(BUILTIN_EVENTS, "Transfer", [("from", "address", True), ("to", "address", True), ("value", "uint256", False)])
_register(BUILTIN_EVENTS, "Approval", [("owner", "address", True), ("spender", "address", True), ("value", "uint256", False)])
# ERC-721-shaped Transfer/Approval: same name+types, tokenId IS indexed.
_register(BUILTIN_EVENTS, "Transfer", [("from", "address", True), ("to", "address", True), ("tokenId", "uint256", True)])
_register(BUILTIN_EVENTS, "Approval", [("owner", "address", True), ("spender", "address", True), ("tokenId", "uint256", True)])
_register(BUILTIN_EVENTS, "ApprovalForAll", [("owner", "address", True), ("operator", "address", True), ("approved", "bool", False)])
# WETH-style
_register(BUILTIN_EVENTS, "Deposit", [("dst", "address", True), ("wad", "uint256", False)])
_register(BUILTIN_EVENTS, "Withdrawal", [("src", "address", True), ("wad", "uint256", False)])
# ERC-4626-style
_register(BUILTIN_EVENTS, "Deposit", [("sender", "address", True), ("owner", "address", True), ("assets", "uint256", False), ("shares", "uint256", False)])
_register(BUILTIN_EVENTS, "Withdraw", [("sender", "address", True), ("receiver", "address", True), ("owner", "address", True), ("assets", "uint256", False), ("shares", "uint256", False)])
# Common admin/lifecycle events
_register(BUILTIN_EVENTS, "OwnershipTransferred", [("previousOwner", "address", True), ("newOwner", "address", True)])
_register(BUILTIN_EVENTS, "Paused", [("account", "address", False)])
_register(BUILTIN_EVENTS, "Unpaused", [("account", "address", False)])
_register(BUILTIN_EVENTS, "RoleGranted", [("role", "bytes32", True), ("account", "address", True), ("sender", "address", True)])
_register(BUILTIN_EVENTS, "RoleRevoked", [("role", "bytes32", True), ("account", "address", True), ("sender", "address", True)])
_register(BUILTIN_EVENTS, "Upgraded", [("implementation", "address", True)])


# Types the EVM can encode directly into a 32-byte topic word. Anything not
# in this shape (string, bytes, arrays, tuples) is "dynamic": when indexed,
# the EVM stores only keccak256(value) in the topic, and the original value
# is *not recoverable* from the log alone.
def _is_dynamic_type(abi_type: str) -> bool:
    if abi_type in ("string", "bytes"):
        return True
    if abi_type.endswith("[]"):
        return True
    if abi_type.startswith("tuple"):
        return True
    return False


def _pick_candidate(candidates: List[Dict[str, Any]], num_topics: int) -> Dict[str, Any]:
    """Disambiguate same-topic0 candidates by matching expected topic count.

    Falls back to the first candidate (flagged via the caller checking
    `expected_topics != num_topics` itself, if it wants to note the mismatch)
    when nothing matches exactly -- still better than refusing to try.
    """
    for cand in candidates:
        indexed_count = sum(1 for i in cand["inputs"] if i["indexed"])
        if indexed_count + 1 == num_topics:
            return cand
    return candidates[0]


class LogDecoder:
    """Decodes raw `eth_getLogs` entries into `DecodedLog` objects."""

    def __init__(
        self,
        abi_event_map: Optional[Dict[str, Dict[str, Any]]] = None,
        cache_dir: Optional[Path] = None,
    ):
        # Authoritative, per-contract map from source_resolver.abi_to_event_map().
        self.abi_event_map = abi_event_map or {}
        self._cache_dir = cache_dir or Path.home() / ".oio" / "event_signatures"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._directory_cache: Dict[str, Optional[str]] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        f = self._cache_dir / "event_signatures.json"
        if f.exists():
            try:
                self._directory_cache.update(json.loads(f.read_text()))
            except Exception as e:
                logger.warning("event_sig_cache_load_failed", error=str(e))

    def _save_cache(self) -> None:
        try:
            (self._cache_dir / "event_signatures.json").write_text(json.dumps(self._directory_cache, indent=2))
        except Exception as e:
            logger.warning("event_sig_cache_save_failed", error=str(e))

    def decode_log(self, log: Dict[str, Any]) -> DecodedLog:
        """Decode a single raw log entry using only local sources (verified
        ABI + builtin table + any previously-cached directory hits) -- no
        network call. Use `adecode_log` if you also want the open
        signature-directory fallback for still-unresolved topic0s.
        """
        topics = log.get("topics") or []
        topic0 = (topics[0] if topics else "0x").lower()
        address = log.get("address", "")
        tx_hash = log.get("transactionHash", "")
        log_index = _to_int(log.get("logIndex"))
        block_number = _to_int(log.get("blockNumber"))

        descriptor, confidence = self._resolve(topic0, num_topics=len(topics))
        if descriptor is None:
            return DecodedLog(
                address=address, tx_hash=tx_hash, log_index=log_index,
                block_number=block_number, topic0=topic0, confidence="unresolved",
                raw=log,
            )

        try:
            args, indexed_hash_only = self._decode_args(descriptor, log)
            arg_types = {i["name"]: i["type"] for i in descriptor["inputs"]}
            return DecodedLog(
                address=address, tx_hash=tx_hash, log_index=log_index,
                block_number=block_number, topic0=topic0, confidence=confidence,
                event_name=descriptor["name"], signature=descriptor.get("signature"),
                args=args, arg_types=arg_types, indexed_hash_only=indexed_hash_only, raw=log,
            )
        except Exception as e:
            # Name/signature resolved, but we couldn't safely pull argument
            # values out (malformed data, layout mismatch, etc). Keep the
            # confirmed event-name claim; do not fabricate args.
            logger.debug("log_arg_decode_failed", topic0=topic0, error=str(e))
            return DecodedLog(
                address=address, tx_hash=tx_hash, log_index=log_index,
                block_number=block_number, topic0=topic0, confidence=confidence,
                event_name=descriptor["name"], signature=descriptor.get("signature"),
                decode_error=str(e), raw=log,
            )

    def decode_logs(self, logs: List[Dict[str, Any]]) -> List[DecodedLog]:
        return [self.decode_log(log) for log in logs]

    async def adecode_log(self, log: Dict[str, Any]) -> DecodedLog:
        """Async equivalent of `decode_log` that also falls back to an open
        event-signature directory for topic0s no local source resolves."""
        topics = log.get("topics") or []
        topic0 = (topics[0] if topics else "0x").lower()
        if topic0 not in self.abi_event_map and topic0 not in BUILTIN_EVENTS:
            await self._adirectory_lookup(topic0)
        return self.decode_log(log)

    async def adecode_logs(self, logs: List[Dict[str, Any]]) -> List[DecodedLog]:
        out = []
        for log in logs:
            out.append(await self.adecode_log(log))
        return out

    def _resolve(self, topic0: str, num_topics: int) -> "tuple[Optional[Dict[str, Any]], str]":
        if topic0 in self.abi_event_map:
            return self.abi_event_map[topic0], "verified_abi"
        if topic0 in BUILTIN_EVENTS:
            return _pick_candidate(BUILTIN_EVENTS[topic0], num_topics), "builtin_table"
        cached_sig = self._directory_cache.get(topic0)
        if cached_sig:
            descriptor = self._descriptor_from_signature(cached_sig, num_topics)
            if descriptor:
                return descriptor, "signature_directory"
        return None, "unresolved"

    def _descriptor_from_signature(self, signature: str, num_topics: int) -> Optional[Dict[str, Any]]:
        """A directory hit only gives us `Name(type1,type2,...)` -- no param
        names and, critically, no indexed/non-indexed layout (that's not part
        of the signature hash input at all). We can recover *how many* params
        are indexed from the observed log's topic count, but not *which*
        ones if there's more than one non-dynamic-typed param past that
        boundary in an unconventional order. We assume declaration order
        matches indexed-first only when the type list's shape is unambiguous
        (all leading params are indexed, matching `num_topics - 1` exactly);
        otherwise we still return the descriptor but leave every param
        unindexed and rely on `_decode_args`'s data-only path, which will
        correctly fail closed (via the except-and-flag-decode_error path in
        `decode_log`) rather than guess.
        """
        try:
            name = signature.split("(")[0]
            types_str = signature[signature.index("(") + 1 : signature.rindex(")")]
            types = [t.strip() for t in types_str.split(",") if t.strip()] if types_str else []
        except Exception:
            return None
        indexed_count = max(0, num_topics - 1)
        params = []
        for i, t in enumerate(types):
            indexed = i < indexed_count
            params.append((f"arg{i}", t, indexed))
        return _descriptor(name, params)

    async def _adirectory_lookup(self, topic0: str) -> None:
        import httpx
        url = f"https://www.4byte.directory/api/v1/event-signatures/?hex_signature={topic0}"
        headers = {"User-Agent": "OnChainIntentOracle/0.1"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, headers=headers)
                data = resp.json()
                results = data.get("results", [])
                if results:
                    sig = min(results, key=lambda r: len(r.get("text_signature", ""))).get("text_signature")
                    if sig:
                        self._directory_cache[topic0] = sig
                        self._save_cache()
        except Exception as e:
            logger.debug("event_directory_lookup_failed", topic0=topic0, error=str(e))

    def _decode_args(self, descriptor: Dict[str, Any], log: Dict[str, Any]) -> "tuple[Dict[str, Any], List[str]]":
        topics = log.get("topics") or []
        data_hex = log.get("data", "0x") or "0x"
        data_bytes = bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex)

        indexed_params = [p for p in descriptor["inputs"] if p["indexed"]]
        non_indexed_params = [p for p in descriptor["inputs"] if not p["indexed"]]

        args: Dict[str, Any] = {}
        indexed_hash_only: List[str] = []

        # topics[0] is topic0 itself; topics[1:] are the indexed args, in
        # declared order.
        indexed_topics = topics[1:]
        for i, param in enumerate(indexed_params):
            if i >= len(indexed_topics):
                break
            word_hex = indexed_topics[i]
            word_bytes = bytes.fromhex(word_hex[2:] if word_hex.startswith("0x") else word_hex)
            if _is_dynamic_type(param["type"]):
                # Original value is unrecoverable -- the EVM only stores its
                # hash. Surface the hash itself, clearly labeled, never as
                # if it were the real value.
                args[param["name"]] = word_hex
                indexed_hash_only.append(param["name"])
            else:
                (decoded,) = abi_decode([param["type"]], word_bytes)
                args[param["name"]] = normalize_decoded_value(decoded)

        if non_indexed_params and data_bytes:
            types = [p["type"] for p in non_indexed_params]
            decoded_values = abi_decode(types, data_bytes)
            for param, value in zip(non_indexed_params, decoded_values):
                args[param["name"]] = normalize_decoded_value(value)

        return args, indexed_hash_only


def _to_int(val: Any) -> int:
    if val is None:
        return 0
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        try:
            return int(val, 16) if val.lower().startswith("0x") else int(val)
        except ValueError:
            return 0
    return 0

