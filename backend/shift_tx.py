import asyncio
import os
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from backend.config import settings

async def main():
    print(f"Connecting to database: {settings.DATABASE_URL}...")
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    print(f"Shifting transaction dates in DB to today: {today_str}...")
    
    async with engine.begin() as conn:
        # Cast to text/varchar, replace, and cast back to timestamp
        query = text(f"UPDATE transactions SET occurred_at = CAST(REPLACE(CAST(occurred_at AS VARCHAR), '2026-04-10', '{today_str}') AS TIMESTAMP)")
        res = await conn.execute(query)
        print("Updated rows count:", res.rowcount)
        
        # Verify transaction timestamps
        range_res = await conn.execute(text("SELECT MIN(occurred_at), MAX(occurred_at) FROM transactions"))
        print("Transactions range:", range_res.fetchone())

if __name__ == '__main__':
    asyncio.run(main())
