"""Resolve verified source code and ABIs from block explorers."""

from typing import Any, Dict, List, Optional

import httpx
import structlog
from eth_utils import keccak

from onchain_intent_oracle.config.chains import get_chain_config
from onchain_intent_oracle.config.settings import get_settings
from onchain_intent_oracle.ingestion.abi_utils import abi_type_string

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
        input_types = ",".join(abi_type_string(i) for i in entry.get("inputs", []))
        signature = f"{name}({input_types})"
        selector = "0x" + keccak(text=signature)[:4].hex()
        out[selector] = name
    return out


def abi_to_function_map(abi: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Build a {4-byte selector: function descriptor} map from an ABI, for
    ABI-decoding *argument values* (not just resolving the function name --
    see `abi_to_selector_map` above for that).

    Each descriptor is `{"name", "signature", "param_names": [...],
    "type_strings": [...]}`, with `type_strings` already expanded for struct
    (tuple) params via `abi_type_string` so they're directly usable with
    `eth_abi.decode()` without the caller needing to know anything about the
    ABI JSON's `components` shape.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for entry in abi or []:
        if not isinstance(entry, dict) or entry.get("type") != "function":
            continue
        name = entry.get("name")
        if not name:
            continue
        inputs = entry.get("inputs", [])
        type_strings = [abi_type_string(i) for i in inputs]
        signature = f"{name}({','.join(type_strings)})"
        selector = "0x" + keccak(text=signature)[:4].hex()
        out[selector] = {
            "name": name,
            "signature": signature,
            "param_names": [i.get("name") or f"arg{idx}" for idx, i in enumerate(inputs)],
            "type_strings": type_strings,
        }
    return out


def abi_to_event_map(abi: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Build a {topic0 (0x-prefixed 32-byte hash): event descriptor} map from an ABI.

    Mirrors `abi_to_selector_map` above but for events: topic0 is
    keccak256(event_signature) over the *full* (indexed + non-indexed)
    parameter type list, per the EVM log spec -- indexed-ness affects where a
    param ends up (topics vs. data), not the signature hash itself.

    Each descriptor is `{"name": str, "inputs": [{"name", "type", "indexed"}]}`
    so a decoder can split params into topics/data in the right order without
    re-deriving that from the raw ABI shape every time. This is authoritative
    the same way `abi_to_selector_map` is -- computed directly from the
    verified ABI's own event signatures, not guessed from an open directory.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for entry in abi or []:
        if not isinstance(entry, dict) or entry.get("type") != "event":
            continue
        name = entry.get("name")
        if not name:
            continue
        inputs = entry.get("inputs", [])
        input_types = ",".join(abi_type_string(i) for i in inputs)
        signature = f"{name}({input_types})"
        topic0 = "0x" + keccak(text=signature).hex()
        out[topic0] = {
            "name": name,
            "signature": signature,
            "anonymous": bool(entry.get("anonymous", False)),
            "inputs": [
                {
                    "name": i.get("name") or f"arg{idx}",
                    "type": i.get("type", ""),
                    "indexed": bool(i.get("indexed", False)),
                }
                for idx, i in enumerate(inputs)
            ],
        }
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
