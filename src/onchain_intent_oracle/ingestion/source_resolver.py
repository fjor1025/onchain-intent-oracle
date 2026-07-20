"""Resolve verified source code and ABIs from block explorers."""

from typing import Any, Dict, Optional

import httpx
import structlog

from onchain_intent_oracle.config.chains import get_chain_config
from onchain_intent_oracle.config.settings import get_settings

logger = structlog.get_logger()


class SourceResolver:
    """Fetches verified source code and ABIs from Etherscan-like explorers."""

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.etherscan_api_key
        self.client = httpx.AsyncClient(timeout=30.0)

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
