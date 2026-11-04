"""Localisation et appels de ffmpeg / ffprobe."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"}

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class FFmpegError(Exception):
    pass


def find_ffmpeg(configured: str | None = None) -> str:
    if configured:
        if Path(configured).exists():
            return configured
        raise FFmpegError(f"ffmpeg introuvable à l'emplacement configuré : {configured}")
    found = shutil.which("ffmpeg")
    if not found:
        raise FFmpegError(
            "ffmpeg est introuvable. Sous Windows : `winget install Gyan.FFmpeg`, puis redémarre "
            "Claude Code (ou renseigne video.ffmpeg dans config.yaml)."
        )
    return found


def find_ffprobe(ffmpeg: str) -> str:
    sibling = Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix)
    if sibling.exists():
        return str(sibling)
    found = shutil.which("ffprobe")
    if not found:
        raise FFmpegError("ffprobe est introuvable (il est normalement livré avec ffmpeg).")
    return found


def run(cmd: list[str], cwd: Path | None = None, timeout: float = 900) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_NO_WINDOW,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        raise FFmpegError(f"ffmpeg a échoué ({proc.returncode}) :\n{tail}")
    return proc


def probe(path: str | Path, ffprobe: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FFmpegError(f"Fichier introuvable : {p}")
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,duration",
         "-of", "json", str(p)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
    )
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe ne sait pas lire {p.name} : {proc.stderr.strip()[:200]}")
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration") or 0) or None
    ext = p.suffix.lower()
    if ext in IMAGE_EXT:
        kind = "image"
    elif video and (duration or 0) > 0.2 and ext not in AUDIO_EXT:
        kind = "video"
    elif audio:
        kind = "audio"
    else:
        kind = "image" if video else "other"
    return {
        "path": str(p),
        "kind": kind,
        "width": int(video["width"]) if video and video.get("width") else None,
        "height": int(video["height"]) if video and video.get("height") else None,
        "duration": duration if kind in ("video", "audio") else None,
        "has_audio": audio is not None,
        "video_codec": video.get("codec_name") if video else None,
        "audio_codec": audio.get("codec_name") if audio else None,
        "size_mb": round(int(data.get("format", {}).get("size") or p.stat().st_size) / 1024 / 1024, 2),
    }
