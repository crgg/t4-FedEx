import enum

from sqlalchemy import JSON, Column, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base, relationship

# Base declarativa compartida por todos los modelos (y usada por Alembic)
Base = declarative_base()


class ShipmentStatus(str, enum.Enum):
    """Ciclo de vida de un envío. Las transiciones válidas viven en
    services/shipment_state.py."""
    PENDING_PAYMENT = "PENDING_PAYMENT"            # Orden registrada, esperando pago
    PAID = "PAID"                                  # Pago confirmado (solo vía webhook de pago)
    LABEL_CREATED = "LABEL_CREATED"                # Etiqueta PDF generada en FedEx
    SCHEDULED_FOR_PICKUP = "SCHEDULED_FOR_PICKUP"  # Retiro programado con FedEx
    IN_TRANSIT = "IN_TRANSIT"                      # En camino (telemetría FedEx)
    DELIVERED = "DELIVERED"                        # Entregado
    CANCELED = "CANCELED"                          # Anulado


# ---- MODELOS DE BASE DE DATOS (SQLAlchemy) ----
class Store(Base):
    """Tienda (tenant) que usa T4Inventory como motor logístico SaaS."""
    __tablename__ = "stores"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    # Cuenta FedEx propia de la tienda (los envíos se facturan a ella)
    fedex_account_number = Column(String, nullable=False)

    shipments = relationship("Shipment", back_populates="store")


class Shipment(Base):
    __tablename__ = "shipments"
    local_id = Column(String, primary_key=True, index=True)
    # Tenant dueño del envío. Nullable solo para no romper filas previas al
    # modelo SaaS; los envíos nuevos deben asignarlo siempre.
    store_id = Column(Integer, ForeignKey("stores.id"), index=True, nullable=True)
    # ID de la orden en T4Inventory (lo usa el webhook de pago para localizar el envío)
    order_id = Column(Integer, unique=True, index=True, nullable=True)
    status = Column(
        Enum(ShipmentStatus, name="shipment_status"),
        nullable=False,
        default=ShipmentStatus.PENDING_PAYMENT,
        server_default=ShipmentStatus.PENDING_PAYMENT.value,
    )
    tracking_number = Column(String, index=True, nullable=True, unique=True)
    # URL del PDF de la etiqueta: permite re-imprimir sin volver a llamar a la
    # API transaccional de FedEx.
    label_pdf_url = Column(String, nullable=True)
    client_name = Column(String)
    contact_phone = Column(String)
    # Datos del paquete (zips, peso, dimensiones...) que necesita Celery para
    # generar la etiqueta cuando llegue el pago.
    ship_request = Column(JSON, nullable=True)

    store = relationship("Store", back_populates="shipments")
