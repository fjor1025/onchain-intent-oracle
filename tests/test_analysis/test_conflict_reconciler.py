"""Tests for ConflictReconciler.

This module previously had NO test coverage at all, which is how a guaranteed
NameError (defaultdict used but never imported) shipped undetected: any call to
reconcile() with an access-control design claim present would crash immediately.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from onchain_intent_oracle.analysis.conflict_reconciler import ConflictReconciler
from onchain_intent_oracle.models.transaction import Transaction


def _tx(method_name, from_address, hash_="0xabc"):
    return Transaction(
        hash=hash_,
        block_number=100,
        timestamp=datetime.now(),
        from_address=from_address,
        to_address="0xContract",
        value=Decimal("0"),
        method_name=method_name,
    )


class TestConflictReconciler:
    """Test design-doc/observed-behavior reconciliation."""

    def test_reconcile_with_no_design_doc(self):
        """Baseline: reconcile() should not crash with no design doc at all."""
        reconciler = ConflictReconciler(design_doc=None)
        report = reconciler.reconcile(txs=[], invariants=[])
        assert report.conflicts == []

    def test_access_control_claim_does_not_crash(self):
        """Regression test: this used to raise `NameError: name 'defaultdict' is
        not defined` unconditionally, because conflict_reconciler.py used
        defaultdict(set) without importing it from collections."""
        design_doc = "Only the owner can call upgrade()."
        reconciler = ConflictReconciler(design_doc=design_doc)

        txs = [
            _tx("upgrade", "0xOwner", hash_="0x1"),
            _tx("upgrade", "0xSomeoneElse", hash_="0x2"),
        ]

        # This must not raise.
        report = reconciler.reconcile(txs=txs, invariants=[])
        assert len(report.conflicts) == 1
        assert report.conflicts[0].category == "access_control"
        assert "2 distinct addresses" in report.conflicts[0].observed_reality

    def test_access_control_claim_single_caller_no_conflict(self):
        """A design claim of 'only X' should NOT produce a conflict when observed
        behavior is consistent with it (single caller)."""
        design_doc = "Only the admin role can call upgrade()."
        reconciler = ConflictReconciler(design_doc=design_doc)

        txs = [
            _tx("upgrade", "0xAdmin", hash_="0x1"),
            _tx("upgrade", "0xAdmin", hash_="0x2"),
        ]

        report = reconciler.reconcile(txs=txs, invariants=[])
        assert report.conflicts == []

    def test_undocumented_function_is_reported_as_omission(self):
        design_doc = "The contract supports pausing via pause()."
        reconciler = ConflictReconciler(design_doc=design_doc)

        txs = [_tx("mint", "0xUser", hash_="0x1")]

        report = reconciler.reconcile(txs=txs, invariants=[])
        omitted_functions = [o["function"] for o in report.omissions]
        assert "mint" in omitted_functions
