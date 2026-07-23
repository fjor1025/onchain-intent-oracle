"""Tests for AutoProverBundleGenerator -- the design-doc bundle shaped to
match AutoProver's own actual expected `system_doc` convention (verified
against AutoProver's source: composer/spec/context.py, cex_remediation.py,
its test_scenarios/*/system.md fixtures, and the design-doc-finder rubric)."""

from pathlib import Path

import pytest

from onchain_intent_oracle.output.autoprover_bundle import AutoProverBundleGenerator


def _base_data(**overrides):
    data = {
        "contract_address": "0xAbC0000000000000000000000000000000000",
        "contract_name": None,
        "chain_id": 1,
        "block_range": [100, 200],
        "tx_count": 5,
        "tx_count_direct": 5,
        "tx_count_internal_call": 0,
        "proxy_info": {"is_proxy": False, "implementation": None, "type": "DIRECT"},
        "contract_type": "unknown",
        "standards": [],
        "state_machine": {"states": [{"name": "initial", "description": "..."}], "transitions": []},
        "invariants": [],
        "evidence_txs": [],
        "conflicts": {"omissions": []},
    }
    data.update(overrides)
    return data


class TestAutoProverBundleGenerator:
    def test_generates_file(self, tmp_path):
        out = tmp_path / "autoprover_system_doc.md"
        result = AutoProverBundleGenerator().generate(_base_data(), out)
        assert result == out
        assert out.exists()

    def test_uses_real_contract_name_when_available(self, tmp_path):
        out = tmp_path / "doc.md"
        AutoProverBundleGenerator().generate(_base_data(contract_name="MyToken"), out)
        content = out.read_text()
        assert content.startswith("# MyToken")

    def test_falls_back_to_address_without_contract_name(self, tmp_path):
        out = tmp_path / "doc.md"
        data = _base_data(contract_address="0xDeadBeef")
        AutoProverBundleGenerator().generate(data, out)
        content = out.read_text()
        assert "Contract 0xDeadBeef" in content

    def test_standards_shown_in_title_when_present(self, tmp_path):
        out = tmp_path / "doc.md"
        data = _base_data(contract_name="USDC", standards=["ERC-20"])
        AutoProverBundleGenerator().generate(data, out)
        content = out.read_text()
        assert content.startswith("# USDC (ERC-20)")

    def test_no_requirements_message_when_no_invariants(self, tmp_path):
        out = tmp_path / "doc.md"
        AutoProverBundleGenerator().generate(_base_data(invariants=[]), out)
        content = out.read_text()
        assert "No statistical invariants were mined" in content

    def test_invariants_rendered_as_qualified_requirements(self, tmp_path):
        out = tmp_path / "doc.md"
        data = _base_data(invariants=[{
            "expression": "transfer() never reverts",
            "confidence": 0.9,
            "note": "Observed 10 calls, all succeeded",
        }])
        AutoProverBundleGenerator().generate(data, out)
        content = out.read_text()
        assert "transfer() never reverts" in content
        assert "0.90" in content
        # Must not be phrased as an unconditional guarantee -- always qualified.
        assert "not a formal guarantee" in content or "not proven" in content

    def test_direct_only_interactions(self, tmp_path):
        out = tmp_path / "doc.md"
        data = _base_data(tx_count_direct=5, tx_count_internal_call=0)
        AutoProverBundleGenerator().generate(data, out)
        content = out.read_text()
        assert "all directly against this contract's own address" in content

    def test_internal_call_interactions_attributed_to_entry_point(self, tmp_path):
        out = tmp_path / "doc.md"
        data = _base_data(
            tx_count_direct=1,
            tx_count_internal_call=3,
            evidence_txs=[
                {"hash": "0x1", "discovered_via": "internal_call", "entry_point": "0xRelayer1", "description": "swap"},
                {"hash": "0x2", "discovered_via": "internal_call", "entry_point": "0xRelayer1", "description": "swap"},
                {"hash": "0x3", "discovered_via": "internal_call", "entry_point": "0xRelayer2", "description": "swap"},
            ],
        )
        AutoProverBundleGenerator().generate(data, out)
        content = out.read_text()
        assert "0xRelayer1" in content
        assert "0xRelayer2" in content
        assert "2 call(s)" in content  # Relayer1 appears twice

    def test_entry_points_only_lists_observed_methods(self, tmp_path):
        out = tmp_path / "doc.md"
        data = _base_data(evidence_txs=[
            {"hash": "0x1", "description": "mint", "discovered_via": "direct"},
            {"hash": "0x2", "description": "unknown", "discovered_via": "direct"},
        ])
        AutoProverBundleGenerator().generate(data, out)
        content = out.read_text()
        assert "`mint()`" in content
        assert "`unknown()`" not in content  # "unknown" is not a real method name

    def test_state_section_honest_when_no_evidenced_transitions(self, tmp_path):
        out = tmp_path / "doc.md"
        AutoProverBundleGenerator().generate(_base_data(), out)
        content = out.read_text()
        assert "does not mean the contract is stateless" in content

    def test_proxy_note_included_when_proxy(self, tmp_path):
        out = tmp_path / "doc.md"
        data = _base_data(proxy_info={
            "is_proxy": True, "type": "OPEN_ZEPPELIN", "implementation": "0xImpl123",
        })
        AutoProverBundleGenerator().generate(data, out)
        content = out.read_text()
        assert "OPEN_ZEPPELIN" in content
        assert "0xImpl123" in content

    def test_cross_check_framing_always_present(self, tmp_path):
        """The doc must always frame itself as a cross-check, not a
        replacement -- this is the whole point of the tool."""
        out = tmp_path / "doc.md"
        AutoProverBundleGenerator().generate(_base_data(), out)
        content = out.read_text()
        assert "cross-check against reality" in content
        assert "not a replacement for a hand-written design doc" in content

    def test_omissions_note_included_when_present(self, tmp_path):
        out = tmp_path / "doc.md"
        data = _base_data(conflicts={"omissions": [{"function": "mint"}, {"function": "burn"}]})
        AutoProverBundleGenerator().generate(data, out)
        content = out.read_text()
        assert "2 observed function(s)" in content

    def test_creates_parent_directories(self, tmp_path):
        out = tmp_path / "nested" / "dir" / "doc.md"
        AutoProverBundleGenerator().generate(_base_data(), out)
        assert out.exists()
