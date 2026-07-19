"""Embedding provider for document indexing."""

from typing import List

import structlog

from onchain_intent_oracle.config.settings import get_settings

logger = structlog.get_logger()


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
        """Generate embeddings for texts."""
        client = self._get_client()
        if client:
            try:
                return client.embed_documents(texts)
            except Exception as e:
                logger.warning("embedding_failed", error=str(e))
        # Fallback: return zero vectors
        dim = self.settings.vector_dimension
        return [[0.0] * dim for _ in texts]

    def embed_query(self, text: str) -> List[float]:
        """Generate embedding for a single query."""
        client = self._get_client()
        if client:
            try:
                return client.embed_query(text)
            except Exception as e:
                logger.warning("query_embedding_failed", error=str(e))
        return [0.0] * self.settings.vector_dimension
