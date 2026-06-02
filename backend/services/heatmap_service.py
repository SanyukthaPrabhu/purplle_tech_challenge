from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from datetime import datetime
import uuid
import random
import numpy as np
from backend.models.event import Event
from backend.models.zone import Zone
from backend.schemas.metrics import HeatmapResponse, ZoneHeatmapData

async def calculate_heatmap(db: AsyncSession, store_id: uuid.UUID, from_time: datetime, to_time: datetime) -> HeatmapResponse:
    # Fetch all active zones of the store
    zones_res = await db.execute(
        select(Zone).filter(Zone.store_id == store_id, Zone.is_active == True)
    )
    zones = zones_res.scalars().all()

    grid_res = 5  # Matching the dashboard's 5x5 grid (25 cells total)
    heatmap_zones = []

    # Map zones to specific grid segments to distribute density
    # Entrance: top-left, Exit: top-right, Billing: bottom-right, Apparel: middle
    zone_grid_regions = {
        "Main Entrance": [(0, 0), (0, 1), (1, 0)],
        "Main Exit": [(0, 3), (0, 4), (1, 4)],
        "Billing Counter": [(3, 3), (3, 4), (4, 3), (4, 4)],
        "Apparel Section": [(1, 1), (1, 2), (2, 1), (2, 2)],
        "Electronics Section": [(2, 3), (2, 4), (3, 2)]
    }

    for zone in zones:
        # Count all events recorded inside this zone during the period
        events_res = await db.execute(
            select(func.count(Event.id))
            .filter(
                Event.store_id == store_id,
                Event.zone_id == zone.name,
                Event.timestamp >= from_time,
                Event.timestamp <= to_time
            )
        )
        event_count = events_res.scalar() or 0

        # Build 5x5 density matrix
        density = np.zeros((grid_res, grid_res), dtype=int)
        
        # Distribute the event counts across the mapped grid cells for that zone
        cells = zone_grid_regions.get(zone.name, [(2, 2)])
        if event_count > 0:
            # Distribute counts across cells
            base_val = event_count // len(cells)
            remainder = event_count % len(cells)
            for i, (r, c) in enumerate(cells):
                density[r, c] = base_val + (1 if i < remainder else 0)

        # Calculate average dwell in this zone
        dwell_res = await db.execute(
            select(func.avg(Event.dwell_ms))
            .filter(
                Event.store_id == store_id,
                Event.zone_id == zone.name,
                Event.event_type == "ZONE_EXIT",
                Event.timestamp >= from_time,
                Event.timestamp <= to_time
            )
        )
        avg_dwell = float((dwell_res.scalar() or 0.0) / 1000.0)

        heatmap_zones.append(ZoneHeatmapData(
            zone_id=zone.id,
            zone_name=zone.name,
            density_matrix=density.tolist(),
            avg_dwell_sec=round(avg_dwell, 2)
        ))

    return HeatmapResponse(grid_resolution=grid_res, zones=heatmap_zones)
