"""Summarizer agent node - generates observed_design.md."""

import json
from pathlib import Path
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader
from langchain_core.messages import AIMessage

from onchain_intent_oracle.agents.state import AgentState

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def summarizer_node(state: AgentState, llm=None) -> Dict[str, Any]:
    """Generate final design document from all analysis."""

    env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))
    template = env.get_template("summarizer.j2")

    context = {
        "contract_address": state["contract_address"],
        "chain_id": state["chain_id"],
        "block_range": state.get("block_range", (0, 0)),
        "state_machine_json": json.dumps(state.get("state_machine", {})),
        "invariants": state.get("invariants", []),
        "common_patterns": [],
        "rare_patterns": [],
        "anomaly_count": len(state.get("anomalies", [])),
        "conflicts": state.get("conflicts", {}).get("conflicts", []),
    }

    prompt = template.render(**context)

    if llm:
        try:
            response = llm.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            return {
                "messages": [AIMessage(content=content)],
                "current_agent": "summarizer",
                "observed_design_md": content,
            }
        except Exception:
            pass

    # Fallback: generate basic markdown directly in Python. (Note: this used to be
    # written as an f-string containing literal Jinja2 `{% %}`/`{{ }}` syntax, which
    # is not valid Python and raised a SyntaxError on import -- taking down this
    # entire module, and with it the whole `agents` package, the moment anything
    # tried to import it.)
    block_range = state.get("block_range", (0, 0))
    invariant_lines = "\n".join(
        f"- **{inv.get('id', 'unknown')}**: {inv.get('expression', '')} "
        f"(confidence: {inv.get('confidence', 0)})"
        for inv in state.get("invariants", [])
    ) or "_None observed._"

    md = f"""# Observed Design: {state['contract_address']}

## Overview
Contract on chain {state['chain_id']} analyzed from block {block_range[0]} to {block_range[1]}.

## State Machine
```json
{json.dumps(state.get('state_machine', {}), indent=2)}
```

## Invariants
{invariant_lines}

## Anomalies
{len(state.get('anomalies', []))} anomalies detected.

## Conflicts
{len(state.get('conflicts', {}).get('conflicts', []))} conflicts with provided design.
"""

    return {
        "messages": [AIMessage(content="Design document generated.")],
        "current_agent": "summarizer",
        "observed_design_md": md,
    }
