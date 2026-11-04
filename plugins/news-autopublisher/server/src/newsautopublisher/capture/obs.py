"""Pilotage d'OBS Studio via obs-websocket (intégré à OBS 28+)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..config import OBSConfig, get_secret
from .windows import CaptureError


class OBS:
    def __init__(self, cfg: OBSConfig):
        self.cfg = cfg
        self._client: Any = None

    def connect(self) -> "OBS":
        if not self.cfg.enabled:
            raise CaptureError("OBS est désactivé dans config.yaml (obs.enabled).")
        try:
            import obsws_python as obsws
        except ImportError as exc:  # pragma: no cover
            raise CaptureError("Le paquet obsws-python n'est pas installé.") from exc
        try:
            self._client = obsws.ReqClient(
                host=self.cfg.host,
                port=self.cfg.port,
                password=get_secret(self.cfg.password_env) or "",
                timeout=self.cfg.timeout,
            )
        except Exception as exc:
            raise CaptureError(
                f"OBS injoignable sur {self.cfg.host}:{self.cfg.port} ({exc.__class__.__name__}). "
                "Lance OBS et active Outils > Paramètres du serveur WebSocket."
            ) from exc
        return self

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None

    def __enter__(self) -> "OBS":
        return self.connect()

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _send(self, request: str, data: dict | None = None) -> dict:
        try:
            return self._client.send(request, data, raw=True) or {}
        except Exception as exc:
            raise CaptureError(f"OBS a refusé {request} : {exc}") from exc

    def current_scene(self) -> str:
        data = self._send("GetCurrentProgramScene")
        return data.get("sceneName") or data.get("currentProgramSceneName") or ""

    def set_scene(self, scene: str | None) -> None:
        if scene:
            self._send("SetCurrentProgramScene", {"sceneName": scene})
            time.sleep(0.3)

    def screenshot(self, out: Path, scene: str | None = None) -> Path:
        self.set_scene(scene)
        source = scene or self.current_scene()
        out.parent.mkdir(parents=True, exist_ok=True)
        self._send(
            "SaveSourceScreenshot",
            {"sourceName": source, "imageFormat": "png", "imageFilePath": str(out.resolve()),
             "imageCompressionQuality": 100},
        )
        for _ in range(20):  # OBS écrit le fichier de façon asynchrone
            if out.exists() and out.stat().st_size > 0:
                break
            time.sleep(0.1)
        return out

    def start_record(self, scene: str | None = None) -> None:
        self.set_scene(scene)
        status = self._send("GetRecordStatus")
        if status.get("outputActive"):
            raise CaptureError("OBS enregistre déjà : arrête l'enregistrement en cours d'abord.")
        self._send("StartRecord")

    def stop_record(self) -> Path:
        data = self._send("StopRecord")
        path = data.get("outputPath")
        if not path:
            raise CaptureError("OBS n'a pas renvoyé le chemin de l'enregistrement.")
        return Path(path)

    def save_replay(self) -> Path:
        status = self._send("GetReplayBufferStatus")
        if not status.get("outputActive"):
            raise CaptureError(
                "Le tampon de relecture d'OBS n'est pas actif (bouton « Démarrer le tampon de relecture »)."
            )
        self._send("SaveReplayBuffer")
        time.sleep(1.0)
        data = self._send("GetLastReplayBufferReplay")
        path = data.get("savedReplayPath")
        if not path:
            raise CaptureError("OBS n'a pas renvoyé le chemin du replay.")
        return Path(path)
