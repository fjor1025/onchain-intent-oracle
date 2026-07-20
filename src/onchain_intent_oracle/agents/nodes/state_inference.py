"""State inference agent node."""

import structlog

logger = structlog.get_logger()

import json
from typing import Any, Dict

from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from langchain_core.messages import AIMessage

from onchain_intent_oracle.agents.state import AgentState

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def state_inference_node(state: AgentState, llm=None) -> Dict[str, Any]:
    """Infer state machine from collected data."""

    env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))
    template = env.get_template("state_inference.j2")

    sm = state.get("state_machine", {})

    context = {
        "contract_address": state["contract_address"],
        "contract_type": "unknown",  # Would come from data collector
        "state_variables": [],  # Would be populated from analysis
        "transitions": sm.get("transitions", []),
        "storage_patterns": [],
    }

    prompt = template.render(**context)

    if llm:
        try:
            response = llm.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            return {
                "messages": [AIMessage(content=content)],
                "current_agent": "state_inference",
                "state_machine": json.loads(content) if content.strip().startswith("{") else sm,
            }
        except Exception as e:
            logger.error("llm_state_inference_failed", error=str(e))

    return {
        "messages": [AIMessage(content="State inference completed.")],
        "current_agent": "state_inference",
    }
