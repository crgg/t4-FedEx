"""
Endpoints de FedEx.

Este router NO importa nada de main.py (evita la dependencia circular
main -> router -> main). Los recursos de infraestructura (Redis, Celery,
sesión de BD) se obtienen de `request.app.state` mediante dependencias,
y toda la comunicación con FedEx se delega a services.fedex_api_calls.
"""
import json
import uuid

import redis.asyncio as redis
from celery import Celery
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from models import Shipment
from schemas import (
    AddressValidationRequest,
    EndOfDayRequest,
    PickupRequest,
    RateRequest,
    ReturnRequest,
    ShipRequest,
    WebhookPayload,
)
from services import fedex_api_calls as fedex
from services.fedex_api_calls import FedExAPIError

router = APIRouter(tags=["FedEx"])


# ---- DEPENDENCIAS (inyectadas desde app.state en main.py) ----
def get_redis(request: Request) -> redis.Redis:
    return request.app.state.redis_client


def get_celery(request: Request) -> Celery:
    return request.app.state.celery_app


async def get_db(request: Request):
    async with request.app.state.session_factory() as session:
        yield session


def _raise_http(exc: FedExAPIError):
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


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


# ---- 3. DESPACHO DESACOPLADO CON CELERY ----
@router.post("/shipments/", status_code=status.HTTP_202_ACCEPTED)
async def create_shipment(
    req: ShipRequest,
    session: AsyncSession = Depends(get_db),
    celery_app: Celery = Depends(get_celery),
):
    local_id = str(uuid.uuid4())

    new_shipment = Shipment(
        local_id=local_id,
        status="pending",
        client_name=req.client_name,
        contact_phone=req.client_phone
    )
    session.add(new_shipment)
    await session.commit()

    celery_app.send_task("tasks.procesar_etiqueta_fedex", args=[local_id, req.dict()])

    return {"message": "Shipment queued", "local_id": local_id, "status": "pending"}


# ---- 4. PROGRAMACIÓN DE RECOLECCIÓN ----
@router.post("/pickup/")
async def schedule_pickup(req: PickupRequest):
    return await fedex.call_schedule_pickup(req)


# ---- 5. WEBHOOK RECEIVER ----
@router.post("/webhooks/fedex")
async def fedex_webhook(payload: WebhookPayload):
    # FastAPI valida automáticamente que FedEx envíe un JSON estructurado
    for event in payload.trackResults:
        tracking_num = event['trackingNumberInfo']['trackingNumber']
        new_status = event['latestStatusDetail']['derivedStatusCode']

        # async with AsyncSessionLocal() as session:
        #     # UPDATE shipments SET status = new_status WHERE tracking_number = tracking_num
        #     pass

    return {"status": "success"}


# ---- 6. CIERRE DE OPERACIONES ----
@router.post("/end-of-day/")
async def close_ground_operations(req: EndOfDayRequest):
    return await fedex.call_end_of_day_close(req)


# ---- 7. LOGÍSTICA INVERSA (Devoluciones) ----
@router.post("/returns/")
async def create_return_label(req: ReturnRequest):
    return await fedex.call_create_return_label(req)
