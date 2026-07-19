"""Data collection agent node."""

import json
from typing import Any, Dict

import structlog
from jinja2 import Environment, FileSystemLoader
from langchain_core.messages import AIMessage

from onchain_intent_oracle.agents.state import AgentState
from onchain_intent_oracle.config.settings import get_settings

logger = structlog.get_logger()


def data_collector_node(state: AgentState, llm=None) -> Dict[str, Any]:
    """Collect and summarize on-chain data."""

    # Load prompt template
    env = Environment(loader=FileSystemLoader("src/onchain_intent_oracle/agents/prompts"))
    template = env.get_template("data_collector.j2")

    # Prepare context
    txs = state.get("transactions", [])

    # Extract basic stats
    unique_callers = len(set(t.get("from") for t in txs if t.get("from")))
    method_counts = {}
    for t in txs:
        method = t.get("method_name", "unknown")
        method_counts[method] = method_counts.get(method, 0) + 1
    top_functions = sorted(method_counts, key=method_counts.get, reverse=True)[:10]

    event_sigs = set()
    for t in txs:
        for log in t.get("logs", []):
            if log.get("topic0"):
                event_sigs.add(log["topic0"][:10])

    context = {
        "contract_address": state["contract_address"],
        "chain_id": state["chain_id"],
        "tx_count": len(txs),
        "unique_callers": unique_callers,
        "top_functions": top_functions,
        "event_signatures": list(event_sigs)[:10],
        "is_proxy": state.get("proxy_info", {}).get("is_proxy", False),
        "implementation": state.get("proxy_info", {}).get("implementation"),
    }

    prompt = template.render(**context)

    # Call LLM if available
    if llm:
        try:
            response = llm.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)

            # Try to parse JSON from response
            try:
                parsed = json.loads(content)
                return {
                    "messages": [AIMessage(content=content)],
                    "current_agent": "data_collector",
                }
            except json.JSONDecodeError:
                return {
                    "messages": [AIMessage(content=content)],
                    "current_agent": "data_collector",
                }
        except Exception as e:
            logger.error("llm_data_collection_failed", error=str(e))

    # Fallback: deterministic analysis
    return {
        "messages": [AIMessage(content=json.dumps({
            "contract_type": "unknown",
            "tx_count": len(txs),
            "priority_txs": [],
            "anomalies": [],
        }))],
        "current_agent": "data_collector",
    }
