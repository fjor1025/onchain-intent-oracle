"""CLI for OnChainIntentOracle using Typer."""
import asyncio
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
import structlog

import typer

from onchain_intent_oracle.agents.graph import build_workflow
from onchain_intent_oracle.analysis.anomaly_detector import AnomalyDetector
from onchain_intent_oracle.analysis.conflict_reconciler import ConflictReconciler
from onchain_intent_oracle.analysis.invariant_miner import InvariantMiner
from onchain_intent_oracle.analysis.pattern_clustering import PatternClustering
from onchain_intent_oracle.analysis.state_machine import StateMachineInference
from onchain_intent_oracle.config.chains import get_chain_config
from onchain_intent_oracle.config.settings import Settings
from onchain_intent_oracle.ingestion.proxy_detector import ProxyDetector
from onchain_intent_oracle.ingestion.rpc_manager import RPCManager
from onchain_intent_oracle.ingestion.signature_decoder import SignatureDecoder
from onchain_intent_oracle.ingestion.source_resolver import SourceResolver, abi_to_selector_map, detect_standards
from onchain_intent_oracle.ingestion.trace_fetcher import TraceFetcher
from onchain_intent_oracle.models.invariant import Invariant, InvariantType
from onchain_intent_oracle.models.transaction import CallTrace, StateDiff, Transaction
from onchain_intent_oracle.output.conflict_report import ConflictReportGenerator
from onchain_intent_oracle.output.json_generator import JSONGenerator
from onchain_intent_oracle.output.markdown_generator import MarkdownGenerator
from onchain_intent_oracle.output.visualizer import Visualizer

logger = structlog.get_logger()
app = typer.Typer()

DEPTH_LEVELS = ("quick", "standard", "deep")

CHAIN_NAME_TO_ID = {
    "ethereum": 1, "mainnet": 1, "sepolia": 11155111, "goerli": 5,
    "polygon": 137, "mumbai": 80001, "arbitrum": 42161, "arbitrum-one": 42161,
    "optimism": 10, "base": 8453, "bsc": 56, "avalanche": 43114,
    "fantom": 250, "gnosis": 100,
}


def resolve_chain_id(chain: str) -> int:
    chain = chain.lower().strip()
    if chain in CHAIN_NAME_TO_ID:
        return CHAIN_NAME_TO_ID[chain]
    try:
        return int(chain)
    except ValueError:
        raise typer.BadParameter(f"Unknown chain: {chain}. Use a known name or numeric chain ID.")


def _extract_trace_output(trace_raw: Any) -> str:
    """Normalize the two different shapes TraceFetcher.fetch_trace() can return.

    It tries debug_traceTransaction (callTracer) first, which returns a dict
    with "output" at the top level. If that's unavailable (many RPC providers
    reject debug_traceTransaction, e.g. on free/growth tiers), it falls back
    to the Parity/OpenEthereum-style trace_transaction RPC, which returns a
    *list* of trace frames, each with a nested "result": {"output": ...}.
    """
    if isinstance(trace_raw, dict):
        return trace_raw.get("output", "")
    if isinstance(trace_raw, list):
        # Prefer the top-level call frame (traceAddress == []); fall back to
        # the first frame if none is marked as top-level.
        top = next((t for t in trace_raw if isinstance(t, dict) and t.get("traceAddress") == []), None)
        if top is None and trace_raw:
            top = trace_raw[0]
        if isinstance(top, dict):
            result = top.get("result") or {}
            if isinstance(result, dict):
                return result.get("output", "")
    return ""


DEFAULT_BLOCK_FETCH_CONCURRENCY = 25
DEFAULT_ENRICH_CONCURRENCY = 10


async def fetch_transactions_for_range(
    rpc: RPCManager,
    address: str,
    from_block: int,
    to_block: int,
    chain_id: int = 1,
    max_concurrency: int = DEFAULT_BLOCK_FETCH_CONCURRENCY,
) -> List[Dict[str, Any]]:
    """Fetch transactions involving address across a block range.

    Blocks are fetched concurrently (bounded by `max_concurrency`) instead of
    one-at-a-time. RPCManager's per-provider rate limiter still paces the
    actual request rate, and multiple configured RPC URLs are used in
    parallel via round-robin, so this is both faster and RPS-safe.
    """
    address_lower = address.lower()
    semaphore = asyncio.Semaphore(max_concurrency)

    async def fetch_block(block_num: int) -> List[Dict[str, Any]]:
        async with semaphore:
            try:
                block = await rpc.request("eth_getBlockByNumber", [hex(block_num), True])
            except Exception as e:
                logger.debug("block_fetch_failed", block=block_num, error=str(e))
                return []
        if not block or not block.get("transactions"):
            return []
        found = []
        for tx in block["transactions"]:
            tx_from = (tx.get("from") or "").lower()
            tx_to = (tx.get("to") or "").lower()
            if tx_from == address_lower or tx_to == address_lower:
                tx["blockNumber"] = block_num
                tx["hash"] = tx.get("hash", "")
                tx["input"] = tx.get("input", "0x")
                found.append(tx)
        return found

    results = await asyncio.gather(*(fetch_block(b) for b in range(from_block, to_block + 1)))
    txs: List[Dict[str, Any]] = []
    for chunk in results:
        txs.extend(chunk)
    return txs


async def enrich_transactions(
    rpc: RPCManager,
    trace_fetcher: TraceFetcher,
    txs: List[Dict[str, Any]],
    chain_id: int = 1,
    max_concurrency: int = DEFAULT_ENRICH_CONCURRENCY,
    fetch_traces: bool = True,
) -> None:
    """Attach real receipt status, call traces, and state diffs to each tx in place.

    This is what makes revert detection and state-machine inference actually see
    on-chain reality instead of degenerating to "every tx succeeded" / "every tx
    is a distinct state". Trace/state-diff fetching is best-effort: many public
    RPC endpoints don't support debug_traceTransaction, in which case those
    fields are simply left unset and downstream analysis falls back gracefully
    (state fingerprinting still works off tx input/from/to; revert detection
    still works off the receipt status, which every RPC supports).

    `fetch_traces=False` (used at --depth=quick) skips the trace/state-diff
    calls entirely and only fetches receipts -- receipts are a single cheap,
    universally-supported call needed for revert detection; traces/state-diffs
    are the expensive part (1-2 extra calls per tx to an endpoint many
    providers don't support on free tiers at all).
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def enrich_one(tx: Dict[str, Any]) -> None:
        tx_hash = tx.get("hash")
        if not tx_hash:
            return
        async with semaphore:
            try:
                receipt = await rpc.get_transaction_receipt(tx_hash)
                if receipt and "status" in receipt:
                    tx["status"] = receipt["status"]
            except Exception as e:
                logger.debug("receipt_fetch_failed", tx_hash=tx_hash, error=str(e))

            if not fetch_traces:
                return

            trace_raw = await trace_fetcher.fetch_trace(tx_hash, chain_id)
            if trace_raw:
                tx["traces"] = [{"output": _extract_trace_output(trace_raw)}]

            diffs = await trace_fetcher.fetch_state_diff(tx_hash, chain_id)
            if diffs:
                tx["state_diff"] = {d.slot: {"old": d.old_value, "new": d.new_value} for d in diffs}

    await asyncio.gather(*(enrich_one(tx) for tx in txs))


def _to_int(val, default=0):
    if val is None:
        return default
    if isinstance(val, str):
        try:
            return int(val, 16) if val.lower().startswith("0x") else int(val)
        except ValueError:
            return default
    return int(val)


def _tx_dict_to_model(tx: Dict[str, Any]) -> Transaction:
    """Adapt cli.py's raw JSON-RPC-shaped tx dict to the Transaction model that
    ConflictReconciler and PatternClustering expect (they're typed against the
    model, not the dict shape the rest of this pipeline uses)."""
    status = tx.get("status")
    state_diff = tx.get("state_diff") or {}
    state_diffs = [
        StateDiff(
            slot=slot,
            old_value=(v.get("old") if isinstance(v, dict) else None),
            new_value=(v.get("new") if isinstance(v, dict) else v),
        )
        for slot, v in state_diff.items()
    ]
    traces = tx.get("traces") or []
    trace = None
    if traces:
        first = traces[0]
        trace = CallTrace(
            type="CALL",
            from_address=tx.get("from", "") or "",
            to_address=tx.get("to"),
            output=first.get("output", "0x") if isinstance(first, dict) else "0x",
        )
    return Transaction(
        hash=tx.get("hash", ""),
        block_number=_to_int(tx.get("blockNumber"), 0),
        # Block timestamp isn't fetched by this pipeline; not used by
        # ConflictReconciler's or PatternClustering's checks, so a
        # placeholder is fine here.
        timestamp=datetime.now(timezone.utc),
        from_address=tx.get("from", "") or "",
        to_address=tx.get("to"),
        value=Decimal(_to_int(tx.get("value"), 0)),
        gas_price=Decimal(_to_int(tx.get("gasPrice"), 0)) if tx.get("gasPrice") else None,
        gas_used=_to_int(tx.get("gas"), 0) or None,
        status=InvariantMiner._normalize_status(status) if status is not None else None,
        input=tx.get("input", "0x"),
        method_name=tx.get("method"),
        trace=trace,
        state_diffs=state_diffs,
    )


def _invariant_dict_to_model(inv: Dict[str, Any]) -> Invariant:
    try:
        inv_type = InvariantType(inv.get("type", "other"))
    except ValueError:
        inv_type = InvariantType.OTHER
    return Invariant(
        id=inv.get("id", ""),
        expression=inv.get("expression", ""),
        type=inv_type,
        confidence=inv.get("confidence", 0.0),
        hold_count=inv.get("holds", 0),
        total_count=inv.get("total", 0),
        evidence=inv.get("evidence", []),
    )


def _conflicts_to_dict(report) -> Dict[str, Any]:
    return {
        "conflicts": [
            {
                "severity": c.severity,
                "category": c.category,
                "design_claim": c.design_claim,
                "observed_reality": c.observed_reality,
                "code_evidence": c.code_evidence,
                "recommendation": c.recommendation,
                "evidence_txs": c.evidence_txs,
            }
            for c in report.conflicts
        ],
        "omissions": report.omissions,
        "weakenings": report.weakenings,
        "security_gaps": report.security_gaps,
    }


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v")):
    """OnChain Intent Oracle CLI."""
    pass


@app.command()
def analyze(
    contract_address: str = typer.Argument(..., help="Contract address to analyze"),
    chain: str = typer.Option("ethereum", "--chain", help="Blockchain network name or ID"),
    block_range: str = typer.Option(..., "--block-range", help="Block range as start:end"),
    output: str = typer.Option("./oio-output", "--output", "-o", help="Output directory"),
    depth: str = typer.Option(
        "standard", "--depth",
        help="Analysis depth: 'quick' (receipts + block data only, skips "
             "trace/state-diff enrichment and ABI resolution -- fastest, "
             "least evidence for the state machine), 'standard' (default -- "
             "full enrichment), or 'deep' (standard, plus a larger evidence-tx "
             "sample and higher enrichment concurrency).",
    ),
    design_doc: Optional[Path] = typer.Option(
        None, "--design-doc", help="Path to a design doc / spec to reconcile against observed behavior"
    ),
    use_agents: bool = typer.Option(
        False, "--agents",
        help="Also run the LLM agent pipeline for richer narrative output. "
             "Requires ANTHROPIC_API_KEY for full effect; safe without one "
             "(falls back to deterministic per-node output).",
    ),
):
    """Analyze a smart contract."""
    if depth not in DEPTH_LEVELS:
        raise typer.BadParameter(f"--depth must be one of {DEPTH_LEVELS}, got {depth!r}")
    settings = Settings()
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)
    start_block, end_block = map(int, block_range.split(":"))
    chain_id = resolve_chain_id(chain)
    chain_config = get_chain_config(chain_id)
    rpc = RPCManager(urls=settings.rpc_urls)
    sig_decoder = SignatureDecoder()
    proxy_detector = ProxyDetector(rpc=rpc)
    trace_fetcher = TraceFetcher(rpc=rpc)
    source_resolver = SourceResolver()
    design_doc_text = design_doc.read_text() if design_doc else None
    typer.echo("Analyzing " + contract_address + " on " + chain + " (chain_id=" + str(chain_id) + ", blocks " + str(start_block) + "-" + str(end_block) + ", depth=" + depth + ")...")
    result, txs = asyncio.run(_run_analysis(contract_address, chain_id, start_block, end_block, rpc, sig_decoder, proxy_detector, trace_fetcher, source_resolver, design_doc_text, depth))
    typer.echo("Generating outputs...")
    MarkdownGenerator().generate(result, output_dir / "observed_design.md")
    JSONGenerator().generate(result, output_dir / "observed_design.json")
    ConflictReportGenerator().generate(result, output_dir / "conflict_report.md")
    Visualizer().generate_all(result, output_dir / "visualizations")
    if use_agents:
        typer.echo("Running agent pipeline (requires network access to the LLM provider)...")
        try:
            agent_state = asyncio.run(_run_agent_pipeline(result, txs, design_doc_text))
        except Exception as e:
            typer.echo(f"Agent pipeline failed, keeping direct-analysis output: {e}", err=True)
        else:
            if agent_state.get("observed_design_md"):
                (output_dir / "observed_design.md").write_text(agent_state["observed_design_md"])
            if agent_state.get("property_candidates"):
                (output_dir / "property_candidates.md").write_text(agent_state["property_candidates"])
            if agent_state.get("conflict_report"):
                (output_dir / "conflict_report.md").write_text(agent_state["conflict_report"])
    typer.echo("Done. Output written to " + str(output_dir))


async def _run_analysis(contract, chain_id, start_block, end_block, rpc, sig_decoder, proxy_detector, trace_fetcher, source_resolver, design_doc_text=None, depth="standard"):
    is_proxy, impl, proxy_type = await proxy_detector.detect_proxy(contract)
    # Real on-chain activity happens against the proxy address -- that's the
    # whole point of the proxy pattern. The implementation/logic contract is
    # only ever reached via DELEGATECALL from the proxy, so it receives ~zero
    # direct external transactions of its own. Fetching against `impl` here
    # (as this used to do) silently returns tx_count=0 for essentially every
    # real proxied contract. `impl` is still tracked for anything that needs
    # the logic contract specifically (e.g. resolving its ABI/source).
    target = contract
    proxy_info = {
        "is_proxy": is_proxy,
        "implementation": impl,
        "type": proxy_type,
    }

    # Best-effort ABI resolution (needs ETHERSCAN_API_KEY + a verified contract;
    # silently yields nothing otherwise -- the pipeline still works either way,
    # just falls back entirely to 4byte.directory guessing below). The *logic*
    # contract's ABI is what we want here, not the proxy's own trivial
    # interface, since that's where the real functions being called live.
    # Skipped entirely at depth="quick" to save the extra network round trip.
    abi_selectors: Dict[str, str] = {}
    standards: List[str] = []
    if depth != "quick":
        abi_target = impl if (is_proxy and impl) else contract
        abi = await source_resolver.get_abi(abi_target, chain_id)
        abi_selectors = abi_to_selector_map(abi) if abi else {}
        standards = detect_standards(abi) if abi else []
    contract_type = ", ".join(standards) if standards else "unknown"

    txs = await fetch_transactions_for_range(rpc, target, start_block, end_block, chain_id)
    # Pull real receipt status + (depth-permitting) call traces + state diffs
    # for each tx. Receipt status is always fetched -- every RPC provider
    # supports it and revert detection depends on it. Trace/state-diff
    # enrichment is skipped at depth="quick" (it's the expensive part: an
    # extra 1-2 RPC calls per tx, often to an endpoint many providers don't
    # even support on free tiers -- see the debug_trace_unavailable warnings
    # in the README's troubleshooting section). At depth="deep", enrichment
    # runs with higher concurrency to push through large ranges faster.
    enrich_concurrency = DEFAULT_ENRICH_CONCURRENCY if depth != "deep" else DEFAULT_ENRICH_CONCURRENCY * 2
    if depth == "quick":
        await enrich_transactions(rpc, trace_fetcher, txs, chain_id, max_concurrency=enrich_concurrency, fetch_traces=False)
    else:
        await enrich_transactions(rpc, trace_fetcher, txs, chain_id, max_concurrency=enrich_concurrency)
    for tx in txs:
        inp = tx.get("input", "")
        if inp and inp != "0x":
            selector = inp[:10].lower()
            abi_name = abi_selectors.get(selector)
            if abi_name:
                # Authoritative: derived directly from the verified ABI's own
                # keccak256(signature), not a 4byte.directory guess that could
                # collide with an unrelated function sharing the same selector.
                method = abi_name
            else:
                method, _ = await sig_decoder.adecode_trace(inp)
            tx["method"] = method
        else:
            tx["method"] = "unknown"
        tx["method_name"] = tx["method"]
    sm = StateMachineInference().infer(txs, signature_decoder=sig_decoder, contract_address=target)
    invariants = InvariantMiner().mine(txs, contract)
    # PatternClustering (like ConflictReconciler) is typed against the
    # Transaction model, not the raw dict shape the rest of this pipeline
    # uses -- feeding it dicts directly raises AttributeError the moment
    # there are enough txs to clear its min_samples threshold (it was never
    # actually exercised in earlier testing because every prior run had too
    # few transactions to reach that code path at all).
    model_txs = [_tx_dict_to_model(tx) for tx in txs]
    patterns = PatternClustering().cluster(model_txs)
    # AnomalyDetector is also typed against the Transaction model -- same
    # deal as PatternClustering above. It also needs >= 20 txs before it'll
    # produce anything (it splits the sample 80/20 into baseline/check), so
    # it stayed silently untested for the same reason PatternClustering did:
    # every prior run's sample size was too small to reach its logic at all.
    anomalies = AnomalyDetector().detect(model_txs)

    # Reconcile against a design doc, if one was provided. Previously this was
    # skipped entirely -- `conflicts` was always hardcoded to empty lists even
    # though comparing design claims to observed behavior is the tool's whole
    # premise, and `omissions`/`weakenings` were recomputed ad hoc below in a
    # way that duplicated (and diverged from) ConflictReconciler's own logic.
    model_invariants = [_invariant_dict_to_model(i) for i in invariants]
    reconciler = ConflictReconciler(design_doc=design_doc_text)
    reconciliation = reconciler.reconcile(model_txs, model_invariants)
    conflicts_out = _conflicts_to_dict(reconciliation)

    evidence = []
    evidence_sample_size = 20 if depth != "deep" else 100
    for tx in txs[:evidence_sample_size]:
        evidence.append({"hash": tx.get("hash", ""), "block": tx.get("blockNumber", 0), "description": tx.get("method", "unknown")})
    await source_resolver.close()
    return {
        "contract_address": contract, "chain_id": chain_id, "block_range": [start_block, end_block],
        "tx_count": len(txs), "proxy_info": proxy_info, "contract_type": contract_type, "standards": standards,
        "state_machine": {"states": [{"name": s.name, "description": s.description, "is_implicit": s.is_implicit} for s in sm.states], "transitions": [{"from": t.from_state, "to": t.to_state, "trigger": t.trigger, "guard": t.guard} for t in sm.transitions]},
        "invariants": invariants, "patterns": patterns, "anomalies": anomalies,
        "conflicts": conflicts_out,
        "evidence_txs": evidence, "high_confidence_invariants": [i for i in invariants if i.get("confidence", 0) >= 0.95],
        "medium_confidence_invariants": [i for i in invariants if 0.8 <= i.get("confidence", 0) < 0.95],
        "overview": "Contract " + contract + " on chain " + str(chain_id) +" analyzed from block " + str(start_block) + " to " + str(end_block) + ".",
        "security_notes": "Proxy: " + proxy_type + ", Implementation: " + (impl or "N/A"),
    }, txs


async def _run_agent_pipeline(result: Dict[str, Any], txs: List[Dict[str, Any]], design_doc_text: Optional[str]) -> Dict[str, Any]:
    """Run the LangGraph agent workflow (data_collector -> state_inference ->
    invariant_proposer -> conflict_reconciler -> summarizer -> property_generator)
    on top of the direct pipeline's output.

    This is the six-agent workflow the README/architecture doc describe as the
    centerpiece; previously `cli.py` never imported anything from
    `onchain_intent_oracle.agents` at all, so this code path was fully unreachable.
    It's opt-in via `--agents` here because it calls out to an LLM (Claude, via
    ANTHROPIC_API_KEY) for its richer narrative output. Without a key configured,
    each node falls back to a deterministic non-LLM path (see build_workflow /
    the individual node implementations) rather than failing, so `--agents` is
    still safe to pass without one -- it just won't add much over the direct
    pipeline's output in that case.
    """
    workflow = build_workflow()
    initial_state = {
        "contract_address": result["contract_address"],
        "chain_id": result["chain_id"],
        "block_range": tuple(result["block_range"]),
        "design_doc": design_doc_text,
        "threat_model": None,
        "source_code": None,
        "abi": None,
        "transactions": txs,
        "traces": [],
        "logs": [],
        "proxy_info": result["proxy_info"],
        "state_machine": result["state_machine"],
        "invariants": result["invariants"],
        "patterns": result["patterns"],
        "anomalies": result["anomalies"],
        "conflicts": result["conflicts"],
        "messages": [],
        "current_agent": "",
        "checkpoint_path": None,
        "observed_design_md": None,
        "observed_design_json": None,
        "property_candidates": None,
        "conflict_report": None,
        "visualizations": [],
    }
    config = {"configurable": {"thread_id": result["contract_address"]}}
    return await workflow.ainvoke(initial_state, config=config)


if __name__ == "__main__":
    app()
