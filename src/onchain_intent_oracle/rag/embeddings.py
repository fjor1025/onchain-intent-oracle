"""Embedding provider for document indexing."""

from typing import List

import structlog

from onchain_intent_oracle.config.settings import get_settings

logger = structlog.get_logger()


class EmbeddingUnavailableError(RuntimeError):
    """Raised when no embedding backend is configured or reachable.

    This used to fail silently: embed()/embed_query() returned all-zero
    vectors instead. That's actively harmful, not just a no-op -- a zero
    vector's cosine distance to anything (including another zero vector) is
    NaN, and pgvector's ivfflat index silently drops every row when ordering
    by a NaN distance (confirmed: the same query against the same data
    returns real rows via a full table scan but zero rows via the index).
    So `populate_kb.sh` would report success, `VectorStore.add_documents()`
    would report success, and `VectorStore.search()` would silently return
    zero results forever, with no error or warning anywhere pointing at why.
    """


class EmbeddingProvider:
    """Generate embeddings for text chunks."""

    def __init__(self, model: str = None):
        self.settings = get_settings()
        self.model = model or self.settings.embedding_model
        self._client = None

    def _get_client(self):
        if self._client is None:
            if self.model == "nomic-embed-text":
                try:
                    # Try langchain-ollama first (newer package)
                    try:
                        from langchain_ollama import OllamaEmbeddings
                        self._client = OllamaEmbeddings(model="nomic-embed-text")
                        logger.info("using_langchain_ollama")
                        return self._client
                    except ImportError:
                        pass

                    # Fallback to langchain_community
                    try:
                        from langchain_community.embeddings import OllamaEmbeddings
                        self._client = OllamaEmbeddings(model="nomic-embed-text")
                        logger.info("using_langchain_community")
                        return self._client
                    except ImportError:
                        pass

                    logger.warning("ollama_package_not_installed")
                    self._client = None

                except Exception as e:
                    logger.warning("ollama_init_failed", error=str(e))
                    self._client = None
            else:
                from langchain_openai import OpenAIEmbeddings
                self._client = OpenAIEmbeddings(
                    model=self.model,
                    api_key=self.settings.openai_api_key,
                )
        return self._client

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for texts.

        Raises EmbeddingUnavailableError rather than silently returning zero
        vectors -- see that class's docstring for why the old fallback was
        actively harmful, not just a harmless no-op.
        """
        client = self._get_client()
        if not client:
            raise EmbeddingUnavailableError(
                f"No embedding backend available for model {self.model!r}. "
                "For the default model, install Ollama and run "
                "`ollama pull nomic-embed-text`, or set OPENAI_API_KEY and "
                "EMBEDDING_MODEL in your .env to use OpenAI embeddings instead."
            )
        try:
            return client.embed_documents(texts)
        except Exception as e:
            raise EmbeddingUnavailableError(f"Embedding backend failed: {e}") from e

    def embed_query(self, text: str) -> List[float]:
        """Generate embedding for a single query.

        Raises EmbeddingUnavailableError rather than silently returning a zero
        vector -- see that class's docstring for why.
        """
        client = self._get_client()
        if not client:
            raise EmbeddingUnavailableError(
                f"No embedding backend available for model {self.model!r}. "
                "For the default model, install Ollama and run "
                "`ollama pull nomic-embed-text`, or set OPENAI_API_KEY and "
                "EMBEDDING_MODEL in your .env to use OpenAI embeddings instead."
            )
        try:
            return client.embed_query(text)
        except Exception as e:
            raise EmbeddingUnavailableError(f"Embedding backend failed: {e}") from e
