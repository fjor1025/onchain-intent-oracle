"""Load and chunk documents for indexing."""

import json
from pathlib import Path
from typing import Dict, List

import structlog

logger = structlog.get_logger()


class DocumentLoader:
    """Load documents from various sources."""

    @staticmethod
    def load_fv_best_practices(path: str) -> List[Dict[str, str]]:
        """Load formal verification best practices."""
        # Generic loader for FV documentation
        return []

    @staticmethod
    def load_defi_patterns() -> List[Dict[str, str]]:
        """Load curated DeFi security patterns."""
        patterns = [
            {
                "source": "defi_patterns",
                "title": "ERC20 Balance Invariant",
                "content": "For any ERC20 token, the sum of all balances must equal totalSupply(). Violations indicate minting/burning bugs or double-spend.",
                "metadata": {"category": "economic", "severity": "critical"},
            },
            {
                "source": "defi_patterns",
                "title": "ERC4626 Deposit/Mint Ratio",
                "content": "In ERC4626 vaults, deposit(assets) and mint(shares) must maintain consistent convertToShares/convertToAssets ratios. Rounding should favor the vault.",
                "metadata": {"category": "economic", "severity": "high"},
            },
            {
                "source": "defi_patterns",
                "title": "Lending Liquidation Incentive",
                "content": "Liquidation incentives must be bounded to prevent protocol insolvency. Typical range: 5-10% bonus to liquidator.",
                "metadata": {"category": "economic", "severity": "high"},
            },
            {
                "source": "defi_patterns",
                "title": "Reentrancy Guard Pattern",
                "content": "External calls must follow checks-effects-interactions pattern or use explicit reentrancy guards. State changes before external calls.",
                "metadata": {"category": "safety", "severity": "critical"},
            },
            {
                "source": "defi_patterns",
                "title": "Access Control Ownership",
                "content": "Privileged functions (upgrade, parameter change, emergency pause) must have explicit access control. Owner should not be single EOA for large protocols.",
                "metadata": {"category": "access_control", "severity": "high"},
            },
        ]
        return patterns

    @staticmethod
    def load_pitfall_articles() -> List[Dict[str, str]]:
        """Load common pitfall articles."""
        return [
            {
                "source": "pitfalls",
                "title": "Integer Division Rounding",
                "content": "Solidity integer division truncates. In financial calculations, this can lead to significant value drift. Use mulDiv or maintain higher precision.",
                "metadata": {"category": "precision", "severity": "medium"},
            },
            {
                "source": "pitfalls",
                "title": "Storage Collision in Proxies",
                "content": "Proxy and implementation must use compatible storage layouts. EIP-1967 and EIP-1822 define standard slots to avoid collision.",
                "metadata": {"category": "upgrade", "severity": "critical"},
            },
        ]
