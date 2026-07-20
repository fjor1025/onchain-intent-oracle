"""Tests for RPC manager."""

import pytest

from onchain_intent_oracle.config.settings import get_settings
from onchain_intent_oracle.ingestion.rpc_manager import RPCManager


class TestRPCManager:
    """Test RPC manager functionality."""

    def test_init_requires_urls(self, monkeypatch):
        """Test that RPCManager requires URLs.

        get_settings() is @lru_cache'd, so if it was already called earlier in
        the process (e.g. by an earlier test, or because a real RPC_URLS value
        is set via a .env file), the cached Settings instance would be reused
        and this monkeypatch would have no effect. Clear the cache so this
        test gets a fresh Settings() read of the patched environment, and
        clear it again afterward so later tests/usage aren't stuck with an
        empty-urls Settings instance.
        """
        get_settings.cache_clear()
        monkeypatch.setenv("RPC_URLS", "")
        try:
            with pytest.raises(ValueError, match="No RPC URLs"):
                RPCManager()
        finally:
            get_settings.cache_clear()

    def test_init_with_urls(self):
        """Test initialization with explicit URLs."""
        manager = RPCManager(urls=["http://localhost:8545"])
        assert len(manager.providers) == 1
        assert manager.providers[0].url == "http://localhost:8545"

    def test_provider_rotation(self):
        """Test round-robin provider selection."""
        manager = RPCManager(urls=["http://a", "http://b", "http://c"])

        p1 = manager._get_next_provider()
        p2 = manager._get_next_provider()
        p3 = manager._get_next_provider()

        assert p1.url == "http://a"
        assert p2.url == "http://b"
        assert p3.url == "http://c"

    def test_fallback_on_unhealthy(self):
        """Test fallback when provider is marked unhealthy."""
        manager = RPCManager(urls=["http://a", "http://b"])
        manager._healthy[0] = False

        provider = manager._get_next_provider()
        assert provider.url == "http://b"