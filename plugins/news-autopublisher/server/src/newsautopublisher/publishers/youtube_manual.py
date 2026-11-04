"""YouTube en mode manuel : MP4 + métadonnées prêts, l'utilisateur glisse le fichier dans YouTube Studio.

Tant que le projet Google Cloud n'a pas passé l'audit de l'API YouTube, toute vidéo envoyée par
l'API est verrouillée en privé : le mode manuel évite ce piège.
"""

from __future__ import annotations

from pathlib import Path

from .. import desktop
from ..models import PublishResult, YouTubePost

UPLOAD_URL = "https://www.youtube.com/upload"


def metadata_text(post: YouTubePost) -> str:
    return (
        f"TITRE\n{post.title}\n\n"
        f"DESCRIPTION\n{post.description}\n\n"
        f"TAGS\n{', '.join(post.tags)}\n\n"
        f"VISIBILITÉ : {post.privacy} — Conçue pour les enfants : {'oui' if post.made_for_kids else 'non'}\n"
    )


def publish_youtube_manual(
    post: YouTubePost,
    channel_id: str,
    video: Path,
    out_dir: Path,
    dry_run: bool = False,
) -> PublishResult:
    meta = out_dir / "youtube.txt"
    meta.write_text(metadata_text(post), encoding="utf-8")
    if dry_run:
        return PublishResult(channel=channel_id, platform="youtube", status="dry_run", url=UPLOAD_URL,
                             message=f"Simulation : métadonnées écrites dans {meta}.")
    copied = desktop.copy_to_clipboard(post.title)
    desktop.open_url(UPLOAD_URL)
    desktop.reveal(video)
    desktop.open_path(meta)
    msg = (
        f"YouTube Studio est ouvert : glisse {video.name}, puis copie titre / description / tags depuis "
        f"{meta.name}{' (le titre est déjà dans le presse-papiers)' if copied else ''}. "
        "Une fois publié, donne-moi l'URL du short pour l'enregistrer (mark_published)."
    )
    return PublishResult(channel=channel_id, platform="youtube", status="pending_manual",
                         url=UPLOAD_URL, message=msg)
