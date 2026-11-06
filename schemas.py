from typing import Literal

from pydantic import BaseModel, Field


# ---- MODELOS PYDANTIC (Para exigir Body JSON en Postman) ----
class Dimensions(BaseModel):
    length: float = Field(..., gt=0)
    width: float = Field(..., gt=0)
    height: float = Field(..., gt=0)


class AddressValidationRequest(BaseModel):
    street: str
    city: str
    state: str
    zip_code: str


class RateRequest(BaseModel):
    origin_zip: str
    dest_zip: str
    weight_kg: float = Field(..., gt=0)
    dimensions: Dimensions
    is_residential: bool = False


class ShipRequest(BaseModel):
    order_id: int = Field(..., gt=0, description="ID de la orden en T4Inventory")
    origin_zip: str
    dest_zip: str
    weight_kg: float
    dimensions: Dimensions
    client_name: str
    client_phone: str = Field(..., pattern=r"^\+?[1-9]\d{1,14}$")
    signature_required: bool = False
    hazmat: bool = False


class PickupRequest(BaseModel):
    order_ids: list[int] = Field(..., min_length=1, description="Órdenes a recolectar (deben estar en LABEL_CREATED)")
    location_zip: str
    total_weight: float
    package_count: int


class ReturnRequest(BaseModel):
    original_tracking: str
    reason: str


class EndOfDayRequest(BaseModel):
    location_id: str
    date: str


class FedExWebhookPayload(BaseModel):
    tracking_number: str | None = None
    status: str | None = None
    trackResults: list[dict] | None = None


WebhookPayload = FedExWebhookPayload


class MockStripeWebhook(BaseModel):
    order_id: int = Field(..., gt=0)
    payment_status: Literal["succeeded", "failed", "processing", "canceled"]
