"""Summarizer agent node - generates observed_design.md."""

from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader
from langchain_core.messages import AIMessage

from onchain_intent_oracle.agents.state import AgentState


def summarizer_node(state: AgentState, llm=None) -> Dict[str, Any]:
    """Generate final design document from all analysis."""

    env = Environment(loader=FileSystemLoader("src/onchain_intent_oracle/agents/prompts"))
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

    # Fallback: generate basic markdown
    md = f"""# Observed Design: {state['contract_address']}

## Overview
Contract on chain {state['chain_id']} analyzed from block {state.get('block_range', (0,0))[0]} to {state.get('block_range', (0,0))[1]}.

## State Machine
```json
{json.dumps(state.get('state_machine', {}), indent=2)}
```

## Invariants
{% for inv in state.get('invariants', []) %}
- **{{ inv.get('id', 'unknown') }}**: {{ inv.get('expression', '') }} (confidence: {{ inv.get('confidence', 0) }})
{% endfor %}

## Anomalies
{{ len(state.get('anomalies', [])) }} anomalies detected.

## Conflicts
{{ len(state.get('conflicts', {}).get('conflicts', [])) }} conflicts with provided design.
"""

    return {
        "messages": [AIMessage(content="Design document generated.")],
        "current_agent": "summarizer",
        "observed_design_md": md,
    }
