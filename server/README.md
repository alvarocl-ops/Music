# Trop AI Karaoke Server (Demucs)

Servidor de separación de stems de audio mediante inteligencia artificial (Meta HTDemucs) para la app iOS **Trop**.

Permite separar cualquier canción de YouTube Music en:
1. **Instrumental limpio** (0% voz, sin ecos ni artefactos de cancelación de fase).
2. **Pista vocal aislada**.
3. **Flujo Quad (4 canales)** que permite al deslizador de la app Trop subir y bajar el volumen de la voz en tiempo real con calidad de estudio.

---

## Opciones de Despliegue

### Opción 1: Hugging Face Spaces (100% GRATIS con GPU)
1. Ve a [Hugging Face Spaces](https://huggingface.co/spaces) y crea un nuevo Space.
2. Selecciona **Docker** como SDK y **Blank**.
3. Sube los archivos de esta carpeta (`Dockerfile`, `requirements.txt`, `main.py`).
4. En Settings del Space, activa **ZeroGPU** (aceleración GPU gratuita de NVIDIA).
5. Copia la URL pública directa de tu Space (ejemplo: `https://tu-usuario-trop-karaoke.hf.space`).
6. En Trop en tu iPhone: ve a **Settings → Player → Karaoke IA** y pega la URL.

### Opción 2: Docker Local (en tu PC / Mac / Servidor Casero)
Si tienes un ordenador en casa en la misma red Wi-Fi:
```bash
cd server
docker compose up -d --build
```
El servidor escuchará en el puerto `8000`.
En tu iPhone conectado al mismo Wi-Fi, pon la IP local de tu ordenador:
`http://192.168.1.XX:8000`

### Opción 3: Railway / Fly.io / VPS
Puedes conectar este repositorio a Railway o Fly.io seleccionando el Dockerfile de la carpeta `server`.

---

## Endpoints de la API

- `GET /api/health` — Comprueba el estado del servidor y si tiene GPU disponible.
- `POST /api/separate` — Recibe `{"video_id": "...", "title": "...", "artist": "..."}` e inicia la separación en segundo plano.
- `GET /api/stems/{video_id}` — Devuelve el estado (`ready`, `processing`, `error`), porcentaje de progreso y las URLs de los stems.
- `GET /stems/{video_id}/quad.m4a` — Archivo de 4 canales utilizado por Trop para mezclar instrumental + voz en vivo.
