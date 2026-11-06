# Autenticación y Seguridad JWT (JSON Web Tokens)

Este documento explica cómo funciona la seguridad en el microservicio logístico de FedEx, cómo crear o cambiar las credenciales (`username` y `password`), cómo generar el hash criptográfico seguro con `bcrypt`, y cómo solicitar el token JWT desde Postman.

---

## 1. Arquitectura de Autenticación

El microservicio utiliza autenticación basada en **JWT (JSON Web Tokens)** con el estándar **OAuth2 (Password Flow)**:

- **Cuenta de Servicio (Service Account):** Las credenciales no se almacenan en tablas de base de datos para usuarios comunes, sino como variables de entorno seguras en el archivo `.env`.
- **Cifrado unidireccional (Bcrypt):** La contraseña nunca se guarda en texto plano; se guarda únicamente su *hash* criptográfico generado mediante la librería `passlib[bcrypt]`.
- **Aislamiento Multi-tenant (SaaS):** Al solicitar el token, además de `username` y `password`, se envía obligatoriamente el `store_id` (tienda o tenant). El token JWT resultante llevará ese `store_id` firmado en su payload, blindando todos los endpoints protegidos contra accesos entre tiendas.

---

## 2. Cómo Crear o Modificar el Usuario y la Contraseña

Para definir un nuevo usuario o cambiar la contraseña de acceso, se deben seguir estos pasos:

### Paso 1: Generar el Hash de la Contraseña

Para transformar la contraseña en texto plano en un hash seguro de `bcrypt`, ejecuta el siguiente comando en tu terminal (sustituye `TuContraseñaSegura123` por la clave que desees asignar):

#### Opción A (Recomendada: Directo en Docker)
```bash
docker compose exec fedex_api python -c "from auth import hash_password; print(hash_password('TuContraseñaSegura123'))"
```

#### Opción B (Con entorno virtual local activo)
```bash
python -c "from auth import hash_password; print(hash_password('TuContraseñaSegura123'))"
```

#### Opción C (Mediante un script Python)
Si prefieres crear un archivo ejecutable temporal (ej. `generar_clave.py`):
```python
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
clave = "TuContraseñaSegura123"
print(pwd_context.hash(clave))
```

**Resultado:**
La terminal imprimirá una cadena que empieza por `$2b$...`, similar a esta:
```text
$2b$12$KeZBXiE6o7gZjlJXdBa42OUuZdf23wj5FxwL0wMMc134jaj0CGEZu
```
Copia esa cadena completa.

---

### Paso 2: Actualizar el Archivo `.env`

Abre tu archivo `.env` en la raíz del proyecto y actualiza las variables de autenticación:

```env
# Seguridad JWT
SECRET_KEY=1d2ca089afcb956ba205e42a4c9b9921b014cfab09e568f07535d1a91eb76390
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Credenciales de Servicio
AUTH_USERNAME=tu_nuevo_usuario
AUTH_PASSWORD_HASH='$2b$12$PEGA_AQUI_EL_HASH_QUE_COPIASTE'
```

> **IMPORTANTE (Regla de Oro):** El valor de `AUTH_PASSWORD_HASH` debe ir obligatoriamente entre **comillas simples (`'...'`)**. El hash contiene múltiples caracteres `$`, y sin comillas simples, Docker y la terminal (Bash/Zsh) intentarán interpretarlos como variables de entorno vacías, corrompiendo la contraseña.

---

### Paso 3: Aplicar Cambios (Reiniciar el Contenedor)

Para que FastAPI recargue las variables de entorno del `.env`:

```bash
docker compose restart fedex_api
```

---

## 3. Cómo Obtener el Token JWT en Postman

Una vez configuradas las credenciales, sigue estos pasos para autenticarte:

1. **Método HTTP:** `POST`
2. **URL:** `http://localhost:8001/auth/token`
3. **Pestaña Body:** Selecciona la opción **`x-www-form-urlencoded`**.
4. **Parámetros requeridos:**

| Key | Value | Descripción |
| :--- | :--- | :--- |
| `username` | `tu_nuevo_usuario` | El usuario configurado en `AUTH_USERNAME` |
| `password` | `TuContraseñaSegura123` | La contraseña en texto plano |
| `store_id` | `1` | ID numérico de la tienda (debe existir en la tabla `stores`) |

5. Haz clic en **Send**.

### Ejemplo de Respuesta Exitosa (`200 OK`):
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0NGludmVudG9yeSIsInN0b3JlX2lkIjoxLCJpYXQiOjE3MDk4MjY0MDAsImV4cCI6MTcwOTgyODIwMH0...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

---

## 4. Uso del Token en los Endpoints Protegidos

Copia el valor del campo `access_token` recibido y agrégalo en las siguientes peticiones (cotizaciones, envíos, pickup, etc.):

1. En Postman, dirígete a la pestaña **Headers** de tu petición.
2. Agrega la cabecera:
   - **Key:** `Authorization`
   - **Value:** `Bearer <tu_access_token>`
3. O bien, ve a la pestaña **Authorization**, selecciona el tipo **Bearer Token** y pega el token en el campo correspondiente.

---

## 5. Generación de una Clave Secreta Fuerte (`SECRET_KEY`)

Para la firma criptográfica de los tokens en producción, se recomienda generar una clave aleatoria de 256 bits:

```bash
openssl rand -hex 32
```
Copia el string resultante y asígnalo a `SECRET_KEY` en tu archivo `.env`.