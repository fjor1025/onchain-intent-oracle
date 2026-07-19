"""Detect anomalies and drift in transaction patterns."""

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from onchain_intent_oracle.models.transaction import Transaction

logger = structlog.get_logger()


class AnomalyDetector:
    """Detect unusual transactions and pattern drift."""

    def __init__(self):
        self._baseline: Optional[Dict] = None

    def _compute_baseline(self, txs: List[Transaction]) -> Dict:
        """Compute baseline statistics from first 80% of data."""
        split = int(len(txs) * 0.8)
        baseline_txs = txs[:split]

        # Method frequencies
        method_counts = defaultdict(int)
        caller_counts = defaultdict(int)
        value_distribution = []

        for tx in baseline_txs:
            if tx.method_name:
                method_counts[tx.method_name] += 1
            caller_counts[tx.from_address] += 1
            if tx.value:
                value_distribution.append(float(tx.value))

        total = len(baseline_txs)

        return {
            "method_frequencies": {k: v/total for k, v in method_counts.items()},
            "common_callers": set(
                addr for addr, count in caller_counts.items() 
                if count > total * 0.01
            ),
            "avg_value": sum(value_distribution) / len(value_distribution) if value_distribution else 0,
            "max_value": max(value_distribution) if value_distribution else 0,
            "tx_count": total,
        }

    def detect(self, txs: List[Transaction]) -> List[Dict]:
        """Detect anomalies in transaction list."""
        if len(txs) < 20:
            return []

        self._baseline = self._compute_baseline(txs)
        baseline = self._baseline

        anomalies = []

        for tx in txs:
            reasons = []
            severity = "low"

            # Anomaly 1: Unknown caller
            if tx.from_address not in baseline["common_callers"]:
                reasons.append(f"Uncommon caller: {tx.from_address}")
                severity = "medium"

            # Anomaly 2: Unusual method
            if tx.method_name and tx.method_name not in baseline["method_frequencies"]:
                reasons.append(f"Never-before-seen method: {tx.method_name}")
                severity = "high"

            # Anomaly 3: Large value
            if tx.value and float(tx.value) > baseline["max_value"] * 2:
                reasons.append(f"Value {float(tx.value)/1e18:.2f} ETH exceeds 2x max baseline")
                severity = "high"

            # Anomaly 4: Failed transaction with unusual pattern
            if tx.status == 0 and tx.method_name in baseline["method_frequencies"]:
                # Function that usually succeeds now failing
                if baseline["method_frequencies"][tx.method_name] > 0.9:
                    reasons.append(f"{tx.method_name}() unexpectedly reverted")
                    severity = "medium"

            # Anomaly 5: First occurrence of a new state transition
            # (Would need state machine context)

            if reasons:
                anomalies.append({
                    "tx_hash": tx.hash,
                    "block": tx.block_number,
                    "timestamp": tx.timestamp.isoformat() if tx.timestamp else None,
                    "severity": severity,
                    "reasons": reasons,
                    "method": tx.method_name,
                    "from": tx.from_address,
                    "value_eth": float(tx.value) / 1e18 if tx.value else 0,
                })

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        anomalies.sort(key=lambda x: severity_order.get(x["severity"], 4))

        logger.info("anomalies_detected", count=len(anomalies))
        return anomalies
