"""Chain configuration and defaults."""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ChainConfig:
    """Configuration for a specific EVM chain."""

    chain_id: int
    name: str
    native_symbol: str
    block_time_seconds: int
    default_rpc: Optional[str] = None
    explorer_url: Optional[str] = None
    explorer_api_url: Optional[str] = None
    supports_traces: bool = True


CHAIN_CONFIGS: Dict[int, ChainConfig] = {
    1: ChainConfig(
        chain_id=1,
        name="ethereum",
        native_symbol="ETH",
        block_time_seconds=12,
        explorer_url="https://etherscan.io",
        explorer_api_url="https://api.etherscan.io/api",
        supports_traces=True,
    ),
    42161: ChainConfig(
        chain_id=42161,
        name="arbitrum",
        native_symbol="ETH",
        block_time_seconds=0.25,
        explorer_url="https://arbiscan.io",
        explorer_api_url="https://api.arbiscan.io/api",
        supports_traces=True,
    ),
    8453: ChainConfig(
        chain_id=8453,
        name="base",
        native_symbol="ETH",
        block_time_seconds=2,
        explorer_url="https://basescan.org",
        explorer_api_url="https://api.basescan.org/api",
        supports_traces=True,
    ),
    10: ChainConfig(
        chain_id=10,
        name="optimism",
        native_symbol="ETH",
        block_time_seconds=2,
        explorer_url="https://optimistic.etherscan.io",
        explorer_api_url="https://api-optimistic.etherscan.io/api",
        supports_traces=True,
    ),
    137: ChainConfig(
        chain_id=137,
        name="polygon",
        native_symbol="MATIC",
        block_time_seconds=2,
        explorer_url="https://polygonscan.com",
        explorer_api_url="https://api.polygonscan.com/api",
        supports_traces=True,
    ),
    56: ChainConfig(
        chain_id=56,
        name="bsc",
        native_symbol="BNB",
        block_time_seconds=3,
        explorer_url="https://bscscan.com",
        explorer_api_url="https://api.bscscan.com/api",
        supports_traces=False,
    ),
}


def get_chain_config(chain_id: int) -> ChainConfig:
    """Get configuration for a chain by ID."""
    if chain_id not in CHAIN_CONFIGS:
        raise ValueError(f"Unsupported chain ID: {chain_id}")
    return CHAIN_CONFIGS[chain_id]


def get_chain_config_by_name(name: str) -> ChainConfig:
    """Get configuration for a chain by name."""
    name_lower = name.lower()
    for config in CHAIN_CONFIGS.values():
        if config.name == name_lower:
            return config
    raise ValueError(f"Unknown chain name: {name}")
