"""Transaction and trace models."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from eth_typing import ChecksumAddress, HexStr


@dataclass
class StateDiff:
    """A single storage slot change."""

    slot: HexStr
    old_value: Optional[HexStr] = None
    new_value: Optional[HexStr] = None
    address: Optional[ChecksumAddress] = None


@dataclass
class CallTrace:
    """A single call frame from debug_traceTransaction."""

    type: str  # CALL, DELEGATECALL, STATICCALL, CREATE
    from_address: ChecksumAddress
    to_address: Optional[ChecksumAddress]
    value: Decimal = Decimal("0")
    gas: int = 0
    gas_used: int = 0
    input: HexStr = "0x"
    output: HexStr = "0x"
    error: Optional[str] = None
    calls: List["CallTrace"] = field(default_factory=list)
    state_diffs: List[StateDiff] = field(default_factory=list)


@dataclass
class Transaction:
    """A complete on-chain transaction with decoded data."""

    hash: HexStr
    block_number: int
    timestamp: datetime
    from_address: ChecksumAddress
    to_address: Optional[ChecksumAddress]
    value: Decimal
    gas_price: Optional[Decimal] = None
    gas_used: Optional[int] = None
    status: Optional[int] = None  # 1 = success, 0 = failure
    input: HexStr = "0x"
    decoded_input: Optional[Dict[str, Any]] = None
    decoded_events: List[Dict[str, Any]] = field(default_factory=list)
    trace: Optional[CallTrace] = None
    state_diffs: List[StateDiff] = field(default_factory=list)
    logs: List[Dict[str, Any]] = field(default_factory=list)

    # Analysis metadata
    method_signature: Optional[str] = None  # e.g., "transfer(address,uint256)"
    method_name: Optional[str] = None
    is_proxy_call: bool = False
    implementation_address: Optional[ChecksumAddress] = None
