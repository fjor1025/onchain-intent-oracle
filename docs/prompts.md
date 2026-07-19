# Prompt Engineering Guide

## Agent Prompts

OnChainIntentOracle uses Jinja2 templates for all LLM prompts. Templates are in `src/onchain_intent_oracle/agents/prompts/`.

### Data Collector Prompt

**Purpose**: Identify contract type and flag anomalies from raw transaction data.

**Key sections**:
- Contract type detection (ERC20, ERC4626, DEX, etc.)
- Anomaly flagging (unusual callers, unexpected methods)
- Priority transaction identification

**Output format**: Structured JSON with:
- `contract_type`
- `priority_txs`
- `anomalies`
- `recommended_focus_areas`

### State Inference Prompt

**Purpose**: Build finite state machine from observed transitions.

**Key sections**:
- State variable analysis
- Transition extraction with guards
- Implicit state identification
- Access control concerns

**Output format**: JSON with `states`, `transitions`, `implicit_states`.

### Invariant Proposer Prompt

**Purpose**: Convert statistical observations into formal property candidates.

**Key sections**:
- Statistical invariant candidates with confidence
- Storage relationship analysis
- RAG context for pattern matching
- Recommended verification approaches

**Output format**: List of invariant objects with `id`, `expression`, `recommended_verification_approach`.

### Conflict Reconciler Prompt

**Purpose**: Three-way merge of design, code, and observed behavior.

**Key sections**:
- Design claim extraction
- Observed behavior summary
- Code analysis
- Conflict categorization

**Output format**: `conflicts`, `omissions`, `weakenings`, `security_gaps`.

### Summarizer Prompt

**Purpose**: Generate human-readable design document.

**Key sections**:
- Protocol overview
- State machine description
- Invariant catalog
- Anomaly summary
- Conflict highlights

**Output format**: Markdown suitable for AutoProver `--design_doc`.

### Property Generator Prompt

**Purpose**: Generate structured property candidates for formal verification tools.

**Key sections**:
- Property ID and expression
- Formal type (safety/liveness/state/access_control/economic)
- Confidence score
- Evidence references
- Recommended verification approach (static analysis | symbolic execution | fuzzing | formal proof)
- Suggested tool (Certora | Foundry | Slither | custom)
- Notes on required assumptions

**Important**: This prompt does NOT generate CVL code. It outputs structured JSON property candidates that humans or AutoProver consume.

**Output format**: JSON array of property candidate objects.

## Prompt Customization

### Adding Domain Knowledge

For specialized protocols (e.g., options, derivatives), add domain-specific context:

```jinja2
{# In data_collector.j2, add: #}
DOMAIN CONTEXT:
This is a decentralized options protocol. Key concerns:
- Exercise deadlines must be enforced
- Collateral must cover max loss at all times
- Oracle price freshness is critical
```

### Adjusting Tone

For different audiences:
- **Auditors**: Technical, precise, evidence-heavy
- **Developers**: Actionable, with code references
- **Executives**: High-level, risk-focused

### Localization

Prompts can be translated for non-English teams. Ensure technical terms (EVM, formal verification) remain in English.

## Testing Prompts

Inspect agent outputs directly:

```bash
# Run with verbose logging to see agent outputs
oio analyze 0xContract --output ./test/ --depth quick 2>&1 | tee agent_output.log
```
