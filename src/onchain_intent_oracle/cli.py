"""CLI for OnChainIntentOracle using Typer."""
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import structlog

import typer

from onchain_intent_oracle.analysis.invariant_miner import InvariantMiner
from onchain_intent_oracle.analysis.pattern_clustering import PatternClustering
from onchain_intent_oracle.analysis.state_machine import StateMachineInference
from onchain_intent_oracle.config.chains import get_chain_config
from onchain_intent_oracle.config.settings import Settings
from onchain_intent_oracle.ingestion.proxy_detector import ProxyDetector
from onchain_intent_oracle.ingestion.rpc_manager import RPCManager
from onchain_intent_oracle.ingestion.signature_decoder import SignatureDecoder
from onchain_intent_oracle.ingestion.trace_fetcher import TraceFetcher
from onchain_intent_oracle.output.conflict_report import ConflictReportGenerator
from onchain_intent_oracle.output.json_generator import JSONGenerator
from onchain_intent_oracle.output.markdown_generator import MarkdownGenerator
from onchain_intent_oracle.output.visualizer import Visualizer

logger = structlog.get_logger()
app = typer.Typer()

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


async def fetch_transactions_for_range(
    rpc: RPCManager,
    address: str,
    from_block: int,
    to_block: int,
    chain_id: int = 1,
) -> List[Dict[str, Any]]:
    """Fetch transactions involving address across a block range."""
    txs = []
    address_lower = address.lower()
    for block_num in range(from_block, to_block + 1):
        try:
            block = await rpc.request("eth_getBlockByNumber", [hex(block_num), True])
            if not block or not block.get("transactions"):
                continue
            for tx in block["transactions"]:
                tx_from = (tx.get("from") or "").lower()
                tx_to = (tx.get("to") or "").lower()
                if tx_from == address_lower or tx_to == address_lower:
                    tx["blockNumber"] = block_num
                    tx["hash"] = tx.get("hash", "")
                    tx["input"] = tx.get("input", "0x")
                    txs.append(tx)
        except Exception as e:
            logger.debug("block_fetch_failed", block=block_num, error=str(e))
    return txs


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
    depth: str = typer.Option("standard", "--depth", help="Analysis depth")
):
    """Analyze a smart contract."""
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
    typer.echo("Analyzing " + contract_address + " on " + chain + " (chain_id=" + str(chain_id) + ", blocks " + str(start_block) + "-" + str(end_block) + ")...")
    result = asyncio.run(_run_analysis(contract_address, chain_id, start_block, end_block, rpc, sig_decoder, proxy_detector, trace_fetcher))
    typer.echo("Generating outputs...")
    MarkdownGenerator().generate(result, output_dir / "observed_design.md")
    JSONGenerator().generate(result, output_dir / "observed_design.json")
    ConflictReportGenerator().generate(result, output_dir / "conflict_report.md")
    Visualizer().generate_all(result, output_dir / "visualizations")
    typer.echo("Done. Output written to " + str(output_dir))


async def _run_analysis(contract, chain_id, start_block, end_block, rpc, sig_decoder, proxy_detector, trace_fetcher):
    is_proxy, impl, proxy_type = await proxy_detector.detect_proxy(contract)
    target = impl or contract
    proxy_info = {
        "is_proxy": is_proxy,
        "implementation": impl,
        "type": proxy_type,
    }
    txs = await fetch_transactions_for_range(rpc, target, start_block, end_block, chain_id)
    for tx in txs:
        inp = tx.get("input", "")
        if inp and inp != "0x":
            method, _ = sig_decoder.decode_trace(inp)
            tx["method"] = method
        else:
            tx["method"] = "unknown"
    sm = StateMachineInference().infer(txs, signature_decoder=sig_decoder)
    invariants = InvariantMiner().mine(txs, contract)
    patterns = PatternClustering().cluster(txs)
    omissions = []
    methods = {}
    for tx in txs:
        m = tx.get("method", "unknown")
        methods[m] = methods.get(m, 0) + 1
    for m, c in sorted(methods.items(), key=lambda x: -x[1]):
        omissions.append({"type": "undocumented_function", "function": m, "observed_calls": c, "recommendation": "Document " + m + "() in design doc"})
    weakenings = [{"invariant": i.get("expression", ""), "confidence": i.get("confidence", 0), "holds": i.get("holds", 0), "total": i.get("total", 0), "note": "Statistical invariant"} for i in invariants if i.get("confidence", 1.0) < 1.0]
    evidence = []
    for tx in txs[:20]:
        evidence.append({"hash": tx.get("hash", ""), "block": tx.get("blockNumber", 0), "description": tx.get("method", "unknown")})
    return {
        "contract_address": contract, "chain_id": chain_id, "block_range": [start_block, end_block],
        "tx_count": len(txs), "proxy_info": proxy_info, "contract_type": "unknown", "standards": [],
        "state_machine": {"states": [{"name": s.name, "description": s.description, "is_implicit": s.is_implicit} for s in sm.states], "transitions": [{"from": t.from_state, "to": t.to_state, "trigger": t.trigger, "guard": t.guard} for t in sm.transitions]},
        "invariants": invariants, "patterns": patterns, "anomalies": [],
        "conflicts": {"conflicts": [], "omissions": omissions, "weakenings": weakenings, "security_gaps": []},
        "evidence_txs": evidence, "high_confidence_invariants": [i for i in invariants if i.get("confidence", 0) >= 0.95],
        "medium_confidence_invariants": [i for i in invariants if 0.8 <= i.get("confidence", 0) < 0.95],
        "overview": "Contract " + contract + " on chain " + str(chain_id) +" analyzed from block " + str(start_block) + " to " + str(end_block) + ".",
        "security_notes": "Proxy: " + proxy_type + ", Implementation: " + (impl or "N/A"),
    }


if __name__ == "__main__":
    app()
