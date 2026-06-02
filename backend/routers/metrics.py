from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone, timedelta
import uuid
from backend.database import get_db
from backend.schemas.metrics import MetricsResponse
from backend.services.metrics_service import calculate_kpis

router = APIRouter(prefix="/stores", tags=["metrics"])

@router.get("/{id}/metrics", response_model=MetricsResponse)
async def get_store_metrics(
    id: uuid.UUID,
    from_time: datetime = Query(None, alias="from"),
    to_time: datetime = Query(None, alias="to"),
    db: AsyncSession = Depends(get_db)
):
    # Set default time frame: last 24 hours if not specified
    if not to_time:
        to_time = datetime.now(timezone.utc)
    if not from_time:
        from_time = to_time - timedelta(hours=24)
        
    try:
        kpis = await calculate_kpis(db, id, from_time, to_time)
        return kpis
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
