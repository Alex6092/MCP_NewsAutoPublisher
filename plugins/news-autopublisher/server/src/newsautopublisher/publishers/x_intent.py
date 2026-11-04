"""X en mode « intent » : éditeur prérempli ouvert dans le navigateur, l'utilisateur clique « Poster ».

Gratuit et conforme aux conditions d'X (aucune automatisation de l'interface web).
Les médias ne peuvent pas être joints par l'URL : le dossier est ouvert pour les glisser à la main.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlencode

from .. import desktop
from ..models import PublishResult, XPost

INTENT_BASE = "https://x.com/intent/post"


def build_intent_url(text: str, url: str | None = None) -> str:
    params = {"text": text}
    if url:
        params["url"] = url
    return f"{INTENT_BASE}?{urlencode(params, quote_via=quote)}"


def publish_x_intent(
    post: XPost,
    channel_id: str,
    media: list[Path],
    dry_run: bool = False,
) -> PublishResult:
    intent = build_intent_url(post.text, post.url)
    steps = ["Vérifie le texte dans l'éditeur X qui vient de s'ouvrir."]
    if media:
        steps.append("Glisse le(s) média(s) depuis l'Explorateur : " + ", ".join(m.name for m in media) + ".")
    steps.append("Clique « Poster », puis donne-moi l'URL du post pour l'enregistrer (mark_published).")
    if dry_run:
        return PublishResult(channel=channel_id, platform="x", status="dry_run", url=intent,
                             message="Simulation : l'éditeur X n'a pas été ouvert.")
    opened = desktop.open_url(intent)
    if media:
        desktop.reveal(media[0])
    message = " ".join(steps)
    if not opened:
        message = f"Ouvre ce lien dans ton navigateur : {intent} — " + message
    return PublishResult(channel=channel_id, platform="x", status="pending_manual", url=intent,
                         message=message)
