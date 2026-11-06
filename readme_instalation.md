# T4Inventory Logistics Microservice - Integración FedEx

Este proyecto implementa un microservicio logístico en FastAPI diseñado para interactuar con las APIs de FedEx, siguiendo la arquitectura de alta disponibilidad propuesta en el PRD de T4Inventory. Utiliza un enfoque asíncrono para garantizar un ecosistema robusto y tolerante a fallos, previniendo cuellos de botella mediante colas de tareas y bases de datos transaccionales.

---

## 1. Activación del Entorno Virtual

Antes de iniciar la instalación de dependencias, es indispensable activar el entorno virtual aislado.

```bash
source .venv/bin/activate

```

**¿Por qué usar `source .venv/bin/activate`?**
El entorno virtual (`.venv`) actúa como una burbuja encapsulada para el proyecto. Al activarlo, garantizamos que las librerías instaladas mediante `pip` no entren en conflicto con las dependencias globales del sistema operativo u otros proyectos. Esto asegura reproducibilidad y previene el síndrome de *"en mi máquina sí funciona"*.

---

## 2. Instalación de Dependencias

Con el entorno virtual activo, procede a instalar las herramientas y librerías definidas en el `requirements.txt`:

```bash
pip install -r requirements.txt

```

### Justificación Técnica del Stack (Alineado al PRD)

Cada librería seleccionada cumple una función específica dentro de la propuesta de arquitectura de sistemas de T4Inventory:

* **`fastapi` & `uvicorn**`: FastAPI provee el enrutamiento para los webhooks asíncronos y la validación de esquemas (usando Pydantic). Uvicorn es el servidor ASGI ultrarrápido que levanta la aplicación.


* **`pydantic`**: Garantiza la validación estricta de datos entrantes en tiempo de ejecución, fundamental para evitar errores HTTP 400 por omisión de datos (como teléfonos sin formato o direcciones truncadas) antes de contactar a FedEx.


* **`httpx`**: Cliente HTTP asíncrono utilizado en el módulo `fedex_api_calls.py` para manejar conexiones de alta concurrencia hacia la API de FedEx sin bloquear el hilo principal.
* **`authlib`**: Manejo de tokens y estándares de autenticación OAuth 2.0 (usado internamente si la seguridad de la red lo requiere).
* **`celery` & `redis**`: Implementan el sistema de **Message Queues** y **Caché**. Celery encola tareas pesadas (como la creación de etiquetas en `/shipments/`) previniendo bloqueos si FedEx presenta errores 503. Redis funciona tanto como el *broker* de mensajería para Celery como el almacenamiento de caché (*Cache-Aside con TTL de 15-30 minutos*) para respuestas de cotizaciones.


* **`sqlalchemy[asyncio]` & `asyncpg**`: SQLAlchemy maneja el ORM asíncrono, mientras que `asyncpg` es el driver nativo asíncrono para conectar con **PostgreSQL**. Esta base de datos relacional asegura la persistencia transaccional y el uso de índices (ej. `tracking numbers`).


* **`psycopg[binary]` & `psycopg2-binary**`: Drivers síncronos requeridos por herramientas de administración (como Alembic) que no soportan operaciones 100% asíncronas para modificar esquemas.
* **`alembic`**: Gestiona las migraciones del esquema de la base de datos (versionamiento de tablas e índices en PostgreSQL) de manera segura y programática.


* **`boto3`**: SDK de AWS para Python, preparado para interactuar con Amazon S3 (**Blob Storage**) para el almacenamiento futuro de archivos grandes no estructurados (etiquetas PDF/ZPL y documentos aduaneros) sin sobrecargar PostgreSQL.


* **`python-dotenv`**: Gestiona de manera segura variables de entorno críticas (ej. credenciales de FedEx) desde un archivo `.env` local, manteniéndolas fuera del código fuente.

---

## 3. Despliegue y Orquestación con Docker

Para levantar y dejar 100% operativo el microservicio y su base de datos PostgreSQL, se deben ejecutar los siguientes 3 comandos en orden:

### 1. Construir y levantar los contenedores

```bash
docker-compose up -d --build
```

- **`docker-compose up`**: Arranca todos los microservicios interconectados (FastAPI, PostgreSQL, Redis, Celery Worker) bajo la red virtual compartida.
- **`-d`** (*detached*): Ejecuta los contenedores en segundo plano.
- **`--build`**: Reconstruye las imágenes desde cero leyendo los últimos cambios del `Dockerfile` y `requirements.txt`.

---

### 2. Ejecutar las migraciones de base de datos (Alembic)

Aplica el historial de migraciones para crear las tablas (`stores`, `shipments`), los tipos `enum` e índices en PostgreSQL:

```bash
docker compose exec fedex_api alembic upgrade head
```

- **`alembic upgrade head`**: Toma todas las revisiones del directorio `alembic/versions` y las impacta directamente en PostgreSQL hasta la versión más reciente (`head`).

---

### 3. Crear la tienda inicial (Seed en PostgreSQL)

Al ser una arquitectura SaaS multi-tenant, la emisión de JWTs y la gestión de envíos requieren la existencia de al menos una tienda (tenant). Se ejecuta el siguiente comando para registrar la tienda de prueba con su número de cuenta de FedEx:

```bash
docker compose exec fedex_api python -c "
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from models import Store

async def seed():
    engine = create_async_engine(os.environ['DB_URL'])
    async with async_sessionmaker(engine)() as session, session.begin():
        session.add(Store(id=1, name='Tienda Principal', fedex_account_number='740980114'))
    await engine.dispose()
    print('Tienda 1 creada exitosamente.')

asyncio.run(seed())
"
```

---

Una vez completados estos 3 pasos, la arquitectura estará en pie y lista para recibir peticiones a través de Postman en `http://localhost:8001`.