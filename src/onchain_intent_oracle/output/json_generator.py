"""Generate JSON output from analysis results."""
import json
from pathlib import Path
import structlog
logger = structlog.get_logger()

class JSONGenerator:
    def generate(self, data, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        logger.info("json_generated", path=str(output_path))
        return output_path
