"""LangGraph workflow definition for the agent pipeline."""

from typing import Any, Optional

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from onchain_intent_oracle.agents.state import AgentState
from onchain_intent_oracle.agents.nodes.data_collector import data_collector_node
from onchain_intent_oracle.agents.nodes.state_inference import state_inference_node
from onchain_intent_oracle.agents.nodes.invariant_proposer import invariant_proposer_node
from onchain_intent_oracle.agents.nodes.conflict_reconciler import conflict_reconciler_node
from onchain_intent_oracle.agents.nodes.summarizer import summarizer_node
from onchain_intent_oracle.agents.nodes.property_generator import property_generator_node
from onchain_intent_oracle.config.settings import get_settings


def build_workflow(checkpointer: Optional[Any] = None) -> Any:
    """Build the LangGraph workflow with all agent nodes."""

    settings = get_settings()

    # Initialize LLM if API key available
    llm = None
    if settings.anthropic_api_key:
        try:
            from langchain_anthropic import ChatAnthropic
            llm = ChatAnthropic(
                model=settings.llm_model,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
                api_key=settings.anthropic_api_key,
            )
        except ImportError:
            pass

    # Create graph
    workflow = StateGraph(AgentState)

    # Add nodes with LLM injection
    workflow.add_node("data_collector", lambda state: data_collector_node(state, llm))
    workflow.add_node("state_inference", lambda state: state_inference_node(state, llm))
    workflow.add_node("invariant_proposer", lambda state: invariant_proposer_node(state, llm))
    workflow.add_node("conflict_reconciler", lambda state: conflict_reconciler_node(state, llm))
    workflow.add_node("summarizer", lambda state: summarizer_node(state, llm))
    workflow.add_node("property_generator", lambda state: property_generator_node(state, llm))

    # Define edges
    workflow.set_entry_point("data_collector")
    workflow.add_edge("data_collector", "state_inference")
    workflow.add_edge("state_inference", "invariant_proposer")
    workflow.add_edge("invariant_proposer", "conflict_reconciler")
    workflow.add_edge("conflict_reconciler", "summarizer")
    workflow.add_edge("summarizer", "property_generator")
    workflow.add_edge("property_generator", END)

    # Compile with checkpointing
    if checkpointer is None:
        checkpointer = MemorySaver()

    return workflow.compile(checkpointer=checkpointer)
