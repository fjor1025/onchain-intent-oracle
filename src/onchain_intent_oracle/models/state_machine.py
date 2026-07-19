"""State machine models."""
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class State:
    name: str
    description: str = ""
    is_implicit: bool = False
    storage_fingerprint: Optional[str] = None

@dataclass
class Transition:
    from_state: str
    to_state: str
    trigger: str
    guard: Optional[str] = None
    confidence: float = 1.0
    evidence_txs: List[str] = field(default_factory=list)

@dataclass
class StateMachine:
    states: List[State] = field(default_factory=list)
    transitions: List[Transition] = field(default_factory=list)

    def add_state(self, name, **kwargs):
        s = State(name=name, **kwargs)
        self.states.append(s)
        return s

    def add_transition(self, from_state, to_state, trigger, **kwargs):
        t = Transition(from_state=from_state, to_state=to_state, trigger=trigger, **kwargs)
        self.transitions.append(t)
        return t
