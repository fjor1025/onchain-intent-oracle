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

# Fix pass — 2026-07-20 (continued)

Follow-up session: wired in the three modules previously flagged as
unexercised/unwired, load-tested the concurrent pipeline, and did the
"anything unexercised is suspect" audit that follow-up implied. Found and
fixed several more real bugs in the process — most were the same class of
bug (dict-vs-model mismatches, or things that "succeed" while silently doing
nothing) as everything found in the original pass.

## Wired in

- **`SourceResolver`** — `oio analyze` now resolves the contract's (or, if
  it's a proxy, the implementation's) verified ABI and uses it for
  authoritative method decoding (selectors computed directly via
  `keccak256(signature)`, verified against known values in tests) *before*
  falling back to the 4byte.directory guess. Also derives real
  `contract_type`/`standards` (ERC-20/721/1155 heuristics) instead of the old
  hardcoded `"unknown"`/`[]`. Added `close()`/async-context-manager support
  for the previously-leaked `httpx.AsyncClient`. 11 new tests.
- **`AnomalyDetector`** — wired in exactly like `PatternClustering` was (via
  the same `model_txs` adapter); `anomalies` in the output is real now.
  Smoke-tested with a deliberately anomalous transaction (unseen caller +
  unseen method + 1000 ETH value) — correctly flagged all three signals.
- **`--depth`** — now has real, concrete semantics instead of being inert:
  `quick` skips ABI resolution and trace/state-diff enrichment (keeps the
  cheap, always-supported receipt fetch, so revert detection still works);
  `standard` is the existing full behavior; `deep` doubles enrichment
  concurrency and widens the evidence-tx sample from 20 to 100. Verified all
  three paths actually differ via call-count assertions. Added validation so
  an invalid value fails loudly instead of being silently ignored.

## More bugs found via the "treat unexercised code as suspect" audit

- **`PatternClustering.cluster()`** was still crashing on any run with 5+
  transactions (same dict-vs-`Transaction`-model mismatch as
  `InvariantMiner`/`ConflictReconciler` from the original pass) — it just
  hadn't been caught yet because every real run so far had `tx_count` below
  its `min_samples=5` threshold. Fixed by routing it through the same
  dict→model adapter as `ConflictReconciler`.
- That then exposed a second bug: DBSCAN's cluster labels are
  `numpy.int64`, which `json.dumps(..., default=str)` would silently
  stringify (`0` → `"0"`) instead of erroring. Fixed by casting to plain
  `int` at the source.
- **The default embedding backend was guaranteed to fail regardless of local
  setup.** `embedding_model` defaults to `"nomic-embed-text"` (Ollama-only),
  but `langchain-ollama` (the Python client needed to talk to Ollama at all)
  was never a declared dependency — `pip install -e .` would never install
  it, so even a user with Ollama running locally would still hit
  `ollama_package_not_installed`. Added `langchain-ollama` to
  `pyproject.toml`.
- **Zero-vector embedding fallback silently poisoned the RAG database.**
  `EmbeddingProvider.embed()`/`embed_query()` returned an all-zero vector
  when no backend was available, instead of erroring. A zero vector's cosine
  distance to anything is `NaN`, and pgvector's `ivfflat` index silently
  drops every row when ordering by a `NaN` distance — confirmed against a
  real Postgres+pgvector instance. So `add_documents()` reported success and
  `search()` silently returned zero results forever, with nothing anywhere
  indicating why. Fixed: raises `EmbeddingUnavailableError` immediately with
  an actionable message instead.
- **The `ivfflat` index was also just a bad fit for this table's real size**,
  independent of the NaN issue — confirmed directly with real (non-zero,
  non-NaN) vectors: the same `ORDER BY ... LIMIT 5` query returned all 5
  expected rows via a full table scan but only 1 via the index. Removed the
  index from `init-db.sql`; a sequential scan is already fast at this table's
  realistic size (a curated knowledge base, not a bulk store).
- **`populate_kb.sh`** had the same nonexistent `.[ml]` extra bug the README
  had (already fixed there in the original pass, missed in this script).
  Fixed.
- **`agents/tools/__init__.py` raised `ModuleNotFoundError` the moment
  anything imported it** — it imported `DeFiPatternTool` and
  `EvidenceFetchTool` from `defi_patterns.py`/`evidence_fetch.py`, neither of
  which exist as files. Nothing in the live `--agents` execution path
  imports this package, which is why it went unnoticed. Fixed by only
  exporting what actually exists (`FVPatternLookupTool`) rather than
  inventing unspecified implementations for the other two.
- **`llm_model` defaulted to a stale model string**
  (`"claude-sonnet-4-20250514"`), and all five agent nodes that call
  `llm.invoke()` other than `data_collector.py` caught the resulting failure
  with a bare `except Exception: pass` — completely silent, no log line at
  all. So a user who set a valid `ANTHROPIC_API_KEY` and ran `--agents` would
  have silently gotten the exact same output as running with no key at all,
  with zero indication why. Fixed the default model string and added
  `logger.error(...)` to all five nodes' exception handlers, matching the one
  node (`data_collector.py`) that already did this correctly.

## Load-testing

Simulated the README's own `18000000:18001000` (1000-block) example with
realistic per-call latency (50ms/call) via a mocked RPC:
- Completed in 2.33s, vs. a theoretical ≥50s for block-fetching alone under
  the old sequential code.
- Verified the concurrency semaphore is actually enforced (max 25 concurrent
  in-flight requests observed, exactly matching the configured cap — not
  unbounded, not under-utilized).
- Verified graceful degradation under a flaky/slow provider (some blocks
  erroring, some slow): completed without hanging, recovered all txs from
  the blocks that succeeded.
- Full result stayed JSON-serializable throughout, confirming the numpy
  int64 fix holds at scale too.

## What's still genuinely open

- **`FVPatternLookupTool`/the RAG knowledge base is real, working
  infrastructure with no current consumer** — it's never instantiated or
  bound to the LLM anywhere in the agent pipeline, so `populate_kb.sh`
  currently has zero effect on `--agents` output. Wiring it in (binding the
  tool to the LLM, updating prompts, handling the tool-call loop in
  LangGraph) is a real feature addition, not a bug fix, and wasn't attempted
  here.
- **The actual Ollama "happy path" (real embeddings, real semantic search
  quality) is unverified** — this sandbox can install the Ollama Python
  client and even the Postgres/pgvector server, but can't reach Ollama's
  model registry to pull actual model weights. The fix was verified with a
  crude synthetic embedding function instead, which is enough to confirm the
  `VectorStore`/index/query plumbing itself is correct, but not embedding
  *quality*.
- **`models/evidence.py`'s `Evidence`/`EvidenceType` classes are unused
  anywhere in the codebase** — not broken, just dead scaffolding. Left as-is
  rather than guessing at an intended integration point.
- **`--agents`' actual LLM-narrated output quality is still unverified**
  against a live API key, same caveat as the original pass — only the
  mechanical wiring and (now) the model-string/error-visibility bugs around
  it have been addressed.

# Fix pass — 2026-07-22: event-log ingestion (Fix 1 of the accuracy-remediation spec)

Diagnostic case: running `oio analyze` against Morpho Blue
(`0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb`) on a block range that happened
to sit right at contract deployment produced a near-empty report — 1 state,
no invariants beyond caller/msg.value trivia — because that window has no
tracing-capable evidence at all (pure admin bootstrap calls) and, it turned
out, the pipeline had no way to fall back to anything else even though a much
richer evidence source was one function call away the whole time.

## Root cause

**`RPCManager.get_logs()` was fully implemented — correct provider-limit
chunking, address/topic filtering, all of it — and was never called anywhere
in `cli.py` or the analysis pipeline.** Same disease as the already-documented
`FVPatternLookupTool`: real, working, unreachable code. Two contributing gaps
compounded it: there was no event-topic0 resolver (the log-decoding analog of
`SignatureDecoder`'s function-selector resolution), and the `Transaction`
model's `logs`/`decoded_events` fields existed but were never populated by
anything.

## Fix

- Added `source_resolver.abi_to_event_map()` (topic0 → event descriptor,
  computed authoritatively from a verified ABI's own event signatures via
  `keccak256`, mirroring the existing `abi_to_selector_map`).
- Added `ingestion/log_decoder.py` (`LogDecoder`): resolves topic0 via
  verified ABI → a small built-in table of common event shapes → an open
  signature-hash directory → `"unresolved"` (never fabricated), and
  ABI-decodes both indexed (topic-word) and non-indexed (data-blob) args into
  typed values. Handles the genuine ambiguity that indexed-ness doesn't
  affect a signature's topic0 hash (e.g. ERC-20 vs. ERC-721 `Transfer` share
  a topic0) by disambiguating built-in candidates against the log's actual
  topic count. Dynamic-typed indexed args (string/bytes/array) are correctly
  surfaced as their keccak256 hash only, never presented as the real value —
  the EVM itself discards the preimage. Added `models/log.py`'s `DecodedLog`
  with an explicit three-way confidence/decode-error distinction
  (`unresolved` topic0 vs. resolved-name-but-`decode_error` vs. fully
  decoded) so a failed decode is never silently folded into either "no
  evidence" or "confirmed transition" — the exact class of silent-degenerate
  bug the zero-vector RAG issue above already burned this project on once.
- Wired `RPCManager.get_logs()` into `_run_analysis` (new
  `fetch_and_decode_logs()`/`summarize_decoded_logs()` helpers in `cli.py`),
  running at **every** `--depth` level, gated only behind a new `--no-logs`
  opt-out — unlike trace/state-diff enrichment, `eth_getLogs` needs no
  `debug_*`/`trace_*` RPC support, so it's the one evidence channel available
  on every provider tier.
- `StateMachineInference._compute_storage_fingerprint` now accepts a
  successfully-resolved decoded log as a second, equally-legitimate evidence
  channel when no state-diff/trace evidence exists — fingerprinted on event
  *names* only (not argument values), deliberately mirroring the state-diff
  branch's own inc/dec/eq direction-only granularity, so this doesn't
  reintroduce the "one state per call" bug already fixed once for the
  trace-based path via a new log-based back door.
- `InvariantMiner` gained `_check_event_argument_consistency`, the log-driven
  counterpart to `_check_access_control`: flags a dominant (≥95%, n≥3)
  argument value across observed instances of the same decoded event.
- `observed_design.json` gained a `decoded_logs` summary (total logs, counts
  by confidence tier, `unresolved_count`, counts by resolved event name);
  `observed_design.md` gained an "Observed Events (from logs)" section that
  states the unresolved count up front rather than only reporting successes.
- Corrected the README line claiming "event logs aren't currently fetched or
  analyzed by this pipeline at all" — now describes what's actually wired.

## Confirmed

- 16 new tests (`tests/test_ingestion/test_log_decoder.py`,
  `tests/test_cli.py`, plus additions to `test_state_machine.py` and
  `test_invariant_miner.py`): builtin-table resolution, verified-ABI priority
  over builtin, ERC-20-vs-721 `Transfer` disambiguation by topic count,
  dynamic-indexed-arg hash-only handling, decode-error-vs-unresolved
  distinction, `get_logs` actually being invoked (it wasn't, before this),
  correlation of decoded logs back to their owning tx, graceful degradation
  when a provider's `eth_getLogs` call fails outright, a state transition
  grounded entirely in decoded logs with zero trace/state-diff evidence, an
  unresolved log correctly failing to ground a transition, log-based
  fingerprints ignoring argument magnitude (regression guard for the
  already-fixed one-state-per-call bug), and the log-argument-consistency
  invariant check correctly ignoring unresolved/decode-failed/hash-only args.
- Full suite: 48 passed, 1 skipped (pre-existing, unrelated), zero
  regressions against the 32 tests that passed before this change.

## What's still open (per the remediation spec's own scope)

- Calldata *argument* decoding (Fix 2), per-entity/singleton-market bucketing
  (Fix 3), block-range activity preflight (Fix 4), and explicit
  trace-coverage-vs-provider-limitation surfacing (Fix 5) are separate,
  not-yet-implemented items in the same spec — this pass is Fix 1 only.
- The signature-directory fallback (`_adirectory_lookup`, 4byte.directory's
  event-signature endpoint) is implemented but unverified against the real
  service in this environment (the sandbox's network egress allowlist
  doesn't include it) — only the local resolution paths (verified ABI,
  built-in table, unresolved) have been exercised end-to-end. It fails
  closed (falls through to `"unresolved"`) on any network error, so this
  doesn't block correctness, just means that specific fallback tier is
  untested against the live service.
- Not yet re-run against real Morpho Blue on-chain data end-to-end in this
  environment for the same reason (no RPC egress here) — validated via unit
  tests with realistic fixture data instead, per the acceptance criteria in
  the remediation spec. Re-running the actual `oio analyze` command against
  a real RPC endpoint on a usage-era block range is the natural next
  validation step once network access allows it.

# Fix pass — 2026-07-22 (continued): calldata argument decoding (Fix 2)

## Root cause

Nothing in the codebase ever decoded calldata *argument values* — only the
method name. `abi_selectors` (built at the top of `_run_analysis`) was a
`{selector: name}` map; `SignatureDecoder.decode_trace()` returned a name and
a raw hex blob. This blocks Fix 3 (per-entity bucketing for
singleton-multiplexed contracts like Morpho Blue) outright: you can't group
calls by "which market" without decoding the argument that says which
market.

**Found and fixed a second, more serious bug while building this:**
`abi_to_selector_map`/`abi_to_event_map` (added in the previous pass) computed
selectors/topic0s by reading each ABI input's `"type"` field directly. For a
struct (tuple) parameter, real Etherscan-family ABI JSON represents that as
`{"type": "tuple", "components": [...]}` — the literal string `"tuple"`, not
the expanded `(type1,type2,...)` Solidity actually hashes into the selector.
Confirmed via direct hash comparison: `createMarket((address,address,
address,address,uint256))` (Morpho Blue's real `createMarket(MarketParams)`
shape) hashes to selector `0x8c1358a2`; the naive `createMarket(tuple)`
string hashes to `0x7495d9fa` — completely different function IDs. So any
function or event with a struct argument would have silently resolved to the
wrong selector/topic0 the moment a real ABI with one was fed through Fix 1's
own code. This is exactly the kind of untested-code-is-suspect bug the
"anything unexercised is suspect" audit from an earlier pass was written to
catch, caught the same way here: by actually testing against a struct-typed
fixture instead of only flat-primitive ones.

## Fix

- Added `ingestion/abi_utils.py`: `abi_type_string()` recursively expands
  `tuple`/`tuple[]`/`tuple[3]` types via their `components`, correctly
  handling nested structs; `split_top_level_types()` splits a
  comma-joined type-string on top-level commas only (a nested tuple's
  internal commas must not be treated as argument separators); shared
  `normalize_decoded_value()` (moved out of `log_decoder.py`, which
  previously had its own private copy).
- `abi_to_selector_map`/`abi_to_event_map` (`source_resolver.py`) now both go
  through `abi_type_string()` instead of reading `"type"` directly — fixes
  the struct-selector/topic0 bug for both calldata and log decoding.
- Added `abi_to_function_map()` (`source_resolver.py`), the calldata analog
  of `abi_to_event_map()`: `{selector: {name, signature, param_names,
  type_strings}}`, with `type_strings` pre-expanded so a decoder never needs
  to know anything about the ABI JSON's `components` shape.
- Added `ingestion/calldata_decoder.py` (`CalldataDecoder`): resolves via
  verified ABI (`"verified_abi"`, authoritative, real param names) → a
  resolved signature string from `SignatureDecoder`'s builtin table or
  4byte.directory fallback (`"selector_signature_only"`, positional
  `arg0`/`arg1`/... names, since a directory hit doesn't carry real ones) →
  `"unresolved"` (never fabricated). Argument-decode failures (malformed
  calldata, a selector collision, a proxy-forwarded call whose calldata
  doesn't match the resolved target's own ABI) keep the resolved method-name
  claim but report an explicit `decode_error`, mirroring the log decoder's
  three-way confidence/decode-error distinction from Fix 1 — same rationale,
  same shape, deliberately kept consistent between the two decoders.
- Wired into `cli.py`'s method-resolution loop (previously computed `method`
  only): now also computes `tx["decoded_args"]` via `CalldataDecoder`, and
  resolves the *full* signature via `sig_decoder.adecode()` in the
  no-ABI-match fallback path instead of `adecode_trace()`, which discarded
  the type info this fix needs. Populated into the previously-unused
  `Transaction.decoded_input` field (same "scaffolded but never filled in"
  pattern `logs`/`decoded_events` were in before Fix 1). Added
  `summarize_decoded_calls()` (mirrors Fix 1's `summarize_decoded_logs()`) →
  new `decoded_calls` section in `observed_design.json` and a one-line
  coverage summary in `observed_design.md`.

## Confirmed

- 14 new tests: `abi_type_string` struct expansion, the exact wrong-vs-right
  selector comparison above as a regression guard, `abi_to_function_map`
  correctness, `CalldataDecoder` against a flat-args ABI, against the
  Morpho-Blue-shaped struct-args ABI end-to-end (encode → decode round trip,
  including verifying `lltv`/`loanToken` land correctly inside the decoded
  tuple), the selector-signature-only fallback path, the nested-tuple
  top-level-comma-splitting edge case (Uniswap-style
  `exactInputSingle((...))`), unresolved/malformed-data/no-args cases, and
  `summarize_decoded_calls`'s unresolved/decode-error visibility.
- Full suite: 62 passed, 1 skipped (pre-existing, unrelated), zero
  regressions against the 48 that passed after Fix 1.

## What's still open

- Fix 3 (per-entity bucketing) can now actually be built on top of this —
  `tx["decoded_args"]["args"]` has real typed values (including struct
  fields) to extract an entity key from — but hasn't been implemented yet.
- Same real-RPC caveat as Fix 1: not re-run against live Morpho Blue calldata
  in this environment (no RPC egress here); validated via realistic fixture
  data (including a MarketParams-shaped struct arg matching Morpho Blue's
  actual interface) instead.

# Fix pass — 2026-07-23: per-entity state/invariant bucketing (Fix 3)

## Root cause

`StateMachineInference.infer()` and `InvariantMiner.mine()` both treat "the
contract address" as one behavioral entity, building a single chain/set
across every transaction observed. For a singleton-multiplexed contract --
Morpho Blue's markets, Uniswap V3's per-position NFTs, any vault factory's
per-vault state -- this necessarily blends unrelated state spaces into one
state machine that doesn't correspond to anything real. This was always
going to be the pipeline's next real accuracy bottleneck once Fix 1/2 gave
it enough evidence to actually see many entities' worth of activity in one
run.

## Fix

- Added `analysis/entity_key.py`: `looks_like_entity_id_name()` (name
  pattern match: `id`, `marketId`, `poolId`, `vaultId`, `tokenId`,
  `trancheId`, or generically `*Id`/`*_id`) and `bucket_by_entity()`, which
  groups transactions by an inferred entity key using two strategies:
  1. **Name+type heuristic**: a decoded call or log argument typed
     `bytes32`/`uint256` whose name matches the pattern above. Verified
     against the real Morpho Blue interface: even though
     `supply`/`borrow`/`withdraw`/`repay` take a `MarketParams` struct (not
     a bare id) on the *call* side, the corresponding `Supply`/`Borrow`/
     `Withdraw`/`Repay` *events* all carry `Id indexed id` directly -- so
     this heuristic alone covers Morpho Blue in practice via the event side,
     confirmed by `TestNameHeuristicFromLogs.test_buckets_by_event_id_across_markets`.
  2. **Struct-hash heuristic**: for a call decoding a single struct argument
     (`CalldataDecoder._struct_hash`, added to Fix 2's decoder specifically
     for this), `keccak256(abi.encode(that struct))` -- exactly Morpho's own
     `Id.wrap(keccak256(abi.encode(marketParams)))` idiom -- is a
     *candidate* key, but only promoted to a real entity key when it matches
     an id value actually observed elsewhere in the same run (via strategy
     1). A bare "we hashed a struct" claim has no grounds to assert this
     contract actually derives its id that way; a hash that matches
     something the contract itself emitted as `id` does. Never promoted on
     its own -- see `TestStructHashHeuristic.test_not_promoted_when_never_observed_as_an_id_elsewhere`.
  - Explicit `--entity-key <name>` escape hatch (CLI flag) that disables
    both heuristics and matches only the named argument, case-insensitively
    -- and correctly does *not* fall back to the heuristics for a tx lacking
    that exact arg (would silently override the user's explicit choice
    otherwise).
  - Flat, non-multiplexed contracts produce zero entity-key candidates and
    land entirely in the `None` bucket -- the pass-through/regression-safe
    default, confirmed by `TestFlatContractRegression`.
  - Contract-wide admin calls (e.g. Morpho's `enableIrm`/`enableLltv`/
    `setOwner` -- none of which are about any one market) correctly land in
    the `None` bucket alongside per-entity buckets rather than being
    force-fit into one or dropped -- `test_admin_calls_with_no_entity_stay_in_none_bucket_alongside_entities`.
  - Unresolved/decode-failed logs and dynamic-typed indexed args (hash-only,
    not the real value -- see Fix 1) never ground an entity key, same
    evidence-gating discipline as everywhere else in this pipeline.
- `CalldataDecoder.decode()` (Fix 2) now also returns `arg_types` (per-arg
  ABI type, needed for the bytes32/uint256 type filter) and `struct_hash`
  (the candidate above). `DecodedLog` (Fix 1) gained the same `arg_types`
  field for parity on the log side.
- Wired into `cli.py`: `bucket_by_entity()` runs after the calldata/log
  decoding loop; `compute_per_entity_results()` (new, standalone/testable)
  computes one `StateMachineInference`/`InvariantMiner` pass per entity,
  ranked by tx count and capped at `MAX_ENTITIES_IN_OUTPUT` (20) for
  rendering. The existing aggregate pass is unchanged and still runs
  unconditionally -- multi-entity output is *additive*, not a replacement,
  since some claims ("never accepts ETH") are genuinely contract-wide.
  `observed_design.json` gained an `entities` section
  (`entity_key_source`, `entities_observed`, `entities_shown`,
  `cross_entity_warning`, `per_entity: [...]`); `observed_design.md` gained
  an explicit cross-entity warning right after the aggregate state machine
  (not buried) plus a "Per-Entity Analysis" section breaking out each
  entity's own state machine/invariants.

## Confirmed

- 20 new tests: `tests/test_analysis/test_entity_key.py` (13 -- name-pattern
  matching, flat-contract regression guard including the "id"-named-but-
  address-typed rejection, the Morpho-shaped name-from-logs case across
  multiple markets, admin calls correctly landing in the aggregate bucket
  alongside entity buckets, unresolved/decode-error/hash-only args never
  grounding a key, both struct-hash promotion and non-promotion cases,
  forced `--entity-key` including its case-insensitivity and its refusal to
  fall back to heuristics) plus `tests/test_cli.py`'s
  `TestComputePerEntityResults` (2 -- a full multi-market run producing
  separate, correctly-ranked state machines end to end, and the flat-
  contract zero-per-entity-output regression guard) and 5 more covering the
  `CalldataDecoder`/`DecodedLog` `arg_types`/`struct_hash` additions.
- Full suite: 77 passed, 1 skipped (pre-existing, unrelated), zero
  regressions against the 62 that passed after Fix 2.

## What's still open (per the remediation spec's own scope)

- Block-range activity preflight (Fix 4) and explicit trace-coverage-vs-
  provider-limitation surfacing (Fix 5) remain unimplemented.
- The entity-key name-pattern list is a fixed heuristic (not learned or
  configurable beyond the single `--entity-key` override) -- a protocol
  whose id-like argument doesn't match any of `id`/`*Id`/`*_id` and isn't
  corroborated by the struct-hash heuristic either will still get
  whole-contract (aggregate-only) treatment. This is a known, intentional
  boundary: the alternative (guessing harder) trades false negatives for
  false positives, and false positives are worse for a formal-verification
  feeder pipeline.
- Same real-RPC caveat as every prior pass in this file: not re-run against
  live Morpho Blue data end-to-end in this environment (no RPC egress here);
  validated via realistic fixture data (including the actual
  Supply/Borrow-event-carries-`id` shape Morpho Blue really uses) instead.

# Fix pass — 2026-07-23 (continued): block-range activity preflight (Fix 4)

## Root cause

`oio analyze` would run -- and present the result with the exact same
confidence formatting as a well-sampled run -- on a block range that's
structurally incapable of representing a contract's real behavior. This is
literally what happened on the original Morpho Blue diagnostic run: 12
transactions, all admin-config calls (`enableIrm`/`enableLltv`/`setOwner`),
one caller, ~324 blocks after mainnet deployment. Nothing checked whether
the sample looked representative before analyzing it; the one related signal
that existed (`InvariantMiner._check_caller_consistency`'s "possible test or
controlled environment" note) was a single invariant bullet buried among
dozens of others, not a structural warning a reader could not miss.

**Found a third instance of the "implemented but never called" bug class**
while building this: `SourceResolver.get_contract_creation()` -- an
Etherscan-family `getcontractcreation` API wrapper -- was fully implemented
and never called anywhere, same as `RPCManager.get_logs()` before Fix 1 and
`FVPatternLookupTool` in the RAG module. It's exactly what's needed for the
`possible_bootstrap_window` check below.

## Fix

- Added `analysis/sample_quality.py`: `assess_sample_quality()` computes
  four *independent* boolean flags (deliberately not a single pass/fail
  verdict, since a bot spamming one function and "too few transactions" are
  different problems that both matter):
  - `single_caller_dominant` (≥90% of tx from one address, n≥3 to avoid a
    redundant flag on samples `low_tx_count` already catches)
  - `low_tx_count` (<20 tx observed)
  - `narrow_function_diversity` (≤3 distinct *resolved* methods called
    across the whole range -- independently computed from tx count
    specifically so many calls to one function doesn't slip past a
    tx-count-only check; threshold tuned to 3, not the spec's example value
    of 2, because the real Morpho Blue diagnostic case has exactly 3 admin
    methods and a threshold of 2 would have missed it -- caught by testing
    against the actual diagnostic shape rather than an assumed threshold)
  - `possible_bootstrap_window` (range starts within ~5000 blocks of the
    contract's own creation block, via the newly-wired
    `get_contract_creation()` above; correctly reports "unknown" via `None`
    rather than `False` when creation-block data isn't available, and
    correctly doesn't fire on a range that starts *before* the creation
    block -- that's malformed input, not evidence of a bootstrap window)
  - `format_sample_quality_warning()` renders these into a one-line,
    stderr-friendly summary naming every reason that fired.
- Wired into `cli.py`: `_get_contract_creation_block()` (new) calls
  `get_contract_creation()` and falls back to a receipt lookup
  (`RPCManager.get_transaction_receipt`, already used elsewhere) when the
  explorer response doesn't include a block number directly, degrading to
  `None` on any failure. The calldata-decoding loop was moved to run
  *before* trace/state-diff enrichment (previously ran after) specifically
  so `narrow_function_diversity` has real decoded method names to check
  *before* the expensive enrichment step -- the preflight check and its
  stderr warning now both run before that step, not after, matching the
  spec's explicit ask to flag a bad range before waiting through a full
  `--depth deep` run.
- None of these flags block the run -- consistent with the rest of this
  pipeline's "keep going with whatever real evidence exists, be honest about
  its limits" philosophy.
- `observed_design.json` gained a `sample_quality` section (every flag plus
  its supporting numbers). `observed_design.md` gained a `> ⚠️ **Sample
  quality warning**` blockquote at the very top of the document -- above
  Overview, above everything -- listing every fired reason in plain
  language, not buried as an invariant bullet.

## Confirmed

- 12 new tests: `tests/test_analysis/test_sample_quality.py` (8 -- the exact
  Morpho Blue diagnostic shape correctly firing all four flags with a
  warning message naming every reason, a large/diverse/multi-caller sample
  correctly showing zero flags, narrow-function-diversity firing
  independently of tx count, single-caller requiring a minimum sample size,
  an unknown creation block correctly yielding "unknown" rather than a false
  positive, a range starting before the creation block correctly not
  counted as a bootstrap window, and the empty-tx-list edge case) plus
  `tests/test_cli.py`'s `TestGetContractCreationBlock` (4 -- the
  block-number-present path, the receipt-lookup fallback path, and both
  failure modes degrading to `None` rather than raising).
- Manually rendered `observed_design.md` against the *exact* real Morpho
  Blue diagnostic shape (12 tx: 2 `enableIrm` + 9 `enableLltv` + 1
  `setOwner`, all from one address, 324 blocks post-creation) and confirmed
  all four flags fire with the correct blockquote rendering at the top of
  the document.
- Full suite: 89 passed, 1 skipped (pre-existing, unrelated), zero
  regressions against the 77 that passed after Fix 3.

## What's still open (per the remediation spec's own scope)

- Fix 5 (explicit trace-coverage-vs-provider-limitation surfacing) remains
  unimplemented -- this pass was Fix 4 only.
- `possible_bootstrap_window`'s ~5000-block window is a fixed default, not
  learned or configurable via a CLI flag. Reasonable for L1 mainnet (roughly
  a day of blocks); a chain-aware default (e.g. scaled by block time) would
  be a natural follow-up but wasn't in the spec's explicit ask.
- Same real-RPC caveat as every prior pass in this file: not re-run against
  a live `get_contract_creation()` API call in this environment (no network
  egress to Etherscan-family explorer APIs here); the block-number-present
  and receipt-fallback code paths are both tested directly against mocked
  responses shaped like the real API's documented output, but not against
  the live service itself.

# Fix pass — 2026-07-23 (continued): explicit trace-coverage surfacing (Fix 5)

## Root cause

`"No state changes were observed"` read identically in `observed_design.md`
regardless of *why* -- whether nothing happened on-chain in the analyzed
window, or the configured RPC provider simply can't serve
`debug_traceTransaction`/`trace_transaction` at all (extremely common on
free tiers -- see the provider table in the README). The only place this
distinction existed at all was a `structlog` `debug_trace_unavailable`
warning line per failed transaction, invisible to anyone reading only the
generated report. This is the last of the five fixes from the original
remediation spec.

## Fix

- `enrich_transactions()` (`cli.py`) now tallies real per-run
  `succeeded_count`/`failed_count` for trace fetches -- not just a debug log
  line per tx -- and returns `{"attempted", "succeeded_count",
  "failed_count"}` instead of `None`.
- Added `compute_trace_coverage()` (`cli.py`): turns those raw counts into
  an explicit `reason` -- `"depth_quick"` (never attempted),
  `"provider_unsupported"` (attempted for every tx, succeeded for none --
  the strong, whole-run-pattern signal that the provider just doesn't
  support tracing, as opposed to one unusual tx), `"not_attempted"`
  (nothing to attempt, e.g. an empty tx list), or `None` when real trace
  evidence was actually obtained (the numbers speak for themselves at that
  point, no explanation needed).
- `observed_design.json` gained a `trace_coverage` section carrying all of
  the above. `observed_design.md` gained an explicit note right under the
  State Machine section stating which case applies in plain language, and,
  specifically for `"provider_unsupported"`, explicitly flags that any
  transitions shown in the state machine above are grounded in decoded
  event-log evidence (Fix 1) rather than on-chain storage changes -- a
  materially weaker but still real evidence channel, and a distinction a
  reader has no way to make on their own without this note.

## Confirmed

- 7 new tests: `compute_trace_coverage`'s four cases (`depth_quick`,
  `provider_unsupported`, genuine-success/no-reason-needed, `not_attempted`,
  and the "missing enrich_result at non-quick depth still degrades safely"
  edge case) plus `enrich_transactions`'s coverage-counting itself (mixed
  success/failure across two txs, and the `--depth quick` case correctly
  reporting `not_attempted` without ever calling `fetch_trace`).
- Manually rendered `observed_design.md` against a `provider_unsupported`
  scenario and confirmed the note renders with the correct plain-language
  explanation and the event-log-evidence caveat.
- Full suite: 96 passed, 1 skipped (pre-existing, unrelated), zero
  regressions against the 89 that passed after Fix 4.

## Where this leaves the remediation spec

All five fixes from the original accuracy-remediation spec are now
implemented: event-log ingestion (Fix 1), calldata argument decoding (Fix
2, plus the struct-selector bug it caught), per-entity bucketing (Fix 3),
block-range activity preflight (Fix 4), and this trace-coverage surfacing
(Fix 5). What's explicitly still open, per the spec's own "explicitly out
of scope" section and the "what's still open" notes accumulated across each
pass above:

- The RAG knowledge base (`rag/`) remains unwired from the agent pipeline
  (`FVPatternLookupTool`) -- same disease as every other "implemented but
  never called" bug found and fixed in this pass (`get_logs`,
  `get_contract_creation`), but explicitly out of scope per the original
  spec.
- The `--design-doc` parser is still a keyword heuristic, not semantically
  aware of the calldata/log/entity evidence the observed side can now
  produce -- flagged as the next real bottleneck once this pass landed, per
  the spec's own note that conflict-detection quality would become
  design-doc-parser-limited once the observed side got this much richer.
- Every fix in this file has the same real-RPC caveat: none of them have
  been exercised against a live RPC endpoint or live explorer API in this
  environment (no network egress here to Ethereum RPC providers or
  Etherscan-family APIs) -- all validated via unit tests against realistic
  fixture data, including data shaped to match Morpho Blue's actual,
  verified real-world interface wherever that mattered (the `MarketParams`
  struct, the `Supply`/`Borrow`/`Withdraw`/`Repay` event shapes, the real
  mainnet deployment block range). Re-running `oio analyze` against real
  Morpho Blue data end-to-end, on a corrected usage-era block range, is the
  natural next validation step for all five fixes together once network
  access allows it.

# Post-delivery fix — 2026-07-23: SignatureDecoder.adecode() concurrency bug

Not part of the original 5-fix remediation spec -- surfaced by running the
delivered patch against a fuller local test suite than this environment had
visibility into (`tests/test_ingestion/test_signature_decoder.py`, which
didn't exist in the clone this whole remediation effort was based on).

## Root cause

`SignatureDecoder.adecode()` had no request deduplication: on a cache miss,
every concurrent caller independently checked `key in self._cache` (a miss,
since none of them had populated it yet), then each independently awaited
its own `_alookup_4byte()` call. Under `asyncio.gather` -- exactly how the
pipeline calls this, once per transaction, and it's completely ordinary for
many transactions in one analyzed range to share a selector (every plain
ERC-20 `transfer` call, for instance) -- N transactions sharing one
uncached selector fired N redundant real network calls against
4byte.directory instead of 1, all racing to populate the same cache key.

## Fix

Added a per-instance `self._inflight: Dict[str, asyncio.Future]`. On a cache
miss, if a lookup for that selector is already in flight, the caller awaits
the existing future instead of starting a new one; the first caller in
registers a future, performs the real lookup, and resolves it for everyone
waiting. Cache hits are unaffected (still return immediately, no futures
touched at all).

## Confirmed

- The exact failing test now passes:
  `TestAdecodeConcurrency::test_concurrent_identical_selector_only_fetches_once`.
- 3 more concurrency edge cases added alongside it: different uncached
  selectors looked up concurrently are NOT collapsed into one call (dedup is
  keyed per-selector); a selector that resolves to `None` doesn't stay
  permanently stuck as in-flight -- a later call can retry; a cache hit never
  touches the in-flight tracking at all.
- Full suite in this environment: 100 passed, 1 skipped (pre-existing),
  zero regressions.

## Caveat

This environment's test suite (101 tests total after this fix) is smaller
than what was run locally (114 total, per the reported failure) -- this
environment's clone doesn't have full visibility into every test file in
the real repository. This fix resolves the specific reported failure and
was validated against the exact test code from the failure output, but a
full local `pytest` run after applying it is the real confirmation.
