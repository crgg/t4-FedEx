"""
Receptores de webhooks externos.

IMPORTANTE: este router NO lleva la dependencia JWT, porque lo invocan
servidores externos (FedEx, Stripe). Su seguridad debe basarse en la
validación de firma / secreto de cada proveedor.
"""
from fastapi import APIRouter

from schemas import WebhookPayload

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


# ---- 5. WEBHOOK RECEIVER ----
@router.post("/fedex")
async def fedex_webhook(payload: WebhookPayload):
    # TODO: validar la firma/secreto del webhook de FedEx antes de procesar.
    # FastAPI valida automáticamente que FedEx envíe un JSON estructurado
    for event in payload.trackResults:
        tracking_num = event['trackingNumberInfo']['trackingNumber']
        new_status = event['latestStatusDetail']['derivedStatusCode']

        # async with AsyncSessionLocal() as session:
        #     # UPDATE shipments SET status = new_status WHERE tracking_number = tracking_num
        #     pass

    return {"status": "success"}


# Futuro: @router.post("/stripe") — validar con el header `Stripe-Signature`.
