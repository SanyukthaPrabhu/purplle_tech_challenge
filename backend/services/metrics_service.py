from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from datetime import datetime, timezone, timedelta
import uuid
import logging
from backend.models.visitor import VisitorSession
from backend.models.event import Event
from backend.models.transaction import Transaction
from backend.models.zone import Zone
from backend.schemas.metrics import MetricsResponse, PeriodSchema

logger = logging.getLogger("metrics_service")

async def calculate_kpis(db: AsyncSession, store_id: uuid.UUID, from_time: datetime, to_time: datetime) -> MetricsResponse:
    # Resolve store code (could be passed as string UUID or code)
    store_res = await db.execute(
        select(VisitorSession.store_code).filter(VisitorSession.store_id == store_id).limit(1)
    )
    store_code = store_res.scalar() or str(store_id)

    # 1. Unique visitors (count of visitor sessions)
    visitors_res = await db.execute(
        select(VisitorSession)
        .filter(
            VisitorSession.store_id == store_id,
            VisitorSession.entry_time >= from_time,
            VisitorSession.entry_time <= to_time,
            VisitorSession.is_staff == False
        )
    )
    sessions = visitors_res.scalars().all()
    unique_visitors = len(sessions)

    # 2. Conversion rate with 5-minute window correlation
    # Fetch all transactions in period
    tx_res = await db.execute(
        select(Transaction)
        .filter(
            Transaction.store_id == store_id,
            Transaction.occurred_at >= from_time,
            Transaction.occurred_at <= to_time
        )
    )
    transactions = tx_res.scalars().all()

    converted_session_ids = set()
    for tx in transactions:
        # 5-minute window before transaction occurred_at
        window_start = tx.occurred_at - timedelta(minutes=5)
        window_end = tx.occurred_at
        
        # Find events in billing zone in this window
        events_res = await db.execute(
            select(Event.session_id)
            .filter(
                Event.store_id == store_id,
                Event.event_type.in_(["ZONE_ENTER", "ZONE_DWELL", "BILLING_QUEUE_JOIN"]),
                Event.timestamp >= window_start,
                Event.timestamp <= window_end,
                Event.session_id.isnot(None)
            )
        )
        for s_id in events_res.scalars().all():
            converted_session_ids.add(s_id)

    # Filter to ensure converted sessions are valid non-staff customer sessions in this window
    valid_converted = [s for s in sessions if s.id in converted_session_ids]
    conversion_rate = (len(valid_converted) / unique_visitors) if unique_visitors > 0 else 0.0

    # 3. Average dwell time (ms to seconds)
    dwell_res = await db.execute(
        select(func.avg(VisitorSession.total_dwell_ms))
        .filter(
            VisitorSession.store_id == store_id,
            VisitorSession.entry_time >= from_time,
            VisitorSession.entry_time <= to_time,
            VisitorSession.total_dwell_ms.isnot(None),
            VisitorSession.is_staff == False
        )
    )
    avg_dwell_sec = float((dwell_res.scalar() or 0.0) / 1000.0)

    # 4. Current queue depth
    # Find billing zone
    billing_zone_res = await db.execute(
        select(Zone).filter(Zone.store_id == store_id, Zone.zone_type == "BILLING", Zone.is_active == True)
    )
    billing_zone = billing_zone_res.scalars().first()
    
    current_queue_depth = 0
    if billing_zone:
        # Check active people in billing zone (joined in last 30m, not exited)
        now = datetime.now(timezone.utc)
        recent_enters = await db.execute(
            select(Event.visitor_id)
            .filter(
                Event.store_id == store_id,
                Event.zone_id == billing_zone.name, # Zone layout name
                Event.event_type == "ZONE_ENTER",
                Event.timestamp >= now - timedelta(minutes=30)
            )
        )
        enters = set(recent_enters.scalars().all())

        recent_exits = await db.execute(
            select(Event.visitor_id)
            .filter(
                Event.store_id == store_id,
                Event.zone_id == billing_zone.name,
                Event.event_type == "ZONE_EXIT",
                Event.timestamp >= now - timedelta(minutes=30)
            )
        )
        exits = set(recent_exits.scalars().all())
        current_queue_depth = len(enters - exits)

    # 5. Abandonment rate = count(BILLING_QUEUE_ABANDON) / count(BILLING_QUEUE_JOIN)
    joins_res = await db.execute(
        select(func.count(Event.id))
        .filter(
            Event.store_id == store_id,
            Event.event_type == "BILLING_QUEUE_JOIN",
            Event.timestamp >= from_time,
            Event.timestamp <= to_time
        )
    )
    total_joins = joins_res.scalar() or 0

    abandons_res = await db.execute(
        select(func.count(Event.id))
        .filter(
            Event.store_id == store_id,
            Event.event_type == "BILLING_QUEUE_ABANDON",
            Event.timestamp >= from_time,
            Event.timestamp <= to_time
        )
    )
    total_abandons = abandons_res.scalar() or 0
    abandonment_rate = (total_abandons / total_joins) if total_joins > 0 else 0.0

    # 6. Reentry count
    reentry_res = await db.execute(
        select(func.sum(VisitorSession.reentry_count))
        .filter(
            VisitorSession.store_id == store_id,
            VisitorSession.entry_time >= from_time,
            VisitorSession.entry_time <= to_time,
            VisitorSession.is_staff == False
        )
    )
    reentry_count = int(reentry_res.scalar() or 0)

    period = PeriodSchema(from_time=from_time, to_time=to_time)

    return MetricsResponse(
        store_id=store_id,
        period=period,
        unique_visitors=unique_visitors,
        conversion_rate=round(conversion_rate, 4),
        avg_dwell_sec=round(avg_dwell_sec, 2),
        current_queue_depth=max(0, current_queue_depth),
        abandonment_rate=round(abandonment_rate, 4),
        reentry_count=reentry_count
    )
