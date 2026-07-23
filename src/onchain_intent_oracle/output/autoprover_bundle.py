"""Generate an AutoProver-compatible design document from observed on-chain behavior.

The convention this follows was verified directly against AutoProver's own
source (github.com/Certora/AutoProver), not guessed at:

- `system_doc` (the actual design-doc input) is read as plain text/PDF and
  injected into an LLM's context verbatim (`SystemDoc.content: Document`,
  `composer/spec/context.py`) -- no schema, no required structure.
- AutoProver's own test fixtures (`test_scenarios/{codegen_capped_vault,
  autoprove_counter,autoprove_answer}/system.md`) and its design-doc-finder
  agent's rubric (`design_doc_finder_system_prompt.j2`) converge on the same
  loose shape: a title, 2-3 sentences of prose, an entry-points/state/
  interactions breakdown per contract, and a plain-English "Requirements"
  list. No CVL, no Preconditions/Postconditions formalism, no
  Application-Type/Sort/Sub-Component structure -- that richer structure
  (`application_context_macro.j2`) is a downstream artifact AutoProver's own
  `application_analysis` agent produces FROM SOURCE CODE
  ("ground all of your conclusions in the source code itself" --
  `application_analysis_prompt.j2`); it is not something a design doc needs
  to supply, and fabricating it here would mean claiming source-level
  structural knowledge this pipeline doesn't have.

This module deliberately does NOT try to replace a hand-written design doc.
It's framed explicitly as an on-chain cross-check: what the contract has
actually done, over a specific block range, as opposed to what any existing
documentation claims it does. Divergence between this and a hand-written doc
is a signal to go investigate which one is stale -- documentation drifts,
on-chain behavior doesn't. That's the whole reason this tool exists.
"""

from pathlib import Path
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.95:
        return "high confidence"
    if confidence >= 0.8:
        return "medium confidence"
    return "low confidence"


def _invariant_to_requirement(inv: Dict[str, Any]) -> str:
    """Translate one mined invariant into a plain-English requirement
    statement, honestly qualified as an observation over a finite sample --
    not a proof, and not phrased as an unconditional guarantee the way a
    human-authored spec might state one."""
    expr = inv.get("expression", "")
    conf = inv.get("confidence", 0.0)
    note = inv.get("note", "")
    total = inv.get("total")
    holds = inv.get("holds")
    sample_note = f" (observed in {holds}/{total} calls)" if total else ""
    label = _confidence_label(conf)
    line = f"- **{expr}**{sample_note} -- {label} ({conf:.2f}) from on-chain observation over the analyzed block range"
    if note:
        line += f". {note}"
    return line


def _entry_points_section(data: Dict[str, Any]) -> List[str]:
    """List only methods actually observed on-chain -- not the full ABI
    surface (which may include functions never called in this window), to
    avoid claiming more than was actually seen."""
    methods = set()
    for tx in data.get("evidence_txs", []):
        desc = tx.get("description")
        if desc and desc != "unknown":
            methods.add(desc)
    for t in data.get("state_machine", {}).get("transitions", []):
        trigger = t.get("trigger")
        if trigger and trigger not in ("unknown", "fallback"):
            methods.add(trigger)

    lines = ["### Entry points observed on-chain", ""]
    if methods:
        lines.append(", ".join(f"`{m}()`" for m in sorted(methods)))
        lines.append("")
        lines.append(
            "_Only methods with at least one observed call in the analyzed range are listed. "
            "The contract's full interface may include additional functions never called here._"
        )
    else:
        lines.append("_No decoded method calls observed in this range._")
    lines.append("")
    return lines


def _state_section(data: Dict[str, Any]) -> List[str]:
    sm = data.get("state_machine", {})
    states = sm.get("states", [])
    transitions = sm.get("transitions", [])
    lines = ["### State observed on-chain", ""]
    if len(states) <= 1:
        lines.append(
            "_No storage-level state changes were observed with evidence (a fetched trace or "
            "state diff) in this range -- this does not mean the contract is stateless, only "
            "that no evidenced state transition was captured here._"
        )
    else:
        lines.append(
            f"{len(states) - 1} distinct on-chain state(s) observed (beyond the initial state), "
            f"via {len(transitions)} evidenced transition(s). State identity here is a fingerprint "
            "over observed storage-diff/trace evidence, not named state variables -- see "
            "`observed_design.json`'s `state_machine` field for the underlying evidence "
            "(transaction hashes, storage slots) behind each transition."
        )
    lines.append("")
    return lines


def _interactions_section(data: Dict[str, Any]) -> List[str]:
    """Summarize any intermediary contracts (relayers/routers/aggregators)
    this contract was reached through, per the internal-call discovery
    mechanism -- see cli.py's discover_internal_call_txs."""
    entry_points: Dict[str, int] = {}
    for tx in data.get("evidence_txs", []):
        if tx.get("discovered_via") == "internal_call" and tx.get("entry_point"):
            ep = tx["entry_point"]
            entry_points[ep] = entry_points.get(ep, 0) + 1

    lines = ["### Interactions", ""]
    direct = data.get("tx_count_direct", data.get("tx_count", 0))
    internal = data.get("tx_count_internal_call", 0)
    if internal:
        lines.append(
            f"{direct} call(s) reached this contract directly; {internal} more were reached "
            "indirectly, via an intermediary contract (a relayer, router, or aggregator) making "
            "an internal call to it:"
        )
        lines.append("")
        for ep, count in sorted(entry_points.items(), key=lambda x: -x[1]):
            lines.append(f"- `{ep}` ({count} call(s))")
    else:
        lines.append(f"{direct} call(s) observed, all directly against this contract's own address.")
    lines.append("")
    return lines


def _proxy_note(data: Dict[str, Any]) -> str:
    proxy_info = data.get("proxy_info", {})
    if not proxy_info.get("is_proxy"):
        return ""
    return (
        f" This contract is a **{proxy_info.get('type', 'proxy')}** proxy; the analyzed "
        f"behavior reflects calls delegated to implementation `{proxy_info.get('implementation', 'unknown')}`."
    )


class AutoProverBundleGenerator:
    """Render observed on-chain behavior as an AutoProver-compatible design
    document (a `system_doc`): title, prose description, entry points /
    state / interactions, and plain-English requirements -- the convention
    verified against AutoProver's own test fixtures and finder-agent rubric.
    """

    def generate(self, data: Dict[str, Any], output_path: Path) -> Path:
        contract = data.get("contract_address", "unknown")
        contract_name = data.get("contract_name")
        chain_id = data.get("chain_id", 1)
        block_start, block_end = data.get("block_range", [0, 0])
        tx_count = data.get("tx_count", 0)
        standards = data.get("standards", [])
        contract_type = data.get("contract_type", "unknown")

        title = contract_name or f"Contract {contract}"
        subtitle_bits = []
        if standards:
            subtitle_bits.append(", ".join(standards))
        subtitle = f" ({', '.join(subtitle_bits)})" if subtitle_bits else ""

        lines: List[str] = [f"# {title}{subtitle}", ""]

        lines.append(
            f"This document describes **observed on-chain behavior** of `{contract}` "
            f"(chain ID {chain_id}) over blocks {block_start}-{block_end} ({tx_count} "
            f"transaction(s) analyzed), generated by OnChainIntentOracle."
            f"{_proxy_note(data)}"
        )
        lines.append("")
        lines.append(
            "**This is a cross-check against reality, not a replacement for a hand-written "
            "design doc.** Everything below reflects what actually happened on-chain in the "
            "analyzed window, with evidence (transaction hashes, confidence levels, sample "
            "sizes) behind every claim -- not what the contract is intended or documented to do. "
            "If this diverges from an existing design doc or NatSpec comments, treat the "
            "divergence as a signal to investigate which one is stale: documentation can go "
            "out of date the moment code changes without an update; on-chain behavior cannot."
        )
        lines.append("")

        lines.append(f"## {title}")
        lines.append("")
        lines.extend(_entry_points_section(data))
        lines.extend(_state_section(data))
        lines.extend(_interactions_section(data))

        lines.append("### Requirements (observed, not proven)")
        lines.append("")
        invariants = data.get("invariants", [])
        if invariants:
            lines.append(
                "Each item below is a statistical observation over the analyzed sample, not a "
                "formal guarantee -- confidence and sample size are given so you can judge how "
                "much weight to put on each one. None of these should be treated as already "
                "verified; they're candidates for the Certora Prover to actually check."
            )
            lines.append("")
            for inv in invariants:
                lines.append(_invariant_to_requirement(inv))
        else:
            lines.append(
                "_No statistical invariants were mined with enough sample size to report in "
                "this range (most checks require at least 3 observed calls to a given method "
                "before reporting anything). This does not mean the contract has no invariants "
                "-- it means this range didn't provide enough evidence to state any with "
                "confidence. A wider block range may surface some._"
            )
        lines.append("")

        conflicts = data.get("conflicts", {})
        omissions = conflicts.get("omissions", [])
        if omissions:
            lines.append(
                f"_{len(omissions)} observed function(s) had no corresponding claim in any "
                "design doc provided to this analysis run (see `conflict_report.md` for "
                "details, if one was generated)._"
            )
            lines.append("")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("autoprover_bundle_generated", path=str(output_path))
        return output_path
