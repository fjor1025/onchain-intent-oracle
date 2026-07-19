"""Invariant models."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from eth_typing import HexStr


class InvariantType(str, Enum):
    """Categories of invariants."""

    SAFETY = "safety"
    LIVENESS = "liveness"
    STATE = "state"
    ACCESS_CONTROL = "access_control"
    ECONOMIC = "economic"
    UPGRADE = "upgrade"
    OTHER = "other"


@dataclass
class Invariant:
    """A proposed invariant with confidence and evidence."""

    id: str
    expression: str
    type: InvariantType
    confidence: float  # 0.0 - 1.0
    hold_count: int = 0
    total_count: int = 0
    evidence: List[HexStr] = field(default_factory=list)
    verification_method: str = "statistical"  # statistical | symbolic | both
    fv_template_hint: Optional[str] = None
    notes: Optional[str] = None
    is_promoted: bool = False  # Promoted from statistical to formal
    counterexamples: List[HexStr] = field(default_factory=list)
