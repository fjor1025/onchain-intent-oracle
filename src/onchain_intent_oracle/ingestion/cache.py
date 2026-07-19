"""Caching layer for on-chain data."""

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import declarative_base, sessionmaker

from onchain_intent_oracle.config.settings import get_settings

logger = structlog.get_logger()

Base = declarative_base()


class CachedTransaction(Base):
    __tablename__ = "cached_transactions"

    id = Column(Integer, primary_key=True)
    cache_key = Column(String, unique=True, index=True)
    chain_id = Column(Integer, nullable=False)
    contract_address = Column(String, nullable=False)
    data_json = Column(Text)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)


class CacheLayer:
    """Two-tier cache: SQLite (local) + Postgres (shared)."""

    def __init__(self, sqlite_path: Optional[Path] = None, postgres_url: Optional[str] = None):
        self.settings = get_settings()
        self.sqlite_path = sqlite_path or self.settings.sqlite_cache_path
        self.postgres_url = postgres_url or str(self.settings.database_url)

        # SQLite for fast local caching
        self._sqlite_conn: Optional[sqlite3.Connection] = None

        # Postgres for shared/persistent caching
        self._pg_engine = None
        self._pg_session = None
        if self.postgres_url:
            try:
                self._pg_engine = create_engine(self.postgres_url)
                Base.metadata.create_all(self._pg_engine)
                self._pg_session = sessionmaker(bind=self._pg_engine)
            except Exception as e:
                logger.warning("postgres_cache_unavailable", error=str(e))

    def _get_sqlite(self) -> sqlite3.Connection:
        if self._sqlite_conn is None:
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            self._sqlite_conn = sqlite3.connect(str(self.sqlite_path))
            self._sqlite_conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    expires_at REAL
                )
            """)
            self._sqlite_conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at)
            """)
        return self._sqlite_conn

    def _make_key(self, *parts: str) -> str:
        """Create a deterministic cache key."""
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache (SQLite first, then Postgres)."""
        # Try SQLite
        try:
            conn = self._get_sqlite()
            cursor = conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()
            if row:
                value, expires_at = row
                if expires_at is None or datetime.now().timestamp() < expires_at:
                    return json.loads(value)
                # Expired
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                conn.commit()
        except Exception as e:
            logger.debug("sqlite_cache_miss", key=key, error=str(e))

        # Try Postgres
        if self._pg_session:
            try:
                with self._pg_session() as session:
                    from sqlalchemy import and_
                    stmt = select(CachedTransaction).where(
                        and_(
                            CachedTransaction.cache_key == key,
                            CachedTransaction.expires_at > datetime.utcnow()
                        )
                    )
                    result = session.execute(stmt).scalar_one_or_none()
                    if result:
                        return json.loads(result.data_json)
            except Exception as e:
                logger.debug("pg_cache_miss", key=key, error=str(e))

        return None

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int = 86400,
    ) -> None:
        """Store value in both cache tiers."""
        json_value = json.dumps(value, default=str)
        expires = datetime.now() + timedelta(seconds=ttl_seconds)

        # SQLite
        try:
            conn = self._get_sqlite()
            conn.execute(
                """INSERT OR REPLACE INTO cache (key, value, expires_at)
                   VALUES (?, ?, ?)""",
                (key, json_value, expires.timestamp())
            )
            conn.commit()
        except Exception as e:
            logger.warning("sqlite_cache_set_failed", key=key, error=str(e))

        # Postgres
        if self._pg_session:
            try:
                with self._pg_session() as session:
                    from sqlalchemy.dialects.postgresql import insert
                    stmt = insert(CachedTransaction).values(
                        cache_key=key,
                        chain_id=0,  # Would need to be passed in
                        contract_address="",
                        data_json=json_value,
                        expires_at=expires,
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["cache_key"],
                        set_={"data_json": json_value, "expires_at": expires, "fetched_at": datetime.utcnow()}
                    )
                    session.execute(stmt)
                    session.commit()
            except Exception as e:
                logger.warning("pg_cache_set_failed", key=key, error=str(e))

    def get_tx_trace(self, chain_id: int, tx_hash: str) -> Optional[Dict]:
        key = self._make_key("trace", str(chain_id), tx_hash.lower())
        return self.get(key)

    def set_tx_trace(self, chain_id: int, tx_hash: str, trace: Dict, ttl: int = 604800) -> None:
        key = self._make_key("trace", str(chain_id), tx_hash.lower())
        self.set(key, trace, ttl)

    def get_contract_logs(
        self,
        chain_id: int,
        contract: str,
        from_block: int,
        to_block: int,
    ) -> Optional[List[Dict]]:
        key = self._make_key("logs", str(chain_id), contract.lower(), str(from_block), str(to_block))
        return self.get(key)

    def set_contract_logs(
        self,
        chain_id: int,
        contract: str,
        from_block: int,
        to_block: int,
        logs: List[Dict],
        ttl: int = 86400,
    ) -> None:
        key = self._make_key("logs", str(chain_id), contract.lower(), str(from_block), str(to_block))
        self.set(key, logs, ttl)
