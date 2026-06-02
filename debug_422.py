import httpx
import uuid
from datetime import datetime, timezone

url = "http://localhost:8000/events/ingest"

# Construct exact JSON structure emitted by event_emitter.py
payload = {
    "event_id": str(uuid.uuid4()),
    "store_id": "550e8400-e29b-41d4-a716-446655440000",
    "camera_id": "cam01",
    "visitor_id": "VIS_1",
    "event_type": "ENTRY",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "zone_id": None,
    "dwell_ms": 0,
    "is_staff": False,
    "confidence": 0.9,
    "metadata": {
        "queue_depth": None,
        "sku_zone": None,
        "session_seq": 1
    }
}

response = httpx.post(url, json=payload)
print("Status Code:", response.status_code)
print("Response Text:", response.text)
