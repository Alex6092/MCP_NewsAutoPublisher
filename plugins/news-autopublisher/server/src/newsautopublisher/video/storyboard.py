"""Storyboard d'un short : suite de scènes + options audio."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_DURATION = {"title": 2.2, "text": 2.6, "image": 3.2, "clip": 4.0, "outro": 3.0}


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["title", "clip", "image", "text", "outro"] = Field(
        ..., description="title/text/outro : grand texte centré ; clip : vidéo ; image : capture animée."
    )
    media: str | None = Field(
        None, description="Chemin ou id de média (m…) : clip/image obligatoires, fond facultatif pour title/text/outro."
    )
    start: float = Field(0.0, ge=0, description="Point d'entrée dans le clip (secondes).")
    duration: float | None = Field(None, gt=0, le=60, description="Durée de la scène (défaut selon le type).")
    text: str | None = Field(None, description="Texte principal (bandeau du haut pour clip/image).")
    subtext: str | None = Field(None, description="Ligne secondaire (ex. lien ou appel à l'action).")
    fit: Literal["contain", "cover"] = Field(
        "contain", description="contain : image entière sur fond flouté ; cover : recadrée plein écran."
    )
    zoom: float = Field(1.0, ge=1.0, le=2.5, description="Grossissement du média en mode contain.")
    ken_burns: float = Field(0.08, ge=0, le=0.4, description="Zoom lent sur les images (0 = fixe).")


class Storyboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str | None = Field(None, description="Bandeau du haut par défaut sur les scènes clip/image.")
    scenes: list[Scene] = Field(..., min_length=1)
    captions: bool = Field(True, description="Sous-titres mot à mot de la voix off.")
    voice_offset: float = Field(0.35, ge=0, le=5, description="Délai avant le début de la voix (s).")
    tail: float = Field(0.8, ge=0, le=5, description="Marge après la fin de la voix (s).")
    music: str | None = Field(None, description="Chemin d'une musique, 'none' pour aucune ; défaut : celle du projet.")
    music_volume: float | None = Field(None, ge=0, le=1)
    fit_to_voice: bool = Field(True, description="Allonge les scènes pour couvrir toute la voix off.")
