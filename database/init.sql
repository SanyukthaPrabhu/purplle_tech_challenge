-- Init script to bootstrap database schema, extensions, and tables

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ================================================================
-- stores
-- ================================================================
CREATE TABLE IF NOT EXISTS stores (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name          TEXT NOT NULL,
    location      TEXT,
    timezone      TEXT NOT NULL DEFAULT 'UTC',
    layout_json   JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ================================================================
-- zones
-- ================================================================
CREATE TABLE IF NOT EXISTS zones (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    store_id      UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    zone_type     TEXT NOT NULL,
    polygon       JSONB NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ================================================================
-- visitor_sessions
-- ================================================================
CREATE TABLE IF NOT EXISTS visitor_sessions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    store_id        UUID REFERENCES stores(id),
    store_code      TEXT NOT NULL,
    visitor_id      TEXT NOT NULL,
    camera_id       TEXT NOT NULL,
    entry_time      TIMESTAMPTZ,
    exit_time       TIMESTAMPTZ,
    total_dwell_ms  INTEGER,
    is_staff        BOOLEAN NOT NULL DEFAULT FALSE,
    reentry_count   INTEGER NOT NULL DEFAULT 0,
    session_hash    TEXT UNIQUE NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ================================================================
-- events
-- ================================================================
CREATE TABLE IF NOT EXISTS events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    store_id        UUID REFERENCES stores(id),
    store_code      TEXT NOT NULL,
    session_id      UUID REFERENCES visitor_sessions(id),
    camera_id       TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    zone_id         TEXT,
    visitor_id      TEXT NOT NULL,
    frame_number    BIGINT,
    bbox            JSONB,
    confidence      FLOAT,
    dwell_ms        INTEGER NOT NULL DEFAULT 0,
    metadata_json   JSONB,
    idempotency_key TEXT UNIQUE NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ================================================================
-- transactions
-- ================================================================
CREATE TABLE IF NOT EXISTS transactions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    store_id        UUID NOT NULL REFERENCES stores(id),
    session_id      UUID REFERENCES visitor_sessions(id),
    amount          NUMERIC(10,2),
    occurred_at     TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ================================================================
-- anomalies
-- ================================================================
CREATE TABLE IF NOT EXISTS anomalies (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    store_id        UUID NOT NULL REFERENCES stores(id),
    anomaly_type    TEXT NOT NULL,
    severity        TEXT NOT NULL,
    description     TEXT,
    metric_value    FLOAT,
    threshold_value FLOAT,
    suggested_action TEXT,
    zone_id         UUID REFERENCES zones(id),
    resolved        BOOLEAN NOT NULL DEFAULT FALSE,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ
);

-- ================================================================
-- INDEXES
-- ================================================================
CREATE INDEX IF NOT EXISTS idx_events_store_time      ON events (store_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_type_store      ON events (event_type, store_id);
CREATE INDEX IF NOT EXISTS idx_events_session         ON events (session_id);
CREATE INDEX IF NOT EXISTS idx_events_idempotency     ON events (idempotency_key);
CREATE INDEX IF NOT EXISTS idx_sessions_store_entry   ON visitor_sessions (store_id, entry_time DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_track         ON visitor_sessions (store_id, visitor_id, camera_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_store_active ON anomalies (store_id, detected_at DESC) WHERE resolved = FALSE;
CREATE INDEX IF NOT EXISTS idx_events_zone_time       ON events (zone_id, timestamp DESC) WHERE zone_id IS NOT NULL;
