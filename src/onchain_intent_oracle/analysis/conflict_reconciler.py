"""Reconcile observed behavior with design documents and code."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from onchain_intent_oracle.models.invariant import Invariant
from onchain_intent_oracle.models.transaction import Transaction

logger = structlog.get_logger()


@dataclass
class Conflict:
    """A conflict between sources of truth."""

    severity: str  # critical, high, medium, low, info
    category: str  # access_control, economic, state, upgrade, other
    design_claim: str
    observed_reality: str
    code_evidence: Optional[str] = None
    recommendation: str = ""
    evidence_txs: List[str] = field(default_factory=list)


@dataclass
class ReconciliationReport:
    """Complete reconciliation report."""

    contract_address: str
    conflicts: List[Conflict] = field(default_factory=list)
    omissions: List[Dict] = field(default_factory=list)
    weakenings: List[Dict] = field(default_factory=list)
    security_gaps: List[Dict] = field(default_factory=list)


class ConflictReconciler:
    """Compare design claims, code, and observed behavior."""

    def __init__(self, design_doc: Optional[str] = None):
        self.design_doc = design_doc
        self._design_claims: List[Dict] = []

    def _parse_design_claims(self) -> List[Dict]:
        """Extract claims from design document (simplified)."""
        if not self.design_doc:
            return []

        # Simple heuristic parsing - in production, use LLM
        claims = []
        lines = self.design_doc.split("\n")

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Look for access control claims
            if any(kw in line.lower() for kw in ["only owner", "only admin", "only", "role"]):
                claims.append({"category": "access_control", "text": line})
            # Economic claims
            elif any(kw in line.lower() for kw in ["fee", "cap", "limit", "maximum", "minimum"]):
                claims.append({"category": "economic", "text": line})
            # State claims
            elif any(kw in line.lower() for kw in ["when paused", "state", "mode", "enabled", "disabled"]):
                claims.append({"category": "state", "text": line})
            # Upgrade claims
            elif any(kw in line.lower() for kw in ["upgrade", "proxy", "implementation"]):
                claims.append({"category": "upgrade", "text": line})
            else:
                claims.append({"category": "other", "text": line})

        return claims

    def reconcile(
        self,
        txs: List[Transaction],
        invariants: List[Invariant],
        source_code: Optional[str] = None,
    ) -> ReconciliationReport:
        """Reconcile all sources of truth."""

        contract = txs[0].to_address if txs else "unknown"
        report = ReconciliationReport(contract_address=contract)

        design_claims = self._parse_design_claims()

        # Check access control claims
        for claim in [c for c in design_claims if c["category"] == "access_control"]:
            # Check if observed behavior matches
            function_callers = defaultdict(set)
            for tx in txs:
                if tx.method_name:
                    function_callers[tx.method_name].add(tx.from_address)

            # If design says "only owner" but multiple callers observed
            if "only" in claim["text"].lower():
                for func, callers in function_callers.items():
                    if len(callers) > 1:
                        report.conflicts.append(Conflict(
                            severity="high",
                            category="access_control",
                            design_claim=claim["text"],
                            observed_reality=f"{func}() called by {len(callers)} distinct addresses",
                            code_evidence=source_code[:200] if source_code else None,
                            recommendation="Verify if multi-caller access is intentional or update design doc",
                        ))

        # Check economic claims
        for claim in [c for c in design_claims if c["category"] == "economic"]:
            # Look for fee cap claims
            if "fee" in claim["text"].lower() and "cap" in claim["text"].lower():
                # Check if any transaction shows fee exceeding claimed cap
                # This would need fee extraction from traces
                pass

        # Check for omissions: things observed but not in design
        observed_methods = set(tx.method_name for tx in txs if tx.method_name)
        # If design doesn't mention certain methods
        for method in observed_methods:
            if not any(method.lower() in c["text"].lower() for c in design_claims):
                report.omissions.append({
                    "type": "undocumented_function",
                    "function": method,
                    "observed_calls": len([t for t in txs if t.method_name == method]),
                    "recommendation": f"Document {method}() in design doc",
                })

        # Check invariant weakenings
        for inv in invariants:
            if inv.confidence < 1.0 and inv.hold_count > 0:
                report.weakenings.append({
                    "invariant": inv.expression,
                    "confidence": inv.confidence,
                    "holds": inv.hold_count,
                    "total": inv.total_count,
                    "note": "Statistical invariant, not guaranteed in all cases",
                })

        # Security gaps: high-value transactions without access control
        high_value_txs = [t for t in txs if t.value and float(t.value) > 1e21]  # > 1000 ETH
        for tx in high_value_txs:
            if tx.method_name in ["transfer", "withdraw", "mint", "burn"]:
                report.security_gaps.append({
                    "type": "high_value_operation",
                    "tx_hash": tx.hash,
                    "value_eth": float(tx.value) / 1e18,
                    "method": tx.method_name,
                    "caller": tx.from_address,
                    "note": "High-value operation observed; verify access controls",
                })

        logger.info("reconciliation_complete", 
                     conflicts=len(report.conflicts),
                     omissions=len(report.omissions),
                     gaps=len(report.security_gaps))

        return report
