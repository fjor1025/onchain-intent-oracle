"""Multi-provider RPC manager with fallback and rate limiting."""

import asyncio
import random
import time
from typing import Any, Dict, List, Optional

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from web3 import Web3
from web3.providers import HTTPProvider
from web3.types import RPCEndpoint, RPCResponse

from onchain_intent_oracle.config.settings import get_settings

logger = structlog.get_logger()


class RateLimitedProvider:
    """Wrapper that enforces rate limiting on a Web3 provider."""

    def __init__(self, url: str, max_rps: float = 10.0):
        self.url = url
        self.max_rps = max_rps
        self.min_interval = 1.0 / max_rps
        self._last_request = 0.0
        self._lock = asyncio.Lock()
        self._w3 = Web3(HTTPProvider(url))

    async def _wait(self):
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_request
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            self._last_request = time.time()

    def make_request(self, method: RPCEndpoint, params: Any) -> RPCResponse:
        """Synchronous request with rate limit."""
        return self._w3.provider.make_request(method, params)

    async def amake_request(self, method: RPCEndpoint, params: Any) -> RPCResponse:
        """Async request with rate limit."""
        await self._wait()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.make_request, method, params)


class RPCManager:
    """Manages multiple RPC endpoints with health checking and fallback."""

    # Alchemy free tier: max 10 blocks per eth_getLogs
    MAX_LOGS_BLOCK_RANGE = 10

    def __init__(self, urls: Optional[List[str]] = None):
        self.settings = get_settings()
        self.urls = urls or self.settings.rpc_urls
        if not self.urls:
            raise ValueError("No RPC URLs configured. Set RPC_URLS env var.")

        self.providers: List[RateLimitedProvider] = [
            RateLimitedProvider(url, self.settings.rpc_rate_limit)
            for url in self.urls
        ]
        self._healthy: List[bool] = [True] * len(self.providers)
        self._current_index = 0

    def _get_next_provider(self) -> RateLimitedProvider:
        """Round-robin with health check."""
        attempts = 0
        while attempts < len(self.providers):
            idx = self._current_index % len(self.providers)
            self._current_index += 1
            if self._healthy[idx]:
                return self.providers[idx]
            attempts += 1
        return random.choice(self.providers)

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, ConnectionError, TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def request(self, method: str, params: Any) -> Any:
        """Make an RPC request with automatic fallback."""
        provider = self._get_next_provider()
        try:
            response = await provider.amake_request(method, params)
            if "error" in response:
                raise ValueError(f"RPC error: {response['error']}")
            return response.get("result")
        except Exception as e:
            for i, p in enumerate(self.providers):
                if p.url == provider.url:
                    self._healthy[i] = False
                    asyncio.create_task(self._health_check(i))
            raise

    async def _health_check(self, index: int, delay: int = 30):
        """Re-check provider health after delay."""
        await asyncio.sleep(delay)
        try:
            provider = self.providers[index]
            response = await provider.amake_request("eth_blockNumber", [])
            if "error" not in response:
                self._healthy[index] = True
                logger.info("rpc_provider_healthy", url=provider.url)
        except Exception:
            pass

    async def get_block_number(self) -> int:
        """Get latest block number."""
        result = await self.request("eth_blockNumber", [])
        return int(result, 16)

    async def get_logs(
        self,
        from_block: int,
        to_block: int,
        address: Optional[str] = None,
        topics: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Get event logs for a block range, chunked for provider limits."""
        all_logs: List[Dict] = []
        current = from_block
        
        while current <= to_block:
            chunk_end = min(current + self.MAX_LOGS_BLOCK_RANGE - 1, to_block)
            
            params = {
                "fromBlock": hex(current),
                "toBlock": hex(chunk_end),
            }
            if address:
                params["address"] = address
            if topics:
                params["topics"] = topics
            
            logger.debug("fetching_logs_chunk", from_block=current, to_block=chunk_end)
            chunk_logs = await self.request("eth_getLogs", [params])
            if chunk_logs:
                all_logs.extend(chunk_logs)
            
            current = chunk_end + 1
        
        return all_logs

    async def get_transaction_receipt(self, tx_hash: str) -> Optional[Dict]:
        """Get transaction receipt."""
        return await self.request("eth_getTransactionReceipt", [tx_hash])

    async def get_transaction(self, tx_hash: str) -> Optional[Dict]:
        """Get transaction by hash."""
        return await self.request("eth_getTransactionByHash", [tx_hash])

    async def trace_transaction(self, tx_hash: str) -> Optional[Dict]:
        """Get trace for a transaction (Parity-style)."""
        try:
            return await self.request("trace_transaction", [tx_hash])
        except Exception as e:
            logger.warning("trace_transaction_unavailable", error=str(e))
            return None

    async def debug_trace_transaction(
        self,
        tx_hash: str,
        tracer: str = "callTracer",
        tracer_config: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """Get debug trace for a transaction."""
        config = {"tracer": tracer}
        if tracer_config:
            config["tracerConfig"] = tracer_config
        try:
            return await self.request("debug_traceTransaction", [tx_hash, config])
        except Exception as e:
            logger.warning("debug_trace_unavailable", error=str(e))
            return None

    async def get_storage_at(self, address: str, slot: str, block: str = "latest") -> str:
        """Get storage slot value."""
        return await self.request("eth_getStorageAt", [address, slot, block])

    async def get_code(self, address: str, block: str = "latest") -> str:
        """Get contract bytecode."""
        return await self.request("eth_getCode", [address, block])
