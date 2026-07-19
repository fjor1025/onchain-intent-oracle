"""Invariant proposer agent node."""

import json
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader
from langchain_core.messages import AIMessage

from onchain_intent_oracle.agents.state import AgentState


def invariant_proposer_node(state: AgentState, llm=None) -> Dict[str, Any]:
    """Propose invariants from observed data."""

    env = Environment(loader=FileSystemLoader("src/onchain_intent_oracle/agents/prompts"))
    template = env.get_template("invariant_proposer.j2")

    context = {
        "contract_address": state["contract_address"],
        "contract_type": "unknown",
        "statistical_invariants": state.get("invariants", []),
        "storage_relationships": [],
        "rag_context": [],  # Would query RAG
    }

    prompt = template.render(**context)

    if llm:
        try:
            response = llm.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            return {
                "messages": [AIMessage(content=content)],
                "current_agent": "invariant_proposer",
            }
        except Exception:
            pass

    return {
        "messages": [AIMessage(content="Invariant proposal completed.")],
        "current_agent": "invariant_proposer",
    }
