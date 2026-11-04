"""Modèles des brouillons de news et des résultats de publication."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DraftStatus = Literal["draft", "approved", "partial", "published", "discarded"]
PublicationStatus = Literal["published", "pending_manual", "dry_run", "failed", "skipped"]


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiscordPost(_Model):
    """Message Discord : texte libre + un embed (titre, corps Markdown, lien, image)."""

    content: str = Field("", description="Texte au-dessus de l'embed (court, facultatif).")
    title: str | None = Field(None, description="Titre de l'embed (≤ 256 caractères).")
    description: str | None = Field(None, description="Corps Markdown de l'embed (≤ 4096).")
    url: str | None = Field(None, description="Lien cliquable du titre.")
    color: str | None = Field(None, description="#RRGGBB ; par défaut la couleur du projet.")
    image: str | None = Field(None, description="Chemin d'une image affichée dans l'embed.")
    attachments: list[str] = Field(default_factory=list, description="Autres fichiers à joindre.")
    attach_short: bool = Field(True, description="Joindre la version Discord du short s'il existe.")


class XPost(_Model):
    text: str = Field(..., description="Texte du post (≤ 280, une URL compte 23).")
    url: str | None = Field(None, description="Lien ajouté à la fin du post (compte 23 + 1).")
    media: list[str] = Field(default_factory=list, description="Images / vidéo à joindre.")
    attach_short: bool = Field(True, description="Proposer le short comme média.")


class YouTubePost(_Model):
    title: str = Field(..., description="Titre (≤ 100 caractères, sans < ni >).")
    description: str = Field("", description="Description (liens, hashtags dont #Shorts).")
    tags: list[str] = Field(default_factory=list)
    privacy: Literal["public", "unlisted", "private"] = "public"
    made_for_kids: bool = False
    publish_at: str | None = Field(
        None, description="Mise en ligne programmée (ISO 8601, ex. 2026-11-20T17:00:00Z) ; mode API uniquement."
    )
    contains_synthetic_media: bool | None = Field(
        None, description="Déclaration YouTube de contenu réaliste modifié ou synthétique (ex. voix clonée)."
    )


class DraftPosts(_Model):
    discord: DiscordPost | None = None
    x: XPost | None = None
    youtube: YouTubePost | None = None


class Word(_Model):
    text: str
    start: float
    end: float


class VoiceInfo(_Model):
    engine: str
    audio_path: str
    duration: float
    script: str
    alignment: str = "estimated"  # estimated | silences | whisper | provider
    words: list[Word] = Field(default_factory=list)


class ShortInfo(_Model):
    path: str | None = None
    discord_path: str | None = None
    duration: float | None = None
    storyboard: dict | None = None
    voice: VoiceInfo | None = None
    rendered_at: str | None = None


class Issue(_Model):
    level: Literal["error", "warning"]
    platform: str
    field: str
    message: str


class Draft(_Model):
    id: str
    project: str
    language: str
    topic: str
    status: DraftStatus = "draft"
    group: str | None = None  # id du brouillon principal : une nouveauté = un groupe (une langue par brouillon)
    channels: list[str] = Field(default_factory=list)
    posts: DraftPosts = Field(default_factory=DraftPosts)
    short: ShortInfo = Field(default_factory=ShortInfo)
    head_commit: str | None = None
    notes: str = ""
    issues: list[Issue] = Field(default_factory=list)
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)
    approved_at: str | None = None


class ProceduralShot(_Model):
    """Plan de caméra généré automatiquement autour d'un objet (Unity) ou d'un acteur (Unreal)."""

    name: str = Field(..., description="Nom unique du plan (devient le nom du média).")
    target: str = Field(..., description="Nom du GameObject Unity ou libellé de l'acteur Unreal à montrer.")
    move: Literal["orbit", "dolly", "pullback", "flyover", "static", "follow"] = Field(
        "orbit",
        description="orbit : tour autour ; dolly : avance vers ; pullback : recul révélant le décor ; "
                    "flyover : survol en hauteur ; static : quasi fixe ; follow : poursuite (Unity uniquement).",
    )
    duration: float = Field(5.0, ge=1.0, le=30.0)
    distance: float = Field(1.0, ge=0.3, le=10.0, description="1 = l'objet remplit le cadre ; 2 = plus large.")
    elevation: float = Field(15.0, ge=-60.0, le=85.0, description="Hauteur de la caméra en degrés.")
    angle: float = Field(25.0, ge=-180.0, le=180.0, description="Décalage par rapport à l'avant de l'objet.")
    arc: float = Field(90.0, gt=0.0, le=360.0, description="Amplitude de l'orbite en degrés.")
    fov: float = Field(0.0, ge=0.0, le=120.0, description="Unity : champ de vision (0 = caméra principale).")
    focal_length: float = Field(0.0, ge=0.0, le=300.0, description="Unreal : focale en mm (0 = 24 mm).")
    map: str | None = Field(None, description="Unreal : map de l'acteur, si différente de celle par défaut.")


class PublishResult(_Model):
    channel: str
    platform: str
    status: PublicationStatus
    url: str | None = None
    external_id: str | None = None
    message: str = ""
    cost_usd: float = 0.0
