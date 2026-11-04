from sqlalchemy import Column, String
from sqlalchemy.orm import declarative_base

# Base declarativa compartida por todos los modelos (y usada por Alembic)
Base = declarative_base()


# ---- MODELOS DE BASE DE DATOS (SQLAlchemy) ----
class Shipment(Base):
    __tablename__ = "shipments"
    local_id = Column(String, primary_key=True, index=True)
    status = Column(String, default="pending")
    tracking_number = Column(String, index=True, nullable=True, unique=True)
    label_url = Column(String, nullable=True)
    client_name = Column(String)
    contact_phone = Column(String)
