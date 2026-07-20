"""Mine statistical invariants from transaction traces."""
from decimal import Decimal
from typing import Any, Dict, List, Optional
import structlog

logger = structlog.get_logger()


def _tx_get(tx, key, default=None):
    if isinstance(tx, dict):
        return tx.get(key, default)
    if hasattr(tx, key):
        return getattr(tx, key, default)
    return default


def _mtx_get(tx, names, default=None):
    """Try each candidate key/attribute name in order.

    The pipeline hands InvariantMiner two different transaction shapes: plain
    dicts straight off eth_getBlockByNumber (used by the CLI, with keys like
    "from"/"method"/"to"), and `Transaction` model instances (used by the agent
    pipeline and tests, with attributes like `from_address`/`method_name`/
    `to_address`). Previously this module only ever looked up the dict-style
    names, so any Transaction-object input silently produced zero invariants
    instead of an error -- every `caller`/`method` lookup fell through to a
    falsy default and got skipped.
    """
    for name in names:
        val = _tx_get(tx, name, None)
        if val is not None:
            return val
    return default


def _to_int(val):
    """Best-effort int conversion for a value that may be a hex string, a
    plain numeric string, an int, or a Decimal (as on the Transaction model)."""
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, Decimal)):
        return int(val)
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        try:
            return int(val, 16) if val.lower().startswith("0x") else int(val)
        except ValueError:
            return None
    return None


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


class InvariantMiner:
    def __init__(self):
        self._invariants = []

    def mine(self, transactions, contract_address=None):
        self._invariants = []
        contract = (contract_address or "").lower()
        if not transactions:
            return self._invariants
        self._check_msg_value(transactions)
        self._check_access_control(transactions, contract)
        self._check_revert_patterns(transactions)
        self._check_caller_consistency(transactions)
        self._check_monotonicity(transactions)
        return self._invariants

    def _check_msg_value(self, txs):
        all_zero = True
        saw_any = False
        for tx in txs:
            raw = _mtx_get(tx, ("value",), "0x0")
            val = _to_int(raw)
            if val is None:
                all_zero = False
                break
            saw_any = True
            if val != 0:
                all_zero = False
                break
        if all_zero and saw_any:
            self._invariants.append({
                "id": "INV-VAL-001",
                "expression": "msg.value == 0 for all observed txs",
                "type": "safety",
                "confidence": min(0.95, 0.7 + 0.05 * len(txs)),
                "evidence": [_mtx_get(tx, ("hash",)) for tx in txs[:3]],
                "note": "Contract does not accept ETH transfers",
            })

    def _check_access_control(self, txs, contract):
        method_callers = {}
        for tx in txs:
            method = _mtx_get(tx, ("method", "method_name"), "unknown")
            caller = (_mtx_get(tx, ("from", "from_address"), "") or "").lower()
            if not caller:
                continue
            method_callers.setdefault(method, {})
            method_callers[method][caller] = method_callers[method].get(caller, 0) + 1
        for method, callers in method_callers.items():
            total = sum(callers.values())
            if total < 3:
                continue
            dominant = max(callers.items(), key=lambda x: x[1])
            if dominant[1] / total >= 0.95:
                self._invariants.append({
                    "id": f"INV-AC-{method}",
                    "expression": f"msg.sender == {dominant[0]} for {method}()",
                    "type": "access_control",
                    "confidence": round(dominant[1] / total, 2),
                    "evidence": [],
                    "note": f"{method}() called exclusively by {dominant[0]}",
                    "holds": dominant[1],
                    "total": total,
                })

    @staticmethod
    def _normalize_status(status):
        """Normalize a receipt `status` field to 1 (success), 0 (reverted), or
        None (unknown -- no receipt was fetched for this tx). Receipts return
        status as a hex string like "0x1"/"0x0"; some callers may already have
        it as an int or bool."""
        if status is None:
            return None
        if isinstance(status, bool):
            return 1 if status else 0
        if isinstance(status, int):
            return status
        if isinstance(status, str):
            try:
                return int(status, 16) if status.lower().startswith("0x") else int(status)
            except ValueError:
                return None
        return None

    def _check_revert_patterns(self, txs):
        method_status = {}
        skipped_no_receipt = 0
        for tx in txs:
            method = _mtx_get(tx, ("method", "method_name"), "unknown")
            # `status` only exists on the transaction *receipt*, not the tx object
            # returned by eth_getBlockByNumber -- it must be fetched separately
            # (RPCManager.get_transaction_receipt) and attached by the caller.
            status = self._normalize_status(_mtx_get(tx, ("status",), None))
            if status is None:
                # No receipt available for this tx. Don't guess: silently treating
                # an unknown outcome as "success" is how you end up asserting
                # "never reverts" invariants with no evidence behind them.
                skipped_no_receipt += 1
                continue
            method_status.setdefault(method, {"success": 0, "revert": 0})
            if status == 1:
                method_status[method]["success"] += 1
            else:
                method_status[method]["revert"] += 1
        if skipped_no_receipt:
            logger.debug("revert_check_missing_receipts", skipped=skipped_no_receipt)
        for method, counts in method_status.items():
            total = counts["success"] + counts["revert"]
            if total < 3:
                continue
            revert_rate = counts["revert"] / total
            success_rate = counts["success"] / total
            if revert_rate == 0:
                self._invariants.append({
                    "id": f"INV-REV-{method}",
                    "expression": f"{method}() never reverts",
                    "type": "safety",
                    "confidence": min(0.9, 0.5 + 0.1 * total),
                    "evidence": [],
                    "note": f"Observed {total} calls (via tx receipts), all succeeded",
                })
            elif success_rate == 0:
                self._invariants.append({
                    "id": f"INV-REV-{method}",
                    "expression": f"{method}() always reverts",
                    "type": "anomaly",
                    "confidence": min(0.9, 0.5 + 0.1 * total),
                    "evidence": [],
                    "note": f"Observed {total} calls (via tx receipts), all reverted",
                })
            elif revert_rate >= 0.8:
                # Not all-or-nothing, but reverting often enough to be worth
                # flagging -- e.g. a function that's frequently called with bad
                # arguments, or is guarded in a way callers routinely trip.
                self._invariants.append({
                    "id": f"INV-REV-{method}",
                    "expression": f"{method}() usually reverts",
                    "type": "anomaly",
                    "confidence": round(revert_rate, 2),
                    "evidence": [],
                    "note": f"Observed {total} calls (via tx receipts), "
                            f"{counts['revert']} reverted ({revert_rate:.0%})",
                })

    def _check_caller_consistency(self, txs):
        all_callers = set()
        for tx in txs:
            caller = (_mtx_get(tx, ("from", "from_address"), "") or "").lower()
            if caller:
                all_callers.add(caller)
        if len(all_callers) == 1 and len(txs) > 5:
            self._invariants.append({
                "id": "INV-CALLER-001",
                "expression": f"all txs from {list(all_callers)[0]}",
                "type": "access_control",
                "confidence": 0.8,
                "evidence": [],
                "note": "Single caller observed - possible test or controlled environment",
            })

    def _check_monotonicity(self, txs):
        """Flag storage slots whose observed value only ever increases or only
        ever decreases across the observed transactions (e.g. a strictly
        increasing nonce/supply counter, or a strictly decreasing balance).

        Like the other checks here, this is a statistical observation over a
        finite sample, not a proof -- it's meant to be a candidate for
        promotion to a symbolic property, same as everything else this module
        produces.
        """
        slot_sequences: Dict[Any, List[Any]] = {}
        for tx in txs:
            block = _mtx_get(tx, ("block_number", "blockNumber"), 0) or 0
            for slot, _old_value, new_value in _extract_state_diffs(tx):
                val = _to_int(new_value)
                if val is None:
                    continue
                slot_sequences.setdefault(slot, []).append((block, val))

        for slot, seq in slot_sequences.items():
            if len(seq) < 3:
                continue
            seq.sort(key=lambda pair: pair[0])
            values = [v for _, v in seq]
            increasing = all(b >= a for a, b in zip(values, values[1:]))
            decreasing = all(b <= a for a, b in zip(values, values[1:]))
            strictly_constant = values[0] == values[-1] and increasing and decreasing
            if strictly_constant:
                continue
            if increasing and not decreasing:
                direction = "increases monotonically"
            elif decreasing and not increasing:
                direction = "decreases monotonically"
            else:
                continue
            self._invariants.append({
                "id": f"INV-MONO-{slot}",
                "expression": f"storage slot {slot} {direction} across observed txs",
                "type": "state",
                "confidence": min(0.9, 0.5 + 0.08 * len(values)),
                "evidence": [],
                "note": f"Observed {len(values)} state changes to slot {slot}",
            })
