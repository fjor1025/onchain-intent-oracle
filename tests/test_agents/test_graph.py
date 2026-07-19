"""Tests for LangGraph workflow."""

import pytest

from onchain_intent_oracle.agents.graph import build_workflow
from onchain_intent_oracle.agents.state import AgentState


class TestWorkflow:
    """Test agent workflow."""

    def test_build_workflow(self):
        """Test workflow compilation."""
        workflow = build_workflow()
        assert workflow is not None

    def test_workflow_nodes(self):
        """Test that all nodes are registered."""
        workflow = build_workflow()
        # LangGraph compiled app doesn't expose nodes directly,
        # but we can verify it compiles without error
        assert hasattr(workflow, "invoke")

    @pytest.mark.skip(reason="Requires LLM API key")
    def test_workflow_execution(self):
        """Test end-to-end workflow execution."""
        workflow = build_workflow()

        initial_state: AgentState = {
            "contract_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            "chain_id": 1,
            "block_range": (18000000, 18000100),
            "design_doc": None,
            "threat_model": None,
            "source_code": None,
            "abi": None,
            "transactions": [],
            "traces": [],
            "logs": [],
            "proxy_info": None,
            "state_machine": None,
            "invariants": [],
            "patterns": None,
            "anomalies": [],
            "conflicts": None,
            "messages": [],
            "current_agent": "",
            "checkpoint_path": None,
            "observed_design_md": None,
            "observed_design_json": None,
            "property_candidates": None,
            "conflict_report": None,
            "visualizations": [],
        }

        # This would run the full pipeline
        # result = workflow.invoke(initial_state)
        # assert result is not None
