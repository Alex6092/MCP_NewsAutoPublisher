"""Capture d'écran / de fenêtre avec ffmpeg sous Windows (gdigrab ou ddagrab), sans OBS."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..ffmpeg import _NO_WINDOW, run
from .windows import CaptureError, WindowInfo, find_window, is_windows


def _even(n: int) -> int:
    return n - (n % 2)


def input_args(backend: str, window: WindowInfo | None, fps: int, monitor: int = 0) -> list[str]:
    if backend == "gdigrab":
        target = f"title={window.title}" if window else "desktop"
        return ["-f", "gdigrab", "-framerate", str(fps), "-draw_mouse", "1", "-i", target]
    if backend == "ddagrab":
        opts = [f"output_idx={monitor}", f"framerate={fps}", "draw_mouse=1"]
        if window:
            # ddagrab capture l'écran : on recadre sur le rectangle de la fenêtre (écran principal).
            opts += [f"offset_x={max(window.x, 0)}", f"offset_y={max(window.y, 0)}",
                     f"video_size={_even(window.width)}x{_even(window.height)}"]
        return ["-f", "lavfi", "-i", "ddagrab=" + ":".join(opts)]
    raise CaptureError(f"Méthode de capture inconnue : {backend}")


def _video_filter(backend: str) -> list[str]:
    base = "pad=ceil(iw/2)*2:ceil(ih/2)*2"
    if backend == "ddagrab":
        return ["-vf", f"hwdownload,format=bgra,{base}"]
    return ["-vf", base]


def screenshot(ffmpeg: str, out: Path, backend: str, window_title: str | None, monitor: int = 0) -> Path:
    if not is_windows():
        raise CaptureError("La capture directe d'écran est réservée à Windows : utilise OBS ou import_media.")
    window = find_window(window_title) if window_title else None
    out.parent.mkdir(parents=True, exist_ok=True)
    args = input_args(backend, window, 1, monitor)
    vf = ["-vf", "hwdownload,format=bgra"] if backend == "ddagrab" else []
    run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args, *vf, "-frames:v", "1", str(out)], timeout=30)
    return out


@dataclass
class Recording:
    id: str
    project: str
    backend: str
    output: Path
    window: str | None
    started: float = field(default_factory=time.time)
    process: subprocess.Popen | None = None  # None quand c'est OBS qui enregistre

    def stop(self, timeout: float = 15) -> Path:
        if self.process is None:
            return self.output
        if self.process.poll() is None:
            try:
                self.process.stdin.write(b"q")  # arrêt propre : ffmpeg finalise le MP4
                self.process.stdin.flush()
            except Exception:
                pass
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=5)
        if not self.output.exists() or self.output.stat().st_size == 0:
            err = b""
            try:
                err = self.process.stderr.read()[-800:] if self.process.stderr else b""
            except Exception:
                pass
            raise CaptureError("L'enregistrement est vide. " + err.decode("utf-8", "replace"))
        return self.output


def start_recording(
    ffmpeg: str,
    rec_id: str,
    project: str,
    out: Path,
    backend: str,
    window_title: str | None,
    fps: int,
    max_seconds: float,
    monitor: int = 0,
) -> Recording:
    if not is_windows():
        raise CaptureError("La capture directe d'écran est réservée à Windows : utilise OBS ou import_media.")
    window = find_window(window_title) if window_title else None
    out.parent.mkdir(parents=True, exist_ok=True)
    encoder = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p"]
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *input_args(backend, window, fps, monitor),
           "-t", f"{max_seconds:.0f}", *_video_filter(backend), *encoder, str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            creationflags=_NO_WINDOW)
    time.sleep(0.8)
    if proc.poll() is not None:
        err = proc.stderr.read().decode("utf-8", "replace")[-800:] if proc.stderr else ""
        raise CaptureError(f"ffmpeg n'a pas pu démarrer la capture ({backend}) : {err}")
    return Recording(rec_id, project, backend, out, window.title if window else None, process=proc)
