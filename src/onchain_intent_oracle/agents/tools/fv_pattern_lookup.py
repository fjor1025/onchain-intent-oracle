"""Tool for looking up formal verification patterns from RAG."""

from typing import Any, Dict, List

from langchain_core.tools import BaseTool
from pydantic import Field

from onchain_intent_oracle.rag.vector_store import VectorStore


class FVPatternLookupTool(BaseTool):
    """Search the formal verification knowledge base for relevant patterns."""

    name: str = "fv_pattern_lookup"
    description: str = "Search the FV knowledge base for relevant patterns and best practices"
    vector_store: VectorStore = Field(default=None)

    def _run(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Synchronous search."""
        if not self.vector_store:
            return []
        return self.vector_store.search(query, top_k=top_k)

    async def _arun(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Async search."""
        return self._run(query, top_k)
