"""Generate conflict reports comparing design docs vs observed behavior."""
from pathlib import Path
import structlog
logger = structlog.get_logger()

class ConflictReportGenerator:
    def generate(self, data, output_path):
        contract = data.get("contract_address", "unknown")
        lines = ["# Conflict Report", "", f"**Contract:** `{contract}`", ""]
        conflicts = data.get("conflicts", {})
        for section, key in [("Conflicts", "conflicts"), ("Omissions", "omissions"), ("Weakenings", "weakenings"), ("Security Gaps", "security_gaps")]:
            items = conflicts.get(key, [])
            lines.extend([f"## {section} ({len(items)})", ""])
            if items:
                for item in items:
                    if key == "omissions": lines.append(f"- **{item['function']}** ({item.get('observed_calls', 0)} calls): {item.get('recommendation', '')}")
                    elif key == "weakenings": lines.append(f"- **{item['invariant']}** -- holds {item.get('holds', 0)}/{item.get('total', 0)} (confidence: {item['confidence']})")
                    else: lines.append(f"- {item.get('description', str(item))}")
            else: lines.append(f"No {section.lower()} detected.")
            lines.append("")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("conflict_report_generated", path=str(output_path))
        return output_path
