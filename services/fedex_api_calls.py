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

FEDEX_API_KEY = os.getenv("FEDEX_API_KEY")
FEDEX_SECRET_KEY = os.getenv("FEDEX_SECRET_KEY")
FEDEX_ACCOUNT_NUMBER = os.getenv("FEDEX_ACCOUNT_NUMBER")

_missing = [name for name, value in {
    "FEDEX_API_KEY": FEDEX_API_KEY,
    "FEDEX_SECRET_KEY": FEDEX_SECRET_KEY,
    "FEDEX_ACCOUNT_NUMBER": FEDEX_ACCOUNT_NUMBER,
}.items() if not value]
if _missing:
    raise RuntimeError(f"Faltan variables de entorno en .env: {', '.join(_missing)}")

FEDEX_BASE_URL = "https://apis-sandbox.fedex.com"

# Si es true, crear/anular envíos devuelve respuestas simuladas en lugar de
# llamar a la Ship API (hoy solo tenemos códigos postales, no direcciones completas).
FEDEX_MOCK_SHIP = os.getenv("FEDEX_MOCK_SHIP", "true").lower() == "true"


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
    payload = {"grant_type": "client_credentials", "client_id": FEDEX_API_KEY, "client_secret": FEDEX_SECRET_KEY}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, data=payload)
        response.raise_for_status()
        return response.json()["access_token"]


async def _request_fedex(method: str, path: str, payload: dict) -> dict:
    """Obtiene token, hace la petición autenticada y lanza FedExAPIError si status != 200."""
    token = await get_fedex_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        response = await client.request(method, f"{FEDEX_BASE_URL}{path}", json=payload, headers=headers)
        if response.status_code != 200:
            raise FedExAPIError(response.status_code, _safe_json(response))
        return response.json()


async def _post_to_fedex(path: str, payload: dict) -> dict:
    return await _request_fedex("POST", path, payload)


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
        "accountNumber": {"value": FEDEX_ACCOUNT_NUMBER},
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


# ---- 3. CREACIÓN DE ENVÍO (ETIQUETA PDF) ----
async def call_create_shipment(local_id: str, ship_data: dict, client_name: str, client_phone: str) -> dict:
    """Crea el envío en FedEx y devuelve {"tracking_number", "label_url"}."""
    if FEDEX_MOCK_SHIP:
        return {
            "tracking_number": f"MOCK{uuid.uuid4().int % 10**12:012d}",
            "label_url": f"https://t4inventory.com/labels/{local_id}.pdf",
        }

    dims = ship_data["dimensions"]
    package = {
        "weight": {"units": "KG", "value": ship_data["weight_kg"]},
        "dimensions": {"length": dims["length"], "width": dims["width"], "height": dims["height"], "units": "CM"},
    }
    if ship_data.get("signature_required"):
        package["packageSpecialServices"] = {"signatureOptionType": "DIRECT"}

    # TODO: FedEx exige direcciones y contactos completos (streetLines, city,
    # stateOrProvinceCode). Hoy solo tenemos códigos postales, por lo que el
    # sandbox rechazará la petición hasta que ShipRequest los incluya.
    payload = {
        "labelResponseOptions": "URL_ONLY",
        "accountNumber": {"value": FEDEX_ACCOUNT_NUMBER},
        "requestedShipment": {
            "shipper": {
                "contact": {"personName": "T4Inventory", "phoneNumber": client_phone},
                "address": {"postalCode": ship_data["origin_zip"], "countryCode": "US"},
            },
            "recipients": [{
                "contact": {"personName": client_name, "phoneNumber": client_phone},
                "address": {"postalCode": ship_data["dest_zip"], "countryCode": "US"},
            }],
            "serviceType": "FEDEX_GROUND",
            "packagingType": "YOUR_PACKAGING",
            "pickupType": "USE_SCHEDULED_PICKUP",
            "shippingChargesPayment": {"paymentType": "SENDER"},
            "labelSpecification": {"imageType": "PDF", "labelStockType": "PAPER_85X11_TOP_HALF_LABEL"},
            "requestedPackageLineItems": [package],
        },
    }
    data = await _post_to_fedex("/ship/v1/shipments", payload)
    shipment = data["output"]["transactionShipments"][0]
    return {
        "tracking_number": shipment["masterTrackingNumber"],
        "label_url": shipment["pieceResponses"][0]["packageDocuments"][0]["url"],
    }


# ---- ANULACIÓN DE ENVÍO ----
async def call_cancel_shipment(tracking_number: str) -> dict:
    """Anula el envío en FedEx para evitar cargos en la cuenta corporativa."""
    if FEDEX_MOCK_SHIP:
        return {"cancelledShipment": True, "trackingNumber": tracking_number}

    payload = {
        "accountNumber": {"value": FEDEX_ACCOUNT_NUMBER},
        "trackingNumber": tracking_number,
        "deletionControl": "DELETE_ALL_PACKAGES",
    }
    data = await _request_fedex("PUT", "/ship/v1/shipments/cancel", payload)
    output = data.get("output", {})
    if not output.get("cancelledShipment"):
        raise FedExAPIError(400, output or data)
    return output


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
