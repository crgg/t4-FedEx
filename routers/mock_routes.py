"""
Endpoints de simulación (solo desarrollo local).

Se registran únicamente si ENABLE_MOCK_ENDPOINTS=true y exigen JWT.
Reemplazan al webhook real de Stripe mientras no haya sandbox.
"""
from celery import Celery
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import verify_token
from dependencies import get_celery, get_db
from models import Shipment, ShipmentStatus, Store
from schemas import MockStripeWebhook
from services.shipment_state import transition

router = APIRouter(prefix="/mock", tags=["Mock (dev)"], dependencies=[Depends(verify_token)])

LABEL_TASK = "tasks.procesar_etiqueta_fedex"


@router.post("/stripe-webhook")
async def mock_stripe_webhook(
    event: MockStripeWebhook,
    session: AsyncSession = Depends(get_db),
    celery_app: Celery = Depends(get_celery),
):
    """Único camino para avanzar PENDING_PAYMENT -> PAID."""
    async with session.begin():
        shipment = (await session.execute(
            select(Shipment).where(Shipment.order_id == event.order_id).with_for_update()
        )).scalar_one_or_none()
        if shipment is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Orden {event.order_id} no encontrada")

        if event.payment_status != "succeeded":
            return {"order_id": event.order_id, "status": shipment.status, "detail": f"Pago '{event.payment_status}': sin cambios"}

        if shipment.status == ShipmentStatus.CANCELED:
            raise HTTPException(status.HTTP_409_CONFLICT, "La orden est\u00e1 cancelada; no se puede marcar como pagada")

        if shipment.status != ShipmentStatus.PENDING_PAYMENT:
            # Idempotencia: los proveedores de pago reintentan webhooks.
            return {"order_id": event.order_id, "status": shipment.status, "detail": "Pago ya procesado"}

        transition(shipment, ShipmentStatus.PAID)
        local_id = shipment.local_id
        store = await session.get(Store, shipment.store_id) if shipment.store_id else None
        client_account_number = store.fedex_account_number if store else None

    # Se dispara DESPUÉS del commit para que el worker ya vea el estado PAID.
    celery_app.send_task(LABEL_TASK, args=[local_id, client_account_number])
    return {"order_id": event.order_id, "status": ShipmentStatus.PAID, "detail": "Pago confirmado; generación de etiqueta encolada"}
