"""Generate markdown design documents from analysis results."""
from pathlib import Path
import structlog
logger = structlog.get_logger()

class MarkdownGenerator:
    def generate(self, data, output_path):
        contract = data.get("contract_address", "unknown")
        chain_id = data.get("chain_id", 1)
        block_start, block_end = data.get("block_range", [0, 0])
        tx_count = data.get("tx_count", 0)

        lines = [
            "# Observed Design Document", "",
            f"**Contract:** `{contract}`",
            f"**Chain:** Ethereum (chain ID: {chain_id})",
            f"**Block Range:** {block_start} to {block_end}",
            f"**Transactions Analyzed:** {tx_count}", "",
            "## Overview", "",
            data.get("overview", f"Contract {contract} on chain {chain_id} analyzed."), "",
            "## Security Notes", "",
            f"Proxy: {data.get('proxy_info', {}).get('type', 'DIRECT')}, Implementation: {data.get('proxy_info', {}).get('implementation', 'N/A')}",
            "", "## State Machine", "",
            f"**States:** {len(data.get('state_machine', {}).get('states', []))}", "",
        ]
        for s in data.get("state_machine", {}).get("states", []):
            lines.append(f"- **{s['name']}**: {s.get('description', '')}")
        trans = data.get("state_machine", {}).get("transitions", [])
        lines.extend(["", f"**Transitions:** {len(trans)}", "", "| From | To | Trigger | Guard |", "|------|-----|---------|-------|"])
        for t in trans:
            lines.append(f"| {t.get('from', '?')} | {t.get('to', '?')} | `{t.get('trigger', '?')}` | {t.get('guard', '') or ''} |")
        lines.append("")

        invs = data.get("invariants", [])
        high = [i for i in invs if i.get("confidence", 0) >= 0.95]
        lines.extend(["## Invariants", "", f"### High Confidence (>= 0.95) -- {len(high)} found", ""])
        for i in high: lines.append(f"- **{i['expression']}** (confidence: {i['confidence']})")
        lines.append("")

        evidence = data.get("evidence_txs", [])
        lines.extend(["## Evidence Transactions", "", f"Showing {min(len(evidence), 10)} of {len(evidence)} transactions:", "", "| Hash | Block | Description |", "|------|-------|-------------|"])
        for tx in evidence[:10]:
            lines.append(f"| `{tx['hash'][:20]}...` | {tx.get('block', '?')} | {tx.get('description', '')} |")
        lines.append("")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("markdown_generated", path=str(output_path))
        return output_path
