# RetailIQ — Retail Store Intelligence System

This repository implements an end-to-end computer vision and analytics system to track store visitors, calculate conversion rates, detect billing anomalies, and display live metrics on a visual dashboard.

---

## 🛠 Setup & Run in 5 Commands

Run the following commands in your terminal to spin up the database, ingest real transactional data, process the CCTV videos, and view the metrics:

```bash
# 1. Install all Python packages (including OpenCV, PyTorch, FastAPI, etc.)
pip install -r detection/requirements.txt -r backend/requirements.txt aiosqlite

# 2. Set up the store ST1008 and tracking zone mappings in the database
python -m backend.setup_store

# 3. Load all actual customer transaction records from the store CSV
python -m backend.ingest_transactions

# 4. Start the backend API and dashboard servers
python -m uvicorn backend.main:app --port 8000 & python -m http.server 3000 --directory dashboard

# 5. Run the tracking engine on the CCTV camera video feed
python run_pipeline.py --cam 1
```

---

## 📊 Live Dashboard URL
Once step 4 is completed, open your browser and navigate to:
- **Dashboard Portal**: `http://localhost:3000`
- **Interactive REST API Documentation**: `http://localhost:8000/docs`

---

## 🏗 Repository Structure
- `detection/`: Bounding box detection (YOLOv8), tracker (ByteTrack), ray-casting zone classification, staff filtering, and HTTP event emission.
- `backend/`: FastAPI routers, models, schemas, and analytics engine (funnels, heatmaps, POS transactional correlation).
- `dashboard/`: Single-page visual dashboard subscribing to live events via WebSockets.
- `database/`: SQL DDL schemas and database bootstrap scripts.
- `DESIGN.md`: Plain-language architecture overview and documentation of AI-assisted decisions.
- `CHOICES.md`: Rationale and technical tradeoffs for chosen tools.
