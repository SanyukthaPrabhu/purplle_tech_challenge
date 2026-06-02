# PROMPT: Generate pytest test suite using asyncio to validate FastAPI store intelligence endpoints. Cover scenarios: empty store, all-staff clips, zero purchases, re-entry, queue build-up, and group entries. Enforce SQLite memory database overrides.
# CHANGES MADE: Customized tests to work with updated challenge schemas (visitor_id, timestamp, dwell_ms) and verified model fields of Store, Zone, Event, and VisitorSession.

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from backend.main import app
from backend.models.store import Store
from backend.models.zone import Zone
from backend.models.event import Event
from backend.models.visitor import VisitorSession
from backend.models.transaction import Transaction
from backend.models.anomaly import Anomaly
from backend.services.event_service import ingest_event_db
from backend.schemas.events import EventIngestRequest
from backend.services.metrics_service import calculate_kpis
from backend.services.anomaly_service import check_and_trigger_anomalies

# Helper to create store and zones
async def setup_test_store(db):
    store_id = uuid.uuid5(uuid.NAMESPACE_DNS, "retailiq.store.STORE_BLR_002")
    store = Store(
        id=store_id,
        name="STORE_BLR_002",
        location="STORE_BLR_002",
        timezone="UTC"
    )
    db.add(store)
    
    # Entrance Zone
    entry_zone = Zone(
        id=uuid.uuid4(),
        store_id=store_id,
        name="Main Entrance",
        zone_type="ENTRY",
        polygon=[[0,0], [10,0], [10,10], [0,10]]
    )
    db.add(entry_zone)
    
    # Billing Zone
    billing_zone = Zone(
        id=uuid.uuid4(),
        store_id=store_id,
        name="Billing Counter",
        zone_type="BILLING",
        polygon=[[50,50], [60,50], [60,60], [50,60]]
    )
    db.add(billing_zone)
    
    await db.commit()
    return store_id

# Helper to build event request
def make_event_request(store_code, visitor_id, event_type, zone_name=None, delta_mins=0, payload=None):
    occurred = datetime.now(timezone.utc) - timedelta(minutes=delta_mins)
    return EventIngestRequest(
        event_id=uuid.uuid4(),
        store_id=store_code,
        camera_id="cam1",
        visitor_id=visitor_id,
        event_type=event_type,
        timestamp=occurred,
        zone_id=zone_name,
        dwell_ms=payload.get("dwell_ms", 0) if payload else 0,
        confidence=0.9,
        metadata={
            "queue_depth": payload.get("queue_depth") if payload else None,
            "sku_zone": zone_name,
            "session_seq": 1
        }
    )


@pytest.mark.asyncio
async def test_empty_store(db_session):
    """Scenario 1: Testing an empty store behavior."""
    store_id = await setup_test_store(db_session)
    
    now = datetime.now(timezone.utc)
    from_time = now - timedelta(hours=24)
    
    kpis = await calculate_kpis(db_session, store_id, from_time, now)
    
    assert kpis.unique_visitors == 0
    assert kpis.conversion_rate == 0.0
    assert kpis.avg_dwell_sec == 0.0
    assert kpis.current_queue_depth == 0
    assert kpis.abandonment_rate == 0.0


@pytest.mark.asyncio
async def test_all_staff_clip(db_session):
    """Scenario 2: Testing staff exclusion where staff tracks are ignored in KPIs."""
    store_id = await setup_test_store(db_session)
    store_code = "STORE_BLR_002"
    
    # Ingest staff member session
    req = make_event_request(store_code, visitor_id="VIS_staff1", event_type="ENTRY")
    status, ev_id = await ingest_event_db(db_session, req)
    assert status == "accepted"
    
    # Flag the session as staff
    session_res = await db_session.execute(
        select(VisitorSession).filter(VisitorSession.store_id == store_id, VisitorSession.visitor_id == "VIS_staff1")
    )
    session = session_res.scalars().first()
    session.is_staff = True
    await db_session.commit()
    
    # Exit event
    req_exit = make_event_request(store_code, visitor_id="VIS_staff1", event_type="EXIT", payload={"dwell_ms": 300000})
    await ingest_event_db(db_session, req_exit)
    
    now = datetime.now(timezone.utc)
    from_time = now - timedelta(hours=24)
    kpis = await calculate_kpis(db_session, store_id, from_time, now)
    
    assert kpis.unique_visitors == 0


@pytest.mark.asyncio
async def test_zero_purchases(db_session):
    """Scenario 3: Visitors join but make zero purchases, leading to 0% conversion."""
    store_id = await setup_test_store(db_session)
    store_code = "STORE_BLR_002"
    
    # Ingest 2 visitor entries
    await ingest_event_db(db_session, make_event_request(store_code, visitor_id="VIS_cust1", event_type="ENTRY"))
    await ingest_event_db(db_session, make_event_request(store_code, visitor_id="VIS_cust2", event_type="ENTRY"))
    
    now = datetime.now(timezone.utc)
    from_time = now - timedelta(hours=24)
    kpis = await calculate_kpis(db_session, store_id, from_time, now)
    
    assert kpis.unique_visitors == 2
    assert kpis.conversion_rate == 0.0


@pytest.mark.asyncio
async def test_reentry(db_session):
    """Scenario 4: Visitor leaves and returns, triggering reentry increments."""
    store_id = await setup_test_store(db_session)
    store_code = "STORE_BLR_002"
    
    # First Entry
    await ingest_event_db(db_session, make_event_request(store_code, visitor_id="VIS_cust3", event_type="ENTRY"))
    # Exit
    await ingest_event_db(db_session, make_event_request(store_code, visitor_id="VIS_cust3", event_type="EXIT"))
    # Reentry event
    await ingest_event_db(db_session, make_event_request(store_code, visitor_id="VIS_cust3", event_type="REENTRY"))
    
    now = datetime.now(timezone.utc)
    from_time = now - timedelta(hours=24)
    kpis = await calculate_kpis(db_session, store_id, from_time, now)
    
    assert kpis.unique_visitors == 1
    assert kpis.reentry_count == 1


@pytest.mark.asyncio
async def test_queue_buildup(db_session):
    """Scenario 5: Simulate many users entering billing queue to trigger queue spike anomaly."""
    store_id = await setup_test_store(db_session)
    store_code = "STORE_BLR_002"
    
    # Ingest 9 users entering billing zone
    for i in range(10):
        vid = f"VIS_queue_{i}"
        # Entry
        await ingest_event_db(db_session, make_event_request(store_code, visitor_id=vid, event_type="ENTRY"))
        # Zone Enter Billing
        await ingest_event_db(db_session, make_event_request(store_code, visitor_id=vid, event_type="ZONE_ENTER", zone_name="Billing Counter"))

    # Evaluate anomalies
    await check_and_trigger_anomalies(db_session, store_id)
    
    # Query active anomalies
    result = await db_session.execute(
        select(Anomaly).filter(Anomaly.store_id == store_id, Anomaly.anomaly_type == "QUEUE_SPIKE")
    )
    anomaly = result.scalars().first()
    
    assert anomaly is not None
    assert anomaly.severity == "HIGH"
    assert "Queue depth" in anomaly.description


@pytest.mark.asyncio
async def test_group_entry(db_session):
    """Scenario 6: Handle a simultaneous group entry event processing."""
    store_id = await setup_test_store(db_session)
    store_code = "STORE_BLR_002"
    
    # Ingest simultaneous entries for different tracks
    reqs = [
        make_event_request(store_code, visitor_id="VIS_grp1", event_type="ENTRY"),
        make_event_request(store_code, visitor_id="VIS_grp2", event_type="ENTRY"),
        make_event_request(store_code, visitor_id="VIS_grp3", event_type="ENTRY")
    ]
    
    for r in reqs:
        status, ev_id = await ingest_event_db(db_session, r)
        assert status == "accepted"
        
    now = datetime.now(timezone.utc)
    from_time = now - timedelta(hours=24)
    kpis = await calculate_kpis(db_session, store_id, from_time, now)
    
    assert kpis.unique_visitors == 3
