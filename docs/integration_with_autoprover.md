# Integration with AutoProver

## Overview

OnChainIntentOracle generates **inputs** (design documents, property candidates, conflict reports) that are consumed by Certora's AutoProver. OIO does **not** generate CVL `.spec` files or run formal proofs — that is AutoProver's domain.

## Artifact Mapping

| OIO Output | AutoProver Input | Flag |
|------------|-----------------|------|
| `observed_design.md` | Design document | positional arg (3rd) |
| `conflict_report.md` | Threat model | `--threat-model` |
| `observed_design.json` | Structured data | Not directly used by AutoProver CLI |

## Workflow

### Step 1: Generate Observed Design

```bash
oio analyze   0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48   --chain ethereum   --block-range 18000000:19000000   --output ./usdc-oio/
```

This produces:
- `./usdc-oio/observed_design.md` — what the contract actually does
- `./usdc-oio/conflict_report.md` — gaps between claimed and observed behavior
- `./usdc-oio/observed_design.json` — structured data for custom tooling

### Step 2: Run AutoProver with Observed Design

```bash
console-autoprove   ./usdc-project   src/USDC.sol:USDC   ./usdc-oio/observed_design.md   --threat-model ./usdc-oio/conflict_report.md   --max-bug-rounds 5   --cloud   --cache-ns usdc-verification
```

AutoProver then:
1. Reads the observed design document
2. Infers properties (with its own LLM agents)
3. Generates CVL `.spec` files
4. Runs formal verification
5. Reports results

## Benefits of Observed Design

### 1. Ground Truth

Developer-provided design docs may be:
- Outdated (code changed, docs didn't)
- Aspirational (describes intended, not actual behavior)
- Incomplete (omits edge cases)

OIO's `observed_design.md` reflects **what actually happens on-chain**.

### 2. Attack Surface Discovery

OIO's anomaly detection and conflict reconciliation identify:
- Functions called in unexpected ways
- Access control bypasses
- Economic parameter drift
- Upgrade patterns

These become high-priority targets for AutoProver's bug-hunting rounds.

### 3. Property Candidate Seeding

OIO's statistical invariants (with confidence scores) can inform AutoProver's property generation:
- High-confidence invariants → AutoProver may generate similar formal rules
- Medium-confidence → candidates for verification
- Conflicts → explicit areas to investigate

However, AutoProver generates its own CVL rules independently. OIO provides **context**, not specifications.

## Best Practices

### Combine with Developer Design Doc

Don't replace the developer's design doc — **augment** it:

```bash
# Merge observed and intended design
cat developer_design.md observed_design.md > combined_design.md

console-autoprover   ./project   src/Contract.sol:Contract   combined_design.md   --threat-model threat_model.md
```

### Use Conflict Report as Threat Model

The conflict report explicitly lists:
- Access control weaker than claimed
- Economic invariants that don't hold
- State transitions not documented

This is ideal input for `--threat-model`.

### Iterate Between OIO and AutoProver

```bash
# Round 1: OIO discovers behavior
oio analyze 0xContract --output ./round1/

# Round 2: AutoProver verifies, finds gaps
console-autoprove ... ./round1/observed_design.md

# Round 3: Update design with AutoProver findings, re-run OIO
# (if AutoProver identifies missing behavior, add to design doc)
oio analyze 0xContract --design-doc ./updated.md --output ./round2/
```

## Troubleshooting

### "Observed design too large"

AutoProver has context limits. If `observed_design.md` is too long:

```bash
# Use summary only
oio analyze ... --depth quick --output ./quick/
```

### "Conflicts not actionable"

If conflict report is too vague:

```bash
# Increase analysis depth for more evidence
oio analyze ... --depth deep --max-bug-rounds 5
```

### "AutoProver generates different properties than expected"

This is expected. OIO provides **observed behavior context**; AutoProver generates properties based on its own inference. The two should complement each other:
- OIO finds what the code actually does
- AutoProver proves what it should do
- Conflicts between the two are exactly what you want to investigate
