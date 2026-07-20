"""Tests for invariant miner.

Note: InvariantMiner.mine() returns plain dicts (not typed Invariant model
instances) -- this is intentional and load-bearing: the CLI pipeline and the
JSON/markdown output generators all consume this shape directly and json.dumps
it as-is. These tests were originally written against a typed-model API that
was never actually implemented; they've been adjusted to match the real,
shipped contract instead of the aspirational one.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from onchain_intent_oracle.analysis.invariant_miner import InvariantMiner
from onchain_intent_oracle.models.transaction import Transaction


class TestInvariantMiner:
    """Test invariant mining."""

    def test_empty_transactions(self):
        """Test with no transactions."""
        miner = InvariantMiner()
        invariants = miner.mine([])
        assert len(invariants) == 0

    def test_access_control_invariant(self):
        """Test access control invariant detection."""
        miner = InvariantMiner()

        txs = [
            Transaction(
                hash=f"0x{i:03x}",
                block_number=100 + i,
                timestamp=datetime.now(),
                from_address="0xAdminOnly",
                to_address="0xContract",
                value=Decimal("0"),
                method_name="upgrade",
                status=1,
            )
            for i in range(10)
        ]

        invariants = miner.mine(txs)
        ac_invs = [inv for inv in invariants if inv["type"] == "access_control"]
        assert len(ac_invs) > 0
        assert ac_invs[0]["confidence"] >= 0.95

    def test_revert_pattern_detection(self):
        """Test revert pattern detection."""
        miner = InvariantMiner()

        txs = [
            Transaction(
                hash=f"0x{i:03x}",
                block_number=100 + i,
                timestamp=datetime.now(),
                from_address="0xUser",
                to_address="0xContract",
                value=Decimal("0"),
                method_name="brokenFunction",
                status=0 if i < 9 else 1,  # 9/10 reverts
            )
            for i in range(10)
        ]

        invariants = miner.mine(txs)
        rev_invs = [inv for inv in invariants if "revert" in inv["expression"].lower()]
        assert len(rev_invs) > 0
        assert rev_invs[0]["confidence"] == 0.9

    def test_monotonicity_detection(self):
        """Test monotonicity invariant."""
        miner = InvariantMiner()

        from onchain_intent_oracle.models.transaction import StateDiff

        txs = [
            Transaction(
                hash=f"0x{i:03x}",
                block_number=100 + i,
                timestamp=datetime.now(),
                from_address="0xUser",
                to_address="0xContract",
                value=Decimal("0"),
                state_diffs=[
                    StateDiff(slot="0x1", old_value=hex(i * 100), new_value=hex((i + 1) * 100)),
                ],
            )
            for i in range(5)
        ]

        invariants = miner.mine(txs)
        mono_invs = [inv for inv in invariants if "monotonically" in inv["expression"].lower()]
        assert len(mono_invs) > 0
