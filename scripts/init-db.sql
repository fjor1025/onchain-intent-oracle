-- Create databases for OIO
CREATE EXTENSION IF NOT EXISTS vector;

-- RAG knowledge base
CREATE TABLE IF NOT EXISTS kb_documents (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    embedding VECTOR(768),  -- nomic-embed-text dimension
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kb_embedding ON kb_documents USING ivfflat (embedding vector_cosine_ops);

-- Transaction cache
CREATE TABLE IF NOT EXISTS tx_cache (
    id SERIAL PRIMARY KEY,
    chain_id INTEGER NOT NULL,
    contract_address BYTEA NOT NULL,
    tx_hash BYTEA NOT NULL UNIQUE,
    block_number INTEGER NOT NULL,
    from_address BYTEA,
    to_address BYTEA,
    value NUMERIC,
    gas_used BIGINT,
    gas_price NUMERIC,
    input BYTEA,
    status INTEGER,
    timestamp TIMESTAMP,
    raw JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tx_contract ON tx_cache(chain_id, contract_address);
CREATE INDEX IF NOT EXISTS idx_tx_hash ON tx_cache(tx_hash);
CREATE INDEX IF NOT EXISTS idx_tx_block ON tx_cache(block_number);

-- Trace cache
CREATE TABLE IF NOT EXISTS trace_cache (
    id SERIAL PRIMARY KEY,
    chain_id INTEGER NOT NULL,
    tx_hash BYTEA NOT NULL,
    trace JSONB NOT NULL,
    state_diff JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trace_tx ON trace_cache(chain_id, tx_hash);

-- Event log cache
CREATE TABLE IF NOT EXISTS log_cache (
    id SERIAL PRIMARY KEY,
    chain_id INTEGER NOT NULL,
    contract_address BYTEA NOT NULL,
    block_number INTEGER NOT NULL,
    log_index INTEGER NOT NULL,
    tx_hash BYTEA NOT NULL,
    topic0 BYTEA,
    topics BYTEA[],
    data BYTEA,
    decoded JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_log_contract ON log_cache(chain_id, contract_address);
CREATE INDEX IF NOT EXISTS idx_log_topic0 ON log_cache(topic0);
CREATE INDEX IF NOT EXISTS idx_log_block ON log_cache(block_number);

-- Analysis results
CREATE TABLE IF NOT EXISTS analysis_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_address BYTEA NOT NULL,
    chain_id INTEGER NOT NULL,
    block_range JSONB,
    status TEXT DEFAULT 'pending',
    results JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);
