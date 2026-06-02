from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone, timedelta
import uuid
from backend.database import get_db
from backend.schemas.metrics import FunnelResponse
from backend.services.funnel_service import calculate_funnel

router = APIRouter(prefix="/stores", tags=["funnel"])

@router.get("/{id}/funnel", response_model=FunnelResponse)
async def get_store_funnel(
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
        funnel = await calculate_funnel(db, id, from_time, to_time)
        return funnel
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
