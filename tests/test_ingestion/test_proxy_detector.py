"""Tests for proxy detector."""

import pytest

from onchain_intent_oracle.ingestion.proxy_detector import (
    EIP1967_IMPLEMENTATION_SLOT,
    ProxyDetector,
)


class TestProxyDetector:
    """Test proxy detection."""

    @pytest.mark.asyncio
    async def test_detect_eip1967_proxy(self, mock_rpc_manager):
        """Test EIP-1967 proxy detection."""
        # Mock storage read to return implementation address
        mock_rpc_manager.get_storage_at.return_value = (
            "0x" + "0" * 24 + "1234567890abcdef1234567890abcdef12345678"
        )
        mock_rpc_manager.get_code.return_value = "0x" + "60" * 50  # Small proxy code

        detector = ProxyDetector(mock_rpc_manager)
        is_proxy, impl, proxy_type = await detector.detect_proxy("0xProxy")

        assert is_proxy is True
        assert impl is not None
        assert proxy_type == "EIP1967"

    @pytest.mark.asyncio
    async def test_detect_direct_contract(self, mock_rpc_manager):
        """Test non-proxy contract detection."""
        # Return zero for all proxy slots
        mock_rpc_manager.get_storage_at.return_value = "0x" + "0" * 64
        mock_rpc_manager.get_code.return_value = "0x" + "60" * 500  # Large contract code

        detector = ProxyDetector(mock_rpc_manager)
        is_proxy, impl, proxy_type = await detector.detect_proxy("0xDirect")

        assert is_proxy is False
        assert impl is None
        assert proxy_type == "DIRECT"

    def test_eip1967_slot_constant(self):
        """Verify EIP-1967 slot constant."""
        assert EIP1967_IMPLEMENTATION_SLOT == (
            "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
        )
