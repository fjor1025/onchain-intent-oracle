"""Property candidate generator agent node."""

import json
from typing import Any, Dict

from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from langchain_core.messages import AIMessage

from onchain_intent_oracle.agents.state import AgentState

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def property_generator_node(state: AgentState, llm=None) -> Dict[str, Any]:
    """Generate structured property candidates from inferred invariants."""

    env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))
    template = env.get_template("property_generator.j2")

    context = {
        "contract_address": state["contract_address"],
        "contract_type": "unknown",
        "invariants": state.get("invariants", []),
        "state_machine_json": json.dumps(state.get("state_machine", {})),
        "high_priority_conflicts": [
            c for c in state.get("conflicts", {}).get("conflicts", [])
            if c.get("severity") in ["critical", "high"]
        ],
        "fv_patterns": [],  # Would come from RAG
    }

    prompt = template.render(**context)

    if llm:
        try:
            response = llm.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            return {
                "messages": [AIMessage(content=content)],
                "current_agent": "property_generator",
            }
        except Exception:
            pass

    # Fallback: generate basic property candidates
    candidates = []
    for i, inv in enumerate(state.get("invariants", [])):
        if inv.get("confidence", 0) >= 0.8:
            candidates.append({
                "id": inv.get("id", f"PROP-{i}"),
                "expression": inv.get("expression", ""),
                "type": inv.get("type", "safety"),
                "confidence": inv.get("confidence", 0),
                "evidence": inv.get("evidence", [])[:3],
                "verification_approach": "formal_proof",
                "suggested_tool": "Certora",
                "notes": "Statistical invariant with high confidence",
            })

    return {
        "messages": [AIMessage(content=json.dumps(candidates, indent=2))],
        "current_agent": "property_generator",
    }
