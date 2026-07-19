"""Mine statistical invariants from transaction traces."""
from typing import Any, Dict, List, Optional
import structlog

logger = structlog.get_logger()


def _tx_get(tx, key, default=None):
    if isinstance(tx, dict):
        return tx.get(key, default)
    if hasattr(tx, key):
        return getattr(tx, key, default)
    return default


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
        return self._invariants

    def _check_msg_value(self, txs):
        all_zero = True
        for tx in txs:
            val = _tx_get(tx, "value", "0x0")
            try:
                if int(val, 16) != 0:
                    all_zero = False
                    break
            except (ValueError, TypeError):
                all_zero = False
                break
        if all_zero and len(txs) > 0:
            self._invariants.append({
                "id": "INV-VAL-001",
                "expression": "msg.value == 0 for all observed txs",
                "type": "safety",
                "confidence": min(0.95, 0.7 + 0.05 * len(txs)),
                "evidence": [_tx_get(tx, "hash") for tx in txs[:3]],
                "note": "Contract does not accept ETH transfers",
            })

    def _check_access_control(self, txs, contract):
        method_callers = {}
        for tx in txs:
            method = _tx_get(tx, "method", "unknown")
            caller = (_tx_get(tx, "from", "") or "").lower()
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

    def _check_revert_patterns(self, txs):
        method_status = {}
        for tx in txs:
            method = _tx_get(tx, "method", "unknown")
            status = _tx_get(tx, "status", "1")
            method_status.setdefault(method, {"success": 0, "revert": 0})
            if status in ("1", 1, True):
                method_status[method]["success"] += 1
            else:
                method_status[method]["revert"] += 1
        for method, counts in method_status.items():
            total = counts["success"] + counts["revert"]
            if total < 3:
                continue
            if counts["revert"] == 0:
                self._invariants.append({
                    "id": f"INV-REV-{method}",
                    "expression": f"{method}() never reverts",
                    "type": "safety",
                    "confidence": min(0.9, 0.5 + 0.1 * total),
                    "evidence": [],
                    "note": f"Observed {total} calls, all succeeded",
                })
            elif counts["success"] == 0:
                self._invariants.append({
                    "id": f"INV-REV-{method}",
                    "expression": f"{method}() always reverts",
                    "type": "anomaly",
                    "confidence": min(0.9, 0.5 + 0.1 * total),
                    "evidence": [],
                    "note": f"Observed {total} calls, all reverted",
                })

    def _check_caller_consistency(self, txs):
        all_callers = set()
        for tx in txs:
            caller = (_tx_get(tx, "from", "") or "").lower()
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
