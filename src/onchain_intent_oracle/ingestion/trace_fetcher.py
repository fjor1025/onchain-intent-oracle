"""Fetch and parse transaction traces with state diffs."""

from typing import Any, Dict, List, Optional

import structlog
from eth_typing import ChecksumAddress, HexStr

from onchain_intent_oracle.ingestion.cache import CacheLayer
from onchain_intent_oracle.ingestion.rpc_manager import RPCManager
from onchain_intent_oracle.ingestion.signature_decoder import SignatureDecoder
from onchain_intent_oracle.models.transaction import CallTrace, StateDiff, Transaction

logger = structlog.get_logger()


class TraceFetcher:
    """Fetches and parses transaction traces."""

    def __init__(self, rpc: RPCManager, cache: Optional[CacheLayer] = None):
        self.rpc = rpc
        self.cache = cache or CacheLayer()
        self.sig_decoder = SignatureDecoder()

    async def fetch_transaction_input(self, tx_hash: str, chain_id: int = 1) -> Optional[str]:
        """Fetch raw transaction input data for method decoding."""
        try:
            tx_data = await self.rpc.get_transaction(tx_hash)
            if tx_data and isinstance(tx_data, dict):
                return tx_data.get("input") or tx_data.get("data")
        except Exception as e:
            logger.debug("fetch_tx_input_failed", tx_hash=tx_hash, error=str(e))
        return None

    async def fetch_trace(self, tx_hash: str, chain_id: int = 1) -> Optional[Dict]:
        """Fetch trace with caching."""
        cached = self.cache.get_tx_trace(chain_id, tx_hash)
        if cached:
            logger.debug("trace_cache_hit", tx_hash=tx_hash)
            return cached
        try:
            trace = await self.rpc.debug_trace_transaction(tx_hash, tracer="callTracer", tracer_config={"withLog": True})
            if trace:
                self.cache.set_tx_trace(chain_id, tx_hash, trace)
                return trace
        except Exception as e:
            logger.warning("debug_trace_failed", tx_hash=tx_hash, error=str(e))
        try:
            trace = await self.rpc.trace_transaction(tx_hash)
            if trace:
                self.cache.set_tx_trace(chain_id, tx_hash, trace)
                return trace
        except Exception as e:
            logger.warning("trace_transaction_failed", tx_hash=tx_hash, error=str(e))
        return None

    async def fetch_state_diff(self, tx_hash: str, chain_id: int = 1) -> List[StateDiff]:
        """Fetch state differences for a transaction."""
        try:
            trace = await self.rpc.debug_trace_transaction(tx_hash, tracer="prestateTracer", tracer_config={"diffMode": True})
            if trace and "post" in trace:
                diffs = []
                for addr, state in trace["post"].items():
                    for slot, value in state.get("storage", {}).items():
                        diffs.append(StateDiff(slot=HexStr(slot), new_value=HexStr(value) if value else None, address=ChecksumAddress(addr)))
                return diffs
        except Exception as e:
            logger.warning("state_diff_fetch_failed", tx_hash=tx_hash, error=str(e))
        return []

    def _decode_method(self, tx: Transaction) -> str:
        """Decode method name from transaction input."""
        if hasattr(tx, 'input') and tx.input and tx.input != "0x":
            decoded = self.sig_decoder.decode(tx.input)
            if decoded:
                return decoded
        if hasattr(tx, 'data') and tx.data and tx.data != "0x":
            decoded = self.sig_decoder.decode(tx.data)
            if decoded:
                return decoded
        return getattr(tx, 'method_name', None) or "unknown"

    def _parse_call_tracer(self, raw: Dict, depth: int = 0) -> CallTrace:
        return CallTrace(
            type=raw.get("type", "CALL"),
            from_address=ChecksumAddress(raw.get("from", "0x")),
            to_address=ChecksumAddress(raw["to"]) if raw.get("to") else None,
            value=int(raw.get("value", "0x0"), 16) if isinstance(raw.get("value"), str) else 0,
            gas=int(raw.get("gas", "0x0"), 16) if isinstance(raw.get("gas"), str) else 0,
            gas_used=int(raw.get("gasUsed", "0x0"), 16) if isinstance(raw.get("gasUsed"), str) else 0,
            input=HexStr(raw.get("input", "0x")),
            output=HexStr(raw.get("output", "0x")),
            error=raw.get("error"),
            calls=[self._parse_call_tracer(c, depth + 1) for c in raw.get("calls", [])],
        )

    async def enrich_transaction(self, tx: Transaction, chain_id: int = 1) -> Transaction:
        """Add trace, state diff, and decoded method to a transaction."""
        if not hasattr(tx, 'input') or not tx.input or tx.input == "0x":
            tx.input = await self.fetch_transaction_input(tx.hash, chain_id)
        tx.method_name = self._decode_method(tx)
        trace_raw = await self.fetch_trace(tx.hash, chain_id)
        if trace_raw:
            tx.trace = self._parse_call_tracer(trace_raw)
            tx.state_diffs = await self.fetch_state_diff(tx.hash, chain_id)
        return tx