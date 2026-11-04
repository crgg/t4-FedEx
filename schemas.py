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
    origin_zip: str
    dest_zip: str
    weight_kg: float
    dimensions: Dimensions
    client_name: str
    client_phone: str = Field(..., pattern=r"^\+?[1-9]\d{1,14}$")
    signature_required: bool = False
    hazmat: bool = False


class PickupRequest(BaseModel):
    location_zip: str
    total_weight: float
    package_count: int


class ReturnRequest(BaseModel):
    original_tracking: str
    reason: str


class EndOfDayRequest(BaseModel):
    location_id: str
    date: str


class WebhookPayload(BaseModel):
    trackResults: list = []
