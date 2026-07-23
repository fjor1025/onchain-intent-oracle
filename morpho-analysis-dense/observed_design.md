# Observed Design Document

**Contract:** `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb`
**Chain:** Ethereum (chain ID: 1)
**Block Range:** 25592646 to 25592907
**Transactions Analyzed:** 7

> ⚠️ **Sample quality warning**: this block range looks like a degenerate or non-representative sample. Everything below is accurate for what was actually observed, but may not generalize to the contract's real, steady-state behavior. Consider re-running against a wider and/or later block range.
>
> - only 7 transaction(s) observed (below the 20-tx sanity threshold)
> - only 2 distinct method(s) were called across the whole range

## Overview

Contract 0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb on chain 1 analyzed from block 25592646 to 25592907.

## Security Notes

Proxy: DIRECT, Implementation: None

## State Machine

**States:** 7

- **initial**: Contract before any observed interaction
- **state_0x1541f24983eb**: Observed state state_0x1541f24983eb
- **state_66bbe9e3aad015**: Observed state state_66bbe9e3aad015
- **state_0x3d897ec4aaf7**: Observed state state_0x3d897ec4aaf7
- **state_e3b0c44298fc1c**: Observed state state_e3b0c44298fc1c
- **state_e2f3888972a4dc**: Observed state state_e2f3888972a4dc
- **state_a54942c8e365f3**: Observed state state_a54942c8e365f3

**Transitions:** 6

| From | To | Trigger | Guard |
|------|-----|---------|-------|
| initial | state_0x1541f24983eb | `withdraw` | withdraw() called by 0x5388a7f2... |
| state_0x1541f24983eb | state_66bbe9e3aad015 | `withdraw` | withdraw() called by 0xafddee0f... |
| state_66bbe9e3aad015 | state_0x3d897ec4aaf7 | `withdraw` | withdraw() called by 0x85c220d2... |
| state_0x3d897ec4aaf7 | state_e3b0c44298fc1c | `withdrawCollateral` | withdrawCollateral() called by 0x52b4c762... |
| state_e3b0c44298fc1c | state_e2f3888972a4dc | `withdraw` | withdraw() called by 0x9a23657e... |
| state_e2f3888972a4dc | state_a54942c8e365f3 | `withdrawCollateral` | withdrawCollateral() called by 0x398454e4... |

_Trace/state-diff enrichment succeeded for 7 of 7 transaction(s) -- the state machine above reflects real on-chain storage changes for those, not just calldata/logs._

## Invariants

### High Confidence (>= 0.95) -- 1 found

- **msg.value == 0 for all observed txs** (confidence: 0.95)

Calldata: 7 call(s) observed (7 decoded against a verified ABI, 0 decoded from a resolved selector signature only, 0 unresolved).

## Evidence Transactions

Showing 7 of 7 transactions:

| Hash | Block | Description |
|------|-------|-------------|
| `0xa0934a9ac847b160d3...` | 25592646 | withdraw |
| `0x65ecf8dbd131538c0f...` | 25592646 | withdraw |
| `0xa7a954fc877772d785...` | 25592694 | withdraw |
| `0xc783441ad57160eaaf...` | 25592835 | withdrawCollateral |
| `0xb3c2625d258d498370...` | 25592864 | withdrawCollateral |
| `0x30b943dbb94d352049...` | 25592901 | withdraw |
| `0x4f9f8d24b950db6ca3...` | 25592907 | withdrawCollateral |
