# OnChainIntentOracle (OIO)

> Extract observed behavior and dynamic design documentation from live EVM smart contracts for formal verification.

## Overview

OnChainIntentOracle bridges the gap between **static code analysis** and **dynamic on-chain behavior**. It:

- Fetches transaction history, traces, and state diffs from deployed contracts
- Infers state machines, invariants, and usage patterns from observed data
- Detects conflicts between design documents and actual behavior
- Generates structured design documents and property candidates for formal verification tools

**Note**: OIO does not generate CVL `.spec` files or formal proofs. It produces **inputs** (design docs, property candidates, conflict reports) that are consumed by formal verification tools like Certora AutoProver.

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose (for Postgres + pgvector)
- `uv` (Python package manager)
- RPC access (Alchemy, QuickNode, or local node)
- Anthropic API key (for LLM features)

### Installation

```bash
# Clone repository
git clone https://github.com/your-org/onchain-intent-oracle.git
cd onchain-intent-oracle

# Install dependencies
uv pip install -e ".[dev]"

# Set up database
docker compose up -d
./scripts/setup_db.sh

# Populate knowledge base
./scripts/populate_kb.sh
```

### Configuration

Create `.env` file:

```bash
ANTHROPIC_API_KEY=sk-ant-...
ETHERSCAN_API_KEY=...
RPC_URLS=https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY
DATABASE_URL=postgresql+psycopg://oio:oio@localhost:5432/oio
```

### Usage

#### Analyze a Contract

```bash
oio analyze   0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48   --chain ethereum   --block-range 18000000:19000000   --design-doc ./usdc_whitepaper.md   --threat-model ./known_attacks.md   --output ./usdc-analysis   --depth deep
```

Outputs:
- `observed_design.md` — Narrative design document (use as AutoProver `--design_doc`)
- `observed_design.json` — Structured analysis data
- `conflict_report.md` — Design vs reality gaps (use as AutoProver `--threat-model`)
- `visualizations/` — State diagrams, call graphs

#### Generate Report

```bash
oio report <run_id> --format markdown
```

## Architecture

```
Inputs                    Ingestion              Analysis
─────────────────        ─────────────          ─────────
Contract Address    ──▶  RPC Manager      ──▶  State Machine Inference
Chain ID / RPC      ──▶  Trace Fetcher    ──▶  Invariant Mining
Design Doc (opt)    ──▶  Log Indexer      ──▶  Pattern Clustering
Threat Model (opt)  ──▶  Proxy Detector   ──▶  Anomaly Detection
                    ──▶  Source Resolver  ──▶  Conflict Reconciliation
                                               │
                                               ▼
                                          Agent Pipeline
                                          ──────────────
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
```

## Output Artifacts

| File | Description | Use With |
|------|-------------|----------|
| `observed_design.md` | Narrative design document from observed behavior | AutoProver `--design_doc` |
| `observed_design.json` | Structured analysis data (state machine, invariants, anomalies) | Custom tooling |
| `conflict_report.md` | Design vs reality gaps and security concerns | AutoProver `--threat-model` |
| `visualizations/` | State diagrams, call graphs, timelines | Documentation, review |

## Integration with AutoProver

```bash
# 1. Generate observed design from on-chain data
oio analyze 0xContract --output ./analysis/

# 2. Feed into AutoProver (AutoProver generates the .spec, not OIO)
console-autoprove   ./project   src/Contract.sol:Contract   ./analysis/observed_design.md   --threat-model ./analysis/conflict_report.md   --max-bug-rounds 5   --cloud
```

## What OIO Does vs What AutoProver Does

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

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=onchain_intent_oracle

# Run specific test suite
pytest tests/test_analysis/
```

## License

MIT

| Provider              | Free Tier Tracing                           | Notes                                                                       |
| --------------------- | ------------------------------------------- | --------------------------------------------------------------------------- |
| **Chainstack**        | ✅ Yes — Debug & Trace APIs on archive nodes | 3M requests/month free, supports custom JS tracers                          |
| **Tenderly**          | ✅ Yes — `debug_*` and `trace_*` methods     | Free account available, Node RPC with tracing                               |
| **NOWNodes**          | ✅ Yes — Archive nodes with Debug API        | Paid but has trial, supports `callTracer`, `prestateTracer`, `4byteTracer`  |
| **QuickNode**         | ❌ No — Paid only                            | Free trial includes it, but not ongoing free tier                           |
| **Alchemy**           | ❌ No — Paid only                            | Free tier blocks `debug_traceTransaction`                                   |
| **Infura**            | ❌ No — Paid only                            | Requires archive add-on                                                     |
| **Local Geth/Erigon** | ✅ Unlimited                                 | Best for privacy and no limits                                              |
