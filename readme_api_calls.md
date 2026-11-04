Aquí tienes el bloque de texto completo, incluyendo el párrafo introductorio, la lista del 1 al 7 y la nueva sección con las 5 APIs perfectamente integradas al final. Está listo para que lo copies y pegues directamente en tu `README.md`:

---

### El Ciclo de Vida del Paquete en T4Inventory (Flujo E2E)

Este flujo de siete pasos materializa el ciclo de vida operativo real de un paquete dentro del almacén de T4Inventory. Al implementar este ciclo de extremo a extremo (E2E), el microservicio transiciona de un frágil modelo de consultas manuales a una arquitectura automatizada, asíncrona y tolerante a fallos. Este diseño mitiga preventivamente discrepancias de facturación (como recargos residenciales ocultos o multas por corrección de ruta) y bloqueos operativos. Al delegar la carga pesada a colas de mensajería y optimizar las lecturas con caché, aseguramos que los operarios del almacén y la plataforma de e-commerce sigan funcionando fluidamente, incluso si la red de FedEx experimenta latencias o caídas temporales.

A continuación, se detalla el propósito operativo de cada endpoint en nuestro flujo de trabajo:

1. **Validación de Direcciones (`/validate_address/`) - *Prevención de Multas*:**
Antes de permitir un pago o imprimir una etiqueta, este endpoint estandariza la dirección del cliente. Identifica si el destino es residencial o comercial, evitando que FedEx nos aplique recargos automáticos ocultos y multas por correcciones de ruta debido a errores tipográficos.


2. **Cotización con Caché (`/quotes/`) - *Precisión y Velocidad*:**
Calcula el costo real del envío enviando el peso volumétrico (DIM Weight) exacto, lo que previene que cobremos tarifas irrealmente bajas que luego destruyen nuestros márgenes. Al usar Redis, las cotizaciones idénticas se responden en milisegundos, protegiendo nuestros límites de cuota (Rate Limiting) ante FedEx.


3. **Despacho Asíncrono (`/shipments/`) - *Tolerancia a Fallos*:**
Es el motor del almacén. En lugar de hacer esperar al sistema, la petición se encola inmediatamente (HTTP 202) y Celery procesa el PDF en segundo plano. Esto garantiza que la interfaz de los operarios nunca se congele si la API de FedEx sufre errores 503 temporales.


4. **Programación de Recolección (`/pickup/`) - *Logística de Andén*:**
Automatiza la solicitud de camiones de FedEx al almacén. Al declarar explícitamente la cantidad de paquetes y el peso consolidado, evitamos enviar requerimientos erróneos y aseguramos que el vehículo despachado tenga la capacidad física suficiente.


5. **Rastreo Automático vía Webhooks (`/webhooks/fedex`) - *Telemetría*:**
Elimina la ineficiencia de consultar repetitivamente (polling) dónde está cada paquete. Funciona como un receptor pasivo donde FedEx nos "empuja" las actualizaciones en tiempo real, actualizando silenciosamente los estados en nuestra base de datos PostgreSQL.


6. **Cierre de Operaciones (`/end-of-day/`) - *Cumplimiento Legal*:**
Ejecutado al final del turno por el jefe de almacén. Es un requerimiento estricto para los envíos terrestres (FedEx Ground) que reconcilia toda la información del día y genera el manifiesto consolidado (PDF) que el chofer debe escanear antes de llevarse la carga.


7. **Logística Inversa (`/returns/`) - *Conciliación de Inventario*:**
Genera etiquetas dinámicas para gestionar las devoluciones post-venta. Configura un enrutamiento preciso para asegurar que el inventario devuelto regrese exactamente a la sucursal de origen correcta, evitando que la mercancía se pierda o corrompa la base de datos central de T4Inventory.



---

### Módulos y APIs de FedEx Habilitados

Para que este ecosistema logístico funcione correctamente, el microservicio orquesta la comunicación con 5 APIs específicas, las cuales deben estar explícitamente habilitadas en el portal de desarrolladores de FedEx (Sandbox/Producción):

* **Address Validation API**: Alimenta el Paso 1. Se encarga de la corrección tipográfica y la resolución de destinos residenciales vs. comerciales.


* **Rates and Transit Times API**: Alimenta el Paso 2. Proveé los costos exactos basados en reglas de negocio y dimensiones físicas (DIM Weight).


* **Ship API**: Es el núcleo del servicio. Se utiliza en el Paso 3 (emisión de etiquetas estándar), el Paso 6 (cierre de manifiestos y reportes) y el Paso 7 (creación de etiquetas RMA para devoluciones).


* **Pickup Request API**: Alimenta el Paso 4. Permite la programación electrónica de recolecciones, indicando capacidades y horarios al centro de despacho de FedEx.


* **Basic Integrated Visibility (anteriormente Track API)**: Alimenta el Paso 5. Permite suscribir nuestra URL a las notificaciones Push (Webhooks) para recibir eventos de telemetría sin necesidad de hacer *polling*.

Para validar la correcta implementación de esta arquitectura en tu entorno local, utiliza la siguiente secuencia lógica de peticiones. Apuntando tu cliente REST (como Postman) al puerto 8001, podrás simular paso a paso el ciclo de vida completo de un paquete y observar la respuesta del sistema automatizado:

**1. Validación (Antes del Checkout)**
Antes de cotizar o imprimir, el sistema debe asegurar que el cliente no ingresó una dirección falsa, lo que evitará multas de FedEx por corrección de ruta.

* **Método:** POST
* **URL:** `[http://127.0.0.1:8001/validate_address/]`
* **Body (JSON):**
```json
{
  "street": "350 5th Ave",
  "city": "New York",
  "state": "NY",
  "zip_code": "10118"
}

```

* **Respuesta esperada:** Un JSON de FedEx detallando si la dirección es válida, si es residencial o comercial, y el formato estandarizado.

**2. Cotización con Caché (Al calcular el envío en el carrito)**
El usuario procede a pagar. T4Inventory solicita el precio.

* **Método:** POST
* **URL:** `[http://127.0.0.1:8001/quotes/]`
* **Body (JSON):**
```json
{
  "origin_zip": "90210",
  "dest_zip": "10118",
  "weight_kg": 2.5,
  "dimensions": {"length": 30.0, "width": 25.5, "height": 10.0},
  "is_residential": false
}

```

* **Comportamiento:** La primera vez tardará ~1 segundo. Envía la petición de nuevo inmediatamente y responderá en milisegundos porque Redis interceptó la llamada.

**3. Despacho Asíncrono (Al confirmar el pago)**
El almacén necesita la etiqueta. Aquí notarás el cambio de arquitectura: la API ya no espera a FedEx, delega el trabajo a Celery.

* **Método:** POST
* **URL:** `[http://127.0.0.1:8001/shipments/]`
* **Body (JSON):**
```json
{
  "origin_zip": "90210",
  "dest_zip": "10118",
  "weight_kg": 2.5,
  "dimensions": {"length": 30.0, "width": 25.5, "height": 10.0},
  "client_name": "Juan Perez",
  "client_phone": "+15551234567",
  "signature_required": true,
  "hazmat": false
}

```

* **Respuesta esperada:** Inmediatamente obtendrás un HTTP 202 con `"status": "pending"`. Revisa la terminal donde corre tu docker-compose; verás los logs del `fedex_celery_worker` procesando el PDF en segundo plano.

**4. Programación de Recolección (A mitad del día)**
Tienes 50 paquetes listos en el andén. En lugar de llamar por teléfono, el sistema le avisa al camión de FedEx Ground o Express que pase a buscar carga.

* **Método:** POST
* **URL:** `[http://127.0.0.1:8001/pickup/]`
* **Body (JSON):**
```json
{
  "location_zip": "90210",
  "total_weight": 125.5,
  "package_count": 50
}

```

* **Respuesta esperada:** Un JSON confirmando la programación y un número de confirmación de recolección (`confirmation`).

**5. Rastreo Automático (Telemetría de Webhooks)**
El endpoint síncrono GET `/track/` desaparece del flujo. Ahora FedEx empuja los datos hacia ti. Para simular que el servidor de FedEx contacta a tu microservicio, haz esta petición:

* **Método:** POST
* **URL:** `[http://127.0.0.1:8001/webhooks/fedex]`
* **Body (JSON):**
```json
{
  "trackResults": [
    {
      "trackingNumberInfo": {"trackingNumber": "777748178880"},
      "latestStatusDetail": {"derivedStatusCode": "IT"}
    }
  ]
}

```

* **Comportamiento:** Tu base de datos PostgreSQL actualizará silenciosamente el estado de ese paquete a "In Transit".

**6. Cierre de Operaciones (Al final del turno)**
Para envíos terrestres (FedEx Ground), es un requerimiento legal transmitir un manifiesto consolidado con todos los paquetes del día antes de que el camión se retire.

* **Método:** POST
* **URL:** `[http://127.0.0.1:8001/end-of-day/]`
* **Body (JSON):**
```json
{
  "location_id": "WH-VINA-01",
  "date": "2026-11-04"
}

```

* **Respuesta esperada:** Un JSON con el estatus y la URL del PDF del manifiesto generado.

**7. Logística Inversa (Post-Venta)**
Si días después el cliente "Juan Perez" solicita una devolución, generas una etiqueta especial con caducidad dinámica.

* **Método:** POST
* **URL:** `[http://127.0.0.1:8001/returns/]`
* **Body (JSON):**
```json
{
  "original_tracking": "777748178880",
  "reason": "Damaged in transit"
}

```

* **Respuesta esperada:** ID del RMA y la nueva etiqueta de retorno.
