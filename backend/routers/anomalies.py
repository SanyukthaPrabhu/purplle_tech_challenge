from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import uuid
from backend.database import get_db
from backend.models.anomaly import Anomaly
from backend.schemas.anomaly import AnomalyListResponse, AnomalyResponse

router = APIRouter(prefix="/stores", tags=["anomalies"])

@router.get("/{id}/anomalies", response_model=AnomalyListResponse)
async def get_store_anomalies(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    try:
        # Fetch active anomalies first (resolved = False)
        result = await db.execute(
            select(Anomaly)
            .filter(Anomaly.store_id == id, Anomaly.resolved == False)
            .order_by(Anomaly.detected_at.desc())
        )
        anomalies_list = result.scalars().all()
        
        response_data = []
        for anomaly in anomalies_list:
            response_data.append(AnomalyResponse(
                id=anomaly.id,
                type=anomaly.anomaly_type,
                severity=anomaly.severity,
                description=anomaly.description,
                metric_value=anomaly.metric_value,
                threshold_value=anomaly.threshold_value,
                suggested_action=anomaly.suggested_action,
                detected_at=anomaly.detected_at,
                resolved=anomaly.resolved,
                resolved_at=anomaly.resolved_at
            ))
            
        return AnomalyListResponse(anomalies=response_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
