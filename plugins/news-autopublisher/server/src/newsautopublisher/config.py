"""Chargement de config.yaml (projets, canaux, voix, vidéo) et des secrets (.env)."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .paths import Paths, package_file

HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


class ConfigError(Exception):
    """Configuration absente ou invalide (message destiné à l'utilisateur)."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaptureConfig(_Model):
    # auto : OBS si joignable, sinon capture ffmpeg de la fenêtre (Windows).
    backend: Literal["auto", "obs", "gdigrab", "ddagrab"] = "auto"
    window_title: str | None = None  # sous-chaîne du titre de la fenêtre du jeu / de l'éditeur
    obs_scene: str | None = None  # scène OBS à activer avant capture
    monitor: int = 0  # écran pour ddagrab
    fps: int = 30


class BrandConfig(_Model):
    color: str = "#7C5CFF"  # couleur principale (fonds, embed Discord)
    accent: str = "#FFD166"  # mot surligné dans les sous-titres
    background: str = "#0E0B1A"
    logo: str | None = None  # PNG (transparent de préférence) pour l'outro
    music: str | None = None  # fichier ou dossier de musiques libres de droits
    music_volume: float = 0.18

    @field_validator("color", "accent", "background")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not HEX_COLOR.match(v):
            raise ValueError("couleur attendue au format #RRGGBB")
        return v.upper()


class ProjectVoice(_Model):
    engine: Literal["piper", "elevenlabs", "recorded", "none"] | None = None
    voices: dict[str, str] = Field(default_factory=dict)  # langue -> voix (Piper ou id ElevenLabs)


class ProjectConfig(_Model):
    name: str
    repo_path: str | None = None
    engine: Literal["unity", "unreal", "web", "other"] = "other"
    languages: list[str] = Field(default_factory=lambda: ["fr"])
    pitch: dict[str, str] = Field(default_factory=dict)  # langue -> présentation courte du projet
    tone: str = ""
    audience: str = ""
    links: dict[str, str] = Field(default_factory=dict)
    hashtags: list[str] = Field(default_factory=list)
    changelog: str | None = None  # chemin relatif au dépôt
    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    brand: BrandConfig = Field(default_factory=BrandConfig)
    voice: ProjectVoice = Field(default_factory=ProjectVoice)
    channels: dict[str, list[str]] = Field(default_factory=dict)  # langue -> ids de canaux


class ChannelConfig(_Model):
    type: Literal["discord_webhook", "x", "youtube"]
    label: str | None = None
    # Discord
    webhook_env: str | None = None  # nom de la variable du .env contenant l'URL du webhook
    mention: str | None = None  # ex. "@everyone" ou "<@&ID_DU_ROLE>" ; vide = aucune notification
    username: str | None = None
    avatar_url: str | None = None
    max_upload_mb: float = 10.0
    # X / YouTube
    mode: Literal["intent", "api", "manual"] | None = None
    monthly_budget_usd: float = 0.0
    handle: str | None = None  # @compte (affichage dans la prévisualisation)

    @property
    def platform(self) -> str:
        return {"discord_webhook": "discord", "x": "x", "youtube": "youtube"}[self.type]

    @property
    def effective_mode(self) -> str:
        if self.type == "discord_webhook":
            return "api"
        if self.mode:
            return self.mode
        return "intent" if self.type == "x" else "manual"


class VoiceConfig(_Model):
    default_engine: Literal["piper", "elevenlabs", "recorded", "none"] = "piper"
    piper: dict[str, str] = Field(
        default_factory=lambda: {"fr": "fr_FR-siwis-medium", "en": "en_US-lessac-medium"}
    )
    piper_length_scale: float = 1.0  # > 1 = plus lent
    sentence_pause: float = 0.28
    elevenlabs_model: str = "eleven_multilingual_v2"
    elevenlabs_key_env: str = "ELEVENLABS_API_KEY"
    elevenlabs_voice_env: str = "ELEVENLABS_VOICE_ID"
    whisper_model: str = "small"


class OBSConfig(_Model):
    enabled: bool = True
    host: str = "localhost"
    port: int = 4455
    password_env: str = "OBS_WEBSOCKET_PASSWORD"
    timeout: float = 3.0


class VideoConfig(_Model):
    ffmpeg: str | None = None  # chemin de ffmpeg si absent du PATH
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 20
    preset: str = "medium"
    max_seconds: float = 60.0


class AppConfig(_Model):
    projects: dict[str, ProjectConfig] = Field(default_factory=dict)
    channels: dict[str, ChannelConfig] = Field(default_factory=dict)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    obs: OBSConfig = Field(default_factory=OBSConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)

    def project(self, key: str) -> ProjectConfig:
        if key not in self.projects:
            known = ", ".join(sorted(self.projects)) or "aucun"
            raise ConfigError(f"Projet inconnu « {key} ». Projets configurés : {known}.")
        return self.projects[key]

    def channel(self, key: str) -> ChannelConfig:
        if key not in self.channels:
            raise ConfigError(f"Canal inconnu « {key} » (section channels de config.yaml).")
        return self.channels[key]

    def channels_for(self, project: str, language: str) -> list[str]:
        return list(self.project(project).channels.get(language, []))


def load_config(paths: Paths) -> AppConfig:
    """Lit config.yaml et charge le .env dans l'environnement (sans écraser l'existant)."""
    if paths.env_file.exists():
        load_dotenv(paths.env_file, override=False)
    if not paths.config_file.exists():
        raise ConfigError(
            f"Configuration introuvable : {paths.config_file}. "
            "Appelle l'outil init_config pour créer le dossier et un exemple à compléter."
        )
    try:
        raw = yaml.safe_load(paths.config_file.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"config.yaml illisible : {exc}") from exc
    try:
        cfg = AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"config.yaml invalide :\n{exc}") from exc
    for pkey, proj in cfg.projects.items():
        for lang, chans in proj.channels.items():
            for ch in chans:
                if ch not in cfg.channels:
                    raise ConfigError(
                        f"Projet « {pkey} » ({lang}) : canal « {ch} » absent de la section channels."
                    )
    return cfg


class ConfigCache:
    """Recharge la configuration quand config.yaml ou .env changent (pas besoin de redémarrer)."""

    def __init__(self, paths: Paths):
        self.paths = paths
        self._stamp: tuple[float, float] | None = None
        self._cfg: AppConfig | None = None

    def _mtimes(self) -> tuple[float, float]:
        def m(p: Path) -> float:
            return p.stat().st_mtime if p.exists() else 0.0

        return (m(self.paths.config_file), m(self.paths.env_file))

    def get(self) -> AppConfig:
        stamp = self._mtimes()
        if self._cfg is None or stamp != self._stamp:
            self._cfg = load_config(self.paths)
            self._stamp = stamp
        return self._cfg


def get_secret(name: str | None) -> str | None:
    if not name:
        return None
    value = os.environ.get(name, "").strip()
    return value or None


def init_data_dir(paths: Paths) -> list[str]:
    """Crée le dossier de données et copie les exemples s'ils n'existent pas. Renvoie les fichiers créés."""
    paths.ensure()
    created = []
    for src_name, dst in (("config.example.yaml", paths.config_file), ("env.example", paths.env_file)):
        if not dst.exists():
            shutil.copyfile(package_file("templates", src_name), dst)
            created.append(str(dst))
    return created
