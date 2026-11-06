"""
Receptores de webhooks externos.

IMPORTANTE: Este router NO lleva la dependencia JWT, porque lo invocan
servidores externos (FedEx, Stripe) o simuladores de pruebas. Su seguridad
en producción debe basarse en la validación de firma / secreto de cada proveedor.

Simulador de Tracking (FedEx):
    Para probar el flujo de tracking sin llamar a FedEx real ni esperar
    eventos físicos, envía una petición POST síncrona a /webhooks/fedex:

    curl -X POST "http://localhost:8001/webhooks/fedex" \
      -H "Content-Type: application/json" \
      -d '{
        "tracking_number": "MOCK012345678901",
        "status": "IN_TRANSIT"
      }'

    El backend buscará el envío en PostgreSQL por su tracking_number y
    actualizará silenciosamente su estado a IN_TRANSIT. A partir de ese momento,
    el guard clause en POST /shipments/{id}/cancel bloqueará cualquier intento
    de cancelación con un error HTTP 400 Bad Request.
"""
import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_db
from models import Shipment, ShipmentStatus
from schemas import FedExWebhookPayload
from services.shipment_state import InvalidTransitionError, transition

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# Mapeo de códigos de estado de FedEx (y simuladores) a la máquina de estados local
FEDEX_STATUS_MAP = {
    # Formato simulador y strings legibles
    "IN_TRANSIT": ShipmentStatus.IN_TRANSIT,
    "ON_THE_WAY": ShipmentStatus.IN_TRANSIT,
    "PICKED_UP": ShipmentStatus.IN_TRANSIT,
    "DELIVERED": ShipmentStatus.DELIVERED,
    "CANCELED": ShipmentStatus.CANCELED,
    "CANCELLED": ShipmentStatus.CANCELED,

    # Códigos estándar de telemetría de FedEx Track API (derivedStatusCode)
    "IT": ShipmentStatus.IN_TRANSIT,        # In Transit
    "PU": ShipmentStatus.SCHEDULED_FOR_PICKUP, # Picked Up
    "DP": ShipmentStatus.IN_TRANSIT,        # Departed FedEx location
    "AR": ShipmentStatus.IN_TRANSIT,        # Arrived at FedEx location
    "OD": ShipmentStatus.IN_TRANSIT,        # Out for Delivery
    "DL": ShipmentStatus.DELIVERED,         # Delivered
    "CA": ShipmentStatus.CANCELED,          # Cancelled
}


# ---- 5. WEBHOOK RECEIVER (SÍNCRONO) ----
@router.post("/fedex", status_code=status.HTTP_200_OK)
async def fedex_webhook(
    payload: FedExWebhookPayload,
    session: AsyncSession = Depends(get_db),
):
    """
    Endpoint síncrono para recepción de eventos de telemetría y tracking de FedEx.

    Soporta dos esquemas en el body JSON:
    1. Formato simulador / testing rápido:
       {"tracking_number": "123456", "status": "IN_TRANSIT"}

    2. Formato oficial de la API de Webhooks de FedEx:
       {
         "trackResults": [
           {
             "trackingNumberInfo": {"trackingNumber": "123456"},
             "latestStatusDetail": {"derivedStatusCode": "IT"}
           }
         ]
       }

    Comportamiento:
    - Busca el envío en PostgreSQL por su tracking_number.
    - Si existe, aplica la transición hacia IN_TRANSIT (u otro estado) de forma silenciosa.
    - Al pasar a IN_TRANSIT, el envío queda protegido contra cancelaciones.
    - Si el tracking no existe, se omite silenciosamente registrando un log informativo
      (evitando rechazar el webhook al proveedor).
    """
    events: list[tuple[str, str]] = []

    # 1. Extraer del formato simulador directo
    if payload.tracking_number:
        events.append((payload.tracking_number, payload.status or "IN_TRANSIT"))

    # 2. Extraer del formato oficial FedEx
    if payload.trackResults:
        for item in payload.trackResults:
            t_num = item.get("trackingNumberInfo", {}).get("trackingNumber")
            st_code = item.get("latestStatusDetail", {}).get("derivedStatusCode") or "IN_TRANSIT"
            if t_num:
                events.append((t_num, st_code))

    processed_events = []

    async with session.begin():
        for tracking_num, raw_st in events:
            # Resolver estado meta
            normalized = raw_st.strip().upper()
            target_status = FEDEX_STATUS_MAP.get(normalized)
            if target_status is None:
                try:
                    target_status = ShipmentStatus(normalized)
                except ValueError:
                    target_status = ShipmentStatus.IN_TRANSIT

            # Buscar envío en PostgreSQL con lock pesimista
            shipment = (await session.execute(
                select(Shipment).where(Shipment.tracking_number == tracking_num).with_for_update()
            )).scalar_one_or_none()

            if shipment is None:
                logger.warning("Webhook FedEx: Tracking '%s' no encontrado en BD. Se ignora silenciosamente.", tracking_num)
                processed_events.append({
                    "tracking_number": tracking_num,
                    "result": "ignored_not_found",
                })
                continue

            # Idempotencia: si ya está en el estado meta, no forzar re-transición
            if shipment.status == target_status:
                logger.info("Webhook FedEx: Tracking '%s' ya está en %s", tracking_num, target_status.value)
                processed_events.append({
                    "tracking_number": tracking_num,
                    "status": target_status.value,
                    "result": "already_in_state",
                })
                continue

            try:
                prev_status = shipment.status.value
                transition(shipment, target_status)
                logger.info(
                    "Webhook FedEx: Tracking '%s' transicionado silenciosamente: %s -> %s",
                    tracking_num, prev_status, target_status.value,
                )
                processed_events.append({
                    "tracking_number": tracking_num,
                    "previous_status": prev_status,
                    "status": target_status.value,
                    "result": "updated",
                })
            except InvalidTransitionError as err:
                logger.warning(
                    "Webhook FedEx: Transición rechazada por la máquina de estados para '%s': %s",
                    tracking_num, err,
                )
                processed_events.append({
                    "tracking_number": tracking_num,
                    "status": shipment.status.value,
                    "result": f"invalid_transition: {err}",
                })

    return {
        "status": "success",
        "processed_count": len(processed_events),
        "events": processed_events,
    }
