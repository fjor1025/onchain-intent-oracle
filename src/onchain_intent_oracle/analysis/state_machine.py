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


def _mtx_get(tx, names, default=None):
    """Try each candidate key/attribute name in order (handles both the raw
    dict shape produced by the CLI's JSON-RPC pipeline -- 'from', 'to',
    'method' -- and the Transaction model's shape -- 'from_address',
    'to_address', 'method_name')."""
    for name in names:
        val = _tx_get(tx, name, None)
        if val is not None:
            return val
    return default


def _extract_state_diffs(tx):
    """Normalize state-diff evidence from either tx shape into a list of
    (slot, old_value, new_value) tuples.

    Dict-style tx (set by cli.py's enrichment step): {"state_diff": {slot:
    {"old": ..., "new": ...}}}. Transaction model: `state_diffs: List[StateDiff]`.
    """
    state_diff = _tx_get(tx, "state_diff", None)
    if state_diff:
        out = []
        for slot, v in state_diff.items():
            if isinstance(v, dict):
                out.append((slot, v.get("old"), v.get("new")))
            else:
                out.append((slot, None, v))
        return out
    diffs = _tx_get(tx, "state_diffs", None)
    if diffs:
        return [(d.slot, d.old_value, d.new_value) for d in diffs]
    return []


def _diff_direction(old_value, new_value):
    """Classify a storage slot change as increasing/decreasing/equal when both
    values are interpretable as integers, otherwise just "changed"."""
    def to_int(v):
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return int(v, 16) if v.lower().startswith("0x") else int(v)
            except ValueError:
                return None
        if isinstance(v, (int, float)):
            return int(v)
        return None

    old_int, new_int = to_int(old_value), to_int(new_value)
    if old_int is not None and new_int is not None:
        if new_int > old_int:
            return "inc"
        if new_int < old_int:
            return "dec"
        return "eq"
    return "changed"


class StateMachineInference:
    def __init__(self):
        self._state_hashes = {}

    def infer(self, transactions, signature_decoder=None, contract_address=None):
        sm = StateMachine(contract_address=contract_address or "unknown")

        if not transactions:
            return sm

        sm.add_state("initial", description="Contract before any observed interaction")
        prev_state = "initial"
        seen_states = {"initial"}

        for tx in transactions:
            if isinstance(tx, list):
                logger.debug("skipping_list_transaction")
                continue

            if contract_address is None:
                to_addr = _mtx_get(tx, ("to", "to_address"), None)
                if to_addr:
                    sm.contract_address = to_addr

            method = self._extract_method(tx, signature_decoder)
            state_fp = self._compute_storage_fingerprint(tx)
            if state_fp is None:
                # No real evidence (state diff / trace output) that this call
                # actually changed contract storage. Don't fabricate a "new
                # state" just because the calldata was different -- e.g.
                # transfer(a, 100) and transfer(a, 200) are the same *state
                # transition* unless we actually observed storage change.
                continue

            state_name = f"state_{state_fp[:14]}"
            if state_name not in seen_states:
                sm.add_state(state_name, description=f"Observed state {state_name}", storage_fingerprint=state_fp)
                seen_states.add(state_name)

            if state_name == prev_state:
                # Same observed state as before (e.g. a read-only call, or a
                # write that happened to net out to the same values) -- no
                # transition to record.
                continue

            caller = (_mtx_get(tx, ("from", "from_address"), "unknown") or "unknown")[:10]
            guard = f"{method}() called by {caller}..."
            sm.add_transition(
                from_state=prev_state,
                to_state=state_name,
                trigger=method,
                guard=guard,
                evidence_txs=[_mtx_get(tx, ("hash",), "")],
            )
            prev_state = state_name

        return sm

    def _extract_method(self, tx, signature_decoder=None):
        # Prefer a method name an earlier pipeline stage already decoded
        # (cli.py sets "method"; the Transaction model uses "method_name").
        pre_decoded = _mtx_get(tx, ("method", "method_name"), None)
        if pre_decoded:
            return pre_decoded
        input_data = _tx_get(tx, "input", "")
        if not input_data or input_data == "0x":
            return "fallback"
        if signature_decoder:
            name, _ = signature_decoder.decode_trace(input_data)
            return name
        return input_data[:10]

    def _compute_storage_fingerprint(self, tx):
        """Compute a fingerprint of the *observed* storage change for this tx.

        Returns None when there's no real evidence (a fetched state diff, or a
        trace) that storage actually changed -- in that case we don't have
        grounds to claim a new contract state was reached at all.
        """
        diffs = _extract_state_diffs(tx)
        if diffs:
            tags = sorted(f"{slot}:{_diff_direction(old, new)}" for slot, old, new in diffs)
            return "|".join(tags)

        traces = _tx_get(tx, "traces", [])
        if traces:
            return hashlib.sha256("".join(str(t.get("output", "")) for t in traces).encode()).hexdigest()[:16]

        return None

    # Backwards-compatible alias for the old (pre-fix) method name.
    _compute_state_fingerprint = _compute_storage_fingerprint
