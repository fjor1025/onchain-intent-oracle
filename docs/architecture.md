# Architecture Documentation

## System Components

### 1. Data Ingestion Layer

**RPCManager**: Multi-provider fallback with rate limiting
- Supports Alchemy, QuickNode, local nodes
- Automatic failover on errors
- Configurable rate limits per provider

**TraceFetcher**: Fetches and parses transaction traces
- `debug_traceTransaction` with callTracer
- `trace_transaction` (Parity style) fallback
- State diff extraction with prestateTracer

**ProxyDetector**: Identifies proxy patterns
- EIP-1967 (transparent proxy)
- EIP-1822 (universal upgradeable)
- EIP-2535 (diamond proxy)
- OpenZeppelin transparent proxy

**SourceResolver**: Fetches verified source from explorers
- Etherscan API integration
- ABI extraction and caching

### 2. Analysis Engine

**StateMachineInference**: Builds FSM from call sequences
- Storage fingerprint-based state identification
- Implicit state detection (behavioral modes)
- Transition guard inference

**InvariantMiner**: Statistical invariant detection
- Balance sum invariants (ERC20)
- Access control patterns
- Monotonicity detection
- Revert pattern analysis

**PatternClustering**: Transaction clustering
- DBSCAN on transaction features
- Common vs rare path identification
- Outlier detection

**AnomalyDetector**: Drift and anomaly detection
- Baseline computation from historical data
- Multi-factor anomaly scoring
- Severity classification

**ConflictReconciler**: Three-way merge
- Design claims vs code vs observed behavior
- Contradiction, omission, weakening detection
- Security gap identification

### 3. Agent Pipeline (LangGraph)

Six-agent workflow with checkpointing:

1. **DataCollectorAgent**: Summarize raw data, identify contract type
2. **StateInferenceAgent**: Build formal state machine
3. **InvariantProposerAgent**: Propose property candidates (not CVL)
4. **ConflictReconcilerAgent**: Identify design/reality gaps
5. **SummarizerAgent**: Generate `observed_design.md`
6. **PropertyCandidateGeneratorAgent**: Output structured property candidates for FV tools

**Note**: The pipeline generates **property candidates** (structured JSON with natural language expressions, confidence scores, and recommended verification approaches). It does **not** generate CVL code or formal proofs. CVL generation is performed by AutoProver or human experts.

### 4. RAG Knowledge Base

**VectorStore**: Postgres + pgvector
- Formal verification best practices
- DeFi security patterns
- Pitfall articles
- On-chain evidence index

### 5. Output Generation

**MarkdownGenerator**: `observed_design.md`
**JSONGenerator**: Structured `observed_design.json`
**ConflictReportGenerator**: Human-readable gap report
**Visualizer**: Mermaid/Graphviz diagrams

## Data Flow

```
Contract Address
    │
    ▼
[RPCManager] ──▶ [TraceFetcher] ──▶ [CacheLayer]
    │                │
    ▼                ▼
[ProxyDetector]  [SourceResolver]
    │                │
    └──────┬─────────┘
           ▼
    [Deterministic Analysis]
    - StateMachineInference
    - InvariantMiner
    - PatternClustering
    - AnomalyDetector
           │
           ▼
    [LangGraph Agent Pipeline]
    - DataCollectorAgent
    - StateInferenceAgent
    - InvariantProposerAgent
    - ConflictReconcilerAgent
    - SummarizerAgent
    - PropertyCandidateGeneratorAgent
           │
           ▼
    [Output Generation]
    - observed_design.md      → AutoProver --design_doc
    - observed_design.json    → Custom tooling
    - conflict_report.md      → AutoProver --threat-model
    - visualizations/         → Documentation
    - property_candidates/    → Human review, AutoProver context
```

## Boundary with AutoProver

| Concern | OIO | AutoProver |
|---------|-----|------------|
| On-chain data | ✅ Fetches & analyzes | ❌ |
| State machine inference | ✅ From traces | ❌ |
| Statistical invariants | ✅ Mines from data | ❌ |
| Design document generation | ✅ `observed_design.md` | ✅ (from code/docs) |
| Property candidate proposals | ✅ Structured JSON | ❌ |
| CVL `.spec` generation | ❌ | ✅ |
| Formal proof execution | ❌ | ✅ |
| Counterexample triage | ❌ | ✅ |

OIO provides **context and ground truth**; AutoProver provides **formal verification**.

## Scalability Considerations

- **Sampling**: For high-volume contracts (>100K txs), sample by block range and value
- **Batching**: RPC requests batched where provider supports it
- **Caching**: Multi-tier (SQLite local, Postgres shared)
- **Async**: All I/O operations are async with asyncio
- **Checkpointing**: LangGraph checkpoints to Postgres for resumability
