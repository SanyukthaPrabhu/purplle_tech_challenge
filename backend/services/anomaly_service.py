from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, and_
from datetime import datetime, timezone, timedelta
import uuid
import logging
from backend.models.anomaly import Anomaly
from backend.models.event import Event
from backend.models.visitor import VisitorSession
from backend.models.transaction import Transaction
from backend.models.zone import Zone
from backend.websocket.manager import manager

logger = logging.getLogger("anomaly_service")

async def check_and_trigger_anomalies(db: AsyncSession, store_id: uuid.UUID):
    now = datetime.now(timezone.utc)
    
    # ─── 1. Queue Spike Check ───
    billing_zone_res = await db.execute(
        select(Zone).filter(Zone.store_id == store_id, Zone.zone_type == "BILLING", Zone.is_active == True)
    )
    billing_zone = billing_zone_res.scalars().first()
    
    if billing_zone:
        recent_enters = await db.execute(
            select(Event.visitor_id)
            .filter(
                Event.store_id == store_id,
                Event.zone_id == billing_zone.name,
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
        queue_threshold = 8.0
        
        if current_queue_depth > queue_threshold:
            existing_res = await db.execute(
                select(Anomaly).filter(
                    Anomaly.store_id == store_id,
                    Anomaly.anomaly_type == "QUEUE_SPIKE",
                    Anomaly.resolved == False
                )
            )
            existing = existing_res.scalars().first()
            if not existing:
                anomaly = Anomaly(
                    store_id=store_id,
                    anomaly_type="QUEUE_SPIKE",
                    severity="HIGH",
                    description=f"Queue depth ({current_queue_depth}) exceeds safe limit of {int(queue_threshold)}.",
                    metric_value=float(current_queue_depth),
                    threshold_value=queue_threshold,
                    suggested_action="Deploy supplementary cashier to billing counter immediately.",
                    zone_id=billing_zone.id
                )
                db.add(anomaly)
                await db.commit()
                logger.warning(f"Anomaly Triggered: QUEUE_SPIKE at store {store_id}")
                await manager.broadcast_to_store(str(store_id), {
                    "type": "anomaly",
                    "data": {
                        "type": "QUEUE_SPIKE",
                        "severity": "HIGH",
                        "description": anomaly.description,
                        "suggested_action": anomaly.suggested_action
                    }
                })

    # ─── 2. Conversion Drop Check ───
    two_hours_ago = now - timedelta(hours=2)
    
    visitors_res = await db.execute(
        select(func.count(VisitorSession.id))
        .filter(VisitorSession.store_id == store_id, VisitorSession.entry_time >= two_hours_ago)
    )
    total_visitors = visitors_res.scalar() or 0

    transactions_res = await db.execute(
        select(func.count(Transaction.id))
        .filter(Transaction.store_id == store_id, Transaction.occurred_at >= two_hours_ago)
    )
    total_transactions = transactions_res.scalar() or 0

    if total_visitors >= 10:
        conversion_rate = total_transactions / total_visitors
        conversion_threshold = 0.15
        
        if conversion_rate < conversion_threshold:
            existing_res = await db.execute(
                select(Anomaly).filter(
                    Anomaly.store_id == store_id,
                    Anomaly.anomaly_type == "CONVERSION_DROP",
                    Anomaly.resolved == False
                )
            )
            existing = existing_res.scalars().first()
            if not existing:
                anomaly = Anomaly(
                    store_id=store_id,
                    anomaly_type="CONVERSION_DROP",
                    severity="MEDIUM",
                    description=f"Store conversion rate dropped to {conversion_rate:.1%} (below threshold of {conversion_threshold:.1%}).",
                    metric_value=float(conversion_rate),
                    threshold_value=conversion_threshold,
                    suggested_action="Analyze pricing displays, check for checkout bottlenecks, or staff sales floor."
                )
                db.add(anomaly)
                await db.commit()
                logger.warning(f"Anomaly Triggered: CONVERSION_DROP at store {store_id}")
                await manager.broadcast_to_store(str(store_id), {
                    "type": "anomaly",
                    "data": {
                        "type": "CONVERSION_DROP",
                        "severity": "MEDIUM",
                        "description": anomaly.description,
                        "suggested_action": anomaly.suggested_action
                    }
                })

    # ─── 3. Dead Zone Check ───
    four_hours_ago = now - timedelta(hours=4)
    zones_res = await db.execute(
        select(Zone).filter(Zone.store_id == store_id, Zone.zone_type == "GENERAL", Zone.is_active == True)
    )
    general_zones = zones_res.scalars().all()
    
    for zone in general_zones:
        event_count_res = await db.execute(
            select(func.count(Event.id))
            .filter(
                Event.store_id == store_id,
                Event.zone_id == zone.name,
                Event.event_type == "ZONE_ENTER",
                Event.timestamp >= four_hours_ago
            )
        )
        events_in_zone = event_count_res.scalar() or 0
        
        if events_in_zone == 0:
            existing_res = await db.execute(
                select(Anomaly).filter(
                    Anomaly.store_id == store_id,
                    Anomaly.anomaly_type == "DEAD_ZONE",
                    Anomaly.zone_id == zone.id,
                    Anomaly.resolved == False
                )
            )
            existing = existing_res.scalars().first()
            if not existing:
                anomaly = Anomaly(
                    store_id=store_id,
                    anomaly_type="DEAD_ZONE",
                    severity="LOW",
                    description=f"Zone '{zone.name}' has recorded 0 visitor events in the past 4 hours.",
                    metric_value=0.0,
                    threshold_value=1.0,
                    suggested_action=f"Inspect signage, lighting, or merchandise layout in the {zone.name} area.",
                    zone_id=zone.id
                )
                db.add(anomaly)
                await db.commit()
                logger.warning(f"Anomaly Triggered: DEAD_ZONE for zone {zone.name} at store {store_id}")
                await manager.broadcast_to_store(str(store_id), {
                    "type": "anomaly",
                    "data": {
                        "type": "DEAD_ZONE",
                        "severity": "LOW",
                        "description": anomaly.description,
                        "suggested_action": anomaly.suggested_action
                    }
                })
