# DESIGN.md — Retail Visitor Analytics System
> **Author:** Staff Software Engineer (Architecture Agent)
> **Version:** 1.1.0
> **Last Updated:** 2026-06-01

---

## PLAIN-LANGUAGE ARCHITECTURE OVERVIEW
The Retail Visitor Analytics System processes CCTV footage from retail stores to track customer behavior, calculate conversions, and detect anomalies. 
1. **Detection Layer**: A lightweight YOLOv8 model detects shoppers (person class), and the ByteTrack algorithm tracks their trajectories. 
2. **Behavioral Engine**: Shoppers are evaluated against polygon zones (Entrance, Exit, Billing). Directional crosses start or close visitor sessions, and stationary tracking measures queue depths and zone dwell times.
3. **Ingestion & Processing**: Behavioral events are packaged into JSON envelopes with unique UUIDs and POSTed to a FastAPI backend.
4. **Metrics & Anomalies**: The backend aggregates unique visitors, correlates transactions to sessions using a 5-minute checkout window, and triggers automated warnings (e.g. queue spikes).
5. **Dashboard**: An interactive Web UI displays real-time statistics and alerts via WebSockets.

---

## AI-ASSISTED DECISIONS
Below are key areas where an LLM model shaped our system design:
1. **Deduplication Strategy**: The AI suggested using database-level `UNIQUE` constraints on `event_id` instead of a Redis cache layer for event deduplication. We agreed, as this drastically reduces container deployment footprint and complexity.
2. **Staff Exclusion**: The AI suggested a combined Entry ROI boundary check and HSV color profiling to classify store staff. We adopted this hybrid rule-based method, which avoids complex VLM prompting or custom uniform training.
3. **POS Correlation Window**: The AI suggested a 5-minute sliding window join to correlate transactions with visitor presence in the billing zone. We implemented this in SQL to calculate the Store Conversion Rate.

---

## 1. FOLDER STRUCTURE

```
retail-analytics/
│
├── detection/                        # CV Pipeline (YOLOv8 + ByteTrack)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                       # Entry point: reads RTSP / video file
│   ├── detector.py                   # YOLOv8 person detection wrapper
│   ├── tracker.py                    # ByteTrack wrapper
│   ├── zone_engine.py                # Polygon zone logic
│   ├── dwell_tracker.py              # Per-track dwell time state machine
│   ├── queue_detector.py             # Queue zone density logic
│   ├── staff_filter.py               # Staff badge / ROI exclusion
│   ├── event_emitter.py              # Publishes events → FastAPI /events/ingest
│   ├── config.py                     # Env-based config (zones, thresholds)
│   └── tests/
│       ├── test_zone_engine.py
│       ├── test_dwell_tracker.py
│       └── test_event_emitter.py
│
├── backend/                          # FastAPI Service
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                       # FastAPI app factory
│   ├── config.py                     # Settings (pydantic BaseSettings)
│   ├── database.py                   # SQLAlchemy async engine + session
│   ├── models/
│   │   ├── __init__.py
│   │   ├── store.py                  # Store ORM model
│   │   ├── visitor.py                # VisitorSession ORM model
│   │   ├── event.py                  # Event ORM model
│   │   ├── zone.py                   # Zone ORM model
│   │   ├── transaction.py            # Transaction ORM model
│   │   └── anomaly.py                # Anomaly ORM model
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── events.py                 # Pydantic event schemas
│   │   ├── metrics.py                # Response schemas
│   │   └── anomaly.py                # Anomaly schemas
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── events.py                 # POST /events/ingest
│   │   ├── metrics.py                # GET /stores/{id}/metrics
│   │   ├── funnel.py                 # GET /stores/{id}/funnel
│   │   ├── heatmap.py                # GET /stores/{id}/heatmap
│   │   ├── anomalies.py              # GET /stores/{id}/anomalies
│   │   └── health.py                 # GET /health
│   ├── services/
│   │   ├── event_service.py          # Ingest + deduplication logic
│   │   ├── metrics_service.py        # Unique visitors, conversion, dwell
│   │   ├── funnel_service.py         # Funnel computation
│   │   ├── heatmap_service.py        # Spatial density aggregation
│   │   └── anomaly_service.py        # Anomaly detection engine
│   ├── middleware/
│   │   ├── logging.py                # Structured JSON logging
│   │   └── idempotency.py            # Idempotency key middleware
│   ├── websocket/
│   │   └── manager.py                # WebSocket broadcast manager
│   └── tests/
│       ├── conftest.py
│       ├── test_events.py
│       ├── test_metrics.py
│       ├── test_funnel.py
│       └── test_anomalies.py
│
├── dashboard/                        # React + Tailwind Frontend
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── MetricCard.tsx
│   │   │   ├── FunnelChart.tsx
│   │   │   ├── HeatmapView.tsx
│   │   │   ├── QueueGauge.tsx
│   │   │   ├── AnomalyFeed.tsx
│   │   │   └── LiveBadge.tsx
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts
│   │   │   └── useMetrics.ts
│   │   ├── api/
│   │   │   └── client.ts
│   │   └── store/
│   │       └── dashboardStore.ts     # Zustand global state
│   └── public/
│
├── database/
│   ├── init.sql                      # DDL: tables, indexes, triggers
│   └── migrations/                   # Alembic migration scripts
│
├── docker-compose.yml                # Full stack orchestration
├── docker-compose.dev.yml            # Dev overrides (hot reload)
├── .env.example
├── Makefile                          # make up / make test / make migrate
└── DESIGN.md                         # This file
```

---

## 2. COMPONENT DIAGRAM

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          RETAIL ANALYTICS SYSTEM                         │
└─────────────────────────────────────────────────────────────────────────┘

  ┌──────────────┐       RTSP/MP4        ┌────────────────────────────────┐
  │  CCTV Camera │──────────────────────▶│       DETECTION SERVICE        │
  └──────────────┘                       │  ┌──────────┐  ┌───────────┐  │
                                         │  │ YOLOv8   │─▶│ ByteTrack │  │
                                         │  └──────────┘  └─────┬─────┘  │
                                         │  ┌──────────────────────────┐  │
                                         │  │   Zone Engine            │  │
                                         │  │   Dwell Tracker          │  │
                                         │  │   Queue Detector         │  │
                                         │  │   Staff Filter           │  │
                                         │  └──────────┬─────────────┘  │
                                         └─────────────┼────────────────┘
                                                        │  HTTP POST
                                                        │  /events/ingest
                                                        ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │                          FASTAPI BACKEND                              │
  │                                                                       │
  │  ┌─────────────┐  ┌─────────────────┐  ┌────────────────────────┐   │
  │  │Event Router │  │ Metrics Router   │  │ Anomaly Router          │   │
  │  └──────┬──────┘  └────────┬────────┘  └───────────┬────────────┘   │
  │         │                  │                         │                │
  │  ┌──────▼──────────────────▼─────────────────────────▼────────────┐  │
  │  │                    SERVICE LAYER                                │  │
  │  │  EventService  MetricsService  FunnelService  AnomalyService   │  │
  │  └──────────────────────────────────────┬──────────────────────┘  │
  │                                          │                          │
  │  ┌───────────────────────────────────────▼──────────────────────┐  │
  │  │                SQLAlchemy Async ORM                          │  │
  │  └───────────────────────────────────────┬──────────────────────┘  │
  │                                           │                          │
  │  ┌────────────────────────────────────────▼─────────────────────┐  │
  │  │              WebSocket Manager (broadcast)                   │  │
  │  └──────────────────────────────────────────────────────────────┘  │
  └──────────────────────────────────┬───────────────────────────────────┘
                                     │
            ┌────────────────────────┴────────────────────────┐
            │                                                   │
            ▼                                                   ▼
  ┌──────────────────┐                             ┌───────────────────────┐
  │   PostgreSQL DB   │                             │   REACT DASHBOARD     │
  │                   │                             │  (WebSocket + REST)   │
  │  - visitor_sessions│                            │                       │
  │  - events         │                             │  MetricCards          │
  │  - zones          │                             │  FunnelChart          │
  │  - anomalies      │                             │  Heatmap              │
  │  - transactions   │                             │  QueueGauge           │
  └──────────────────┘                             │  AnomalyFeed          │
                                                    └───────────────────────┘
```

---

## 3. DATABASE SCHEMA

### 3.1 DDL

```sql
-- ================================================================
-- stores
-- ================================================================
CREATE TABLE stores (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,
    location      TEXT,
    timezone      TEXT NOT NULL DEFAULT 'UTC',
    layout_json   JSONB,                  -- zone polygon definitions
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ================================================================
-- zones
-- ================================================================
CREATE TABLE zones (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id      UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,          -- e.g. "Billing Counter", "Entrance"
    zone_type     TEXT NOT NULL,          -- ENTRY | EXIT | BILLING | GENERAL
    polygon       JSONB NOT NULL,         -- [[x1,y1],[x2,y2],...]
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ================================================================
-- visitor_sessions
-- ================================================================
CREATE TABLE visitor_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id        UUID REFERENCES stores(id),
    store_code      TEXT NOT NULL,
    visitor_id      TEXT NOT NULL,
    camera_id       TEXT NOT NULL,
    entry_time      TIMESTAMPTZ,
    exit_time       TIMESTAMPTZ,
    total_dwell_ms  INTEGER,              -- dwell time in milliseconds
    is_staff        BOOLEAN NOT NULL DEFAULT FALSE,
    reentry_count   INTEGER NOT NULL DEFAULT 0,
    session_hash    TEXT UNIQUE NOT NULL, -- dedup: store_code + visitor_id + date
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ================================================================
-- events
-- ================================================================
CREATE TABLE events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id        UUID REFERENCES stores(id),
    store_code      TEXT NOT NULL,
    session_id      UUID REFERENCES visitor_sessions(id),
    camera_id       TEXT NOT NULL,
    event_type      TEXT NOT NULL,        -- ENTRY|EXIT|ZONE_ENTER|ZONE_EXIT|...
    zone_id         TEXT,                 -- zone name string
    visitor_id      TEXT NOT NULL,
    frame_number    BIGINT,
    bbox            JSONB,                -- {x,y,w,h}
    confidence      FLOAT,
    dwell_ms        INTEGER NOT NULL DEFAULT 0,
    metadata_json   JSONB,                -- event-specific metadata
    idempotency_key TEXT UNIQUE NOT NULL, -- dedup key
    timestamp       TIMESTAMPTZ NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ================================================================
-- transactions
-- ================================================================
CREATE TABLE transactions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id        UUID NOT NULL REFERENCES stores(id),
    session_id      UUID REFERENCES visitor_sessions(id),
    amount          NUMERIC(10,2),
    occurred_at     TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ================================================================
-- anomalies
-- ================================================================
CREATE TABLE anomalies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id        UUID NOT NULL REFERENCES stores(id),
    anomaly_type    TEXT NOT NULL,        -- QUEUE_SPIKE|CONVERSION_DROP|DEAD_ZONE
    severity        TEXT NOT NULL,        -- LOW | MEDIUM | HIGH | CRITICAL
    description     TEXT,
    metric_value    FLOAT,
    threshold_value FLOAT,
    suggested_action TEXT,
    zone_id         UUID REFERENCES zones(id),
    resolved        BOOLEAN NOT NULL DEFAULT FALSE,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ
);
```

### 3.2 Indexes

```sql
-- Hot path: events by store + time
CREATE INDEX idx_events_store_time      ON events (store_id, occurred_at DESC);
CREATE INDEX idx_events_type_store      ON events (event_type, store_id);
CREATE INDEX idx_events_session         ON events (session_id);
CREATE INDEX idx_events_idempotency     ON events (idempotency_key); -- UNIQUE enforces dedup

-- Visitor sessions
CREATE INDEX idx_sessions_store_entry   ON visitor_sessions (store_id, entry_time DESC);
CREATE INDEX idx_sessions_track         ON visitor_sessions (store_id, track_id, camera_id);

-- Anomalies
CREATE INDEX idx_anomalies_store_active ON anomalies (store_id, detected_at DESC) WHERE resolved = FALSE;

-- Heatmap: zone events in time window
CREATE INDEX idx_events_zone_time       ON events (zone_id, occurred_at DESC) WHERE zone_id IS NOT NULL;

-- BRIN for large time-series scans
CREATE INDEX idx_events_brin            ON events USING BRIN (occurred_at);
```

---

## 4. EVENT SCHEMA

### 4.1 Event Types & Payloads

| Event Type          | Trigger                                      | Key Payload Fields                          |
|---------------------|----------------------------------------------|---------------------------------------------|
| `ENTRY`             | Track crosses entry zone polygon inward      | `track_id`, `camera_id`, `bbox`, `frame`    |
| `EXIT`              | Track crosses exit zone polygon outward      | `track_id`, `dwell_sec`, `visited_zones`    |
| `ZONE_ENTER`        | Track centroid enters a zone polygon         | `track_id`, `zone_id`, `zone_name`          |
| `ZONE_EXIT`         | Track centroid exits a zone polygon          | `track_id`, `zone_id`, `dwell_in_zone_sec`  |
| `ZONE_DWELL`        | Track stationary >threshold in zone          | `track_id`, `zone_id`, `dwell_sec`          |
| `REENTRY`           | Same track_id seen again after EXIT          | `track_id`, `reentry_count`, `gap_sec`      |
| `BILLING_QUEUE_JOIN`| Track enters billing zone                   | `track_id`, `queue_depth`, `zone_id`        |
| `BILLING_QUEUE_ABANDON`| Track exits billing zone without purchase| `track_id`, `wait_sec`, `zone_id`          |

### 4.2 Canonical Event Envelope (JSON)

```json
{
  "event_id":        "uuid-v4",
  "idempotency_key": "store_001:cam01:track42:ENTRY:20260601T172045Z",
  "event_type":      "ENTRY",
  "store_id":        "uuid-v4",
  "camera_id":       "cam01",
  "track_id":        42,
  "frame_number":    18240,
  "occurred_at":     "2026-06-01T17:20:45.123Z",
  "zone_id":         "uuid-v4-or-null",
  "bbox":            { "x": 120, "y": 80, "w": 60, "h": 140 },
  "confidence":      0.91,
  "payload":         {}
}
```

---

## 5. API DESIGN

### 5.1 Endpoints

| Method | Path                          | Description                               | Auth     |
|--------|-------------------------------|-------------------------------------------|----------|
| POST   | `/events/ingest`              | Ingest event from detection service       | API Key  |
| GET    | `/stores/{id}/metrics`        | KPIs: visitors, conversion, dwell, queue  | Bearer   |
| GET    | `/stores/{id}/funnel`         | Funnel: entry→zone→billing→purchase       | Bearer   |
| GET    | `/stores/{id}/heatmap`        | Spatial density grid per zone             | Bearer   |
| GET    | `/stores/{id}/anomalies`      | Active anomalies list                     | Bearer   |
| GET    | `/health`                     | Liveness + DB connectivity                | None     |
| WS     | `/ws/stores/{id}/live`        | WebSocket live metric push                | Bearer   |

### 5.2 Request / Response Contracts

#### POST /events/ingest
```json
// Request
{
  "idempotency_key": "store_001:cam01:track42:ENTRY:20260601T172045Z",
  "event_type": "ENTRY",
  "store_id": "uuid",
  "camera_id": "cam01",
  "track_id": 42,
  "frame_number": 18240,
  "occurred_at": "2026-06-01T17:20:45Z",
  "zone_id": null,
  "bbox": { "x": 120, "y": 80, "w": 60, "h": 140 },
  "confidence": 0.91,
  "payload": {}
}

// Response 201
{ "status": "accepted", "event_id": "uuid" }

// Response 200 (duplicate)
{ "status": "duplicate", "event_id": "existing-uuid" }
```

#### GET /stores/{id}/metrics?from=ISO8601&to=ISO8601
```json
{
  "store_id": "uuid",
  "period": { "from": "...", "to": "..." },
  "unique_visitors": 342,
  "conversion_rate": 0.38,
  "avg_dwell_sec": 847,
  "current_queue_depth": 5,
  "abandonment_rate": 0.12,
  "reentry_count": 23
}
```

#### GET /stores/{id}/funnel
```json
{
  "steps": [
    { "name": "Store Entry",    "count": 342 },
    { "name": "Zone Visit",     "count": 289 },
    { "name": "Billing Queue",  "count": 130 },
    { "name": "Purchase",       "count": 130 }
  ],
  "drop_off_rates": [0.155, 0.550, 0.0]
}
```

#### GET /stores/{id}/heatmap
```json
{
  "grid_resolution": 50,
  "zones": [
    {
      "zone_id": "uuid",
      "zone_name": "Apparel Section",
      "density_matrix": [[0,2,5],[3,8,4],[1,2,0]],
      "avg_dwell_sec": 120
    }
  ]
}
```

#### GET /stores/{id}/anomalies
```json
{
  "anomalies": [
    {
      "id": "uuid",
      "type": "QUEUE_SPIKE",
      "severity": "HIGH",
      "description": "Queue depth 12 exceeds threshold 8",
      "metric_value": 12,
      "threshold_value": 8,
      "suggested_action": "Open additional billing counter",
      "detected_at": "2026-06-01T17:30:00Z"
    }
  ]
}
```

---

## 6. DASHBOARD DESIGN

### 6.1 Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  🏪  RetailIQ Live Dashboard   [Store: Connaught Place] [🔴 LIVE]   │
├──────────────┬──────────────┬──────────────┬───────────────────────┤
│  👥 Visitors │ 💰 Conv Rate │ ⏱ Avg Dwell  │  🧾 Queue Depth        │
│     342      │    38.0%     │   14m 07s    │    ████░░░ 5/12        │
├──────────────┴──────────────┴──────────────┴───────────────────────┤
│                                                                     │
│   FUNNEL                          HEATMAP                           │
│   ┌──────────────────────┐        ┌───────────────────────────────┐│
│   │ Entry       342 ████ │        │  [Floor Plan Overlay]         ││
│   │ Zone Visit  289 ███  │        │  Hot: Apparel, Billing        ││
│   │ Queue       130 ██   │        │  Cold: Back Aisles            ││
│   │ Purchase    130 ██   │        │  Colour: green→yellow→red     ││
│   └──────────────────────┘        └───────────────────────────────┘│
│                                                                     │
│   ANOMALIES (Live Feed)                                             │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │ 🔴 HIGH   QUEUE_SPIKE       17:30  "Open extra counter"     │  │
│   │ 🟡 MEDIUM CONVERSION_DROP   17:15  "Check billing staff"    │  │
│   └─────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 Real-Time Update Strategy
- WebSocket connects on load → receives delta pushes every 5 seconds
- Metrics panel: incremental update via Zustand store
- Heatmap: debounced re-render every 10 seconds
- Anomaly feed: push-on-event (immediate)
- Funnel chart: recalculated every 30 seconds

### 6.3 Tech Stack
| Layer       | Technology              |
|-------------|-------------------------|
| Framework   | React 18 + Vite         |
| Styling     | Tailwind CSS v3         |
| Charts      | Recharts                |
| WebSocket   | Native browser WS API   |
| State       | Zustand                 |
| HTTP client | Axios                   |
| Heatmap     | react-heatmap-grid      |

---

## 7. DEPLOYMENT FLOW

### 7.1 docker-compose.yml Architecture

```yaml
# Services:
#   postgres    → db:5432
#   backend     → api:8000
#   detection   → cv:9000  (internal)
#   dashboard   → ui:3000
#   nginx       → :80/:443 (reverse proxy)

version: "3.9"
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: retail_analytics
      POSTGRES_USER: analytics
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./database/init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U analytics"]
      interval: 10s

  backend:
    build: ./backend
    environment:
      DATABASE_URL: postgresql+asyncpg://analytics:${POSTGRES_PASSWORD}@postgres/retail_analytics
      SECRET_KEY: ${SECRET_KEY}
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "8000:8000"

  detection:
    build: ./detection
    environment:
      BACKEND_URL: http://backend:8000
      STORE_ID: ${STORE_ID}
    volumes:
      - ${VIDEO_SOURCE}:/app/input.mp4:ro
    depends_on:
      - backend
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]   # GPU optional, CPU fallback

  dashboard:
    build: ./dashboard
    environment:
      VITE_API_URL: http://localhost:8000
      VITE_WS_URL: ws://localhost:8000
    ports:
      - "3000:3000"

  nginx:
    image: nginx:alpine
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
    ports:
      - "80:80"
    depends_on:
      - backend
      - dashboard

volumes:
  pg_data:
```

### 7.2 Deployment Flow Diagram

```
git push → CI Pipeline
    │
    ├── 1. Lint + Type Check
    ├── 2. pytest (>80% coverage)
    ├── 3. docker build (all 4 services)
    ├── 4. docker-compose up --build -d
    ├── 5. alembic upgrade head      ← run migrations
    ├── 6. health check GET /health
    └── 7. Smoke test: POST /events/ingest + GET /stores/{id}/metrics
```

### 7.3 Environment Variables

| Variable            | Service     | Description                        |
|---------------------|-------------|------------------------------------|
| `POSTGRES_PASSWORD` | postgres    | DB password                        |
| `DATABASE_URL`      | backend     | SQLAlchemy async connection string |
| `SECRET_KEY`        | backend     | JWT / API key signing secret       |
| `STORE_ID`          | detection   | UUID of the store being monitored  |
| `VIDEO_SOURCE`      | detection   | Path to RTSP URL or MP4 file       |
| `BACKEND_URL`       | detection   | Internal backend URL               |
| `VITE_API_URL`      | dashboard   | Public API base URL                |
| `VITE_WS_URL`       | dashboard   | Public WebSocket base URL          |

---

## 8. KEY ARCHITECTURAL DECISIONS

| Decision                  | Choice                         | Rationale                                           |
|---------------------------|--------------------------------|-----------------------------------------------------|
| Async ORM                 | SQLAlchemy 2.0 async + asyncpg | Non-blocking I/O for high event throughput           |
| Deduplication             | `idempotency_key` UNIQUE index  | DB-level guarantee, no extra cache layer            |
| Event transport           | Direct HTTP POST (detection→API)| Simple, observable, retry-able                     |
| Real-time push            | WebSocket (native)             | Low latency, no extra broker for MVP                |
| GPU optional              | Docker deploy.resources        | Works CPU-only for demo; GPU for production         |
| Staff exclusion           | ROI mask + badge colour filter | Avoids false visitor counts                        |
| ByteTrack                 | Kalman Filter + IoU matching   | State-of-the-art, handles occlusion well            |
| Zone definition           | Polygon JSON in store layout   | Flexible, store-specific, hot-reloadable            |

---

*End of DESIGN.md — Phase 1 Complete*
