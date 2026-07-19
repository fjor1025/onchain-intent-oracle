"""Pgvector-based vector store for RAG."""

import json
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from onchain_intent_oracle.config.settings import get_settings
from onchain_intent_oracle.rag.embeddings import EmbeddingProvider

logger = structlog.get_logger()


class VectorStore:
    """Vector store using Postgres + pgvector."""
    
    def __init__(self, connection_string: str = None):
        self.settings = get_settings()
        self.connection_string = connection_string or str(self.settings.database_url)
        self.embedder = EmbeddingProvider()
        self.engine = create_engine(self.connection_string)
        self.Session = sessionmaker(bind=self.engine)
    
    def add_documents(self, documents: List[Dict[str, str]]) -> None:
        """Index documents with embeddings."""
        texts = [doc["content"] for doc in documents]
        embeddings = self.embedder.embed(texts)
        
        with self.Session() as session:
            for doc, emb in zip(documents, embeddings):
                session.execute(
                    text("""
                        INSERT INTO kb_documents (source, title, content, metadata, embedding)
                        VALUES (:source, :title, :content, :meta, :embedding)
                    """),
                    {
                        "source": doc.get("source", "unknown"),
                        "title": doc.get("title", ""),
                        "content": doc["content"],
                        "meta": json.dumps(doc.get("metadata", {})),
                        "embedding": str(emb),
                    }
                )
            session.commit()
    
    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search for relevant documents."""
        query_embedding = self.embedder.embed_query(query)
        
        with self.Session() as session:
            result = session.execute(
                text("""
                    SELECT source, title, content, metadata,
                           embedding <=> :embedding as distance
                    FROM kb_documents
                    ORDER BY embedding <=> :embedding
                    LIMIT :limit
                """),
                {
                    "embedding": str(query_embedding),
                    "limit": top_k,
                }
            )
            
            return [
                {
                    "source": row.source,
                    "title": row.title,
                    "content": row.content,
                    "metadata": row.metadata,
                    "distance": row.distance,
                }
                for row in result
            ]
