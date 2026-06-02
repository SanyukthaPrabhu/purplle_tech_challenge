import asyncio
import json
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.future import select
from backend.config import settings
from backend.models import Store, Zone, Base

async def setup():
    print("Setting up store ST1008 (Brigade Road) in database...")
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        # Create tables if not exist (precautionary)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Mapped Store ID for ST1008
        store_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        
        # Check if store already exists
        store_res = await session.execute(select(Store).filter(Store.id == store_uuid))
        store = store_res.scalars().first()

        if not store:
            store = Store(
                id=store_uuid,
                name="Brigade Road Store (ST1008)",
                location="Brigade Road, Bangalore",
                timezone="Asia/Kolkata",
                layout_json={}
            )
            session.add(store)
            print("Created store: Brigade Road Store (ST1008)")
        else:
            print("Store already exists.")

        # Load zones from store_layout.json
        layout_path = r"c:\Users\sriva\OneDrive\Desktop\Purple task\detection\store_layout.json"
        try:
            with open(layout_path, "r") as f:
                layout = json.load(f)
            
            for zone_data in layout.get("zones", []):
                zone_uuid = uuid.UUID(zone_data["id"])
                # Check if zone exists
                zone_res = await session.execute(select(Zone).filter(Zone.id == zone_uuid))
                zone = zone_res.scalars().first()

                if not zone:
                    zone = Zone(
                        id=zone_uuid,
                        store_id=store_uuid,
                        name=zone_data["name"],
                        zone_type=zone_data["zone_type"],
                        polygon=zone_data["polygon"],
                        is_active=True
                    )
                    session.add(zone)
                    print(f"Created zone: {zone_data['name']} ({zone_data['zone_type']})")
            
            await session.commit()
            print("Store and zones successfully registered.")
        except Exception as e:
            print(f"Error loading layout: {e}")
            await session.rollback()

if __name__ == "__main__":
    asyncio.run(setup())
