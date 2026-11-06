# Guía de Pruebas: Orquestación Asíncrona (Celery) y Simuladores (Pickup y Tracking)

Esta guía detalla cómo probar todo el flujo logístico end-to-end sin consumir saldo de la API de FedEx ni depender de webhooks reales de Stripe o FedEx.

---

## 1. Configuración de Entorno (.env)

Asegúrate de que en el archivo `.env` tengas activadas las banderas de simulación:

```bash
FEDEX_MOCK_SHIP=true
ENABLE_MOCK_ENDPOINTS=true
MOCK_MODE=true
```

- **`FEDEX_MOCK_SHIP=true`**: Simula la generación de etiquetas en FedEx devolviendo un tracking y una URL de PDF ficticia (`https://t4inventory.com/labels/{id}.pdf`).
- **`ENABLE_MOCK_ENDPOINTS=true`**: Expone el endpoint `POST /mock/stripe-webhook` para simular confirmaciones de pago.
- **`MOCK_MODE=true`**: Activa el interceptor en `POST /pickup/` que evita la llamada a FedEx, cambia el estado a `SCHEDULED_FOR_PICKUP` y retorna `MOCK-PICKUP-999`.

---

## 2. Flujo Completo Paso a Paso

### Paso 1: Autenticación y obtención de JWT con `store_id`
Obtén un token Bearer para una tienda (ejemplo: Store 1):

```bash
curl -X POST "http://localhost:8001/auth/token" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "t4inventory",
    "password": "eRJK4NMerqxkCfMCv2zofAsV",
    "store_id": 1
  }'
```
Guarda el `access_token` devuelto para las siguientes peticiones.

---

### Paso 2: Registrar un nuevo envío (`PENDING_PAYMENT`)
Registra una orden para la tienda actual:

```bash
curl -X POST "http://localhost:8001/shipments/" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": 7001,
    "origin_zip": "90210",
    "dest_zip": "10001",
    "weight_kg": 2.5,
    "dimensions": {"length": 20, "width": 15, "height": 10},
    "client_name": "Cliente Prueba",
    "client_phone": "+1234567890"
  }'
```
Respuesta esperada: `201 Created` con `"status": "PENDING_PAYMENT"`.

---

### Paso 3: Confirmación de Pago y Orquestación Celery
Simula el pago mediante el webhook mock:

```bash
curl -X POST "http://localhost:8001/mock/stripe-webhook" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": 7001,
    "payment_status": "succeeded"
  }'
```

**Qué ocurre tras bambalinas:**
1. El backend cambia el estado de `PENDING_PAYMENT` a `PAID`.
2. Lee el `store_id` del envío y obtiene el `fedex_account_number` del Store (ej. `"740980114"`).
3. Encola la tarea `tasks.procesar_etiqueta_fedex` en Celery pasando `[local_id, client_account_number]`.
4. El worker de Celery ejecuta la tarea, llama a `call_create_shipment(...)` con la cuenta del cliente y persiste la URL del PDF en la columna `label_pdf_url` de PostgreSQL.
5. El envío pasa a estado `LABEL_CREATED`.

Puedes verificar que la etiqueta fue generada consultando el endpoint de re-impresión:

```bash
curl -X GET "http://localhost:8001/shipments/7001/label" \
  -H "Authorization: Bearer <TOKEN>"
```
Respuesta:
```json
{
  "order_id": 7001,
  "local_id": "...",
  "store_id": 1,
  "tracking_number": "MOCK...",
  "label_pdf_url": "https://t4inventory.com/labels/....pdf"
}
```

---

### Paso 4: Simulador de Retiros (`POST /pickup/`)
Con `MOCK_MODE=true`, programa el retiro de los paquetes con etiqueta creada:

```bash
curl -X POST "http://localhost:8001/pickup/" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "order_ids": [7001],
    "location_zip": "90210",
    "total_weight": 2.5,
    "package_count": 1
  }'
```

**Respuesta recibida:**
```json
{
  "status": "success",
  "message": "Pickup scheduled successfully (MOCK)",
  "confirmation_id": "MOCK-PICKUP-999",
  "scheduled_orders": [7001],
  "pickup_status": "SCHEDULED_FOR_PICKUP",
  "location_zip": "90210",
  "packages": 1
}
```
Todos los paquetes en `order_ids` ahora están en estado `SCHEDULED_FOR_PICKUP` en PostgreSQL.

---

### Paso 5: Simulador de Tracking (`POST /webhooks/fedex`)
El endpoint `POST /webhooks/fedex` es público (no requiere JWT) para recibir telemetría externa.

Para simular que el conductor de FedEx recolectó el paquete y ya está en ruta:

```bash
curl -X POST "http://localhost:8001/webhooks/fedex" \
  -H "Content-Type: application/json" \
  -d '{
    "tracking_number": "MOCK012345678901",
    "status": "IN_TRANSIT"
  }'
```

*Nota: Reemplaza `"MOCK012345678901"` con el `tracking_number` real obtenido en el Paso 3.*

**Efecto en el sistema:**
- El backend busca el envío por `tracking_number` en PostgreSQL.
- Transiciona silenciosamente su estado a `IN_TRANSIT`.
- Responde `200 OK` con:
```json
{
  "status": "success",
  "processed_count": 1,
  "events": [
    {
      "tracking_number": "MOCK...",
      "previous_status": "SCHEDULED_FOR_PICKUP",
      "status": "IN_TRANSIT",
      "result": "updated"
    }
  ]
}
```

---

### Paso 6: Verificación del Bloqueo de Cancelación
Una vez que el paquete está en `IN_TRANSIT`, si el usuario intenta cancelar el envío:

```bash
curl -X POST "http://localhost:8001/shipments/7001/cancel" \
  -H "Authorization: Bearer <TOKEN>"
```

**Respuesta devuelta:** `HTTP 400 Bad Request`
```json
{
  "detail": "No se puede cancelar un paquete en estado IN_TRANSIT: ya está en movimiento o fue entregado"
}
```
¡La cancelación queda estrictamente bloqueada por la máquina de estados!
