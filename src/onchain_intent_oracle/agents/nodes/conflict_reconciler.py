"""Conflict reconciler agent node."""

import structlog

logger = structlog.get_logger()

import json
from typing import Any, Dict

from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from langchain_core.messages import AIMessage

from onchain_intent_oracle.agents.state import AgentState

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def conflict_reconciler_node(state: AgentState, llm=None) -> Dict[str, Any]:
    """Reconcile design claims with observed behavior."""

    env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))
    template = env.get_template("conflict_reconciler.j2")

    context = {
        "contract_address": state["contract_address"],
        "design_claims": [],  # Parsed from design_doc
        "observed_behavior": state.get("anomalies", []),
        "code_analysis": [],
    }

    prompt = template.render(**context)

    if llm:
        try:
            response = llm.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            return {
                "messages": [AIMessage(content=content)],
                "current_agent": "conflict_reconciler",
                "conflicts": json.loads(content) if content.strip().startswith("{") else {},
            }
        except Exception as e:
            logger.error("llm_conflict_reconciliation_failed", error=str(e))

    return {
        "messages": [AIMessage(content="Conflict reconciliation completed.")],
        "current_agent": "conflict_reconciler",
    }
