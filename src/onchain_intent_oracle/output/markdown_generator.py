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
        ]

        sq = data.get("sample_quality") or {}
        if sq.get("any_flag"):
            reasons = []
            if sq.get("possible_bootstrap_window"):
                reasons.append(
                    f"the range starts only {sq.get('blocks_since_creation')} blocks after this "
                    "contract's own creation -- likely deployment/bootstrap activity, not organic usage"
                )
            if sq.get("low_tx_count"):
                reasons.append(
                    f"only {sq.get('tx_count')} transaction(s) observed "
                    f"(below the {sq.get('low_tx_count_threshold')}-tx sanity threshold)"
                )
            if sq.get("narrow_function_diversity"):
                reasons.append(f"only {sq.get('distinct_methods_observed')} distinct method(s) were called across the whole range")
            if sq.get("single_caller_dominant"):
                pct = int(round((sq.get("dominant_caller_ratio") or 0) * 100))
                reasons.append(f"{pct}% of transactions came from a single address ({sq.get('dominant_caller')})")
            lines.extend([
                "> ⚠️ **Sample quality warning**: this block range looks like a degenerate or "
                "non-representative sample. Everything below is accurate for what was actually "
                "observed, but may not generalize to the contract's real, steady-state behavior. "
                "Consider re-running against a wider and/or later block range.",
                ">",
            ])
            for r in reasons:
                lines.append(f"> - {r}")
            lines.append("")

        lines.extend([
            "## Overview", "",
            data.get("overview", f"Contract {contract} on chain {chain_id} analyzed."), "",
            "## Security Notes", "",
            f"Proxy: {data.get('proxy_info', {}).get('type', 'DIRECT')}, Implementation: {data.get('proxy_info', {}).get('implementation', 'N/A')}",
            "", "## State Machine", "",
            f"**States:** {len(data.get('state_machine', {}).get('states', []))}", "",
        ])
        for s in data.get("state_machine", {}).get("states", []):
            lines.append(f"- **{s['name']}**: {s.get('description', '')}")
        trans = data.get("state_machine", {}).get("transitions", [])
        lines.extend(["", f"**Transitions:** {len(trans)}", "", "| From | To | Trigger | Guard |", "|------|-----|---------|-------|"])
        for t in trans:
            lines.append(f"| {t.get('from', '?')} | {t.get('to', '?')} | `{t.get('trigger', '?')}` | {t.get('guard', '') or ''} |")
        lines.append("")

        tc = data.get("trace_coverage") or {}
        reason = tc.get("reason")
        tc_succeeded = tc.get("succeeded_count", 0)
        tc_failed = tc.get("failed_count", 0)
        reason_text = {
            "depth_quick": "skipped this run (`--depth quick`)",
            "provider_unsupported": (
                "attempted for every transaction but did not succeed for any of them -- "
                "the configured RPC provider does not appear to support "
                "`debug_traceTransaction`/`trace_transaction`"
            ),
            "not_attempted": "there were no transactions to attempt it on",
        }.get(reason)
        if reason_text:
            note = f"_Trace/state-diff enrichment {reason_text}."
            if reason == "provider_unsupported":
                note += (
                    " Any transitions in the state machine above are grounded in decoded "
                    "event-log evidence instead (see \"Observed Events\" below), not on-chain "
                    "storage changes -- this is a materially weaker evidence channel for "
                    "state-machine inference specifically, though still real evidence."
                )
            note += "_"
            lines.append(note)
            lines.append("")
        elif tc_succeeded > 0:
            lines.append(
                f"_Trace/state-diff enrichment succeeded for {tc_succeeded} of "
                f"{tc_succeeded + tc_failed} transaction(s) -- the state machine above reflects "
                "real on-chain storage changes for those, not just calldata/logs._"
            )
            lines.append("")

        entities = data.get("entities") or {}
        if entities.get("cross_entity_warning"):
            lines.append(
                f"**Note:** {entities.get('entities_observed', 0)} distinct entities "
                "(markets/pools/vaults/etc., inferred via "
                f"`{entities.get('entity_key_source', 'heuristic')}`) were observed behind "
                "this single contract address. The state machine above is the "
                "**aggregate across all of them -- cross-entity, use with caution** as a "
                "single coherent state machine. See \"Per-Entity Analysis\" below for each "
                "entity's own observed behavior."
            )
            lines.append("")

        invs = data.get("invariants", [])
        high = [i for i in invs if i.get("confidence", 0) >= 0.95]
        lines.extend(["## Invariants", "", f"### High Confidence (>= 0.95) -- {len(high)} found", ""])
        for i in high: lines.append(f"- **{i['expression']}** (confidence: {i['confidence']})")
        lines.append("")

        per_entity = entities.get("per_entity") or []
        if per_entity:
            lines.extend(["## Per-Entity Analysis", ""])
            lines.append(
                f"{entities.get('entities_observed', len(per_entity))} distinct entities observed; "
                f"showing the top {len(per_entity)} by transaction count. Each entity's state "
                "machine/invariants below are scoped to *that entity's own transactions only* "
                "-- unlike the aggregate section above, these are not blended across markets/"
                "pools/vaults."
            )
            lines.append("")
            for e in per_entity:
                key = e["entity_key"]
                short_key = key if len(key) <= 20 else f"{key[:10]}...{key[-6:]}"
                lines.append(f"### Entity `{short_key}` ({e['tx_count']} tx)")
                e_states = e["state_machine"]["states"]
                e_trans = e["state_machine"]["transitions"]
                lines.append(f"- **States:** {len(e_states)}, **Transitions:** {len(e_trans)}")
                e_high = [inv for inv in e["invariants"] if inv.get("confidence", 0) >= 0.95]
                if e_high:
                    lines.append("- **High-confidence invariants:**")
                    for inv in e_high[:5]:
                        lines.append(f"  - {inv['expression']} (confidence: {inv['confidence']})")
                lines.append("")

        log_summary = data.get("decoded_logs", {})
        if log_summary.get("total_logs"):
            lines.extend(["## Observed Events (from logs)", ""])
            lines.append(
                f"{log_summary['total_logs']} log(s) observed; "
                f"{log_summary.get('unresolved_count', 0)} could not be resolved to a named event."
            )
            lines.append("")
            for event_name, count in sorted(log_summary.get("by_event_name", {}).items(), key=lambda kv: -kv[1]):
                lines.append(f"- **{event_name}**: {count} occurrence(s)")
            lines.append("")

        call_summary = data.get("decoded_calls", {})
        if call_summary.get("total_calls"):
            by_conf = call_summary.get("by_confidence", {})
            lines.append(
                f"Calldata: {call_summary['total_calls']} call(s) observed "
                f"({by_conf.get('verified_abi', 0)} decoded against a verified ABI, "
                f"{by_conf.get('selector_signature_only', 0)} decoded from a resolved "
                f"selector signature only, {call_summary.get('unresolved_count', 0)} unresolved)."
            )
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
