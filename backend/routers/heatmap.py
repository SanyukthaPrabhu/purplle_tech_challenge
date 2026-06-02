from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone, timedelta
import uuid
from backend.database import get_db
from backend.schemas.metrics import HeatmapResponse
from backend.services.heatmap_service import calculate_heatmap

router = APIRouter(prefix="/stores", tags=["heatmap"])

@router.get("/{id}/heatmap", response_model=HeatmapResponse)
async def get_store_heatmap(
    id: uuid.UUID,
    from_time: datetime = Query(None, alias="from"),
    to_time: datetime = Query(None, alias="to"),
    db: AsyncSession = Depends(get_db)
):
    if not to_time:
        to_time = datetime.now(timezone.utc)
    if not from_time:
        from_time = to_time - timedelta(hours=24)

    try:
        heatmap = await calculate_heatmap(db, id, from_time, to_time)
        return heatmap
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
