# Trop AI Karaoke Server (Demucs)

Servidor de separación de stems de audio mediante inteligencia artificial (Meta HTDemucs) para la app iOS **Trop**.

Permite separar cualquier canción de YouTube Music en:
1. **Instrumental limpio** (0% voz, sin ecos ni artefactos de cancelación de fase).
2. **Pista vocal aislada**.
3. **Flujo Quad (4 canales)** que permite al deslizador de la app Trop subir y bajar el volumen de la voz en tiempo real con calidad de estudio.

---

## Despliegue en la Nube (100% GRATIS en Hugging Face Spaces)

No necesitas tener tu ordenador encendido ni pagar nada:

1. En la pantalla de **Create a new Space** de Hugging Face:
   - **Space name:** ponle por ejemplo `trop-karaoke`
   - **License:** elige `mit` o déjalo vacío
   - **Select the Space SDK:** Deja seleccionado **Gradio**
   - **Choose a Gradio template:** Deja seleccionado **Blank**
   - **Space hardware:** Selecciona **CPU Basic** (gratis e ilimitado 24/7) o **ZeroGPU Free**
   - Haz clic en **Create Space** al final de la página.

2. En tu nuevo Space:
   - Haz clic en la pestaña **Files** → **Add file** → **Create a new file**.
   - Crea un archivo llamado `packages.txt` con el contenido:
     ```text
     ffmpeg
     ```
   - Crea un archivo llamado `requirements.txt` con el contenido de [requirements.txt](requirements.txt).
   - Crea un archivo llamado `app.py` con el contenido de [app.py](app.py).

3. Una vez creado el archivo, Hugging Face construirá el Space automáticamente en 1-2 minutos.
4. Tu URL directa será:
   `https://<tu-usuario>-trop-karaoke.hf.space`
5. En tu iPhone, abre Trop y ve a:
   **Ajustes → Reproductor → Karaoke & Separación IA**
   Pega esa URL en **URL Servidor IA** y activa **Separar con Servidor IA**.

---

## Opciones Alternativas de Despliegue

### Docker Local (en tu PC / Mac / Servidor Casero)
Si tienes un ordenador en casa en la misma red Wi-Fi:
```bash
cd server
docker compose up -d --build
```
El servidor escuchará en el puerto `8000`.
En tu iPhone conectado al mismo Wi-Fi, pon la IP local de tu ordenador:
`http://192.168.1.XX:8000`

---

## Endpoints de la API

- `GET /api/health` — Comprueba el estado del servidor y disponibilidad de aceleración.
- `POST /api/separate` — Recibe `{"video_id": "...", "title": "...", "artist": "..."}` e inicia la separación con Demucs.
- `GET /api/stems/{video_id}` — Devuelve el estado (`ready`, `processing`, `error`), porcentaje de progreso y las URLs de los stems.
- `GET /stems/{video_id}/quad.m4a` — Archivo de 4 canales utilizado por Trop para mezclar instrumental + voz en vivo.
