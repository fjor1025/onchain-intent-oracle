# Fix pass — 2026-07-20

This documents everything fixed in this pass, following up on a code review
(`onchain-intent-oracle-review.md`) plus additional issues found while
verifying and fixing that review's findings.

## From the original review

1. **Dead agent pipeline / unused TraceFetcher (critical).**
   `cli.py` now actually calls `TraceFetcher.fetch_trace()` /
   `.fetch_state_diff()` and `RPCManager.get_transaction_receipt()` for every
   transaction (`enrich_transactions()`), instead of constructing them and
   never using them. The 6-agent LangGraph workflow is now wired in as an
   opt-in `--agents` flag (see "New: `--agents` flag" below) — it was fully
   unreachable code before, and turned out to also be **broken** (see item
   below), so simply importing it wasn't enough.

2. **State machine collapsed to ~1 state per transaction.**
   `_compute_state_fingerprint` (now `_compute_storage_fingerprint`) only
   returns a fingerprint when there's real evidence of a storage change (a
   fetched state diff, or trace output) — it no longer falls back to hashing
   raw calldata, which was the root cause of a fingerprint changing between
   `transfer(a, 100)` and `transfer(a, 200)`. `StateMachineInference.infer()`
   also no longer emits a transition when the observed state didn't actually
   change.

3. **Revert/invariant mining couldn't see reverts.**
   `_check_revert_patterns` now uses the real receipt `status` (fetched via
   `get_transaction_receipt`), normalizes hex/int/bool status values
   correctly, and — critically — **skips** transactions with no receipt
   available rather than defaulting them to "success". A "never reverts"
   invariant can no longer be asserted from zero evidence. The check is also
   generalized to a "usually reverts" tier (≥80% revert rate) instead of only
   all-or-nothing.

4. **`ConflictReconciler` crash.** Added the missing
   `from collections import defaultdict`. Added
   `tests/test_analysis/test_conflict_reconciler.py`, since this module had
   zero test coverage before.

5. **Wrong/malformed proxy storage slots.** Recomputed and fixed
   `EIP1822_LOGIC_SLOT` (keccak256("PROXIABLE")) and
   `OPEN_ZEPPELIN_IMPLEMENTATION_SLOT` (was truncated to 28 bytes; now the
   correct 32-byte `keccak256("org.zeppelinos.proxy.implementation")`,
   verified against a real deployed contract's source).

6. **Dead Etherscan-family integration.** Migrated `chains.py` and
   `source_resolver.py` from the deprecated per-chain V1 endpoints to the
   unified V2 endpoint (`api.etherscan.io/v2/api?chainid=...`).

7. **Sequential block fetching.** `fetch_transactions_for_range` now fetches
   blocks concurrently (bounded by a semaphore), instead of one
   `eth_getBlockByNumber` call at a time. The existing per-provider rate
   limiter still paces the actual request rate, and multiple configured RPC
   URLs are now used in parallel via round-robin instead of sitting idle
   between sequential awaits.

8. **Async/sync mixing.** `SignatureDecoder` now has non-blocking
   `adecode`/`adecode_trace` methods (using `httpx.AsyncClient`) that the CLI
   pipeline uses instead of the blocking `urllib` call. `CacheLayer.set()` now
   accepts real `chain_id`/`contract_address` instead of hardcoding them to
   `0`/`""`.

9. **Over-aggressive RPC health check.** `RPCManager.request()` now only
   marks a provider unhealthy on actual connectivity failures (`httpx.HTTPError`,
   `ConnectionError`, `TimeoutError`, `OSError`), not on a normal
   application-level JSON-RPC error (e.g. `execution reverted` from one bad
   `eth_call`).

10. **Repo hygiene.** Removed the committed `README (3).md` and
    `onchain-intent-oracle.zip` from git; added patterns to `.gitignore` to
    stop them recurring. Fixed the Quick Start install command (there never
    was, and still isn't, an `ml` extra — those dependencies are already in
    the base `dependencies` list).

## Found during this pass, not in the original review

- **The `agents` package didn't actually import.** `summarizer.py`'s fallback
  markdown block was written as a Python f-string containing literal Jinja2
  syntax (`{% for %}` / `{{ }}`), which is not valid Python — a guaranteed
  `SyntaxError` on import, plus a missing `import json`. Since
  `agents/__init__.py` chains through `graph.py` → all six node modules, this
  took down the *entire* `agents` package the moment anything tried to import
  it — not just "dead code", genuinely broken code.
- **CWD-relative template paths in every agent node.** All six node modules
  did `FileSystemLoader("src/onchain_intent_oracle/agents/prompts")` — a path
  relative to the process's current working directory, not the package. This
  only worked if `oio` was run from the repo root; from anywhere else
  (the normal case for an installed CLI) it would raise a Jinja2
  `TemplateNotFound`. Fixed to resolve relative to `__file__`.
- **`InvariantMiner`/`ConflictReconciler` field-name mismatch.** The analysis
  code was written against dict keys (`"method"`, `"from"`) that only exist on
  the raw JSON-RPC-shaped tx dicts the CLI builds — not on the `Transaction`
  model's attributes (`method_name`, `from_address`) that the agent pipeline
  and tests use. Fed a `Transaction` object, every lookup silently fell
  through to a falsy default, so `InvariantMiner.mine()` produced **zero**
  access-control/caller-consistency invariants with no error at all. Added a
  `_mtx_get()` helper that tries both naming conventions.
- **`ConflictReconciler` was never called by the CLI at all.** `conflicts` in
  the JSON/markdown output was hardcoded to
  `{"conflicts": [], "omissions": [...], "weakenings": [...], "security_gaps": []}`,
  with `omissions`/`weakenings` recomputed ad hoc in `cli.py` in a way that
  duplicated (and diverged from) `ConflictReconciler`'s own logic — meanwhile
  the actual conflict-detection logic (comparing a design doc's claims to
  observed behavior) was unreachable. Added a `--design-doc PATH` option to
  `oio analyze` and wired `ConflictReconciler` into `_run_analysis` for real,
  via small adapters (`_tx_dict_to_model`, `_invariant_dict_to_model`) that
  convert the CLI's dict-shaped data into the `Transaction`/`Invariant` model
  objects `ConflictReconciler` expects.
- **7 pre-existing test failures** in `test_state_machine.py` and
  `test_invariant_miner.py` — tests written against features/shapes that were
  never actually implemented (`StateMachine.contract_address`,
  `_compute_storage_fingerprint` with inc/dec direction tags, a
  "monotonicity" invariant check that didn't exist, `Invariant`
  model objects with enum `.type` instead of the dicts the pipeline actually
  relies on). Resolved by: adding `contract_address` to the `StateMachine`
  model, rewriting the fingerprint algorithm to encode real inc/dec/eq
  direction per changed slot (using old/new values now preserved through
  enrichment), implementing `_check_monotonicity`, and updating the three
  `InvariantMiner` tests to use dict access (`inv["type"]`) rather than
  migrating `mine()`'s return type to model objects — the latter would break
  the CLI pipeline and both output generators, which all consume the dict
  shape directly and `json.dumps` it as-is.
- **Missing `pytest-mock` dev dependency** — `test_proxy_detector.py`'s
  `mocker` fixture errored on every test (ERROR, not FAIL) because
  `pytest-mock` was never declared in `pyproject.toml`'s `dev` extra.

## New: `--agents` flag

`oio analyze <address> --block-range A:B --agents` now runs the six-agent
LangGraph workflow after the direct analysis pipeline, using the direct
pipeline's output (transactions, state machine, invariants, patterns,
conflicts) as the agents' input. It requires `ANTHROPIC_API_KEY` for full
effect (richer LLM-narrated `observed_design.md` / `property_candidates.md`);
without a key it's still safe to pass — each node falls back to its
deterministic non-LLM path (this fallback path is what's actually been
exercised/verified in this pass, since no LLM key was available in the
environment this fix was made in). The default (`--agents` omitted) behavior
is unchanged and does not require any API key.

## What's still open

- The `--agents` LLM path itself (the actual Claude-narrated output, not the
  fallback) hasn't been exercised against a live API key — only the
  mechanical wiring (imports, template loading, graph execution, state
  threading) has been verified.
- No load/perf testing was done on the concurrent block-fetching change
  against a real high-volume RPC provider; the concurrency cap
  (`DEFAULT_BLOCK_FETCH_CONCURRENCY = 25`) is a reasonable default, not a
  tuned one.
