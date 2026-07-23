"""Tests for ingestion/signature_decoder.py's async concurrency behavior."""

import asyncio

import pytest

from onchain_intent_oracle.ingestion.signature_decoder import SignatureDecoder


class TestAdecodeConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_identical_selector_only_fetches_once(self, mocker):
        decoder = SignatureDecoder(cache_dir=None)
        decoder._cache.pop("0xdeadbeef", None)

        call_count = 0

        async def fake_lookup(selector):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)  # simulate real network latency
            return "someFunction(uint256)"

        mocker.patch.object(decoder, "_alookup_4byte", side_effect=fake_lookup)
        mocker.patch.object(decoder, "_save_cache")

        # 20 concurrent lookups of the exact same uncached selector
        results = await asyncio.gather(*(decoder.adecode("0xdeadbeef") for _ in range(20)))

        assert call_count == 1, f"expected exactly 1 real lookup, got {call_count}"
        assert all(r == "someFunction(uint256)" for r in results)
        assert decoder._cache["0xdeadbeef"] == "someFunction(uint256)"

    @pytest.mark.asyncio
    async def test_concurrent_different_selectors_each_fetch_independently(self, mocker):
        """Dedup must be keyed per-selector -- different uncached selectors
        looked up concurrently must NOT be collapsed into one call."""
        decoder = SignatureDecoder(cache_dir=None)
        for sel in ("0xaaaaaaaa", "0xbbbbbbbb", "0xcccccccc"):
            decoder._cache.pop(sel, None)

        call_count = 0

        async def fake_lookup(selector):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.02)
            return f"fn_{selector}()"

        mocker.patch.object(decoder, "_alookup_4byte", side_effect=fake_lookup)
        mocker.patch.object(decoder, "_save_cache")

        results = await asyncio.gather(
            decoder.adecode("0xaaaaaaaa"),
            decoder.adecode("0xbbbbbbbb"),
            decoder.adecode("0xcccccccc"),
            decoder.adecode("0xaaaaaaaa"),  # duplicate of the first
        )
        assert call_count == 3
        assert results[0] == results[3]

    @pytest.mark.asyncio
    async def test_a_failed_lookup_does_not_permanently_poison_the_selector(self, mocker):
        """After an in-flight lookup resolves to None (not found anywhere),
        the selector must not stay stuck as permanently in-flight -- a later
        call must be able to try again (e.g. after the cache/4byte directory
        catches up), not hang or return a stale None forever."""
        decoder = SignatureDecoder(cache_dir=None)
        decoder._cache.pop("0xdeadbeef", None)

        mocker.patch.object(decoder, "_alookup_4byte", side_effect=[None, "foundLater()"])
        mocker.patch.object(decoder, "_save_cache")

        first = await decoder.adecode("0xdeadbeef")
        assert first is None

        second = await decoder.adecode("0xdeadbeef")
        assert second == "foundLater()"

    @pytest.mark.asyncio
    async def test_cached_selector_never_touches_inflight_tracking(self, mocker):
        decoder = SignatureDecoder(cache_dir=None)
        lookup = mocker.patch.object(decoder, "_alookup_4byte")

        # "0xa9059cbb" (transfer(address,uint256)) is in BUILTIN_SIGNATURES.
        result = await decoder.adecode("0xa9059cbb")
        assert result == "transfer(address,uint256)"
        lookup.assert_not_called()
        assert decoder._inflight == {}
