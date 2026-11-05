import enum

from sqlalchemy import JSON, Column, Enum, Integer, String
from sqlalchemy.orm import declarative_base

# Base declarativa compartida por todos los modelos (y usada por Alembic)
Base = declarative_base()


class ShipmentStatus(str, enum.Enum):
    """Ciclo de vida de un envío. Las transiciones válidas viven en
    services/shipment_state.py."""
    PENDING_PAYMENT = "PENDING_PAYMENT"  # Orden registrada, esperando pago
    PAID = "PAID"                        # Pago confirmado (solo vía webhook de pago)
    LABEL_CREATED = "LABEL_CREATED"      # Etiqueta PDF generada en FedEx
    IN_TRANSIT = "IN_TRANSIT"            # En camino (telemetría FedEx)
    DELIVERED = "DELIVERED"              # Entregado
    CANCELED = "CANCELED"                # Anulado


# ---- MODELOS DE BASE DE DATOS (SQLAlchemy) ----
class Shipment(Base):
    __tablename__ = "shipments"
    local_id = Column(String, primary_key=True, index=True)
    # ID de la orden en T4Inventory (lo usa el webhook de pago para localizar el envío)
    order_id = Column(Integer, unique=True, index=True, nullable=True)
    status = Column(
        Enum(ShipmentStatus, name="shipment_status"),
        nullable=False,
        default=ShipmentStatus.PENDING_PAYMENT,
        server_default=ShipmentStatus.PENDING_PAYMENT.value,
    )
    tracking_number = Column(String, index=True, nullable=True, unique=True)
    label_url = Column(String, nullable=True)
    client_name = Column(String)
    contact_phone = Column(String)
    # Datos del paquete (zips, peso, dimensiones...) que necesita Celery para
    # generar la etiqueta cuando llegue el pago.
    ship_request = Column(JSON, nullable=True)
