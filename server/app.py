import os
import sys

try:
    import spaces
    gpu_decorator = spaces.GPU(duration=120)
except Exception:
    def gpu_decorator(func):
        return func

import shutil
import asyncio
import subprocess
import re
from pathlib import Path
from typing import Dict, Optional
import torch
from fastapi import BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import gradio as gr

BASE_DIR = Path(__file__).resolve().parent
STEMS_DIR = BASE_DIR / "stems"
CACHE_DIR = BASE_DIR / "cache"
STEMS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

jobs: Dict[str, dict] = {}

class SeparateRequest(BaseModel):
    video_id: str
    title: Optional[str] = None
    artist: Optional[str] = None

def get_job_dir(video_id: str) -> Path:
    return STEMS_DIR / video_id

def stems_exist(video_id: str) -> bool:
    d = get_job_dir(video_id)
    return (d / "quad.m4a").is_file() and (d / "instrumental.m4a").is_file()

def process_separation_sync(video_id: str, title: Optional[str] = None, artist: Optional[str] = None):
    job_dir = get_job_dir(video_id)
    temp_dir = CACHE_DIR / f"temp_{video_id}"
    try:
        jobs[video_id] = {"status": "processing", "progress": 10, "message": "Descargando audio de YouTube..."}
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        job_dir.mkdir(parents=True, exist_ok=True)

        input_audio = temp_dir / "input.m4a"
        yt_url = f"https://www.youtube.com/watch?v={video_id}"

        dl_cmd = [
            "yt-dlp",
            "--extractor-args", "youtube:player_client=ios,android,web",
            "-f", "bestaudio[ext=m4a]/bestaudio/best",
            "-x",
            "--audio-format", "m4a",
            "--audio-quality", "0",
            "-o", str(input_audio),
            yt_url
        ]
        res = subprocess.run(dl_cmd, capture_output=True, text=True)
        if res.returncode != 0 or not input_audio.exists():
            found = list(temp_dir.glob("input.*"))
            if found:
                input_audio = found[0]
            else:
                raise RuntimeError(f"Error descargando pista de YouTube: {res.stderr[:200]}")

        jobs[video_id] = {"status": "processing", "progress": 35, "message": "Separando voz con IA (Demucs)..."}

        device = "cuda" if torch.cuda.is_available() else "cpu"
        demucs_out = temp_dir / "demucs_out"
        demucs_cmd = [
            "demucs",
            "-d", device,
            "--two-stems=vocals",
            "-n", "htdemucs",
            "-o", str(demucs_out),
            str(input_audio)
        ]
        res_demucs = subprocess.run(demucs_cmd, capture_output=True, text=True)
        if res_demucs.returncode != 0:
            raise RuntimeError(f"Demucs fallo: {res_demucs.stderr[:200]}")

        jobs[video_id] = {"status": "processing", "progress": 80, "message": "Codificando pistas de audio..."}

        stem_track_dir = list(demucs_out.glob("htdemucs/*"))
        if not stem_track_dir:
            raise RuntimeError("No se encontraron los stems generados por Demucs.")
        target_dir = stem_track_dir[0]

        vocals_wav = target_dir / "vocals.wav"
        no_vocals_wav = target_dir / "no_vocals.wav"

        if not vocals_wav.exists() or not no_vocals_wav.exists():
            raise RuntimeError("Faltan archivos vocals.wav o no_vocals.wav")

        subprocess.run([
            "ffmpeg", "-y", "-i", str(no_vocals_wav),
            "-c:a", "aac", "-b:a", "256k",
            str(job_dir / "instrumental.m4a")
        ], check=True, capture_output=True)

        subprocess.run([
            "ffmpeg", "-y", "-i", str(vocals_wav),
            "-c:a", "aac", "-b:a", "256k",
            str(job_dir / "vocals.m4a")
        ], check=True, capture_output=True)

        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(no_vocals_wav),
            "-i", str(vocals_wav),
            "-filter_complex", "[0:a][1:a]amerge=inputs=2[aout]",
            "-map", "[aout]",
            "-c:a", "aac", "-b:a", "320k",
            str(job_dir / "quad.m4a")
        ], check=True, capture_output=True)

        jobs[video_id] = {"status": "ready", "progress": 100, "message": "Separacion completada con exito."}

    except Exception as e:
        jobs[video_id] = {"status": "error", "progress": 0, "message": str(e)}
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

def get_cached_count():
    try:
        return len([d for d in STEMS_DIR.iterdir() if d.is_dir() and (d / "quad.m4a").is_file()])
    except Exception:
        return 0

@gpu_decorator
def web_separate(video_id_or_url: str):
    cleaned = video_id_or_url.strip()
    m = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", cleaned)
    video_id = m.group(1) if m else cleaned
    if not video_id:
        return "Introduce un ID o enlace de YouTube valido.", None, None
    process_separation_sync(video_id)
    if stems_exist(video_id):
        job_dir = get_job_dir(video_id)
        return (
            f"Separacion completada para {video_id}!",
            str(job_dir / "instrumental.m4a"),
            str(job_dir / "vocals.m4a")
        )
    else:
        err = jobs.get(video_id, {}).get("message", "Error desconocido")
        return f"Error: {err}", None, None

# Gradio Interface
with gr.Blocks(title="Trop AI Karaoke Server") as demo:
    gr.Markdown("# Trop AI Karaoke Server (Online)")
    gr.Markdown("Servidor de Inteligencia Artificial para separar voz e instrumentos en la app **Trop iOS**.")
    with gr.Row():
        gr.Markdown(f"**Estado:** Online | **Pistas en cache:** {get_cached_count()}")
    gr.Markdown("---")
    gr.Markdown("### Como conectarlo a Trop en tu iPhone:")
    gr.Markdown("""
    1. Abre **Trop** en tu iPhone.
    2. Ve a **Settings -> Player -> Karaoke & Separacion IA**.
    3. En **URL Servidor IA**, pega la URL de este Space (terminada en `.hf.space`).
    4. Activa **Separar con Servidor IA** y ajusta la barra de volumen de voz a tu gusto.
    """)
    gr.Markdown("---")
    gr.Markdown("### Prueba rapida desde el navegador:")
    with gr.Row():
        url_input = gr.Textbox(label="ID o URL de YouTube", placeholder="Ej: dQw4w9WgXcQ o enlace completo")
    with gr.Row():
        btn = gr.Button("Separar Audio", variant="primary")
    with gr.Row():
        out_msg = gr.Markdown()
    with gr.Row():
        out_inst = gr.Audio(label="Instrumental (Sin voz)")
        out_voc = gr.Audio(label="Voz Aislada (Acapella)")
    btn.click(fn=web_separate, inputs=[url_input], outputs=[out_msg, out_inst, out_voc])

# Attach FastAPI endpoints directly to demo.app
demo.app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@demo.app.get("/api/health")
def health():
    cuda_avail = torch.cuda.is_available()
    return {
        "status": "ok",
        "service": "Trop AI Karaoke Server",
        "cuda_available": cuda_avail,
        "device": "cuda" if cuda_avail else "cpu",
        "active_jobs": len(jobs)
    }

@demo.app.get("/api/stems/{video_id}")
def get_stems_status(video_id: str):
    if stems_exist(video_id):
        return {
            "status": "ready",
            "progress": 100,
            "quad_url": f"/stems/{video_id}/quad.m4a",
            "instrumental_url": f"/stems/{video_id}/instrumental.m4a",
            "vocals_url": f"/stems/{video_id}/vocals.m4a"
        }
    if video_id in jobs:
        job = jobs[video_id]
        return {
            "status": job.get("status", "processing"),
            "progress": job.get("progress", 0),
            "message": job.get("message", "")
        }
    return {"status": "not_found", "message": "Pista no procesada aun"}

@demo.app.post("/api/separate")
async def separate(req: SeparateRequest, bg: BackgroundTasks):
    video_id = req.video_id.strip()
    if not video_id:
        raise HTTPException(status_code=400, detail="video_id requerido")

    if stems_exist(video_id):
        return {
            "status": "ready",
            "progress": 100,
            "quad_url": f"/stems/{video_id}/quad.m4a",
            "instrumental_url": f"/stems/{video_id}/instrumental.m4a",
            "vocals_url": f"/stems/{video_id}/vocals.m4a"
        }

    if video_id in jobs and jobs[video_id].get("status") == "processing":
        return jobs[video_id]

    jobs[video_id] = {"status": "processing", "progress": 5, "message": "En cola para separacion..."}
    bg.add_task(process_separation_sync, video_id, req.title, req.artist)
    return jobs[video_id]

@demo.app.get("/stems/{video_id}/{filename}")
def serve_stem(video_id: str, filename: str):
    file_path = get_job_dir(video_id) / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(file_path, media_type="audio/mp4")

if __name__ == "__main__":
    demo.launch(ssr_mode=False)
