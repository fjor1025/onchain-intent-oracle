"""Evidence linking claims to on-chain data."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from eth_typing import HexStr


class EvidenceType(str, Enum):
    """Types of evidence."""

    TRANSACTION = "transaction"
    TRACE = "trace"
    STATE_DIFF = "state_diff"
    EVENT_LOG = "event_log"
    CODE_REFERENCE = "code_reference"
    DESIGN_DOC = "design_doc"


@dataclass
class Evidence:
    """A piece of evidence linking a claim to on-chain reality."""

    type: EvidenceType
    tx_hash: Optional[HexStr] = None
    block_number: Optional[int] = None
    description: str = ""
    raw_data: Optional[Dict[str, Any]] = None
    url: Optional[str] = None  # Etherscan link
