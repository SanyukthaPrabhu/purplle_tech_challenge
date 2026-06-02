# CHOICES.md — Architectural Trade-offs & Decisions
> **Retail Visitor Analytics System**
> **Author:** Staff Software Engineer

This document outlines the three major technical decisions made during the design and implementation of the Retail Visitor Analytics pipeline, detailing the options considered, AI suggestions, and final rationale.

---

## 1. Detection Model Selection

### Options Considered
1. **YOLOv8 (Nano/Medium)**: Lightweight, real-time bounding box inference. Extensive community bindings.
2. **RT-DETR**: High accuracy transformer-based detector, but heavy compute requirements.
3. **MediaPipe Pose**: High precision landmark detection, but slow and inefficient for multi-person CCTV tracking.

### AI Suggestion
The AI recommended starting with YOLOv8 Nano (`yolov8n.pt`) for real-time edge processing and fallback CPU speed, with a suggestion to swap to YOLOv8 Medium (`yolov8m.pt`) for final deployment where resolution and camera angles vary.

### Final Choice & Rationale
We chose **YOLOv8 Nano** coupled with the **ByteTrack** algorithm. Retail CCTV feeds operate under tight CPU/GPU budget constraints. YOLOv8n achieves high inference frame rates (>30 FPS on CPU/cheap GPU hosts) while maintaining robust person detection precision. 

To resolve the **Staff Exclusion** edge case, rather than training a heavy multi-class custom detector, we combined a rule-based Entry ROI filter with HSV color torso profiling for employee badge detection. This hybrid logic kept pipeline overhead extremely low compared to custom YOLO training or VLM prompts.

---

## 2. Event Schema Design Rationale

### Options Considered
1. **Flat Schema**: Storing all metadata keys at the root level.
2. **Nested Behavioral Schema**: Standard JSON envelope with a dedicated `metadata` block containing contextual indicators (`queue_depth`, `session_seq`, `sku_zone`).

### AI Suggestion
The AI suggested a flexible, flat schema to simplify database indexing and parsing.

### Final Choice & Rationale
We chose the **Nested Schema** matching the strict challenge specification. Encapsulating event characteristics into a `metadata` object (such as `queue_depth` for `BILLING_QUEUE_JOIN` and `sku_zone` for general zone events) separates core transport concerns (e.g. `event_id`, `visitor_id`, `timestamp`) from analytical parameters. 

Deduplication is achieved at the database level using a `UNIQUE` index on the `event_id` field. On ingestion, duplicate calls return a status `200` with the existing UUID, ensuring idempotent event transport even during network retries.

---

## 3. Database & Storage Architecture

### Options Considered
1. **PostgreSQL**: Robust, relational SQL database supporting ACID, JSONB query operators, and complex joins.
2. **MongoDB**: Scalable NoSQL JSON storage, but lacks strong transaction bounds and relational constraints required for financial order matches.
3. **SQLite**: Fast, serverless SQL database suitable for development, testing, and edge computing.

### AI Suggestion
The AI suggested using PostgreSQL for production and SQLite for local integration testing.

### Final Choice & Rationale
We selected **PostgreSQL** (with an **SQLite** fallback for local testing). Relational tables (`stores`, `zones`, `visitor_sessions`, `events`, `transactions`, `anomalies`) are highly structured. 

Evaluating the **North Star Metric (Conversion Rate)** requires joining transaction timestamps with billing zone dwell times. Performing a 5-minute window lookup ($[T - 5\text{ mins}, T]$) is highly optimized in SQL via B-Tree indices on `occurred_at`/`timestamp` fields, ensuring real-time response rates under load.
