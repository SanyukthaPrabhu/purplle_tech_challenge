# RetailIQ — Retail Store Intelligence System

This repository implements an end-to-end computer vision and analytics system to track store visitors, calculate conversion rates, detect billing anomalies, and display live metrics on a visual dashboard.

---

## 🛠 Run Strategies

You can run this project either via **Docker Compose** (fully containerized) or **Locally** (for development).

### Option A: Running via Docker Compose (Recommended)
You can start the entire stack (PostgreSQL database, FastAPI backend, and Nginx dashboard) in one command:
```bash
# 1. Start the services (PostgreSQL, Backend API, Dashboard UI)
docker compose up --build
```
Once healthy, follow the setup commands to register the store layouts and ingest transaction logs into the containerized database:
```bash
# 2. Register the store layouts in the running container database
docker compose exec backend python -m backend.setup_store

# 3. Ingest customer transaction logs
docker compose exec backend python -m backend.ingest_transactions

# 4. Run the tracking pipeline on the host machine against the CCTV video
python run_pipeline.py --cam 1
```

### Option B: Running Locally (Bare Metal)
If you prefer to run the project locally without Docker:
```bash
# 1. Install all Python dependencies
pip install -r detection/requirements.txt -r backend/requirements.txt aiosqlite

# 2. Initialize the local SQLite database and store mappings
python -m backend.setup_store

# 3. Ingest customer transaction logs
python -m backend.ingest_transactions

# 4. Start the backend API server (serves the backend endpoints and the UI)
python -m uvicorn backend.main:app --port 8000

# 5. Run the tracking engine on the CCTV camera video feed
python run_pipeline.py --cam 1
```

---

## 📊 Live Dashboard URLs

| Setup Type | Service | URL |
|---|---|---|
| **Docker Compose** | Live Dashboard | 👉 [http://localhost:3000](http://localhost:3000) |
| **Docker Compose** | API Swagger docs | 👉 [http://localhost:8000/docs](http://localhost:8000/docs) |
| **Local Run** | Live Dashboard | 👉 [http://localhost:8000/dashboard/](http://localhost:8000/dashboard/) |
| **Local Run** | API Swagger docs | 👉 [http://localhost:8000/docs](http://localhost:8000/docs) |

---

## 🏗 Repository Structure
- `detection/`: Bounding box detection (YOLOv8), tracker (ByteTrack), ray-casting zone classification, staff filtering, and HTTP event emission.
- `backend/`: FastAPI routers, models, schemas, and analytics engine (funnels, heatmaps, POS transactional correlation).
- `dashboard/`: Single-page visual dashboard subscribing to live events via WebSockets.
- `database/`: SQL DDL schemas and database bootstrap scripts.
- `DESIGN.md`: Plain-language architecture overview and documentation of AI-assisted decisions.
- `CHOICES.md`: Rationale and technical tradeoffs for chosen tools.
