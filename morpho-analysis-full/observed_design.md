# Observed Design Document

**Contract:** `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb`
**Chain:** Ethereum (chain ID: 1)
**Block Range:** 25592073 to 25593546
**Transactions Analyzed:** 24

## Overview

Contract 0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb on chain 1 analyzed from block 25592073 to 25593546.

## Security Notes

Proxy: DIRECT, Implementation: None

## State Machine

**States:** 20

- **initial**: Contract before any observed interaction
- **state_0x1541f24983eb**: Observed state state_0x1541f24983eb
- **state_4b62a53c662585**: Observed state state_4b62a53c662585
- **state_e3b0c44298fc1c**: Observed state state_e3b0c44298fc1c
- **state_4aeab67602288d**: Observed state state_4aeab67602288d
- **state_0x261b8ca617be**: Observed state state_0x261b8ca617be
- **state_0x022271a7479a**: Observed state state_0x022271a7479a
- **state_a54942c8e365f3**: Observed state state_a54942c8e365f3
- **state_c7965c89f604be**: Observed state state_c7965c89f604be
- **state_0x3d897ec4aaf7**: Observed state state_0x3d897ec4aaf7
- **state_0x7576504885e3**: Observed state state_0x7576504885e3
- **state_e2f3888972a4dc**: Observed state state_e2f3888972a4dc
- **state_0x17e4b7eab25e**: Observed state state_0x17e4b7eab25e
- **state_0x0071a49187bc**: Observed state state_0x0071a49187bc
- **state_0x3d0a0c174110**: Observed state state_0x3d0a0c174110
- **state_0x04884eb6176b**: Observed state state_0x04884eb6176b
- **state_0x17a0409b9ba9**: Observed state state_0x17a0409b9ba9
- **state_0x4a6c2c05e74c**: Observed state state_0x4a6c2c05e74c
- **state_88ed7650297ded**: Observed state state_88ed7650297ded
- **state_0x00f553acf83c**: Observed state state_0x00f553acf83c

**Transitions:** 22

| From | To | Trigger | Guard |
|------|-----|---------|-------|
| initial | state_0x1541f24983eb | `withdraw` | withdraw() called by 0x5388a7f2... |
| state_0x1541f24983eb | state_4b62a53c662585 | `borrow` | borrow() called by 0x687f584f... |
| state_4b62a53c662585 | state_e3b0c44298fc1c | `setAuthorization` | setAuthorization() called by 0xb0f157db... |
| state_e3b0c44298fc1c | state_4aeab67602288d | `withdraw` | withdraw() called by 0xd7583e3c... |
| state_4aeab67602288d | state_0x261b8ca617be | `withdrawCollateral` | withdrawCollateral() called by 0x398454e4... |
| state_0x261b8ca617be | state_0x022271a7479a | `withdrawCollateral` | withdrawCollateral() called by 0xf9a52743... |
| state_0x022271a7479a | state_a54942c8e365f3 | `withdrawCollateral` | withdrawCollateral() called by 0x76013dae... |
| state_a54942c8e365f3 | state_c7965c89f604be | `withdraw` | withdraw() called by 0x5388a7f2... |
| state_c7965c89f604be | state_0x3d897ec4aaf7 | `withdraw` | withdraw() called by 0xafddee0f... |
| state_0x3d897ec4aaf7 | state_0x7576504885e3 | `withdrawCollateral` | withdrawCollateral() called by 0x52b4c762... |
| state_0x7576504885e3 | state_e3b0c44298fc1c | `withdrawCollateral` | withdrawCollateral() called by 0x398454e4... |
| state_e3b0c44298fc1c | state_e2f3888972a4dc | `withdraw` | withdraw() called by 0x9a23657e... |
| state_e2f3888972a4dc | state_0x261b8ca617be | `withdrawCollateral` | withdrawCollateral() called by 0x398454e4... |
| state_0x261b8ca617be | state_0x17e4b7eab25e | `createMarket` | createMarket() called by 0xe2f7702a... |
| state_0x17e4b7eab25e | state_0x0071a49187bc | `supply` | supply() called by 0xe2f7702a... |
| state_0x0071a49187bc | state_0x3d0a0c174110 | `withdraw` | withdraw() called by 0x47163ad3... |
| state_0x3d0a0c174110 | state_0x04884eb6176b | `withdrawCollateral` | withdrawCollateral() called by 0xfe691c29... |
| state_0x04884eb6176b | state_0x17a0409b9ba9 | `withdraw` | withdraw() called by 0x40534e51... |
| state_0x17a0409b9ba9 | state_0x4a6c2c05e74c | `withdrawCollateral` | withdrawCollateral() called by 0xf4f44a44... |
| state_0x4a6c2c05e74c | state_0x1541f24983eb | `withdraw` | withdraw() called by 0x5388a7f2... |
| state_0x1541f24983eb | state_88ed7650297ded | `withdraw` | withdraw() called by 0x40534e51... |
| state_88ed7650297ded | state_0x00f553acf83c | `withdraw` | withdraw() called by 0x5388a7f2... |

_Trace/state-diff enrichment succeeded for 23 of 24 transaction(s) -- the state machine above reflects real on-chain storage changes for those, not just calldata/logs._

## Invariants

### High Confidence (>= 0.95) -- 1 found

- **msg.value == 0 for all observed txs** (confidence: 0.95)

Calldata: 24 call(s) observed (24 decoded against a verified ABI, 0 decoded from a resolved selector signature only, 0 unresolved).

## Evidence Transactions

Showing 10 of 24 transactions:

| Hash | Block | Description |
|------|-------|-------------|
| `0xd3876289fd0199c763...` | 25592073 | withdraw |
| `0x44a0e9f599c8f21076...` | 25592073 | borrow |
| `0x376480c0e0cf93269b...` | 25592242 | setAuthorization |
| `0xc9121903fd89318dcf...` | 25592329 | withdraw |
| `0x492ba7961f9980c422...` | 25592368 | withdrawCollateral |
| `0xc7bfa4cd01479c2cc5...` | 25592441 | withdrawCollateral |
| `0x2ff382c84b1524dcef...` | 25592504 | withdrawCollateral |
| `0xa0934a9ac847b160d3...` | 25592646 | withdraw |
| `0x65ecf8dbd131538c0f...` | 25592646 | withdraw |
| `0xa7a954fc877772d785...` | 25592694 | withdraw |
