"""Agent tools for RAG and evidence lookup."""

from .fv_pattern_lookup import FVPatternLookupTool

# NOTE: DeFiPatternTool (defi_patterns.py) and EvidenceFetchTool
# (evidence_fetch.py) were referenced here but their source files were never
# created -- `from .defi_patterns import DeFiPatternTool` raised
# ModuleNotFoundError the moment anything imported this package. Nothing in
# the live agent pipeline (graph.py, the node modules) currently imports this
# package at all, which is why it went unnoticed. Only exporting what
# actually exists rather than inventing unspecified implementations for the
# other two -- if/when they're built, add them back here.
__all__ = ["FVPatternLookupTool"]
