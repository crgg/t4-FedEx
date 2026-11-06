"""
Script de inicialización (seeds) para poblar tiendas de prueba en PostgreSQL.

Uso dentro de Docker:
    docker compose exec fedex_api python scripts/seed_db.py
"""
import asyncio
import os
import sys
from pathlib import Path

# Asegurar que la raíz del proyecto esté en el path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv()

from models import Store


DEFAULT_STORES = [
    {"id": 1, "name": "Tienda Norte", "fedex_account_number": "740980114"},
    {"id": 2, "name": "Tienda Sur", "fedex_account_number": "851091225"},
]


async def seed():
    db_url = os.getenv("DB_URL")
    if not db_url:
        raise RuntimeError("Falta DB_URL en el entorno o .env")

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session, session.begin():
        for data in DEFAULT_STORES:
            existing = await session.get(Store, data["id"])
            if existing is None:
                store = Store(
                    id=data["id"],
                    name=data["name"],
                    fedex_account_number=data["fedex_account_number"],
                )
                session.add(store)
                print(f"✓ Tienda creada: id={data['id']}, nombre='{data['name']}', cuenta={data['fedex_account_number']}")
            else:
                print(f"• Tienda id={data['id']} ya existe ('{existing.name}')")

    await engine.dispose()
    print("Seed completado exitosamente.")


if __name__ == "__main__":
    asyncio.run(seed())
