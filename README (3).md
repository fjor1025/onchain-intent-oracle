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
- RPC access (Alchemy, QuickNode, Infura, Chainstack, Tenderly, or local node)
- Anthropic API key (for LLM features)

### Installation

```bash
# Clone repository
git clone https://github.com/your-org/onchain-intent-oracle.git
cd onchain-intent-oracle

# Install dependencies
uv pip install -e "."

# Set up database (optional — for RAG knowledge base)
docker compose up -d
./scripts/setup_db.sh

# Populate knowledge base (optional)
./scripts/populate_kb.sh
```

### Configuration

Create `.env` file in the project root:

```bash
ANTHROPIC_API_KEY=sk-ant-...
ETHERSCAN_API_KEY=...
RPC_URLS=https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY
DATABASE_URL=postgresql+psycopg://oio:oio@localhost:5432/oio
```

**Multiple RPC providers** (recommended for redundancy and higher rate limits):

```bash
# Comma-separated list — OIO will round-robin and fallback automatically
RPC_URLS=https://eth-mainnet.g.alchemy.com/v2/KEY1,https://ethereum-mainnet.core.chainstack.com/KEY2,https://mainnet.infura.io/v3/KEY3
```

## Usage

### Analyze a Contract

```bash
oio analyze \
  0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  --chain ethereum \
  --block-range 18000000:18001000 \
  --output ./test-output \
  --depth quick
```

**Supported chain names**: `ethereum`, `mainnet`, `sepolia`, `goerli`, `polygon`, `mumbai`, `arbitrum`, `arbitrum-one`, `optimism`, `base`, `bsc`, `avalanche`, `fantom`, `gnosis`

You can also use numeric chain IDs directly: `--chain 1`

Outputs:
- `observed_design.md` — Narrative design document (use as AutoProver `--design_doc`)
- `observed_design.json` — Structured analysis data
- `conflict_report.md` — Design vs reality gaps (use as AutoProver `--threat-model`)
- `visualizations/` — State diagrams, call graphs

### Example Output

```json
{
  "contract_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
  "chain_id": 1,
  "block_range": [18000000, 18000004],
  "tx_count": 4,
  "proxy_info": {
    "is_proxy": false,
    "implementation": null,
    "type": "DIRECT"
  },
  "state_machine": {
    "states": [...],
    "transitions": [...]
  },
  "invariants": [...],
  "conflicts": {
    "omissions": [...],
    "weakenings": [...]
  }
}
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

## RPC Provider Setup

### Provider Comparison

| Provider | Free Tier | Tracing | Best For |
|----------|-----------|---------|----------|
| Alchemy | 330 CU/s | Paid only | Reliability, US/EU |
| QuickNode | Yes | Paid only | Speed, global edge |
| Infura | Yes | Paid only | Enterprise, stability |
| Chainstack | Yes | Paid only | Archive data |
| Tenderly | Yes | Yes | Simulation, debugging |
| Local Geth/Erigon | Unlimited | ✅ Full | Privacy, no limits |

OIO fetches full blocks via `eth_getBlockByNumber` and filters transactions client-side. This works with any standard JSON-RPC endpoint — no special tracing or log indexing endpoints required.

### Local Node (Best for Tracing)

For full trace and state diff support without provider limits:

```bash
# Erigon with tracing
./erigon --chain=mainnet --http.api=eth,debug,trace

# Add to .env
RPC_URLS=http://localhost:8545
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
console-autoprove \
  ./project \
  src/Contract.sol:Contract \
  ./analysis/observed_design.md \
  --threat-model ./analysis/conflict_report.md \
  --max-bug-rounds 5 \
  --cloud
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

## Troubleshooting

### `403 Client Error: Forbidden` or `429 Too Many Requests`

**Cause**: RPC provider rate limit or authentication issue.  
**Fix**: Configure multiple providers in `RPC_URLS` (comma-separated). OIO will automatically fallback to the next provider.

### `No module named 'click'`

**Cause**: Outdated CLI using Click instead of Typer.  
**Fix**: The CLI now uses Typer (already included in dependencies). Ensure you have the latest `src/onchain_intent_oracle/cli.py`.

### Traces not available / `debug_traceTransaction` fails

**Cause**: Your RPC provider does not support tracing on your tier.  
**Fix**: OIO works without tracing — it fetches full blocks and filters transactions. For trace-dependent features, use a local Erigon/Geth node or a paid RPC plan with tracing.

### `Unknown chain: ...`

**Cause**: Chain name not recognized.  
**Fix**: Use a supported chain name (`ethereum`, `polygon`, `arbitrum`, etc.) or pass the numeric chain ID directly (e.g., `--chain 1`).

## Development

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
