# RetailIQ — Real-Time Store Intelligence & Analytics System

RetailIQ is an end-to-end computer vision and real-time analytics system designed to track store visitors, calculate purchase conversion rates, monitor queue depth, and identify store-floor anomalies. It correlates live CCTV camera detections (using YOLOv8 and ByteTrack) with POS transactions, presenting live metrics on a premium, interactive web dashboard.

---

## 🏗 System Architecture

1. **Computer Vision Pipeline (`/detection`)**: Processes CCTV video feeds to track visitors, detect entry/exit events, monitor queue depth, and record dwell times across specific zones.
2. **Backend API (`/backend`)**: Built with FastAPI. Stores state in a database (PostgreSQL in Docker, SQLite locally), calculates metrics, and streams real-time updates via WebSockets.
3. **Live Dashboard (`/dashboard`)**: Single-page analytics dashboard built with modern glassmorphism UI, visualizing conversion funnels, floor density heatmaps, anomaly alerts, and system health.

---

## 📋 Prerequisites

To run this project, ensure you have the following installed:
* **Python 3.10 or 3.11** (recommended)
* **Git**
* **Docker & Docker Compose** (highly recommended for one-command execution)

---

## 🚀 How to Run the Project

You can run the project using either **Option A (Docker Compose)** or **Option B (Local Bare Metal)**.

### Option A: Running via Docker Compose (Recommended)

This strategy starts the PostgreSQL database, FastAPI backend API, and Nginx dashboard webserver automatically in containerized mode.

1. **Start the containers**:
   ```bash
   docker compose up --build
   ```
   *Keep this terminal open.*

2. **Initialize and Seed the Database**:
   Open a new terminal tab and run these commands to create store layouts and ingest transaction logs into the container database:
   ```bash
   # Register the store zones/layouts
   docker compose exec backend python -m backend.setup_store

   # Ingest customer transaction logs (POS data)
   docker compose exec backend python -m backend.ingest_transactions
   ```

3. **Run the Video Tracking Pipeline**:
   Run the tracking engine on your host machine to process the CCTV video feed:
   ```bash
   # Make sure dependencies are installed locally
   pip install -r detection/requirements.txt
   
   # Start processing Camera 1 feed
   python run_pipeline.py --cam 1
   ```

---

### Option B: Running Locally (Bare Metal)

If you prefer to run the project locally without Docker containers (uses a local SQLite database):

1. **Set up a Virtual Environment**:
   ```bash
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r detection/requirements.txt -r backend/requirements.txt aiosqlite
   ```

3. **Initialize SQLite Database & Load Data**:
   ```bash
   # Create SQLite database and register store zones
   python -m backend.setup_store

   # Ingest customer transaction logs
   python -m backend.ingest_transactions
   ```

4. **Start the Backend API Server**:
   ```bash
   python -m uvicorn backend.main:app --port 8000
   ```
   *Keep this terminal running.*

5. **Start the Video Tracking Pipeline**:
   Open a new terminal tab, activate the virtual environment, and run:
   ```bash
   python run_pipeline.py --cam 1
   ```

---

## 📊 Live Access Points & URLs

Once everything is running, the judge can access the endpoints below:

| Setup Method | Service | URL | Description |
|---|---|---|---|
| **Docker Compose** | **Live Dashboard** | 👉 [http://localhost:3000](http://localhost:3000) | Main interface with real-time graphs |
| **Docker Compose** | **API Swagger Docs** | 👉 [http://localhost:8000/docs](http://localhost:8000/docs) | Interactive API exploration |
| **Local Run** | **Live Dashboard** | 👉 [http://localhost:8000/dashboard/](http://localhost:8000/dashboard/) | UI served directly by FastAPI |
| **Local Run** | **API Swagger Docs** | 👉 [http://localhost:8000/docs](http://localhost:8000/docs) | Interactive API exploration |

---

## 🎥 Sample Datasets
* **Video Feeds**: The pipeline reads sample CCTV clips located in the `CCTV Footage/` folder (e.g. `CAM 1.mp4`).
* **Store Layout**: Zone points are defined in `detection/store_layout.json` representing Entrance, Exit, Billing Queue, and general shopping zones.

---

## ⚠️ Troubleshooting & Common Pitfalls

### 1. File Not Found Errors (Now Resolved)
Earlier commits had local absolute paths in `backend/setup_store.py` and `backend/ingest_transactions.py`. We have fixed these to resolve paths dynamically relative to the repository directory. Make sure you pull the latest commit.

### 2. Directory Context (Import Errors)
All commands (e.g., `python -m backend.setup_store`, `python run_pipeline.py`, `uvicorn`) **must be run from the root directory** of the repository. Running commands from inside `backend/` or `detection/` will lead to `ModuleNotFoundError: No module named 'backend'` errors.

### 3. PowerShell Script Execution Restriction (Windows)
If your friend runs `.\venv\Scripts\activate` on Windows and gets:
> *"File ... cannot be loaded because running scripts is disabled on this system."*

Have them run this command in their PowerShell terminal to bypass the execution policy for their session, and then run activate again:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
```

### 4. Headless Environments / Server Terminals
If you are running the tracking pipeline on a remote server or container without a display monitor, make sure you **do not** pass the `--display` flag to `run_pipeline.py`. If you need debug visuals, you can enable `debug_save_frames` in `detection/config.py` to write output frames directly to disk.

