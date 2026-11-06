"""
Tareas de Celery.

`tasks.procesar_etiqueta_fedex` genera la etiqueta en FedEx y pasa el envío
de PAID a LABEL_CREATED. Solo se dispara después de confirmar el pago
(webhook de pago o reintento manual en POST /shipments/{order_id}/label).

No importa main.py: se registra en la app de Celery vía `include=["tasks"]`.
"""
import asyncio
import logging
import os

import httpx
from celery import shared_task
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from models import Shipment, ShipmentStatus, Store
from services import fedex_api_calls as fedex
from services.fedex_api_calls import FedExAPIError
from services.shipment_state import transition

load_dotenv()
logger = logging.getLogger(__name__)


async def _procesar_etiqueta(local_id: str, client_account_number: str = None) -> dict:
    # Engine por ejecución (NullPool): cada tarea corre en su propio event loop
    # vía asyncio.run y las conexiones asyncpg no pueden compartirse entre loops.
    engine = create_async_engine(os.environ["DB_URL"], poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        # 1. Validar estado (bloqueo corto, sin retener la fila durante la llamada HTTP)
        async with session_factory() as session, session.begin():
            shipment = (await session.execute(
                select(Shipment).where(Shipment.local_id == local_id).with_for_update()
            )).scalar_one_or_none()
            if shipment is None:
                logger.warning("Shipment %s no existe; se omite", local_id)
                return {"skipped": "not_found"}
            if shipment.status != ShipmentStatus.PAID:
                logger.info("Shipment %s en %s (no PAID); se omite", local_id, shipment.status.value)
                return {"skipped": shipment.status.value}
            ship_data = shipment.ship_request or {}
            client_name, client_phone = shipment.client_name, shipment.contact_phone
            store_id = shipment.store_id

            if not client_account_number:
                store = None
                if store_id:
                    store = await session.get(Store, store_id)
                if not store or not store.fedex_account_number:
                    logger.error("Shipment %s no tiene Store o cuenta FedEx asociada", local_id)
                    return {"error": f"Store {store_id} no encontrado o sin fedex_account_number"}
                client_account_number = store.fedex_account_number

        # 2. Generar etiqueta en FedEx con la cuenta dinámica del cliente (Store)
        label = await fedex.call_create_shipment(
            local_id, ship_data, client_name, client_phone, client_account_number
        )

        # 3. Persistir resultado, re-validando el estado: pudo cancelarse (o
        #    procesarse por otra tarea) mientras se generaba la etiqueta.
        async with session_factory() as session, session.begin():
            shipment = (await session.execute(
                select(Shipment).where(Shipment.local_id == local_id).with_for_update()
            )).scalar_one()
            if shipment.status != ShipmentStatus.PAID:
                logger.warning(
                    "Shipment %s pasó a %s durante la generación; anulando etiqueta huérfana %s",
                    local_id, shipment.status.value, label["tracking_number"],
                )
                await fedex.call_cancel_shipment(label["tracking_number"], client_account_number)
                return {"skipped": shipment.status.value, "voided": label["tracking_number"]}

            shipment.tracking_number = label["tracking_number"]
            # Guardar la URL o string del documento generado en PostgreSQL
            shipment.label_pdf_url = label.get("label_url") or label.get("label_pdf_url")
            transition(shipment, ShipmentStatus.LABEL_CREATED)

        return {"status": ShipmentStatus.LABEL_CREATED.value, **label}
    finally:
        await engine.dispose()


@shared_task(
    name="tasks.procesar_etiqueta_fedex",
    autoretry_for=(FedExAPIError, httpx.HTTPError),
    retry_backoff=True,
    max_retries=3,
)
def procesar_etiqueta_fedex(local_id: str, client_account_number: str = None) -> dict:
    return asyncio.run(_procesar_etiqueta(local_id, client_account_number))
