"""Tests for state machine inference."""

from datetime import datetime
from decimal import Decimal

import pytest

from onchain_intent_oracle.analysis.state_machine import StateMachineInference
from onchain_intent_oracle.models.transaction import StateDiff, Transaction


class TestStateMachineInference:
    """Test state machine inference."""

    def test_empty_transaction_list(self):
        """Test inference with no transactions."""
        inference = StateMachineInference()
        sm = inference.infer([])
        assert sm.contract_address == "unknown"
        assert len(sm.states) == 0

    def test_single_state_no_transitions(self):
        """Test with one transaction."""
        inference = StateMachineInference()
        tx = Transaction(
            hash="0xabc",
            block_number=100,
            timestamp=datetime.now(),
            from_address="0xUser",
            to_address="0xContract",
            value=Decimal("0"),
            method_name="transfer",
        )
        sm = inference.infer([tx])
        assert sm.contract_address == "0xContract"
        assert len(sm.transitions) == 0  # No state change

    def test_state_transition_on_storage_change(self):
        """Test transition detected on storage change."""
        inference = StateMachineInference()

        tx1 = Transaction(
            hash="0xabc",
            block_number=100,
            timestamp=datetime.now(),
            from_address="0xUser",
            to_address="0xContract",
            value=Decimal("0"),
            method_name="transfer",
            state_diffs=[
                StateDiff(slot="0x1", old_value="0x0", new_value="0x100"),
            ],
        )
        tx2 = Transaction(
            hash="0xdef",
            block_number=101,
            timestamp=datetime.now(),
            from_address="0xUser",
            to_address="0xContract",
            value=Decimal("0"),
            method_name="pause",
            state_diffs=[
                StateDiff(slot="0x2", old_value="0x0", new_value="0x1"),
            ],
        )

        sm = inference.infer([tx1, tx2])
        assert len(sm.transitions) == 2  # initial->state1, state1->state2
        assert sm.transitions[0].trigger == "transfer"
        assert sm.transitions[1].trigger == "pause"

    def test_storage_fingerprint_computation(self):
        """Test fingerprint generation."""
        inference = StateMachineInference()
        tx = Transaction(
            hash="0xabc",
            block_number=100,
            timestamp=datetime.now(),
            from_address="0xUser",
            to_address="0xContract",
            value=Decimal("0"),
            state_diffs=[
                StateDiff(slot="0x1", old_value="0x0", new_value="0x100"),
                StateDiff(slot="0x2", old_value="0x5", new_value="0x3"),
            ],
        )
        fp = inference._compute_storage_fingerprint(tx)
        assert "inc" in fp  # 0x0 -> 0x100 is increase
        assert "dec" in fp  # 0x5 -> 0x3 is decrease
