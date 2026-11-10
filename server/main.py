import os
import sys
import shutil
import asyncio
import subprocess
from pathlib import Path
from typing import Dict, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="Trop AI Karaoke Stem Separation Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
STEMS_DIR = BASE_DIR / "stems"
CACHE_DIR = BASE_DIR / "cache"
STEMS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Tracks ongoing jobs: video_id -> {"status": ..., "progress": ..., "error": ...}
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

def process_separation_sync(video_id: str, title: Optional[str], artist: Optional[str]):
    job_dir = get_job_dir(video_id)
    temp_dir = CACHE_DIR / f"temp_{video_id}"
    
    try:
        jobs[video_id] = {"status": "processing", "progress": 10, "message": "Descargando audio..."}
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        job_dir.mkdir(parents=True, exist_ok=True)

        input_audio = temp_dir / "input.m4a"
        yt_url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Download highest quality audio using yt-dlp
        dl_cmd = [
            "yt-dlp",
            "-f", "bestaudio[ext=m4a]/bestaudio/best",
            "-x",
            "--audio-format", "m4a",
            "--audio-quality", "0",
            "-o", str(input_audio),
            yt_url
        ]
        res = subprocess.run(dl_cmd, capture_output=True, text=True)
        if res.returncode != 0 or not input_audio.exists():
            # If m4a extension didn't match exactly, find any audio file downloaded
            found = list(temp_dir.glob("input.*"))
            if found:
                input_audio = found[0]
            else:
                raise RuntimeError(f"Error descargando pista de YouTube: {res.stderr[:200]}")

        jobs[video_id] = {"status": "processing", "progress": 35, "message": "Separando voz con IA (Demucs)..."}

        # Run Demucs 2-stems (vocals + no_vocals)
        # Using htdemucs model (high quality, fast)
        demucs_out = temp_dir / "demucs_out"
        demucs_cmd = [
            "demucs",
            "--two-stems=vocals",
            "-n", "htdemucs",
            "-o", str(demucs_out),
            str(input_audio)
        ]
        res_demucs = subprocess.run(demucs_cmd, capture_output=True, text=True)
        if res_demucs.returncode != 0:
            raise RuntimeError(f"Demucs fallo: {res_demucs.stderr[:200]}")

        jobs[video_id] = {"status": "processing", "progress": 80, "message": "Codificando pistas de audio..."}

        # Locate separated stems
        stem_track_dir = list(demucs_out.glob("htdemucs/*"))
        if not stem_track_dir:
            raise RuntimeError("No se encontraron los stems generados por Demucs.")
        target_dir = stem_track_dir[0]
        
        vocals_wav = target_dir / "vocals.wav"
        no_vocals_wav = target_dir / "no_vocals.wav"
        
        if not vocals_wav.exists() or not no_vocals_wav.exists():
            raise RuntimeError("Faltan archivos vocals.wav o no_vocals.wav")

        # Encode instrumental.m4a
        subprocess.run([
            "ffmpeg", "-y", "-i", str(no_vocals_wav),
            "-c:a", "aac", "-b:a", "256k",
            str(job_dir / "instrumental.m4a")
        ], check=True, capture_output=True)

        # Encode vocals.m4a
        subprocess.run([
            "ffmpeg", "-y", "-i", str(vocals_wav),
            "-c:a", "aac", "-b:a", "256k",
            str(job_dir / "vocals.m4a")
        ], check=True, capture_output=True)

        # Merge into 4-channel quad.m4a (ch0,1: instrumental, ch2,3: vocals)
        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(no_vocals_wav),
            "-i", str(vocals_wav),
            "-filter_complex", "[0:a][1:a]amerge=inputs=2[aout]",
            "-map", "[aout]",
            "-c:a", "aac", "-b:a", "320k",
            str(job_dir / "quad.m4a")
        ], check=True, capture_output=True)

        jobs[video_id] = {"status": "ready", "progress": 100, "message": "Separación completada con éxito."}

    except Exception as e:
        jobs[video_id] = {"status": "error", "progress": 0, "message": str(e)}
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

@app.get("/api/health")
def health():
    import torch
    return {
        "status": "ok",
        "service": "Trop AI Karaoke Server",
        "cuda_available": torch.cuda.is_available(),
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "active_jobs": len(jobs)
    }

@app.get("/api/stems/{video_id}")
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

    return {"status": "not_found", "message": "Pista no procesada aún"}

@app.post("/api/separate")
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

    jobs[video_id] = {"status": "processing", "progress": 5, "message": "En cola para separación..."}
    bg.add_task(process_separation_sync, video_id, req.title, req.artist)
    return jobs[video_id]

@app.get("/stems/{video_id}/{filename}")
def serve_stem(video_id: str, filename: str):
    file_path = get_job_dir(video_id) / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(file_path, media_type="audio/mp4")

@app.get("/", response_class=HTMLResponse)
def dashboard():
    separated_count = len([d for d in STEMS_DIR.iterdir() if d.is_dir() and (d / "quad.m4a").is_file()])
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Trop AI Karaoke Server</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f1015; color: #fff; margin: 0; padding: 40px 20px; display: flex; justify-content: center; }}
            .container {{ max-width: 650px; width: 100%; background: #1a1c23; padding: 32px; border-radius: 16px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }}
            h1 {{ margin-top: 0; color: #38bdf8; font-size: 26px; }}
            .badge {{ display: inline-block; padding: 4px 10px; border-radius: 999px; background: #0284c7; color: white; font-size: 13px; font-weight: 600; margin-bottom: 20px; }}
            p {{ line-height: 1.6; color: #94a3b8; }}
            .stat {{ background: #262936; border-radius: 12px; padding: 18px; margin: 20px 0; display: flex; justify-content: space-between; align-items: center; }}
            .stat-num {{ font-size: 28px; font-weight: bold; color: #38bdf8; }}
            code {{ background: #0f1015; padding: 3px 8px; border-radius: 6px; font-family: monospace; color: #f43f5e; }}
        </style>
    </head>
    <body>
        <div class="container">
            <span class="badge">● Online</span>
            <h1>Trop AI Karaoke Server</h1>
            <p>Servidor de separación de fuentes musicales (Stems) impulsado por <strong>Meta HTDemucs</strong> y <strong>FFmpeg</strong> para la app Trop iOS.</p>
            <div class="stat">
                <div><strong>Canciones separadas en caché:</strong><br><small style="color:#64748b">Listas para reproducción instantánea</small></div>
                <div class="stat-num">{separated_count}</div>
            </div>
            <p>Para usar este servidor en Trop iOS:</p>
            <ol style="color:#cbd5e1; line-height: 1.8;">
                <li>Abre Trop en tu iPhone.</li>
                <li>Ve a <strong>Settings → Player → Karaoke IA</strong>.</li>
                <li>Introduce la URL de este servidor y pulsa <em>Guardar</em>.</li>
            </ol>
        </div>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
