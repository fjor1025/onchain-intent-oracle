#!/bin/bash
set -e

echo "Populating OnChainIntentOracle knowledge base..."

# Check if uv is available
if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed. Install from https://github.com/astral-sh/uv"
    exit 1
fi

# Install dependencies (the numpy/scikit-learn/pandas deps some of this
# needs are already in the base `dependencies` list in pyproject.toml --
# there's no separate "ml" extra, despite what this script used to say)
cd "$(dirname "$0")/.."
uv pip install -e "."

# Populate DeFi patterns
echo "Indexing DeFi patterns..."
uv run python -c "
from onchain_intent_oracle.rag.document_loader import DocumentLoader
from onchain_intent_oracle.rag.vector_store import VectorStore

loader = DocumentLoader()
store = VectorStore()

# Index DeFi patterns
patterns = loader.load_defi_patterns()
store.add_documents(patterns)
print(f'Indexed {len(patterns)} DeFi patterns')

# Index pitfall articles
pitfalls = loader.load_pitfall_articles()
store.add_documents(pitfalls)
print(f'Indexed {len(pitfalls)} pitfall articles')
"


echo "Knowledge base population complete!"
