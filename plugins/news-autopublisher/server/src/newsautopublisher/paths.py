"""Emplacements du dossier de données (hors dépôts) et des ressources embarquées."""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path


def _default_root() -> Path:
    env = os.environ.get("NAP_DATA_DIR", "").strip()
    # Ignore une variable non substituée du type "${user_config.data_dir}".
    if env and "${" not in env:
        return Path(env).expanduser()
    return Path.home() / ".newsautopublisher"


@dataclass(frozen=True)
class Paths:
    root: Path

    @classmethod
    def default(cls) -> "Paths":
        return cls(_default_root())

    @property
    def config_file(self) -> Path:
        return self.root / "config.yaml"

    @property
    def env_file(self) -> Path:
        return self.root / ".env"

    @property
    def db(self) -> Path:
        return self.root / "state.db"

    @property
    def drafts(self) -> Path:
        return self.root / "drafts"

    @property
    def media(self) -> Path:
        return self.root / "media"

    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def credentials(self) -> Path:
        return self.root / "credentials"

    def draft_dir(self, draft_id: str) -> Path:
        return self.drafts / draft_id

    def media_dir(self, project: str) -> Path:
        return self.media / project

    def ensure(self) -> None:
        for p in (self.root, self.drafts, self.media, self.models, self.credentials):
            p.mkdir(parents=True, exist_ok=True)


def package_file(*parts: str) -> Path:
    """Chemin d'une ressource embarquée dans le paquet (gabarits, polices)."""
    ref = resources.files("newsautopublisher")
    for part in parts:
        ref = ref.joinpath(part)
    return Path(str(ref))


def fonts_dir() -> Path:
    return package_file("assets", "fonts")
