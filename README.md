# OnChainIntentOracle (OIO)

> Extract observed behavior and dynamic design documentation from live EVM smart contracts for formal verification.

**This is a fixed/patched build.** See [CHANGES.md](./CHANGES.md) for the full list of bugs fixed and features added relative to the original — the short version is: the previous build silently produced wrong output in several places (a degenerate one-state-per-transaction "state machine", a "never reverts" invariant asserted with zero evidence, a design-doc reconciliation feature that was wired up but never actually called). This build fixes those and is meant to fail loudly or say "no evidence" rather than fabricate a confident-looking answer.

## Overview

OnChainIntentOracle bridges the gap between **static code analysis** and **dynamic on-chain behavior**. It:

- Fetches transaction history, receipts, traces, and state diffs from deployed contracts
- Infers state machines, invariants, and usage patterns from *observed* data — only from data it actually has evidence for
- Detects conflicts between a design document's claims and actual on-chain behavior
- Generates structured design documents and property candidates for formal verification tools

**Note**: OIO does not generate CVL `.spec` files or formal proofs. It produces **inputs** (design docs, property candidates, conflict reports) that are consumed by formal verification tools like Certora AutoProver.

## Quick Start

### Prerequisites

- Python 3.12+
- `uv` (Python package manager) — or plain `pip`
- RPC access (Alchemy, QuickNode, Infura, Chainstack, Tenderly, or a local node)
- Docker & Docker Compose — **optional**, only needed for the Postgres/pgvector-backed RAG knowledge base; `oio analyze` works fully without it (it falls back to a local SQLite cache)
- Anthropic API key — **optional**, only needed for the `--agents` flag's LLM-narrated output (see [Usage](#usage) below)

### Installation

```bash
# Clone repository
git clone https://github.com/your-org/onchain-intent-oracle.git
cd onchain-intent-oracle

# Install dependencies (includes test/dev tooling)
uv pip install -e ".[dev]"
```

```bash
# Optional: set up Postgres + pgvector for the RAG knowledge base
docker compose up -d
./scripts/setup_db.sh
./scripts/populate_kb.sh
```

### Configuration

Create a `.env` file in the project root:

```bash
RPC_URLS=https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY

# Optional -- only used by --agents for LLM-narrated output
ANTHROPIC_API_KEY=sk-ant-...

# Optional -- used for ABI/source lookups via Etherscan's V2 API
ETHERSCAN_API_KEY=...

# Optional -- only needed if you set up the RAG knowledge base above
DATABASE_URL=postgresql+psycopg://oio:oio@localhost:5432/oio
```

**Multiple RPC providers** (recommended — OIO round-robins across them and automatically falls back if one is unhealthy):

```bash
RPC_URLS=https://eth-mainnet.g.alchemy.com/v2/KEY1,https://ethereum-mainnet.core.chainstack.com/KEY2,https://mainnet.infura.io/v3/KEY3
```

## Usage

### Analyze a contract

```bash
oio analyze 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  --chain ethereum \
  --block-range 18000000:18001000 \
  --output ./usdc-analysis
```

**All flags** (this is the complete, actual CLI surface — run `oio analyze --help` to see it yourself):

| Flag | Required | Description |
|------|----------|-------------|
| `contract_address` (positional) | Yes | Contract address to analyze |
| `--chain` | No (default `ethereum`) | Chain name or numeric ID — see supported names below |
| `--block-range` | Yes | `start:end`, e.g. `18000000:18001000` |
| `--output`, `-o` | No (default `./oio-output`) | Output directory |
| `--depth` | No (default `standard`) | `quick` (skips ABI resolution and trace/state-diff enrichment — fastest, least evidence for the state machine, but still fetches receipts so revert detection still works), `standard` (full enrichment), or `deep` (standard, plus a larger evidence-tx sample and higher enrichment concurrency) |
| `--design-doc` | No | Path to a design doc / spec to reconcile against observed behavior (populates `conflicts` in the output — see below) |
| `--agents` | No (flag) | Also run the LLM agent pipeline for richer narrative output. Requires `ANTHROPIC_API_KEY` for full effect; safe to pass without one (each agent falls back to deterministic, non-LLM output) |

**Supported chain names**: `ethereum`, `mainnet`, `sepolia`, `goerli`, `polygon`, `mumbai`, `arbitrum`, `arbitrum-one`, `optimism`, `base`, `bsc`, `avalanche`, `fantom`, `gnosis`. You can also pass a numeric chain ID directly: `--chain 1`.

### Reconcile against a design doc

```bash
oio analyze 0xYourContract \
  --chain ethereum \
  --block-range 18000000:18001000 \
  --design-doc ./spec.md \
  --output ./analysis
```

`--design-doc` accepts a plain-text/markdown file. Parsing is a simple keyword heuristic (looks for lines mentioning "only owner"/"admin"/"role", "fee"/"cap"/"limit", "paused"/"state"/"mode", "upgrade"/"proxy", etc.) — not an LLM — so it works without any API key, but treat it as a first pass, not a substitute for reading `conflict_report.md` yourself. It's what actually populates the `conflicts` (not just `omissions`/`weakenings`) section of the output; without `--design-doc`, every observed function is reported as an "omission" by default since there's nothing to compare it against.

### Run the LLM agent pipeline

```bash
oio analyze 0xYourContract \
  --chain ethereum \
  --block-range 18000000:18001000 \
  --agents \
  --output ./analysis
```

This runs a six-node LangGraph workflow (`data_collector → state_inference → invariant_proposer → conflict_reconciler → summarizer → property_generator`) on top of the direct analysis pipeline's output, using Claude (via `ANTHROPIC_API_KEY`) to produce a richer, narrative `observed_design.md` and a `property_candidates.md`. Without a key set, it still runs (each node has a deterministic fallback), but you won't get much benefit over the direct pipeline's output.

Outputs (all runs, with or without the flags above):
- `observed_design.md` — narrative design document (use as AutoProver's design-doc input)
- `observed_design.json` — structured analysis data
- `conflict_report.md` — design vs. reality gaps (use as AutoProver's threat-model input)
- `visualizations/` — state machine diagram, call graph (Mermaid `.mmd` files)
- with `--agents`: `property_candidates.md` if the pipeline produced one

## Verifying results against Etherscan

The tool is designed to say "no evidence" rather than guess, but you should still spot-check its output against ground truth, especially before feeding it into anything downstream. The simplest way is to pull a transaction hash straight out of `observed_design.json` and cross-reference it on Etherscan:

```bash
# Pull the evidence transaction hashes out of a run's output
cat ./analysis/observed_design.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for tx in data['evidence_txs']:
    print(tx['hash'], tx['block'], tx['description'])
"
```

Then look up one of those hashes directly:

```
https://etherscan.io/tx/<hash>
```

Things worth checking on the Etherscan page against what OIO reported:

- **Status** — does Etherscan show "Success"/"Fail" matching what `invariants`/`conflicts` implied about that method's revert behavior?
- **Value** — if `INV-VAL-001` ("msg.value == 0 for all observed txs") did or didn't fire, does the actual ETH value transferred on Etherscan agree? (This check has no minimum-sample-size floor — unlike the access-control/revert/monotonicity checks, which all require at least 3 observed calls before asserting anything — so it's worth a manual check on small runs in particular.)
- **Method / function name** — if `evidence_txs` shows `"description": "unknown"`, Etherscan's "Input Data" decoded view (if the contract is verified) will usually tell you what the real function was, which tells you the 4-byte selector lookup didn't find a match rather than something being broken.
- **Proxy info** — if `proxy_info.is_proxy` is `true`, Etherscan's contract page for a verified proxy shows a "Read as Proxy"/"Write as Proxy" tab with the implementation address; compare it against `proxy_info.implementation`.

For non-mainnet chains, swap the domain: `sepolia.etherscan.io`, `arbiscan.io`, `basescan.org`, `optimistic.etherscan.io`, `polygonscan.com`, `bscscan.com` (or `.io` — check the chain's current explorer).

## Architecture

```
Inputs                    Ingestion                 Analysis
─────────────────        ──────────────            ─────────
Contract Address    ──▶  RPC Manager         ──▶  State Machine Inference
Chain ID / RPC      ──▶  Trace Fetcher       ──▶  Invariant Mining
Design Doc (opt)    ──▶  Proxy Detector      ──▶  Pattern Clustering
                    ──▶  Source Resolver     ──▶  Anomaly Detection
                                              ──▶  Conflict Reconciliation
                                                    │
                                                    ▼
                                               Agent Pipeline (opt-in, --agents)
                                               ────────────────────────────────
                                               Data Collector Agent
                                               State Inference Agent
                                               Invariant Proposer Agent
                                               Conflict Reconciler Agent
                                               Summarizer Agent
                                               Property Candidate Generator
                                                    │
                                                    ▼
                                                  Output
                                               ──────────
                                               observed_design.md
                                               observed_design.json
                                               conflict_report.md
                                               visualizations/
                                               property_candidates.md (--agents only)
```

`Source Resolver` resolves a contract's verified ABI (Etherscan-family explorers via `ETHERSCAN_API_KEY`) and uses it for authoritative method-name decoding (computed directly from the ABI's own `keccak256(signature)`) and ERC-20/721/1155 standards detection — it's skipped at `--depth quick` to save the extra network round trip, and silently falls back to a 4byte.directory best-effort guess if no key is set or the contract isn't verified. There's no separate log-indexing module — earlier versions of this diagram implied one ("Log Indexer") that was never actually built; event logs aren't currently fetched or analyzed by this pipeline at all.

## RPC Provider Setup

OIO fetches full blocks via `eth_getBlockByNumber` and filters transactions client-side — this always works on any standard JSON-RPC endpoint, no special indexing required. Trace/state-diff enrichment (used for evidence-based state machine inference) needs `debug_traceTransaction` or `trace_transaction` support, which varies a lot by provider and tier:

| Provider | Free-tier tracing | Notes |
|---|---|---|
| **Chainstack** | ✅ Yes — Debug & Trace APIs on archive nodes | Generous free monthly quota, supports custom JS tracers |
| **Tenderly** | ✅ Yes — `debug_*` and `trace_*` methods | Free account available |
| **QuickNode** | ❌ Paid only | Free trial includes it, ongoing free tier does not |
| **Alchemy** | ❌ Paid only | Free/growth tier rejects `debug_traceTransaction` with a `400 Bad Request` — you'll see this in the logs as `debug_trace_unavailable`, and it's expected, not a bug. The pipeline falls back to `trace_transaction` automatically, and to receipt-only data if that's unavailable too. |
| **Infura** | ❌ Paid only | Requires an archive add-on |
| **Local Geth/Erigon** | ✅ Full, unlimited | Best for privacy, no rate limits, and consistent trace coverage |

```bash
# Local Erigon with full tracing enabled
./erigon --chain=mainnet --http.api=eth,debug,trace

# Point OIO at it
RPC_URLS=http://localhost:8545
```

If your provider doesn't support tracing, OIO still works — `state_machine`/some invariants will just have less to go on (this is intentional degradation, not a failure: it reports what it actually observed rather than fabricating states from calldata alone).

## RAG Knowledge Base (optional, currently standalone)

```bash
docker compose up -d postgres
./scripts/setup_db.sh
./scripts/populate_kb.sh
```

**Be aware this doesn't currently affect anything `oio analyze` outputs.** `FVPatternLookupTool` (the LangChain tool that would let an agent query this knowledge base) exists but is never instantiated or bound to the LLM anywhere in `graph.py` or the six agent nodes — so populating the knowledge base has no effect on `--agents` output today. It's real, working infrastructure (see below) with no current consumer.

**Hard prerequisite, not optional despite what the default config implies**: the default `embedding_model` (`nomic-embed-text`) requires a running [Ollama](https://ollama.com) instance with that model pulled (`ollama pull nomic-embed-text`) — without it, `populate_kb.sh` now fails loudly and immediately with a clear error, rather than silently "succeeding" while writing unusable data (see below for why that used to be much worse). Alternatively, set `OPENAI_API_KEY` and `EMBEDDING_MODEL=text-embedding-3-small` (or similar) in `.env` to use OpenAI embeddings instead.

Two bugs worth knowing about if you're relying on this, both fixed in this build:
- **Zero-vector embeddings used to fail silently and poison the database.** With no embedding backend configured, the old code returned an all-zero vector instead of erroring. A zero vector's cosine distance to anything (including another zero vector) is `NaN`, and pgvector's `ivfflat` index silently drops every row when ordering by a `NaN` distance — so `add_documents()` reported success, and `search()` silently returned zero results forever, with no error anywhere pointing at why. Fixed: no embedding backend now raises `EmbeddingUnavailableError` immediately, with an actionable message.
- **The `ivfflat` index itself is a poor fit for this table's actual size.** `ivfflat` is an approximate index that partitions rows into `lists` clusters and only probes a handful per query; with a curated knowledge base of a few dozen-to-hundred documents, most real matches end up outside the probed clusters and never come back — confirmed directly: the same `ORDER BY ... LIMIT 5` query returned all 5 expected rows via a full table scan but only 1 via the index. Fixed: the index was removed from `init-db.sql` (a sequential scan over this table's realistic size is already fast; if the knowledge base ever grows into the thousands of rows, revisit with a properly-tuned HNSW index instead).

`redis` in `docker-compose.yml` is provisioned but genuinely unused anywhere in the codebase right now — it's honestly labeled "Optional" in the compose file, not a broken promise, just unbuilt.

## Output Artifacts

| File | Description | Use with |
|------|-------------|----------|
| `observed_design.md` | Narrative design document from observed behavior | AutoProver's design-doc input |
| `observed_design.json` | Structured analysis data (state machine, invariants, patterns, conflicts) | Custom tooling, the Etherscan spot-check above |
| `conflict_report.md` | Design vs. reality gaps and security concerns | AutoProver's threat-model input |
| `visualizations/` | State machine diagram, call graph (Mermaid) | Documentation, review |
| `property_candidates.md` | Candidate formal-verification properties (only with `--agents`) | Formal verification tooling |

## Integration with AutoProver

```bash
# 1. Generate observed design from on-chain data
oio analyze 0xContract --chain ethereum --block-range 18000000:18001000 --output ./analysis/

# 2. Feed into AutoProver (AutoProver generates the .spec, not OIO)
console-autoprove \
  ./project \
  src/Contract.sol:Contract \
  ./analysis/observed_design.md \
  --threat-model ./analysis/conflict_report.md \
  --max-bug-rounds 5 \
  --cloud
```

## What OIO Does vs. What AutoProver Does

| Task | OIO | AutoProver |
|------|-----|------------|
| Fetch on-chain data | ✅ | ❌ |
| Infer state machines from traces | ✅ | ❌ |
| Mine statistical invariants | ✅ | ❌ |
| Detect design/reality conflicts | ✅ | ❌ |
| Generate design documents | ✅ | ✅ (from code/docs) |
| Generate CVL `.spec` files | ❌ | ✅ |
| Run formal proofs | ❌ | ✅ |
| Generate Foundry tests | ❌ | ✅ |

OIO **complements** AutoProver by providing ground-truth observed behavior that AutoProver cannot access from code alone.

## Troubleshooting

### `403 Client Error: Forbidden` or `429 Too Many Requests`

**Cause**: RPC provider rate limit or authentication issue.
**Fix**: Configure multiple providers in `RPC_URLS` (comma-separated). OIO automatically falls back to the next healthy provider. A single genuine RPC-application-level error (e.g. one bad `eth_call`) won't take a provider out of rotation — only real connectivity failures do.

### `debug_trace_unavailable` warnings / traces not available

**Cause**: Your RPC provider doesn't support tracing on your current tier (very common on Alchemy/Infura/QuickNode free tiers — see the provider table above).
**Fix**: Not actually an error — OIO logs it and continues with receipt-only data. For full trace/state-diff coverage, use a provider with free tracing (Chainstack, Tenderly) or a local Erigon/Geth node.

### `tx_count: 0` when analyzing a known-active contract

**Cause**: Almost always means the contract is a proxy and you're (or an older build is) fetching against the implementation address instead of the proxy address — the implementation only receives internal `DELEGATECALL`s, essentially never direct transactions. Check `proxy_info.is_proxy` in the output.
**Fix**: This build fetches against the address you actually passed in, not the resolved implementation, specifically to avoid this. If you still see it, check that your RPC provider is returning full block data (`eth_getBlockByNumber` with `true` for full transactions) and that the block range actually has activity for that address — the Etherscan spot-check above is the fastest way to confirm.

### `Unknown chain: ...`

**Cause**: Chain name not recognized.
**Fix**: Use a supported chain name (see the list under [Usage](#usage)) or pass the numeric chain ID directly (e.g. `--chain 1`).

## Development

```bash
# Run all tests
pytest -q

# Run with coverage
pytest --cov=onchain_intent_oracle

# Run a specific test suite
pytest tests/test_analysis/
```

See [CHANGES.md](./CHANGES.md) for the fix history and known open items.

## License

MIT
