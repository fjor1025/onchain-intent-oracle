"""Shared state for LangGraph agent workflow."""

from typing import Annotated, Any, Dict, List, Optional

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """Shared state across all agent nodes."""

    # Input
    contract_address: str
    chain_id: int
    block_range: tuple[int, int]
    design_doc: Optional[str]
    threat_model: Optional[str]
    source_code: Optional[str]
    abi: Optional[list]

    # Data collection
    transactions: List[Dict]
    traces: List[Dict]
    logs: List[Dict]
    proxy_info: Optional[Dict]

    # Analysis
    state_machine: Optional[Dict]
    invariants: List[Dict]
    patterns: Optional[Dict]
    anomalies: List[Dict]
    conflicts: Optional[Dict]

    # Agent outputs
    messages: Annotated[list, add_messages]
    current_agent: str
    checkpoint_path: Optional[str]

    # Final output
    observed_design_md: Optional[str]
    observed_design_json: Optional[Dict]
    property_candidates: Optional[str]
    conflict_report: Optional[str]
    visualizations: List[str]
