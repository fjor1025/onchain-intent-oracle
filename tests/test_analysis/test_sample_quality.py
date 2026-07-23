"""Tests for analysis/sample_quality.py (Fix 4)."""

from onchain_intent_oracle.analysis.sample_quality import (
    assess_sample_quality,
    format_sample_quality_warning,
)


def _tx(from_addr="0xUser", method="transfer"):
    return {"from": from_addr, "method": method}


class TestMorphoBootstrapDiagnosticCase:
    """The exact shape of the run that motivated this fix: 12 txs, all
    admin config calls, one caller, right at contract deployment."""

    def test_all_four_flags_fire(self):
        txs = (
            [_tx("0xAdmin", "enableIrm")] * 2
            + [_tx("0xAdmin", "enableLltv")] * 9
            + [_tx("0xAdmin", "setOwner")] * 1
        )
        result = assess_sample_quality(txs, start_block=18883124, contract_creation_block=18882800)

        assert result["possible_bootstrap_window"] is True
        assert result["low_tx_count"] is True
        assert result["narrow_function_diversity"] is True
        assert result["single_caller_dominant"] is True
        assert result["any_flag"] is True

    def test_warning_message_names_every_fired_reason(self):
        txs = [_tx("0xAdmin", "enableLltv")] * 12
        result = assess_sample_quality(txs, start_block=18883124, contract_creation_block=18882800)
        warning = format_sample_quality_warning(result)

        assert "bootstrap" in warning.lower() or "contract creation" in warning.lower()
        assert "12 tx" in warning
        assert "1 distinct method" in warning
        assert "0xadmin" in warning


class TestWellSampledRunShowsNoFlags:
    def test_no_flags_on_a_large_diverse_multi_caller_sample(self):
        txs = []
        callers = [f"0xUser{i}" for i in range(30)]
        methods = ["supply", "borrow", "withdraw", "repay", "liquidate"]
        for i in range(100):
            txs.append(_tx(callers[i % len(callers)], methods[i % len(methods)]))

        result = assess_sample_quality(txs, start_block=19_500_000, contract_creation_block=18_882_800)

        assert result["possible_bootstrap_window"] is False
        assert result["low_tx_count"] is False
        assert result["narrow_function_diversity"] is False
        assert result["single_caller_dominant"] is False
        assert result["any_flag"] is False


class TestIndependentFlags:
    def test_narrow_function_diversity_independent_of_low_tx_count(self):
        """Many transactions all calling the same one function is degenerate
        for a different reason than a small sample -- must be caught even
        with plenty of transactions and many distinct callers."""
        txs = [_tx(f"0xUser{i}", "deposit") for i in range(50)]
        result = assess_sample_quality(txs, start_block=100, contract_creation_block=None)

        assert result["low_tx_count"] is False
        assert result["single_caller_dominant"] is False
        assert result["narrow_function_diversity"] is True

    def test_single_caller_requires_minimum_sample_size(self):
        """A 1-2 tx sample is already caught by low_tx_count -- avoid a
        redundant/noisy single_caller_dominant flag on trivial samples."""
        txs = [_tx("0xSame"), _tx("0xSame")]
        result = assess_sample_quality(txs, start_block=100, contract_creation_block=None)
        assert result["single_caller_dominant"] is False
        assert result["low_tx_count"] is True

    def test_unknown_creation_block_yields_false_not_true(self):
        """Missing creation-block data must not be silently treated as
        confirmation of a bootstrap window -- it's genuinely unknown."""
        txs = [_tx(f"0xUser{i}", m) for i, m in enumerate(["a", "b", "c"] * 10)]
        result = assess_sample_quality(txs, start_block=100, contract_creation_block=None)
        assert result["possible_bootstrap_window"] is False
        assert result["contract_creation_block"] is None

    def test_bootstrap_window_only_fires_when_range_is_at_or_after_creation(self):
        """A range that starts *before* the contract even existed (negative
        blocks-since-creation) is not a bootstrap window -- it's nonsensical
        input, and shouldn't be conflated with the real signal."""
        txs = [_tx(f"0xUser{i}", m) for i, m in enumerate(["a", "b", "c"] * 10)]
        result = assess_sample_quality(txs, start_block=100, contract_creation_block=500)
        assert result["possible_bootstrap_window"] is False
        assert result["blocks_since_creation"] == -400

    def test_empty_tx_list_does_not_crash(self):
        result = assess_sample_quality([], start_block=100, contract_creation_block=None)
        assert result["tx_count"] == 0
        assert result["low_tx_count"] is True
        assert result["narrow_function_diversity"] is False
        assert result["single_caller_dominant"] is False
