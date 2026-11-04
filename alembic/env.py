from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import sys
import os
from dotenv import load_dotenv

# Cargar variables del .env
load_dotenv()

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Inyectar dinámicamente la URL desde el .env
# Reemplazamos postgresql+asyncpg por postgresql para que Alembic use el driver síncrono (psycopg)
db_url = os.getenv("DB_URL")
if db_url:
    # Alembic necesita el driver síncrono psycopg
    sync_url = db_url.replace("postgresql+asyncpg", "postgresql")
    config.set_main_option("sqlalchemy.url", sync_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Configurar target_metadata
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from models import Base
target_metadata = Base.metadata