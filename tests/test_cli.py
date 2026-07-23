"""Tests for cli.py's log-ingestion wiring (Fix 1: RPCManager.get_logs() was
fully implemented but never called anywhere in the pipeline before this).
"""

import pytest
from eth_abi import encode
from eth_utils import keccak

from onchain_intent_oracle.cli import fetch_and_decode_logs, summarize_decoded_logs
from onchain_intent_oracle.ingestion.log_decoder import LogDecoder


def _topic0(sig: str) -> str:
    return "0x" + keccak(text=sig).hex()


def _addr_topic(addr_hex: str) -> str:
    return "0x" + "00" * 12 + addr_hex.replace("0x", "")


class TestFetchAndDecodeLogs:
    """Confirms get_logs -- previously implemented but dead code, never
    called from anywhere -- is now actually invoked and its results decoded
    and correlated back to the owning transaction."""

    @pytest.mark.asyncio
    async def test_get_logs_is_actually_called(self, mock_rpc_manager):
        mock_rpc_manager.get_logs.return_value = []

        raw_by_tx, decoded_by_tx = await fetch_and_decode_logs(
            mock_rpc_manager, "0xContract", 100, 200, LogDecoder()
        )

        mock_rpc_manager.get_logs.assert_awaited_once()
        args, kwargs = mock_rpc_manager.get_logs.await_args
        assert 100 in args and 200 in args
        assert raw_by_tx == {}
        assert decoded_by_tx == {}

    @pytest.mark.asyncio
    async def test_decoded_logs_are_correlated_to_their_transaction(self, mock_rpc_manager):
        from_addr = "0x1111111111111111111111111111111111111111"
        to_addr = "0x2222222222222222222222222222222222222222"
        raw_log = {
            "address": "0xContract",
            "transactionHash": "0xtx1",
            "logIndex": "0x0",
            "blockNumber": "0x64",
            "topics": [
                _topic0("Transfer(address,address,uint256)"),
                _addr_topic(from_addr),
                _addr_topic(to_addr),
            ],
            "data": "0x" + encode(["uint256"], [42]).hex(),
        }
        mock_rpc_manager.get_logs.return_value = [raw_log]

        raw_by_tx, decoded_by_tx = await fetch_and_decode_logs(
            mock_rpc_manager, "0xContract", 100, 200, LogDecoder()
        )

        assert raw_by_tx["0xtx1"] == [raw_log]
        assert decoded_by_tx["0xtx1"][0]["event_name"] == "Transfer"
        assert decoded_by_tx["0xtx1"][0]["args"]["value"] == 42
        assert decoded_by_tx["0xtx1"][0]["confidence"] == "builtin_table"

    @pytest.mark.asyncio
    async def test_get_logs_failure_degrades_gracefully(self, mock_rpc_manager):
        """A provider that can't serve eth_getLogs at all must not crash the
        whole analysis -- degrade to empty evidence, same philosophy as the
        rest of the pipeline's best-effort enrichment."""
        mock_rpc_manager.get_logs.side_effect = Exception("boom")

        raw_by_tx, decoded_by_tx = await fetch_and_decode_logs(
            mock_rpc_manager, "0xContract", 100, 200, LogDecoder()
        )
        assert raw_by_tx == {}
        assert decoded_by_tx == {}


class TestSummarizeDecodedCalls:
    def test_unresolved_and_decode_error_counts_are_both_visible(self):
        from onchain_intent_oracle.cli import summarize_decoded_calls

        txs = [
            {"decoded_args": {"method_name": "transfer", "confidence": "verified_abi", "args": {"to": "0x1"}, "decode_error": None}},
            {"decoded_args": {"method_name": "unknown", "confidence": "unresolved", "args": {}, "decode_error": None}},
            {"decoded_args": {"method_name": "borrow", "confidence": "verified_abi", "args": {}, "decode_error": "malformed"}},
        ]
        summary = summarize_decoded_calls(txs)
        assert summary["total_calls"] == 3
        assert summary["unresolved_count"] == 1
        assert summary["arg_decode_error_count"] == 1
        assert summary["by_confidence"]["verified_abi"] == 2


class TestComputeTraceCoverage:
    """Confirms the depth_quick / provider_unsupported / not_attempted /
    None (genuine success) distinction -- see cli.py's compute_trace_coverage
    docstring for why conflating these was the bug this fix exists for."""

    def test_depth_quick_is_never_attempted(self):
        from onchain_intent_oracle.cli import compute_trace_coverage

        coverage = compute_trace_coverage("quick", enrich_result=None)
        assert coverage == {"attempted": False, "succeeded_count": 0, "failed_count": 0, "reason": "depth_quick"}

    def test_every_attempt_failing_is_provider_unsupported(self):
        from onchain_intent_oracle.cli import compute_trace_coverage

        coverage = compute_trace_coverage("standard", {"attempted": True, "succeeded_count": 0, "failed_count": 12})
        assert coverage["attempted"] is True
        assert coverage["reason"] == "provider_unsupported"

    def test_some_successes_needs_no_explanation(self):
        from onchain_intent_oracle.cli import compute_trace_coverage

        coverage = compute_trace_coverage("standard", {"attempted": True, "succeeded_count": 8, "failed_count": 4})
        assert coverage["reason"] is None
        assert coverage["succeeded_count"] == 8
        assert coverage["failed_count"] == 4

    def test_nothing_to_attempt_is_not_attempted(self):
        """An empty tx list -- attempted=True but zero of everything -- is a
        distinct case from provider failure; nothing was actually tried."""
        from onchain_intent_oracle.cli import compute_trace_coverage

        coverage = compute_trace_coverage("standard", {"attempted": True, "succeeded_count": 0, "failed_count": 0})
        assert coverage["reason"] == "not_attempted"

    def test_missing_enrich_result_at_non_quick_depth_still_degrades_safely(self):
        from onchain_intent_oracle.cli import compute_trace_coverage

        coverage = compute_trace_coverage("standard", None)
        assert coverage["attempted"] is False
        assert coverage["reason"] == "depth_quick"


class TestEnrichTransactionsCoverageTracking:
    @pytest.mark.asyncio
    async def test_returns_succeeded_and_failed_counts(self, mocker, mock_rpc_manager):
        from onchain_intent_oracle.cli import enrich_transactions

        trace_fetcher = mocker.AsyncMock()
        # First tx: trace succeeds. Second tx: provider returns nothing.
        trace_fetcher.fetch_trace.side_effect = [{"output": "0x01"}, None]
        trace_fetcher.fetch_state_diff.return_value = []

        txs = [{"hash": "0x1"}, {"hash": "0x2"}]
        result = await enrich_transactions(mock_rpc_manager, trace_fetcher, txs, chain_id=1)

        assert result == {"attempted": True, "succeeded_count": 1, "failed_count": 1}
        assert "traces" in txs[0]
        assert "traces" not in txs[1]

    @pytest.mark.asyncio
    async def test_quick_depth_reports_not_attempted(self, mocker, mock_rpc_manager):
        from onchain_intent_oracle.cli import enrich_transactions

        trace_fetcher = mocker.AsyncMock()
        txs = [{"hash": "0x1"}]
        result = await enrich_transactions(mock_rpc_manager, trace_fetcher, txs, chain_id=1, fetch_traces=False)

        assert result == {"attempted": False, "succeeded_count": 0, "failed_count": 0}
        trace_fetcher.fetch_trace.assert_not_called()


class TestGetContractCreationBlock:
    """Confirms SourceResolver.get_contract_creation() -- previously
    implemented but, like get_logs before Fix 1, never called anywhere --
    is now actually used, feeding the Fix 4 bootstrap-window check."""

    @pytest.mark.asyncio
    async def test_uses_block_number_directly_when_present(self, mocker, mock_rpc_manager):
        from onchain_intent_oracle.cli import _get_contract_creation_block

        source_resolver = mocker.AsyncMock()
        source_resolver.get_contract_creation.return_value = {"blockNumber": "12345", "txHash": "0xabc"}

        block = await _get_contract_creation_block(source_resolver, mock_rpc_manager, "0xContract", 1)
        assert block == 12345
        mock_rpc_manager.get_transaction_receipt.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_receipt_lookup_when_no_block_number(self, mocker, mock_rpc_manager):
        from onchain_intent_oracle.cli import _get_contract_creation_block

        source_resolver = mocker.AsyncMock()
        source_resolver.get_contract_creation.return_value = {"txHash": "0xabc"}
        mock_rpc_manager.get_transaction_receipt.return_value = {"blockNumber": "0x64"}

        block = await _get_contract_creation_block(source_resolver, mock_rpc_manager, "0xContract", 1)
        assert block == 100
        mock_rpc_manager.get_transaction_receipt.assert_awaited_once_with("0xabc")

    @pytest.mark.asyncio
    async def test_returns_none_when_creation_lookup_fails(self, mocker, mock_rpc_manager):
        """No explorer API key / unverified contract / rate-limited -- must
        degrade to None (unknown), never raise and never silently guess."""
        from onchain_intent_oracle.cli import _get_contract_creation_block

        source_resolver = mocker.AsyncMock()
        source_resolver.get_contract_creation.return_value = None

        block = await _get_contract_creation_block(source_resolver, mock_rpc_manager, "0xContract", 1)
        assert block is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception_rather_than_raising(self, mocker, mock_rpc_manager):
        from onchain_intent_oracle.cli import _get_contract_creation_block

        source_resolver = mocker.AsyncMock()
        source_resolver.get_contract_creation.side_effect = Exception("rate limited")

        block = await _get_contract_creation_block(source_resolver, mock_rpc_manager, "0xContract", 1)
        assert block is None


class TestSummarizeDecodedLogs:
    def test_unresolved_count_is_never_silently_dropped(self):
        """See models/log.py: an unresolved log is evidence *something*
        happened, not evidence of nothing -- the summary must always surface
        how many logs are still unresolved, not just how many resolved."""
        txs = [
            {"decoded_logs": [
                {"event_name": "Transfer", "confidence": "builtin_table", "decode_error": None},
                {"event_name": None, "confidence": "unresolved"},
            ]},
            {"decoded_logs": [
                {"event_name": None, "confidence": "unresolved"},
            ]},
        ]
        summary = summarize_decoded_logs(txs)
        assert summary["total_logs"] == 3
        assert summary["unresolved_count"] == 2
        assert summary["by_event_name"] == {"Transfer": 1}


class TestComputePerEntityResults:
    """End-to-end coverage of Fix 3's core acceptance criterion: a
    multi-market contract must produce a *separate* state machine per
    market, not one blended chain -- exercised here via bucket_by_entity +
    compute_per_entity_results together, the same path _run_analysis uses."""

    def test_separate_state_machine_per_entity(self):
        from onchain_intent_oracle.analysis.entity_key import bucket_by_entity
        from onchain_intent_oracle.cli import compute_per_entity_results

        market_a = "0x" + "aa" * 32
        market_b = "0x" + "bb" * 32

        def _supply_tx(h, market_id, amount):
            return {
                "hash": h, "decoded_args": {"method_name": "supply", "args": {}, "arg_types": {}, "confidence": "verified_abi", "decode_error": None, "struct_hash": None},
                "decoded_logs": [{
                    "event_name": "Supply", "confidence": "verified_abi", "decode_error": None,
                    "args": {"id": market_id, "assets": amount}, "arg_types": {"id": "bytes32", "assets": "uint256"},
                    "indexed_hash_only": [],
                }],
            }

        def _borrow_tx(h, market_id, amount):
            return {
                "hash": h, "decoded_args": {"method_name": "borrow", "args": {}, "arg_types": {}, "confidence": "verified_abi", "decode_error": None, "struct_hash": None},
                "decoded_logs": [{
                    "event_name": "Borrow", "confidence": "verified_abi", "decode_error": None,
                    "args": {"id": market_id, "assets": amount}, "arg_types": {"id": "bytes32", "assets": "uint256"},
                    "indexed_hash_only": [],
                }],
            }

        txs = [
            _supply_tx("0x1", market_a, 100),
            _borrow_tx("0x2", market_a, 50),
            _supply_tx("0x3", market_b, 200),
        ]

        buckets, source = bucket_by_entity(txs)
        assert source == "heuristic"
        entity_keys = [k for k in buckets if k is not None]
        assert set(entity_keys) == {market_a, market_b}

        per_entity = compute_per_entity_results(buckets, entity_keys, sig_decoder=None, contract_address="0xContract", contract="0xContract")

        assert len(per_entity) == 2
        # Ranked by tx count -- market_a (2 txs) before market_b (1 tx).
        assert per_entity[0]["entity_key"] == market_a
        assert per_entity[0]["tx_count"] == 2
        assert per_entity[1]["entity_key"] == market_b
        assert per_entity[1]["tx_count"] == 1

        # Market A saw two distinct event types (Supply, Borrow) -- its own
        # state machine should reflect that, independent of market B.
        market_a_states = per_entity[0]["state_machine"]["states"]
        market_b_states = per_entity[1]["state_machine"]["states"]
        assert len(market_a_states) >= 1
        assert len(market_b_states) >= 1

    def test_flat_contract_produces_no_per_entity_results(self):
        """Regression guard: a flat contract's txs all land in the None
        bucket, so entity_keys is empty and no per-entity computation runs
        at all -- matches _run_analysis's `if entity_keys:` gate exactly."""
        from onchain_intent_oracle.analysis.entity_key import bucket_by_entity
        from onchain_intent_oracle.cli import compute_per_entity_results

        txs = [
            {"hash": "0x1", "decoded_args": {"method_name": "transfer", "args": {"to": "0xU", "amount": 1}, "arg_types": {"to": "address", "amount": "uint256"}, "confidence": "verified_abi", "decode_error": None, "struct_hash": None}, "decoded_logs": []},
        ]
        buckets, source = bucket_by_entity(txs)
        entity_keys = [k for k in buckets if k is not None]
        assert entity_keys == []
        assert compute_per_entity_results(buckets, entity_keys, sig_decoder=None, contract_address="0xC", contract="0xC") == []
