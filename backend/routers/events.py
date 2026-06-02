from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.schemas.events import EventIngestRequest, EventIngestResponse
from backend.services.event_service import ingest_event_db

router = APIRouter(prefix="/events", tags=["events"])

@router.post("/ingest", response_model=EventIngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest_event(req: EventIngestRequest, db: AsyncSession = Depends(get_db)):
    try:
        status_res, event_id = await ingest_event_db(db, req)
        
        # If duplicate, return 200 instead of 201
        if status_res == "duplicate":
            # FastAPI returns 201 by default unless we modify response status or manually build JSONResponse
            # Let's import JSONResponse to return exact status code
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"status": "duplicate", "event_id": str(event_id)}
            )
            
        return EventIngestResponse(status="accepted", event_id=event_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest event: {str(e)}"
        )
