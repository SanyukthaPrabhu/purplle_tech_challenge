import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from backend.config import settings

async def main():
    print(f"Connecting to database: {settings.DATABASE_URL}...")
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    
    async with engine.begin() as conn:
        # Get max event timestamp
        event_res = await conn.execute(text("SELECT MAX(timestamp) FROM events"))
        max_event_time = event_res.scalar()
        
        if not max_event_time:
            # Fallback to current time if no events are present yet
            max_event_time = datetime.now(timezone.utc)
        else:
            if max_event_time.tzinfo is None:
                max_event_time = max_event_time.replace(tzinfo=timezone.utc)
                
        print(f"Aligning transactions around max event time: {max_event_time}")
        
        # Get max transaction timestamp
        tx_res = await conn.execute(text("SELECT MAX(occurred_at) FROM transactions"))
        max_tx_time = tx_res.scalar()
        
        if max_tx_time:
            if max_tx_time.tzinfo is None:
                max_tx_time = max_tx_time.replace(tzinfo=timezone.utc)
                
            time_diff = max_event_time - max_tx_time
            print(f"Time difference to shift: {time_diff}")
            
            # Shift all transactions by the difference
            # In PostgreSQL and SQLite, we can add intervals or use timedelta strings
            # To be database-independent, we can calculate the new datetime for each transaction in python and update them!
            # Since there are only 24 transactions, updating them one by one is extremely fast and 100% reliable across SQLite and PostgreSQL.
            all_tx = await conn.execute(text("SELECT id, occurred_at FROM transactions"))
            rows = all_tx.fetchall()
            
            for tx_id, occurred_at in rows:
                if occurred_at.tzinfo is None:
                    occurred_at = occurred_at.replace(tzinfo=timezone.utc)
                new_time = occurred_at + time_diff
                # Update
                await conn.execute(
                    text("UPDATE transactions SET occurred_at = :new_time WHERE id = :tx_id"),
                    {"new_time": new_time, "tx_id": tx_id}
                )
            
            print(f"Successfully aligned {len(rows)} transactions.")
        else:
            print("No transactions found to shift.")
            
        # Verify transaction timestamps
        range_res = await conn.execute(text("SELECT MIN(occurred_at), MAX(occurred_at) FROM transactions"))
        print("New Transactions range:", range_res.fetchone())

if __name__ == '__main__':
    asyncio.run(main())
