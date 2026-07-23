# Observed Design Document

**Contract:** `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb`
**Chain:** Ethereum (chain ID: 1)
**Block Range:** 18883124 to 18883954
**Transactions Analyzed:** 12

## Overview

Contract 0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb on chain 1 analyzed from block 18883124 to 18883954.

## Security Notes

Proxy: DIRECT, Implementation: None

## State Machine

**States:** 1

- **initial**: Contract before any observed interaction

**Transitions:** 0

| From | To | Trigger | Guard |
|------|-----|---------|-------|

## Invariants

### High Confidence (>= 0.95) -- 2 found

- **msg.value == 0 for all observed txs** (confidence: 0.95)
- **msg.sender == 0x937ce2d6c488b361825d2db5e8a70e26d48afed5 for enableLltv()** (confidence: 1.0)

## Evidence Transactions

Showing 10 of 12 transactions:

| Hash | Block | Description |
|------|-------|-------------|
| `0x42ca1af71d1f2125f0...` | 18883124 | enableIrm |
| `0xa18c738197ae604bf7...` | 18883125 | enableIrm |
| `0x81ef8f35ff9b454532...` | 18883125 | enableLltv |
| `0xd71a12bf712feec1b3...` | 18883126 | enableLltv |
| `0x9ebaec4a7fbf25bc3e...` | 18883126 | enableLltv |
| `0xf60c266af3e61a32d4...` | 18883127 | enableLltv |
| `0x5c788a0443629ab452...` | 18883127 | enableLltv |
| `0x7272e35ca224a2ecb7...` | 18883127 | enableLltv |
| `0x8b02ae3fcabbc5626e...` | 18883128 | enableLltv |
| `0x4adae9b8b721f4a3cc...` | 18883128 | enableLltv |
