"""
Endpoints de FedEx (protegidos con JWT).

Este router NO importa nada de main.py (evita la dependencia circular
main -> router -> main). Los recursos de infraestructura (Redis, Celery,
sesión de BD) se obtienen de `request.app.state` mediante dependencias,
y toda la comunicación con FedEx se delega a services.fedex_api_calls.

Todos los endpoints exigen `Authorization: Bearer <token>` mediante la
dependencia a nivel de router. Los webhooks viven en webhook_routes.py
porque NO deben llevar JWT.

Guard clauses: los endpoints que operan sobre envíos existentes consultan
el `status` en PostgreSQL ANTES de tocar FedEx o Celery. Las transiciones
válidas están definidas en services/shipment_state.py.
"""
import json
import uuid

import redis.asyncio as redis
from celery import Celery
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth import verify_token
from dependencies import get_celery, get_db, get_redis
from models import Shipment, ShipmentStatus
from schemas import (
    AddressValidationRequest,
    EndOfDayRequest,
    PickupRequest,
    RateRequest,
    ReturnRequest,
    ShipRequest,
)
from services import fedex_api_calls as fedex
from services.fedex_api_calls import FedExAPIError
from services.shipment_state import NON_CANCELABLE, transition

router = APIRouter(tags=["FedEx"], dependencies=[Depends(verify_token)])

LABEL_TASK = "tasks.procesar_etiqueta_fedex"


def _raise_http(exc: FedExAPIError):
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


def _bad_request(detail: str):
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


async def _get_shipment_for_update(session: AsyncSession, identifier: str) -> Shipment:
    criteria = [Shipment.local_id == identifier]
    if identifier.isdigit():
        criteria.append(Shipment.order_id == int(identifier))
    shipment = (await session.execute(
        select(Shipment).where(or_(*criteria)).with_for_update()
    )).scalar_one_or_none()
    if shipment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Envío u orden '{identifier}' no encontrada")
    return shipment


# ---- 1. VALIDACIÓN DE DIRECCIONES ----
@router.post("/validate_address/")
async def validate_address(req: AddressValidationRequest):
    try:
        return await fedex.call_validate_address(req)
    except FedExAPIError as exc:
        _raise_http(exc)


# ---- 2. COTIZACIÓN CON CACHÉ REDIS ----
@router.post("/quotes/")
async def get_rates(req: RateRequest, redis_client: redis.Redis = Depends(get_redis)):
    cache_key = f"quote:{req.origin_zip}:{req.dest_zip}:{req.weight_kg}:{req.is_residential}"
    cached_quote = await redis_client.get(cache_key)

    if cached_quote:
        return json.loads(cached_quote)

    try:
        data = await fedex.call_get_rates(req)
    except FedExAPIError as exc:
        _raise_http(exc)

    await redis_client.setex(cache_key, 900, json.dumps(data))
    return data


# ---- 3. REGISTRO DE ENVÍO / GUARD DE GENERACIÓN ----
@router.post("/shipments/", status_code=status.HTTP_201_CREATED)
async def create_shipment(
    req: ShipRequest,
    session: AsyncSession = Depends(get_db),
    celery_app: Celery = Depends(get_celery),
):
    """
    Registra una nueva orden en estado PENDING_PAYMENT.
    Guard: Si la orden ya existe:
      - Si está en PENDING_PAYMENT: rechaza con 400 Bad Request ('No se puede generar la etiqueta de un paquete sin pago aprobado').
      - Si está en PAID: encola la generación de etiqueta y retorna 202 Accepted.
      - En cualquier otro estado: rechaza con 400 Bad Request.
    """
    existing = (await session.execute(
        select(Shipment).where(Shipment.order_id == req.order_id)
    )).scalar_one_or_none()

    if existing:
        if existing.status == ShipmentStatus.PENDING_PAYMENT:
            _bad_request("No se puede generar la etiqueta de un paquete sin pago aprobado")
        elif existing.status == ShipmentStatus.PAID:
            celery_app.send_task(LABEL_TASK, args=[existing.local_id])
            return {
                "message": "Label generation queued",
                "local_id": existing.local_id,
                "order_id": existing.order_id,
                "status": ShipmentStatus.PAID,
            }
        else:
            _bad_request(f"No se puede generar la etiqueta: la orden {req.order_id} ya está en estado {existing.status.value}")

    local_id = str(uuid.uuid4())

    new_shipment = Shipment(
        local_id=local_id,
        order_id=req.order_id,
        status=ShipmentStatus.PENDING_PAYMENT,
        client_name=req.client_name,
        contact_phone=req.client_phone,
        ship_request=req.model_dump(exclude={"order_id", "client_name", "client_phone"}),
    )
    session.add(new_shipment)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"La orden {req.order_id} ya tiene un envío registrado")

    return {
        "message": "Shipment registered; awaiting payment",
        "local_id": local_id,
        "order_id": req.order_id,
        "status": ShipmentStatus.PENDING_PAYMENT,
    }


# ---- 3b. GENERACIÓN / REINTENTO DE ETIQUETA ----
@router.post("/shipments/{id}/label", status_code=status.HTTP_202_ACCEPTED)
async def generate_label(
    id: str,
    session: AsyncSession = Depends(get_db),
    celery_app: Celery = Depends(get_celery),
):
    """Reintento manual si la tarea de Celery falló tras el pago (acepta order_id o local_id)."""
    async with session.begin():
        shipment = await _get_shipment_for_update(session, id)
        if shipment.status == ShipmentStatus.PENDING_PAYMENT:
            _bad_request("No se puede generar la etiqueta de un paquete sin pago aprobado")
        if shipment.status != ShipmentStatus.PAID:
            _bad_request(f"No se puede generar la etiqueta: el envío está en estado {shipment.status.value}")
        local_id = shipment.local_id

    celery_app.send_task(LABEL_TASK, args=[local_id])
    return {
        "message": "Label generation queued",
        "local_id": shipment.local_id,
        "order_id": shipment.order_id,
        "status": ShipmentStatus.PAID,
    }


# ---- 3c. CANCELACIÓN CON RESTRICCIONES ----
@router.post("/shipments/{id}/cancel")
async def cancel_shipment(id: str, session: AsyncSession = Depends(get_db)):
    """Cancela un paquete bajo restricciones de estado (acepta order_id o local_id)."""
    async with session.begin():
        # FOR UPDATE: bloquea la fila para que la tarea de Celery no la cambie
        # a mitad de la cancelación.
        shipment = await _get_shipment_for_update(session, id)

        if shipment.status in NON_CANCELABLE:
            _bad_request(
                f"No se puede cancelar un paquete en estado {shipment.status.value}: "
                "ya está en movimiento o fue entregado"
            )
        if shipment.status == ShipmentStatus.CANCELED:
            _bad_request("El envío ya está cancelado")

        fedex_result = None
        if shipment.tracking_number:
            # Hay envío creado en FedEx: anularlo para evitar cargos. Si FedEx
            # falla, se hace rollback y el estado local no cambia.
            try:
                fedex_result = await fedex.call_cancel_shipment(shipment.tracking_number)
            except FedExAPIError as exc:
                _raise_http(exc)
        # Si está PAID sin tracking, aún no existe en FedEx. Si la tarea de
        # Celery termina después, verá CANCELED y anulará la etiqueta huérfana.

        previous = shipment.status
        transition(shipment, ShipmentStatus.CANCELED)

    return {
        "local_id": shipment.local_id,
        "order_id": shipment.order_id,
        "previous_status": previous,
        "status": ShipmentStatus.CANCELED,
        "fedex_cancellation": fedex_result,
    }


# ---- 4. PROGRAMACIÓN DE RECOLECCIÓN ----
@router.post("/pickup/")
async def schedule_pickup(req: PickupRequest, session: AsyncSession = Depends(get_db)):
    order_ids = set(req.order_ids)
    rows = (await session.execute(
        select(Shipment.order_id, Shipment.status).where(Shipment.order_id.in_(order_ids))
    )).all()
    found = {order_id: st for order_id, st in rows}

    missing = sorted(order_ids - found.keys())
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"\u00d3rdenes no encontradas: {missing}")

    not_ready = {oid: st.value for oid, st in found.items() if st != ShipmentStatus.LABEL_CREATED}
    if not_ready:
        _bad_request(f"Solo se pueden recolectar paquetes con etiqueta generada (LABEL_CREATED). No v\u00e1lidos: {not_ready}")

    return await fedex.call_schedule_pickup(req)


# ---- 5. WEBHOOK RECEIVER ----
# Movido a routers/webhook_routes.py (público, sin JWT).


# ---- 6. CIERRE DE OPERACIONES ----
@router.post("/end-of-day/")
async def close_ground_operations(req: EndOfDayRequest):
    return await fedex.call_end_of_day_close(req)


# ---- 7. LOGÍSTICA INVERSA (Devoluciones) ----
@router.post("/returns/")
async def create_return_label(req: ReturnRequest):
    return await fedex.call_create_return_label(req)
