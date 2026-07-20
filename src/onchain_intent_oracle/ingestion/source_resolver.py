"""Resolve verified source code and ABIs from block explorers."""

from typing import Any, Dict, List, Optional

import httpx
import structlog
from eth_utils import keccak

from onchain_intent_oracle.config.chains import get_chain_config
from onchain_intent_oracle.config.settings import get_settings

logger = structlog.get_logger()


def abi_to_selector_map(abi: List[Dict[str, Any]]) -> Dict[str, str]:
    """Build a {4-byte selector (with 0x prefix): function name} map from an ABI.

    This is authoritative (computed directly from the verified ABI's function
    signatures via keccak256), unlike a 4byte.directory lookup which is a
    best-effort guess that can collide across unrelated functions sharing the
    same selector.
    """
    out: Dict[str, str] = {}
    for entry in abi or []:
        if not isinstance(entry, dict) or entry.get("type") != "function":
            continue
        name = entry.get("name")
        if not name:
            continue
        input_types = ",".join(i.get("type", "") for i in entry.get("inputs", []))
        signature = f"{name}({input_types})"
        selector = "0x" + keccak(text=signature)[:4].hex()
        out[selector] = name
    return out


# Minimal signature sets used to guess ERC-20/721/1155 conformance from an ABI.
# Not a substitute for a real interface-detection check (ERC-165, bytecode
# analysis) -- just a cheap, transparent heuristic based on function presence.
_ERC20_REQUIRED = {"transfer", "balanceOf", "totalSupply"}
_ERC721_REQUIRED = {"ownerOf", "safeTransferFrom", "balanceOf"}
_ERC1155_REQUIRED = {"balanceOfBatch", "safeBatchTransferFrom"}


def detect_standards(abi: List[Dict[str, Any]]) -> List[str]:
    """Heuristically detect common token standards from an ABI's function names."""
    if not abi:
        return []
    names = {entry.get("name") for entry in abi if isinstance(entry, dict) and entry.get("type") == "function"}
    standards = []
    if _ERC20_REQUIRED.issubset(names):
        standards.append("ERC-20")
    if _ERC721_REQUIRED.issubset(names):
        standards.append("ERC-721")
    if _ERC1155_REQUIRED.issubset(names):
        standards.append("ERC-1155")
    return standards


class SourceResolver:
    """Fetches verified source code and ABIs from Etherscan-like explorers."""

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.etherscan_api_key
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self.client.aclose()

    async def __aenter__(self) -> "SourceResolver":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    async def get_abi(self, address: str, chain_id: int = 1) -> Optional[list]:
        """Get contract ABI from explorer."""
        config = get_chain_config(chain_id)
        if not config.explorer_api_url:
            logger.warning("no_explorer_api", chain_id=chain_id)
            return None

        url = config.explorer_api_url
        params = {
            "chainid": chain_id,
            "module": "contract",
            "action": "getabi",
            "address": address,
            "apikey": self.api_key or "",
        }

        try:
            response = await self.client.get(url, params=params)
            data = response.json()
            if data.get("status") == "1" and data.get("result"):
                import json
                return json.loads(data["result"])
        except Exception as e:
            logger.warning("abi_fetch_failed", address=address, error=str(e))
        return None

    async def get_source_code(self, address: str, chain_id: int = 1) -> Optional[Dict[str, Any]]:
        """Get verified source code from explorer."""
        config = get_chain_config(chain_id)
        if not config.explorer_api_url:
            return None

        url = config.explorer_api_url
        params = {
            "chainid": chain_id,
            "module": "contract",
            "action": "getsourcecode",
            "address": address,
            "apikey": self.api_key or "",
        }

        try:
            response = await self.client.get(url, params=params)
            data = response.json()
            if data.get("status") == "1" and data.get("result"):
                return data["result"][0] if isinstance(data["result"], list) else data["result"]
        except Exception as e:
            logger.warning("source_fetch_failed", address=address, error=str(e))
        return None

    async def get_contract_creation(
        self,
        address: str,
        chain_id: int = 1,
    ) -> Optional[Dict]:
        """Get contract creation transaction."""
        config = get_chain_config(chain_id)
        if not config.explorer_api_url:
            return None

        url = config.explorer_api_url
        params = {
            "chainid": chain_id,
            "module": "contract",
            "action": "getcontractcreation",
            "contractaddresses": address,
            "apikey": self.api_key or "",
        }

        try:
            response = await self.client.get(url, params=params)
            data = response.json()
            if data.get("status") == "1":
                return data["result"][0] if isinstance(data["result"], list) else None
        except Exception as e:
            logger.warning("creation_fetch_failed", address=address, error=str(e))
        return None
