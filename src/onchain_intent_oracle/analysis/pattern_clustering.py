"""Cluster transactions by method, parameters, and outcomes."""

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sklearn.cluster import DBSCAN
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler

from onchain_intent_oracle.models.transaction import Transaction

logger = structlog.get_logger()


class PatternClustering:
    """Cluster transactions to identify common vs rare patterns."""

    def __init__(self, min_samples: int = 5, eps: float = 0.5):
        self.min_samples = min_samples
        self.eps = eps

    def _extract_features(self, tx: Transaction) -> Dict[str, Any]:
        """Extract numerical features from a transaction."""
        features = {
            "value_eth": float(tx.value) / 1e18 if tx.value else 0,
            "gas_used": tx.gas_used or 0,
            "gas_price_gwei": float(tx.gas_price) / 1e9 if tx.gas_price else 0,
            "input_length": len(tx.input) if tx.input else 0,
            "has_trace": 1 if tx.trace else 0,
            "state_diff_count": len(tx.state_diffs),
            "log_count": len(tx.logs),
            "status": tx.status or 0,
        }

        # Add method-specific features
        if tx.method_name:
            features[f"method_{tx.method_name}"] = 1

        # Add caller features (simplified)
        if tx.from_address:
            features["caller_known_contract"] = 1 if tx.from_address.startswith("0x") else 0

        return features

    def cluster(self, txs: List[Transaction]) -> Dict[str, Any]:
        """Cluster transactions and return pattern analysis."""
        if len(txs) < self.min_samples:
            return {
                "clusters": [],
                "common_patterns": [],
                "rare_patterns": [],
                "outliers": [],
            }

        # Extract features
        features = [self._extract_features(tx) for tx in txs]

        # Convert to matrix
        vectorizer = DictVectorizer(sparse=False)
        X = vectorizer.fit_transform(features)

        # Scale
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # Cluster
        clustering = DBSCAN(eps=self.eps, min_samples=self.min_samples)
        labels = clustering.fit_predict(X_scaled)

        # Analyze clusters
        clusters = defaultdict(list)
        for i, label in enumerate(labels):
            clusters[label].append(txs[i])

        # Identify common vs rare
        cluster_sizes = {k: len(v) for k, v in clusters.items()}
        total = len(txs)

        common = []
        rare = []
        outliers = []

        for label, txs_in_cluster in clusters.items():
            ratio = len(txs_in_cluster) / total

            if label == -1:
                # Noise/outliers
                outliers.extend([
                    {"tx_hash": tx.hash, "method": tx.method_name}
                    for tx in txs_in_cluster
                ])
            elif ratio > 0.2:
                common.append({
                    "cluster_id": label,
                    "size": len(txs_in_cluster),
                    "ratio": ratio,
                    "dominant_method": Counter(
                        tx.method_name for tx in txs_in_cluster if tx.method_name
                    ).most_common(1)[0][0] if any(tx.method_name for tx in txs_in_cluster) else "unknown",
                    "avg_value_eth": sum(
                        float(tx.value or 0) / 1e18 for tx in txs_in_cluster
                    ) / len(txs_in_cluster),
                })
            else:
                rare.append({
                    "cluster_id": label,
                    "size": len(txs_in_cluster),
                    "ratio": ratio,
                    "methods": list(set(
                        tx.method_name for tx in txs_in_cluster if tx.method_name
                    )),
                })

        return {
            "clusters": [
                {"id": k, "size": len(v), "txs": [tx.hash for tx in v]}
                for k, v in clusters.items() if k != -1
            ],
            "common_patterns": common,
            "rare_patterns": rare,
            "outliers": outliers,
        }
