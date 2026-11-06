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
import os
import uuid

import redis.asyncio as redis
from celery import Celery
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

load_dotenv()
MOCK_MODE = os.getenv("MOCK_MODE", "true").lower() in ("true", "1", "yes")

from auth import CurrentUser, get_current_user, verify_token
from dependencies import get_celery, get_db, get_redis
from models import Shipment, ShipmentStatus, Store
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


# ---- 2. COTIZACIÓN CON CACHÉ REDIS Y CUENTA DE TENANT ----
@router.post("/quotes/")
async def get_rates(
    req: RateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    store_id = current_user.store_id
    store = await session.get(Store, store_id)
    if not store:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Tienda {store_id} no encontrada")

    cache_key = f"quote:{store_id}:{req.origin_zip}:{req.dest_zip}:{req.weight_kg}:{req.is_residential}"
    cached_quote = await redis_client.get(cache_key)

    if cached_quote:
        return json.loads(cached_quote)

    try:
        data = await fedex.call_get_rates(req, client_account_number=store.fedex_account_number)
    except FedExAPIError as exc:
        _raise_http(exc)

    await redis_client.setex(cache_key, 900, json.dumps(data))
    return data


# ---- 3. REGISTRO DE ENVÍO / GUARD DE GENERACIÓN (MULTI-TENANT) ----
@router.post("/shipments/", status_code=status.HTTP_201_CREATED)
async def create_shipment(
    req: ShipRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    celery_app: Celery = Depends(get_celery),
):
    """
    Registra una nueva orden en estado PENDING_PAYMENT asociada al store_id del JWT.
    a) Lee el store_id del JWT (current_user.store_id).
    b) Consulta asíncronamente el modelo Store para verificar y obtener datos del tenant.
    c) Guarda el envío en PENDING_PAYMENT amarrado a ese store_id.
    """
    store_id = current_user.store_id
    store = await session.get(Store, store_id)
    if not store:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Tienda {store_id} no encontrada en PostgreSQL")

    existing = (await session.execute(
        select(Shipment).where(Shipment.order_id == req.order_id)
    )).scalar_one_or_none()

    if existing:
        if existing.status == ShipmentStatus.PENDING_PAYMENT:
            _bad_request("No se puede generar la etiqueta de un paquete sin pago aprobado")
        elif existing.status == ShipmentStatus.PAID:
            account_num = store.fedex_account_number if store else None
            celery_app.send_task(LABEL_TASK, args=[existing.local_id, account_num])
            return {
                "message": "Label generation queued",
                "local_id": existing.local_id,
                "order_id": existing.order_id,
                "store_id": existing.store_id,
                "status": ShipmentStatus.PAID,
            }
        else:
            _bad_request(f"No se puede generar la etiqueta: la orden {req.order_id} ya está en estado {existing.status.value}")

    local_id = str(uuid.uuid4())

    new_shipment = Shipment(
        local_id=local_id,
        store_id=store.id,
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
        "store_id": store.id,
        "status": ShipmentStatus.PENDING_PAYMENT,
    }


# ---- 3b. RE-IMPRESIÓN DE ETIQUETA (SIN LLAMAR A FEDEX) ----
@router.get("/shipments/{id}/label")
async def reprint_label(
    id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """
    Re-impresión de etiqueta (satisface caja del diagrama sin conectar a FedEx).
    Verifica que el envío pertenezca a la tienda del JWT y devuelve label_pdf_url directamente de Postgres.
    """
    criteria = [Shipment.local_id == id]
    if id.isdigit():
        criteria.append(Shipment.order_id == int(id))
    shipment = (await session.execute(
        select(Shipment).where(or_(*criteria))
    )).scalar_one_or_none()

    if shipment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Envío u orden '{id}' no encontrada")

    # Aislamiento multi-tenant: validar pertenencia
    if shipment.store_id and shipment.store_id != current_user.store_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permiso para consultar envíos de otra tienda")

    if not shipment.label_pdf_url:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"El paquete se encuentra en estado '{shipment.status.value}' y todavía no tiene una etiqueta generada",
        )

    return {
        "order_id": shipment.order_id,
        "local_id": shipment.local_id,
        "store_id": shipment.store_id,
        "tracking_number": shipment.tracking_number,
        "label_pdf_url": shipment.label_pdf_url,
    }


# ---- 3c. GENERACIÓN / REINTENTO DE ETIQUETA (MANUAL TRAS PAGO) ----
@router.post("/shipments/{id}/label", status_code=status.HTTP_202_ACCEPTED)
async def generate_label(
    id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    celery_app: Celery = Depends(get_celery),
):
    """Reintento manual si la tarea de Celery falló tras el pago (acepta order_id o local_id)."""
    async with session.begin():
        shipment = await _get_shipment_for_update(session, id)

        if shipment.store_id and shipment.store_id != current_user.store_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permiso para gestionar envíos de otra tienda")

        if shipment.status == ShipmentStatus.PENDING_PAYMENT:
            _bad_request("No se puede generar la etiqueta de un paquete sin pago aprobado")
        if shipment.status != ShipmentStatus.PAID:
            _bad_request(f"No se puede generar la etiqueta: el envío está en estado {shipment.status.value}")
        store = await session.get(Store, shipment.store_id) if shipment.store_id else None
        account_num = store.fedex_account_number if store else None
        local_id = shipment.local_id

    celery_app.send_task(LABEL_TASK, args=[local_id, account_num])
    return {
        "message": "Label generation queued",
        "local_id": shipment.local_id,
        "order_id": shipment.order_id,
        "store_id": shipment.store_id,
        "status": ShipmentStatus.PAID,
    }


# ---- 3d. CANCELACIÓN CON RESTRICCIONES (MULTI-TENANT) ----
@router.post("/shipments/{id}/cancel")
async def cancel_shipment(
    id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Cancela un paquete bajo restricciones de estado (acepta order_id o local_id)."""
    async with session.begin():
        shipment = await _get_shipment_for_update(session, id)

        if shipment.store_id and shipment.store_id != current_user.store_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permiso para cancelar envíos de otra tienda")

        if shipment.status in NON_CANCELABLE:
            _bad_request(
                f"No se puede cancelar un paquete en estado {shipment.status.value}: "
                "ya está en movimiento o fue entregado"
            )
        if shipment.status == ShipmentStatus.CANCELED:
            _bad_request("El envío ya está cancelado")

        fedex_result = None
        if shipment.tracking_number:
            store = await session.get(Store, shipment.store_id) if shipment.store_id else None
            account_number = store.fedex_account_number if store else "MOCK_ACCOUNT"
            try:
                fedex_result = await fedex.call_cancel_shipment(shipment.tracking_number, client_account_number=account_number)
            except FedExAPIError as exc:
                _raise_http(exc)

        previous = shipment.status
        transition(shipment, ShipmentStatus.CANCELED)

    return {
        "local_id": shipment.local_id,
        "order_id": shipment.order_id,
        "store_id": shipment.store_id,
        "previous_status": previous,
        "status": ShipmentStatus.CANCELED,
        "fedex_cancellation": fedex_result,
    }


# ---- 4. PROGRAMACIÓN DE RECOLECCIÓN (SIMULADOR MOCK_MODE) ----
@router.post("/pickup/")
async def schedule_pickup(
    req: PickupRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    order_ids = set(req.order_ids)
    async with session.begin():
        rows = (await session.execute(
            select(Shipment).where(Shipment.order_id.in_(order_ids)).with_for_update()
        )).scalars().all()
        found = {s.order_id: s for s in rows}

        missing = sorted(order_ids - found.keys())
        if missing:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Órdenes no encontradas: {missing}")

        for s in rows:
            if s.store_id and s.store_id != current_user.store_id:
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"La orden {s.order_id} pertenece a otra tienda")

        not_ready = {s.order_id: s.status.value for s in rows if s.status != ShipmentStatus.LABEL_CREATED}
        if not_ready:
            _bad_request(f"Solo se pueden recolectar paquetes con etiqueta generada (LABEL_CREATED). No válidos: {not_ready}")

        if MOCK_MODE:
            for s in rows:
                transition(s, ShipmentStatus.SCHEDULED_FOR_PICKUP)
            return {
                "status": "success",
                "message": "Pickup scheduled successfully (MOCK)",
                "confirmation_id": "MOCK-PICKUP-999",
                "scheduled_orders": sorted(list(order_ids)),
                "pickup_status": ShipmentStatus.SCHEDULED_FOR_PICKUP.value,
                "location_zip": req.location_zip,
                "packages": req.package_count,
            }

        # Modo real (llamada a FedEx)
        fedex_resp = await fedex.call_schedule_pickup(req)
        for s in rows:
            transition(s, ShipmentStatus.SCHEDULED_FOR_PICKUP)

        return {
            "status": "success",
            "confirmation_id": fedex_resp.get("confirmation"),
            "scheduled_orders": sorted(list(order_ids)),
            "pickup_status": ShipmentStatus.SCHEDULED_FOR_PICKUP.value,
            "fedex_response": fedex_resp,
        }


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
