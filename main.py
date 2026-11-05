import os

import redis.asyncio as redis
from celery import Celery
from dotenv import load_dotenv
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base  # noqa: F401  (re-exportado para compatibilidad)
from routers.auth_routes import router as auth_router
from routers.fedex_routes import router as fedex_router
from routers.mock_routes import router as mock_router
from routers.webhook_routes import router as webhook_router

# Carga las variables definidas en el archivo .env
load_dotenv()

# ---- CONFIGURACIÓN DE INFRAESTRUCTURA ----
app = FastAPI(title="T4Inventory Logistics Microservice - FedEx")

# Motores Asíncronos
DB_URL = os.getenv("DB_URL")
if not DB_URL:
    raise RuntimeError("Falta la variable de entorno DB_URL en .env")

engine = create_async_engine(DB_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

redis_client = redis.Redis(host='fedex_redis', port=6379, db=0, decode_responses=True)
# include=["tasks"] registra tasks.procesar_etiqueta_fedex en el worker
celery_app = Celery('fedex_tasks', broker='redis://fedex_redis:6379/0', include=["tasks"])

# Recursos compartidos accesibles desde los routers vía request.app.state
app.state.session_factory = AsyncSessionLocal
app.state.redis_client = redis_client
app.state.celery_app = celery_app

# ---- ROUTERS ----
app.include_router(auth_router)      # Público: emisión de tokens
app.include_router(fedex_router)     # Protegido con JWT
app.include_router(webhook_router)   # Público: validación por firma de webhook

# Simulaciones de desarrollo (JWT). Nunca activar en producción.
if os.getenv("ENABLE_MOCK_ENDPOINTS", "false").lower() == "true":
    app.include_router(mock_router)