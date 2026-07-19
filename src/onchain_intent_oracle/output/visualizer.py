"""Generate Mermaid diagrams for state machines and call graphs."""
from pathlib import Path
import structlog
logger = structlog.get_logger()

class Visualizer:
    def generate_all(self, data, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        sm = data.get("state_machine", {})
        states, transitions = sm.get("states", []), sm.get("transitions", [])
        if states and transitions:
            lines = ["stateDiagram-v2", "    [*] --> initial"]
            for s in {s["name"] for s in states}:
                if s != "initial": lines.append(f"    {s}")
            for t in transitions:
                if t.get("from") and t.get("to"): lines.append(f"    {t['from']} --> {t['to']}: {t.get('trigger', '')}")
            p = output_dir / "state_machine.mmd"
            p.write_text("\n".join(lines), encoding="utf-8")
            paths.append(p)
            logger.info("state_machine_diagram", path=str(p))

        evidence = data.get("evidence_txs", [])
        if evidence:
            lines, seen = ["graph TD"], set()
            for tx in evidence:
                m = tx.get("description", "unknown")
                if m not in seen: seen.add(m); lines.append(f"    {m}[{m}]")
            ml = list(seen)
            for i in range(len(ml) - 1): lines.append(f"    {ml[i]} --> {ml[i+1]}")
            p = output_dir / "call_graph.mmd"
            p.write_text("\n".join(lines), encoding="utf-8")
            paths.append(p)
            logger.info("call_graph", path=str(p))
        return paths
