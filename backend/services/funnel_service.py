from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from datetime import datetime
import uuid
from backend.models.event import Event
from backend.models.transaction import Transaction
from backend.schemas.metrics import FunnelResponse, FunnelStep

async def calculate_funnel(db: AsyncSession, store_id: uuid.UUID, from_time: datetime, to_time: datetime) -> FunnelResponse:
    # Step 1: Store Entry (Unique visitor ids with ENTRY in the period)
    entry_res = await db.execute(
        select(func.count(func.distinct(Event.visitor_id)))
        .filter(
            Event.store_id == store_id,
            Event.event_type == "ENTRY",
            Event.timestamp >= from_time,
            Event.timestamp <= to_time
        )
    )
    entries = entry_res.scalar() or 0

    # Step 2: Zone Visit (Unique visitor ids with ZONE_ENTER in the period)
    zone_visit_res = await db.execute(
        select(func.count(func.distinct(Event.visitor_id)))
        .filter(
            Event.store_id == store_id,
            Event.event_type == "ZONE_ENTER",
            Event.timestamp >= from_time,
            Event.timestamp <= to_time
        )
    )
    zone_visits = zone_visit_res.scalar() or 0
    zone_visits = min(zone_visits, entries)

    # Step 3: Billing Queue (Unique visitor ids with BILLING_QUEUE_JOIN in the period)
    queue_res = await db.execute(
        select(func.count(func.distinct(Event.visitor_id)))
        .filter(
            Event.store_id == store_id,
            Event.event_type == "BILLING_QUEUE_JOIN",
            Event.timestamp >= from_time,
            Event.timestamp <= to_time
        )
    )
    queue_joins = queue_res.scalar() or 0
    queue_joins = min(queue_joins, zone_visits)

    # Step 4: Purchase (Unique sessions that completed transaction in period)
    purchase_res = await db.execute(
        select(func.count(func.distinct(Transaction.session_id)))
        .filter(
            Transaction.store_id == store_id,
            Transaction.occurred_at >= from_time,
            Transaction.occurred_at <= to_time
        )
    )
    purchases = purchase_res.scalar() or 0
    purchases = min(purchases, queue_joins)

    steps = [
        FunnelStep(name="Store Entry", count=entries),
        FunnelStep(name="Zone Visit", count=zone_visits),
        FunnelStep(name="Billing Queue", count=queue_joins),
        FunnelStep(name="Purchase", count=purchases),
    ]

    drop_off_rates = []
    for i in range(len(steps) - 1):
        current_count = steps[i].count
        next_count = steps[i+1].count
        if current_count > 0:
            rate = (current_count - next_count) / current_count
        else:
            rate = 0.0
        drop_off_rates.append(round(rate, 4))

    return FunnelResponse(steps=steps, drop_off_rates=drop_off_rates)
