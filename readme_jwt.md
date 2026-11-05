Aquí tienes el contenido completo del README actualizado que incluye la sección de **cómo obtener el Bearer Token en Postman** basándose exactamente en la configuración visual de la interfaz:

---

### Cómo cambiar o crear un nuevo usuario y contraseña

Si necesitas actualizar el usuario y la contraseña de acceso en tu microservicio, el proceso se realiza directamente modificando el archivo `.env` y generando un nuevo código de cifrado (hash).

Sigue estos pasos en tu terminal:

#### Paso 1: Generar el hash de la nueva contraseña

Como el sistema almacena la contraseña de forma segura utilizando *bcrypt*, debes generar el código cifrado ejecutando el siguiente comando en la raíz de tu proyecto (reemplaza `TuNuevaContraseña123` por la clave que quieras usar):

```bash
.venv/bin/python -c "from auth import hash_password; print(hash_password('TuNuevaContraseña123'))"

```

Este comando te devolverá una cadena larga de texto que comienza con `$2b$...` (por ejemplo: `$2b$12$eXtp...`). Copia esa cadena completa.

#### Paso 2: Actualizar el archivo `.env`

Abre tu archivo `.env` en el editor de código (VS Code) y modifica los valores de usuario y contraseña con tus nuevos datos:

```env
# Seguridad JWT
SECRET_KEY=tu_clave_secreta_actual_de_64_caracteres
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Nuevas credenciales
AUTH_USERNAME=tu_nuevo_usuario
AUTH_PASSWORD_HASH='$2b$12$PEGA_AQUI_EL_HASH_QUE_COPIASTE'

```

> **Nota importante:** Asegúrate de envolver el hash copiado entre comillas simples (`'...'`) dentro del archivo `.env` para evitar que los símbolos especiales (como el signo pesos `$`) causen problemas de expansión en la terminal.

#### Paso 3: Reiniciar el servidor

Para que la aplicación de FastAPI detecte los cambios realizados en el archivo `.env`, debes reiniciar el servidor (si lo tienes corriendo localmente o mediante Docker):

* **Si corres con Uvicorn manual:** Presiona `Ctrl + C` en la terminal y vuelve a encenderlo con `.venv/bin/uvicorn main:app --reload`.
* **Si corres con Docker:** Ejecuta el reinicio de contenedores:
```bash
docker compose down
docker compose up --build

```



---

#### Paso 4: Obtener el Bearer Token en Postman

Una vez que el servidor esté activo con tus nuevas credenciales, realiza los siguientes pasos en Postman para autenticarte y obtener el token de acceso:

1. Crea una nueva petición de tipo **POST** y apunta a la URL: `[http://127.0.0.1:8001/auth/token](http://127.0.0.1:8001/auth/token)`.


2. Dirígete a la pestaña **Body** y marca la opción **`x-www-form-urlencoded`**.


3. Agrega los campos de autenticación en la tabla de parámetros:


* **Key:** `username` | **Value:** Tu nuevo usuario (`tu_nuevo_usuario`)


* **Key:** `password` | **Value:** Tu contraseña en texto plano




4. Haz clic en el botón azul **Send**.



Como respuesta del servidor obtendrás un objeto JSON con el `access_token`. Deberás copiar esa cadena de texto y enviarla en las subsiguientes peticiones protegidas dentro de la pestaña **Headers** utilizando la cabecera:

* **Key:** `Authorization`
* **Value:** `Bearer <tu_access_token_copiado>`