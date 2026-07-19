"""Detect and resolve proxy contracts."""

from typing import Optional, Tuple

import structlog
from eth_typing import ChecksumAddress, HexStr

from onchain_intent_oracle.ingestion.rpc_manager import RPCManager

logger = structlog.get_logger()

# Standard proxy storage slots
EIP1967_IMPLEMENTATION_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
EIP1967_BEACON_SLOT = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"
EIP1822_LOGIC_SLOT = "0xc5f16f0fcc639fa48a6947836d9850f504798523bf8c9a3a87e587b162bc9b9b"
OPEN_ZEPPELIN_IMPLEMENTATION_SLOT = "0x7050c9e0f4ca769c69bd3a8ef740bc22934ac8b7b92d1caeb3b4f6f5"


class ProxyDetector:
    """Detects proxy patterns and resolves implementation addresses."""

    def __init__(self, rpc: RPCManager):
        self.rpc = rpc

    async def detect_proxy(self, address: str) -> Tuple[bool, Optional[str], str]:
        """
        Detect if address is a proxy and return implementation.

        Returns: (is_proxy, implementation_address, proxy_type)
        """
        address = ChecksumAddress(address)

        # Check EIP-1967 direct proxy
        impl = await self._read_storage(address, EIP1967_IMPLEMENTATION_SLOT)
        if impl and impl != "0x" + "0" * 40:
            logger.info("eip1967_proxy_detected", address=address, implementation=impl)
            return True, impl, "EIP1967"

        # Check EIP-1967 beacon proxy
        beacon = await self._read_storage(address, EIP1967_BEACON_SLOT)
        if beacon and beacon != "0x" + "0" * 40:
            # Read implementation from beacon
            impl = await self._get_beacon_implementation(beacon)
            if impl:
                logger.info("eip1967_beacon_proxy_detected", address=address, implementation=impl)
                return True, impl, "EIP1967_BEACON"

        # Check EIP-1822 (Universal Upgradeable Proxy)
        impl = await self._read_storage(address, EIP1822_LOGIC_SLOT)
        if impl and impl != "0x" + "0" * 40:
            logger.info("eip1822_proxy_detected", address=address, implementation=impl)
            return True, impl, "EIP1822"

        # Check OpenZeppelin transparent proxy
        impl = await self._read_storage(address, OPEN_ZEPPELIN_IMPLEMENTATION_SLOT)
        if impl and impl != "0x" + "0" * 40:
            logger.info("oz_transparent_proxy_detected", address=address, implementation=impl)
            return True, impl, "OPEN_ZEPPELIN"

        # Check if code at address is minimal (proxy bytecode is typically < 100 bytes)
        code = await self.rpc.get_code(address)
        if len(code) <= 100:  # Minimal proxy or similar
            # Try to detect Diamond proxy (EIP-2535)
            diamond_impl = await self._check_diamond_proxy(address)
            if diamond_impl:
                return True, diamond_impl, "EIP2535_DIAMOND"

        return False, None, "DIRECT"

    async def _read_storage(self, address: str, slot: str) -> Optional[str]:
        """Read a storage slot and parse as address."""
        try:
            value = await self.rpc.get_storage_at(address, slot)
            if value and len(value) >= 42:
                # Last 20 bytes are the address
                addr = "0x" + value[-40:]
                if addr != "0x" + "0" * 40:
                    return ChecksumAddress(addr)
        except Exception as e:
            logger.debug("storage_read_failed", address=address, slot=slot, error=str(e))
        return None

    async def _get_beacon_implementation(self, beacon: str) -> Optional[str]:
        """Read implementation from beacon contract."""
        try:
            # implementation() selector: 0x5c60da1b
            result = await self.rpc.request("eth_call", [{
                "to": beacon,
                "data": "0x5c60da1b",
            }, "latest"])
            if result and len(result) >= 66:
                addr = "0x" + result[-40:]
                return ChecksumAddress(addr)
        except Exception as e:
            logger.debug("beacon_impl_failed", beacon=beacon, error=str(e))
        return None

    async def _check_diamond_proxy(self, address: str) -> Optional[str]:
        """Check for Diamond proxy pattern (EIP-2535)."""
        try:
            # diamondStorage() or facetAddress(bytes4) might be available
            # This is a simplified check
            code = await self.rpc.get_code(address)
            if "0x7a0ed627" in code:  # diamondCut selector
                logger.info("possible_diamond_proxy", address=address)
                # Would need more sophisticated detection
                return None
        except Exception:
            pass
        return None

    async def get_implementation_history(
        self,
        address: str,
        from_block: int,
        to_block: int,
    ) -> list:
        """Track implementation changes over time."""
        # Look for Upgraded events or similar
        # This would require log analysis
        logger.info("tracking_implementation_history", address=address)
        return []
