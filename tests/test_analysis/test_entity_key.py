"""Tests for analysis/entity_key.py."""

from onchain_intent_oracle.analysis.entity_key import (
    bucket_by_entity,
    looks_like_entity_id_name,
)

MARKET_A = "0x" + "aa" * 32
MARKET_B = "0x" + "bb" * 32


def _tx(hash_, decoded_args=None, decoded_logs=None):
    return {
        "hash": hash_,
        "decoded_args": decoded_args or {"method_name": "unknown", "args": {}, "arg_types": {}, "confidence": "unresolved", "decode_error": None, "struct_hash": None},
        "decoded_logs": decoded_logs or [],
    }


def _supply_event(market_id, amount, confidence="verified_abi"):
    return {
        "event_name": "Supply", "confidence": confidence, "decode_error": None,
        "args": {"id": market_id, "onBehalf": "0xUser", "assets": amount},
        "arg_types": {"id": "bytes32", "onBehalf": "address", "assets": "uint256"},
        "indexed_hash_only": [],
    }


class TestLooksLikeEntityIdName:
    def test_matches_common_names(self):
        for name in ["id", "marketId", "poolId", "vaultId", "tokenId", "trancheId", "vault_id", "someRandomId"]:
            assert looks_like_entity_id_name(name), name

    def test_rejects_unrelated_names(self):
        for name in ["amount", "owner", "assets", "shares", "receiver", ""]:
            assert not looks_like_entity_id_name(name), name


class TestFlatContractRegression:
    """Flat, non-multiplexed contracts must land entirely in the None
    bucket -- this is the pass-through/regression-safe default."""

    def test_no_entity_key_candidates_anywhere(self):
        txs = [
            _tx("0x1", decoded_args={"method_name": "transfer", "args": {"to": "0xUser", "amount": 100}, "arg_types": {"to": "address", "amount": "uint256"}, "confidence": "verified_abi", "decode_error": None, "struct_hash": None}),
            _tx("0x2", decoded_args={"method_name": "approve", "args": {"spender": "0xUser", "amount": 50}, "arg_types": {"spender": "address", "amount": "uint256"}, "confidence": "verified_abi", "decode_error": None, "struct_hash": None}),
        ]
        buckets, source = bucket_by_entity(txs)
        assert list(buckets.keys()) == [None]
        assert len(buckets[None]) == 2
        assert source == "none"

    def test_address_typed_id_field_is_not_matched(self):
        """An arg literally named "id" but typed `address` must NOT match --
        the spec requires bytes32/uint256, not just a name match."""
        txs = [
            _tx("0x1", decoded_args={"method_name": "foo", "args": {"id": "0xSomeAddress"}, "arg_types": {"id": "address"}, "confidence": "verified_abi", "decode_error": None, "struct_hash": None}),
        ]
        buckets, source = bucket_by_entity(txs)
        assert list(buckets.keys()) == [None]
        assert source == "none"


class TestNameHeuristicFromLogs:
    """The Morpho Blue case in practice: supply/borrow/etc. calls take a
    MarketParams struct, but the corresponding events carry `id` directly."""

    def test_buckets_by_event_id_across_markets(self):
        txs = [
            _tx("0x1", decoded_logs=[_supply_event(MARKET_A, 100)]),
            _tx("0x2", decoded_logs=[_supply_event(MARKET_A, 200)]),
            _tx("0x3", decoded_logs=[_supply_event(MARKET_B, 50)]),
        ]
        buckets, source = bucket_by_entity(txs)
        assert source == "heuristic"
        assert set(buckets.keys()) == {MARKET_A, MARKET_B}
        assert len(buckets[MARKET_A]) == 2
        assert len(buckets[MARKET_B]) == 1

    def test_admin_calls_with_no_entity_stay_in_none_bucket_alongside_entities(self):
        """Contract-wide admin calls (Morpho's enableIrm/enableLltv/
        setOwner) aren't about any one market -- they must land in the
        aggregate None bucket, not get force-fit into an entity bucket or
        silently dropped."""
        txs = [
            _tx("0x1", decoded_logs=[_supply_event(MARKET_A, 100)]),
            _tx("0x2", decoded_args={"method_name": "enableIrm", "args": {"irm": "0xIrm"}, "arg_types": {"irm": "address"}, "confidence": "verified_abi", "decode_error": None, "struct_hash": None}),
        ]
        buckets, source = bucket_by_entity(txs)
        assert source == "heuristic"
        assert set(buckets.keys()) == {MARKET_A, None}
        assert len(buckets[None]) == 1

    def test_unresolved_or_decode_error_logs_never_ground_a_bucket(self):
        txs = [
            _tx("0x1", decoded_logs=[
                {"event_name": None, "confidence": "unresolved", "args": {}, "arg_types": {}, "indexed_hash_only": [], "decode_error": None},
            ]),
            _tx("0x2", decoded_logs=[
                {"event_name": "Supply", "confidence": "verified_abi", "decode_error": "boom", "args": {"id": MARKET_A}, "arg_types": {"id": "bytes32"}, "indexed_hash_only": []},
            ]),
        ]
        buckets, source = bucket_by_entity(txs)
        assert list(buckets.keys()) == [None]
        assert source == "none"

    def test_hash_only_indexed_arg_never_used_as_entity_key(self):
        """An indexed dynamic-typed arg is only its keccak256 hash -- even if
        it happens to be named/typed like an id, it must never be used as an
        entity key (see indexed_hash_only in log_decoder.py)."""
        txs = [
            _tx("0x1", decoded_logs=[{
                "event_name": "Tagged", "confidence": "verified_abi", "decode_error": None,
                "args": {"id": "0x" + "11" * 32}, "arg_types": {"id": "bytes32"},
                "indexed_hash_only": ["id"],
            }]),
        ]
        buckets, source = bucket_by_entity(txs)
        assert list(buckets.keys()) == [None]
        assert source == "none"


class TestStructHashHeuristic:
    def test_promoted_when_it_matches_an_observed_id_elsewhere(self):
        create_market_tx = _tx(
            "0x1",
            decoded_args={
                "method_name": "createMarket", "args": {"marketParams": ["0xA", "0xB", "0xC", "0xD", 860000000000000000]},
                "arg_types": {"marketParams": "(address,address,address,address,uint256)"},
                "confidence": "verified_abi", "decode_error": None, "struct_hash": MARKET_A,
            },
        )
        supply_tx = _tx("0x2", decoded_logs=[_supply_event(MARKET_A, 100)])

        buckets, source = bucket_by_entity([create_market_tx, supply_tx])
        assert source == "heuristic"
        assert MARKET_A in buckets
        assert create_market_tx in buckets[MARKET_A]
        assert supply_tx in buckets[MARKET_A]

    def test_not_promoted_when_never_observed_as_an_id_elsewhere(self):
        """A computed struct hash with nothing to corroborate it must NOT be
        treated as a confirmed entity key -- that would be a blind guess,
        not evidence-grounded bucketing."""
        create_market_tx = _tx(
            "0x1",
            decoded_args={
                "method_name": "createMarket", "args": {"marketParams": ["0xA", "0xB", "0xC", "0xD", 1]},
                "arg_types": {"marketParams": "(address,address,address,address,uint256)"},
                "confidence": "verified_abi", "decode_error": None, "struct_hash": "0x" + "cc" * 32,
            },
        )
        buckets, source = bucket_by_entity([create_market_tx])
        assert list(buckets.keys()) == [None]
        assert source == "none"


class TestForcedEntityKey:
    def test_forces_a_specific_arg_name_case_insensitively(self):
        txs = [
            _tx("0x1", decoded_args={"method_name": "foo", "args": {"vaultId": "V1"}, "arg_types": {"vaultId": "bytes32"}, "confidence": "verified_abi", "decode_error": None, "struct_hash": None}),
            _tx("0x2", decoded_args={"method_name": "bar", "args": {"vaultId": "V2"}, "arg_types": {"vaultId": "bytes32"}, "confidence": "verified_abi", "decode_error": None, "struct_hash": None}),
        ]
        buckets, source = bucket_by_entity(txs, forced_arg_name="VAULTID")
        assert source == "user_specified"
        assert set(buckets.keys()) == {"V1", "V2"}

    def test_forced_key_disables_heuristic_fallback(self):
        """When the user forces a specific arg name, a tx lacking that exact
        arg must land in the None bucket -- it must NOT silently fall back
        to the name/struct-hash heuristics, which would ignore the user's
        explicit choice."""
        txs = [
            _tx("0x1", decoded_logs=[_supply_event(MARKET_A, 100)]),  # has "id", not "vaultId"
        ]
        buckets, source = bucket_by_entity(txs, forced_arg_name="vaultId")
        assert list(buckets.keys()) == [None]
        assert source == "none"


class TestEntityKeyTaggingSideEffects:
    def test_dict_txs_are_tagged_with_their_resolved_key(self):
        txs = [_tx("0x1", decoded_logs=[_supply_event(MARKET_A, 100)])]
        bucket_by_entity(txs)
        assert txs[0]["_entity_key"] == MARKET_A
        assert txs[0]["_entity_key_source"] == "heuristic"
