"""Decode transaction function signatures from 4-byte selectors."""
import asyncio
import json
from pathlib import Path
from typing import Dict, Optional
import structlog

logger = structlog.get_logger()

BUILTIN_SIGNATURES = {
    "0xa9059cbb": "transfer(address,uint256)",
    "0x23b872dd": "transferFrom(address,address,uint256)",
    "0x095ea7b3": "approve(address,uint256)",
    "0xdd62ed3e": "allowance(address,address)",
    "0x70a08231": "balanceOf(address)",
    "0x18160ddd": "totalSupply()",
    "0x06fdde03": "name()",
    "0x95d89b41": "symbol()",
    "0x313ce567": "decimals()",
    "0x42842e0e": "safeTransferFrom(address,address,uint256)",
    "0xb88d4fde": "safeTransferFrom(address,address,uint256,bytes)",
    "0xa22cb465": "setApprovalForAll(address,bool)",
    "0x6352211e": "ownerOf(uint256)",
    "0xc87b56dd": "tokenURI(uint256)",
    "0x38ed1739": "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)",
    "0x8803dbee": "swapTokensForExactTokens(uint256,uint256,address[],address,uint256)",
    "0x7ff36ab5": "swapExactETHForTokens(uint256,address[],address,uint256)",
    "0x18cbafe5": "swapExactTokensForETH(uint256,uint256,address[],address,uint256)",
    "0xb6f9de95": "exactInputSingle((address,address,uint24,address,uint256,uint256,uint256,uint160))",
    "0xc04b8d59": "exactInput(bytes,(address,uint256,uint256,uint256,address))",
    "0x472b43f3": "swap(address,bool,int256,uint160,bytes)",
    "0x8dbdbe6d": "deposit()",
    "0x2e1a7d4d": "withdraw(uint256)",
    "0xa0712d68": "mint(uint256)",
    "0x42966c68": "burn(uint256)",
    "0x8f9a55c0": "configureMinter(address,uint256)",
    "0x983b2d56": "removeMinter(address)",
    "0xdaddcb5f": "mint(address,uint256)",
    "0xf2fde38b": "transferOwnership(address)",
    "0x8da5cb5b": "owner()",
    "0x5c975abb": "paused()",
    "0x8456cb59": "pause()",
    "0x3f4ba83a": "unpause()",
    "0x5c60da1b": "implementation()",
    "0x3659cfe6": "upgradeTo(address)",
    "0x4f1ef286": "upgradeToAndCall(address,bytes)",
    "0xc9567bf9": "changeAdmin(address)",
    "0xf851a440": "admin()",
    "0xd0e30db0": "deposit()",
    "0x617ba037": "supply(address,uint256,address,uint16)",
    "0x69328dec": "withdraw(address,uint256,address)",
    "0xe8eda9df": "borrow(address,uint256,uint256,uint16,address)",
    "0x573ade81": "repay(address,uint256,uint256,address)",
    "0xc2998238": "mint(uint256)",
    "0xdb006a75": "redeem(uint256)",
    "0x852a12e3": "redeemUnderlying(uint256)",
    "0x4b8a4279": "borrow(uint256)",
    "0x0e752702": "repayBorrow(uint256)",
    "0x1edbeb22": "repayBorrowBehalf(address,uint256)",
    "0x360894a1": "implementation()",
    "0xb5312768": "admin()",
    "0x3593564c": "execute(bytes,bytes[],uint256)",
    "0x12aa3caf": "swap(address,tuple,bytes)",
    "0x6af479b2": "sellTokenForTokenToUniswapV3(bytes,uint256,bytes)",
    "0x2434c20c": "initializeLoan(tuple)",
    "0xce2e62ff": "multicall(bytes[])",
    "0xd48e983d": "permit(address,address,uint256,uint256,uint8,bytes32,bytes32)",
    "0xa415bcad": "transferWithAuthorization(address,address,uint256,uint256,uint256,bytes32,uint8,bytes32,bytes32)",
    "0x57ecfd28": "receiveMessage(bytes)",
    "0x6a676110": "fillOtcOrderWithEth(tuple,tuple,uint128,tuple)",
    "0x": "fallback()",
}

class SignatureDecoder:
    def __init__(self, cache_dir=None):
        self._cache = dict(BUILTIN_SIGNATURES)
        self._cache_dir = cache_dir or Path.home() / ".oio" / "signatures"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._load_cache()
        # Selector -> in-flight asyncio.Future, for `adecode`'s singleflight
        # dedup (see that method). Sync `decode`/`_lookup_4byte` don't need
        # this: they're blocking calls with no concurrent-coroutine race to
        # dedup in the first place.
        self._inflight: Dict[str, "asyncio.Future"] = {}

    def _load_cache(self):
        f = self._cache_dir / "signatures.json"
        if f.exists():
            try:
                self._cache.update(json.loads(f.read_text()))
            except Exception as e:
                logger.warning("cache_load_failed", error=str(e))

    def _save_cache(self):
        try:
            (self._cache_dir / "signatures.json").write_text(json.dumps(self._cache, indent=2))
        except Exception as e:
            logger.warning("cache_save_failed", error=str(e))

    def decode(self, selector):
        sel = selector.lower().removeprefix("0x")[:8]
        if not sel or len(sel) < 8:
            return None
        key = "0x" + sel
        if key in self._cache:
            return self._cache[key]
        name = self._lookup_4byte(sel)
        if name:
            self._cache[key] = name
            self._save_cache()
        return name

    def _lookup_4byte(self, selector):
        # NOTE: synchronous/blocking. Only safe to call outside a running event
        # loop (e.g. from sync tests or scripts). Async callers should use
        # `adecode`/`adecode_trace` below, which do not block the event loop.
        import urllib.request
        url = f"https://www.4byte.directory/api/v1/signatures/?hex_signature=0x{selector}"
        req = urllib.request.Request(url, headers={"User-Agent": "OnChainIntentOracle/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                results = data.get("results", [])
                if results:
                    return min(results, key=lambda r: len(r.get("text_signature", ""))).get("text_signature")
        except Exception as e:
            logger.debug("4byte_failed", selector=selector, error=str(e))
        return None

    def decode_trace(self, input_data):
        if not input_data or input_data == "0x":
            return "fallback", ""
        sig = self.decode(input_data[:10])
        args = input_data[10:] if len(input_data) > 10 else ""
        if sig:
            return sig.split("(")[0], args
        return "unknown", input_data

    async def adecode(self, selector):
        """Async, non-blocking equivalent of `decode`. Use this from async code
        (e.g. the ingestion pipeline) instead of `decode`, which does a blocking
        urllib call on a cache miss and would stall the event loop.

        Concurrent calls for the *same* uncached selector are deduplicated
        (singleflight): the pipeline calls this once per transaction via
        `asyncio.gather`, and it's completely ordinary for many transactions
        in the same analyzed range to share a selector (every plain ERC-20
        `transfer` call, for instance) -- without dedup, N concurrent
        transactions with the same unresolved selector previously fired N
        redundant real lookups against 4byte.directory instead of 1, all
        racing to populate the same cache key.
        """
        sel = selector.lower().removeprefix("0x")[:8]
        if not sel or len(sel) < 8:
            return None
        key = "0x" + sel
        if key in self._cache:
            return self._cache[key]

        existing = self._inflight.get(key)
        if existing is not None:
            return await existing

        future: "asyncio.Future" = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            name = await self._alookup_4byte(sel)
            if name:
                self._cache[key] = name
                self._save_cache()
            future.set_result(name)
            return name
        except Exception as e:  # pragma: no cover -- _alookup_4byte already catches everything
            future.set_exception(e)
            raise
        finally:
            self._inflight.pop(key, None)

    async def _alookup_4byte(self, selector):
        import httpx
        url = f"https://www.4byte.directory/api/v1/signatures/?hex_signature=0x{selector}"
        headers = {"User-Agent": "OnChainIntentOracle/0.1"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, headers=headers)
                data = resp.json()
                results = data.get("results", [])
                if results:
                    return min(results, key=lambda r: len(r.get("text_signature", ""))).get("text_signature")
        except Exception as e:
            logger.debug("4byte_failed", selector=selector, error=str(e))
        return None

    async def adecode_trace(self, input_data):
        """Async, non-blocking equivalent of `decode_trace`."""
        if not input_data or input_data == "0x":
            return "fallback", ""
        sig = await self.adecode(input_data[:10])
        args = input_data[10:] if len(input_data) > 10 else ""
        if sig:
            return sig.split("(")[0], args
        return "unknown", input_data
