"""pytest configuration and fixtures."""

import json
import os
from pathlib import Path

import pytest

# Test data directory
TEST_DATA_DIR = Path(__file__).parent / "test_data"


@pytest.fixture
def sample_usdc_abi():
    """Load USDC ABI fixture."""
    path = TEST_DATA_DIR / "usdc_abi.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    # Minimal ERC20 ABI fallback
    return [
        {"type": "function", "name": "transfer", "inputs": [{"type": "address"}, {"type": "uint256"}], "outputs": [{"type": "bool"}], "stateMutability": "nonpayable"},
        {"type": "function", "name": "balanceOf", "inputs": [{"type": "address"}], "outputs": [{"type": "uint256"}], "stateMutability": "view"},
        {"type": "function", "name": "totalSupply", "inputs": [], "outputs": [{"type": "uint256"}], "stateMutability": "view"},
        {"type": "function", "name": "approve", "inputs": [{"type": "address"}, {"type": "uint256"}], "outputs": [{"type": "bool"}], "stateMutability": "nonpayable"},
        {"type": "function", "name": "transferFrom", "inputs": [{"type": "address"}, {"type": "address"}, {"type": "uint256"}], "outputs": [{"type": "bool"}], "stateMutability": "nonpayable"},
        {"type": "function", "name": "mint", "inputs": [{"type": "address"}, {"type": "uint256"}], "outputs": [], "stateMutability": "nonpayable"},
        {"type": "function", "name": "burn", "inputs": [{"type": "uint256"}], "outputs": [], "stateMutability": "nonpayable"},
        {"type": "function", "name": "pause", "inputs": [], "outputs": [], "stateMutability": "nonpayable"},
        {"type": "function", "name": "unpause", "inputs": [], "outputs": [], "stateMutability": "nonpayable"},
        {"type": "function", "name": "blacklist", "inputs": [{"type": "address"}], "outputs": [], "stateMutability": "nonpayable"},
        {"type": "event", "name": "Transfer", "inputs": [{"indexed": True, "type": "address"}, {"indexed": True, "type": "address"}, {"type": "uint256"}]},
        {"type": "event", "name": "Approval", "inputs": [{"indexed": True, "type": "address"}, {"indexed": True, "type": "address"}, {"type": "uint256"}]},
        {"type": "event", "name": "Paused", "inputs": [{"indexed": False, "type": "address"}]},
        {"type": "event", "name": "Unpaused", "inputs": [{"indexed": False, "type": "address"}]},
    ]


@pytest.fixture
def sample_transactions():
    """Generate sample transaction fixtures."""
    from datetime import datetime
    from decimal import Decimal

    return [
        {
            "hash": "0xabc123...",
            "block_number": 18500000,
            "timestamp": datetime(2024, 1, 15, 10, 30),
            "from_address": "0xUserA...",
            "to_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            "value": Decimal("0"),
            "gas_used": 65000,
            "gas_price": Decimal("20000000000"),
            "status": 1,
            "input": "0xa9059cbb000000000000000000000000...",
            "method_name": "transfer",
            "decoded_input": {"to": "0xUserB...", "value": 1000000000},
            "logs": [
                {"topic0": "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef", "topics": ["0x...", "0x..."], "data": "0x..."}
            ],
            "state_diffs": [
                {"slot": "0x...balances[UserA]", "old_value": "0x...", "new_value": "0x..."},
                {"slot": "0x...balances[UserB]", "old_value": "0x...", "new_value": "0x..."},
            ],
        },
        {
            "hash": "0xdef456...",
            "block_number": 18500100,
            "timestamp": datetime(2024, 1, 15, 11, 0),
            "from_address": "0xMinter...",
            "to_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            "value": Decimal("0"),
            "gas_used": 85000,
            "gas_price": Decimal("25000000000"),
            "status": 1,
            "input": "0x40c10f19000000000000000000000000...",
            "method_name": "mint",
            "decoded_input": {"to": "0xUserC...", "amount": 1000000000000},
            "logs": [],
            "state_diffs": [
                {"slot": "0x...balances[UserC]", "old_value": "0x0", "new_value": "0x..."},
                {"slot": "0x...totalSupply", "old_value": "0x...", "new_value": "0x..."},
            ],
        },
        {
            "hash": "0xghi789...",
            "block_number": 18500200,
            "timestamp": datetime(2024, 1, 15, 12, 0),
            "from_address": "0xAdmin...",
            "to_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            "value": Decimal("0"),
            "gas_used": 45000,
            "gas_price": Decimal("22000000000"),
            "status": 1,
            "input": "0x8456cb59000000000000000000000000...",
            "method_name": "pause",
            "decoded_input": {},
            "logs": [
                {"topic0": "0x62e78cea01bee320cd4e420270b5ea74000d11b0c9f74754ebdbfc544b05a258", "topics": [], "data": "0x..."}
            ],
            "state_diffs": [
                {"slot": "0x...paused", "old_value": "0x0", "new_value": "0x1"},
            ],
        },
    ]


@pytest.fixture
def mock_rpc_manager(mocker):
    """Mock RPC manager for testing."""
    from onchain_intent_oracle.ingestion.rpc_manager import RPCManager

    mock = mocker.MagicMock(spec=RPCManager)
    mock.get_block_number.return_value = 19000000
    mock.get_logs.return_value = []
    mock.get_transaction_receipt.return_value = {"status": "0x1", "gasUsed": "0x10000"}
    mock.get_transaction.return_value = {"hash": "0xabc", "from": "0xuser", "to": "0xcontract", "value": "0x0"}
    mock.trace_transaction.return_value = {"output": "0x", "calls": []}
    mock.debug_trace_transaction.return_value = {"type": "CALL", "from": "0x", "to": "0x", "calls": []}
    mock.get_storage_at.return_value = "0x" + "0" * 64
    mock.get_code.return_value = "0x60806040"
    return mock
