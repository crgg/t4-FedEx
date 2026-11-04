"""
Cliente HTTP hacia las APIs de FedEx.

Este módulo concentra toda la comunicación con FedEx (autenticación,
construcción de payloads y llamadas HTTP). No depende de FastAPI ni de
main.py, por lo que puede reutilizarse desde Celery u otros servicios.
"""
import os
import uuid

import httpx
from dotenv import load_dotenv

from schemas import (
    AddressValidationRequest,
    EndOfDayRequest,
    PickupRequest,
    RateRequest,
    ReturnRequest,
)

# Se carga aquí también porque este módulo se importa antes de que
# main.py termine de inicializarse.
load_dotenv()

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ACCOUNT_NUMBER = os.getenv("ACCOUNT_NUMBER")

_missing = [name for name, value in {
    "API_KEY": API_KEY,
    "SECRET_KEY": SECRET_KEY,
    "ACCOUNT_NUMBER": ACCOUNT_NUMBER,
}.items() if not value]
if _missing:
    raise RuntimeError(f"Faltan variables de entorno en .env: {', '.join(_missing)}")

FEDEX_BASE_URL = "https://apis-sandbox.fedex.com"


class FedExAPIError(Exception):
    """Error devuelto por FedEx (status distinto de 200)."""

    def __init__(self, status_code: int, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"FedEx API error {status_code}: {detail}")


def _safe_json(response: httpx.Response):
    try:
        return response.json()
    except ValueError:
        return response.text


# ---- HELPER AUTENTICACIÓN ----
async def get_fedex_token() -> str:
    url = f"{FEDEX_BASE_URL}/oauth/token"
    payload = {"grant_type": "client_credentials", "client_id": API_KEY, "client_secret": SECRET_KEY}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, data=payload)
        response.raise_for_status()
        return response.json()["access_token"]


async def _post_to_fedex(path: str, payload: dict) -> dict:
    """Obtiene token, hace POST autenticado y lanza FedExAPIError si status != 200."""
    token = await get_fedex_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{FEDEX_BASE_URL}{path}", json=payload, headers=headers)
        if response.status_code != 200:
            raise FedExAPIError(response.status_code, _safe_json(response))
        return response.json()


# ---- 1. VALIDACIÓN DE DIRECCIONES ----
async def call_validate_address(req: AddressValidationRequest) -> dict:
    payload = {
        "addressesToValidate": [{
            "address": {
                "streetLines": [req.street],
                "city": req.city,
                "stateOrProvinceCode": req.state,
                "postalCode": req.zip_code,
                "countryCode": "US"
            }
        }]
    }
    return await _post_to_fedex("/address/v1/addresses/resolve", payload)


# ---- 2. COTIZACIÓN ----
async def call_get_rates(req: RateRequest) -> dict:
    payload = {
        "accountNumber": {"value": ACCOUNT_NUMBER},
        "requestedShipment": {
            "shipper": {"address": {"postalCode": req.origin_zip, "countryCode": "US"}},
            "recipient": {"address": {"postalCode": req.dest_zip, "countryCode": "US", "residential": req.is_residential}},
            "pickupType": "DROPOFF_AT_FEDEX_LOCATION",
            "rateRequestType": ["ACCOUNT", "LIST"],
            "requestedPackageLineItems": [{
                "weight": {"units": "KG", "value": req.weight_kg},
                "dimensions": {"length": req.dimensions.length, "width": req.dimensions.width, "height": req.dimensions.height, "units": "CM"}
            }]
        }
    }
    return await _post_to_fedex("/rate/v1/rates/quotes", payload)


# ---- 4. PROGRAMACIÓN DE RECOLECCIÓN ----
async def call_schedule_pickup(req: PickupRequest) -> dict:
    # Aquí irá la lógica real hacia https://apis-sandbox.fedex.com/pickup/v1/pickups
    return {
        "status": "Pickup scheduled successfully",
        "location": req.location_zip,
        "packages": req.package_count,
        "confirmation": str(uuid.uuid4())
    }


# ---- 6. CIERRE DE OPERACIONES ----
async def call_end_of_day_close(req: EndOfDayRequest) -> dict:
    # Aquí irá la lógica hacia la API Ground End of Day Close
    return {
        "status": "Manifest created",
        "location": req.location_id,
        "manifest_url": f"https://t4inventory.com/manifests/eod_{req.date}.pdf"
    }


# ---- 7. LOGÍSTICA INVERSA (Devoluciones) ----
async def call_create_return_label(req: ReturnRequest) -> dict:
    # Aquí irá el payload hacia Returns API
    return {
        "status": "Return label created",
        "original_tracking": req.original_tracking,
        "rma_id": str(uuid.uuid4())
    }
