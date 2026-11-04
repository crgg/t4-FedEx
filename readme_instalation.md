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

## 3. Orquestación del Entorno (Docker)

La orquestación de la arquitectura (API, Worker de Celery, Redis y PostgreSQL) se ejecuta mediante contenedores de Docker.

```bash
docker-compose up -d --build

```

**¿Por qué usamos este comando?**

* `docker-compose up`: Lee el archivo `docker-compose.yml` y arranca todos los microservicios interconectados (FastAPI, Postgres, Redis, Celery Worker) bajo una misma red virtual.
* `-d` (*detached*): Libera tu terminal, ejecutando los contenedores en segundo plano.
* `--build`: Obliga a Docker a reconstruir las imágenes desde cero leyendo los últimos cambios del `Dockerfile` y de tu `requirements.txt`, asegurando un entorno fresco.

---

## 4. Migraciones de la Base de Datos (Alembic)

Una vez que los contenedores (incluyendo la base de datos PostgreSQL) están ejecutándose, es necesario estructurar las tablas internamente utilizando Alembic.

```bash
docker exec -it t4_fedex_api alembic revision --autogenerate -m "Crear tabla shipments"
docker exec -it t4_fedex_api alembic upgrade head

```

**Explicación de los Comandos:**
El diseño del PRD exige una persistencia estructurada. Como la API se está ejecutando dentro de un contenedor Docker llamado `t4_fedex_api`, debemos enviar comandos hacia el interior del mismo usando `docker exec -it`.

1. **`alembic revision --autogenerate ...`**: Alembic lee tu código (el modelo `Shipment` en `models.py`) y lo compara con el estado actual de la base de datos vacía. Al notar que faltan tablas e índices, "autogenera" un archivo Python (migración) con las instrucciones SQL exactas para crear la estructura.
2. **`alembic upgrade head`**: Toma ese archivo generado y lo aplica (impacta) directamente contra la base de datos de PostgreSQL, actualizándola a su última versión (`head`).

Una vez completados estos pasos, la arquitectura estará en pie y la API estará lista para recibir peticiones POST a través de Postman en el puerto mapeado.

```

```