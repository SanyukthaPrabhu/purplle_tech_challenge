import asyncio
import csv
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.future import select
from backend.config import settings
from backend.models import Transaction, Store

import os
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(base_dir, "Brigade_Bangalore_10_April_26 (1)bc6219c.csv")
STORE_UUID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")

async def ingest_transactions():
    print(f"Ingesting transactions from: {CSV_PATH}...")
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    # Dictionary to collect unique orders with total amount
    # (since the CSV contains individual item details for each order, we group by order_id)
    orders = {}

    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            order_id = row.get("order_id")
            if not order_id:
                continue
            
            # Extract date and time
            date_str = row.get("order_date") # e.g. "10-04-2026"
            time_str = row.get("order_time") # e.g. "16:55:36"
            
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", "%d-%m-%Y %H:%M:%S")
                # Make timezone aware (UTC)
                dt = dt.replace(tzinfo=timezone.utc)
            except Exception as e:
                # Fallback to current time if error parsing
                dt = datetime.now(timezone.utc)

            # Amount
            try:
                amt = float(row.get("total_amount", 0.0))
            except:
                amt = 0.0

            # Accumulate or set
            if order_id not in orders:
                orders[order_id] = {
                    "occurred_at": dt,
                    "amount": amt
                }
            else:
                orders[order_id]["amount"] += amt

    print(f"Parsed {len(orders)} unique customer orders.")

    async with async_session() as session:
        # Check if store ST1008 exists, if not setup
        store_res = await session.execute(select(Store).filter(Store.id == STORE_UUID))
        store = store_res.scalars().first()
        if not store:
            print("Store ST1008 not found in database. Please run setup_store.py first.")
            return

        added_count = 0
        for order_id, order_data in orders.items():
            # Check if transaction already exists (optional, based on unique order check)
            # To make it simple and repeatable: we check if any transaction matches order_id in transaction metadata/id
            # We can use order_id to generate a deterministic UUID
            # This ensures running the script multiple times won't duplicate transactions!
            deterministic_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, f"retailiq.order.{order_id}")
            
            trans_res = await session.execute(
                select(Transaction).filter(Transaction.id == deterministic_uuid)
            )
            existing = trans_res.scalars().first()

            if not existing:
                trans = Transaction(
                    id=deterministic_uuid,
                    store_id=STORE_UUID,
                    amount=order_data["amount"],
                    occurred_at=order_data["occurred_at"]
                )
                session.add(trans)
                added_count += 1

        await session.commit()
        print(f"Successfully loaded {added_count} transactions into database.")

if __name__ == "__main__":
    asyncio.run(ingest_transactions())
