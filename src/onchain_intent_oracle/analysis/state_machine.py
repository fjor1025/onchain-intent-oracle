"""Infer state machines from transaction traces."""
import hashlib
from typing import Dict, List, Optional, Set
import structlog
from onchain_intent_oracle.models.state_machine import StateMachine

logger = structlog.get_logger()


def _tx_get(tx, key, default=None):
    if isinstance(tx, dict):
        return tx.get(key, default)
    if hasattr(tx, key):
        return getattr(tx, key, default)
    return default


class StateMachineInference:
    def __init__(self):
        self._state_hashes = {}

    def infer(self, transactions, signature_decoder=None):
        sm = StateMachine()
        sm.add_state("initial", description="Contract before any observed interaction")
        prev_state = "initial"
        seen_states = {"initial"}

        for tx in transactions:
            if isinstance(tx, list):
                logger.debug("skipping_list_transaction")
                continue
            method = self._extract_method(tx, signature_decoder)
            state_fp = self._compute_state_fingerprint(tx)
            state_name = f"state_{state_fp[:14]}" if state_fp else "state_default"
            if state_name not in seen_states:
                sm.add_state(state_name, description=f"Observed state {state_name}", storage_fingerprint=state_fp)
                seen_states.add(state_name)
            caller = _tx_get(tx, "from", "unknown")[:10]
            guard = f"{method}() called by {caller}..."
            sm.add_transition(from_state=prev_state, to_state=state_name, trigger=method, guard=guard, evidence_txs=[_tx_get(tx, "hash", "")])
            prev_state = state_name

        if len(sm.states) == 1:
            sm.add_state("state_default", description="Default observed state")
        return sm

    def _extract_method(self, tx, signature_decoder=None):
        input_data = _tx_get(tx, "input", "")
        if not input_data or input_data == "0x":
            return "fallback"
        if signature_decoder:
            name, _ = signature_decoder.decode_trace(input_data)
            return name
        return input_data[:10]

    def _compute_state_fingerprint(self, tx):
        state_diff = _tx_get(tx, "state_diff", {})
        if state_diff:
            return hashlib.sha256("".join(sorted(state_diff.keys())).encode()).hexdigest()[:16]
        traces = _tx_get(tx, "traces", [])
        if traces:
            return hashlib.sha256("".join(str(t.get("output", "")) for t in traces).encode()).hexdigest()[:16]
        raw = _tx_get(tx, "input", "") + _tx_get(tx, "from", "") + _tx_get(tx, "to", "")
        if raw:
            return hashlib.sha256(raw.encode()).hexdigest()[:16]
        return None
