"""YouTube en mode API : OAuth « application de bureau » + upload résumable (videos.insert).

ATTENTION : tant que le projet Google Cloud n'a pas passé l'audit de conformité de l'API YouTube,
toute vidéo envoyée est verrouillée en privé, sans recours. Le canal doit donc déclarer
`audited: true` pour publier en public ou non répertorié.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

import httpx

from ..models import PublishResult, YouTubePost

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",  # pour afficher la chaîne connectée
]
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
CHUNK = 8 * 1024 * 1024  # multiple de 256 Kio, comme l'exige le protocole résumable


class YouTubeApiError(Exception):
    pass


# ---------------------------------------------------------------------------- authentification
def connect(client_secret: Path, token_file: Path, open_browser: bool = True) -> dict[str, Any]:
    """Consentement OAuth dans le navigateur (une fois), puis jeton de rafraîchissement enregistré."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:  # pragma: no cover
        raise YouTubeApiError("Le paquet google-auth-oauthlib n'est pas installé.") from exc
    if not client_secret.exists():
        raise YouTubeApiError(
            f"Fichier client OAuth introuvable : {client_secret}. Dans Google Cloud Console : API YouTube "
            "Data v3 activée > Identifiants > ID client OAuth « Application de bureau » > Télécharger le JSON."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), scopes=SCOPES)
    # La bibliothèque affiche l'URL avec print() : on la renvoie vers stderr pour ne pas polluer
    # le flux stdio du protocole MCP.
    with contextlib.redirect_stdout(sys.stderr):
        creds = flow.run_local_server(port=0, open_browser=open_browser, prompt="consent",
                                      authorization_prompt_message="Autorise l'accès YouTube : {url}",
                                      success_message="Connexion YouTube réussie, tu peux fermer cet onglet.",
                                      timeout_seconds=600)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return channel_info(access_token(token_file))


def access_token(token_file: Path) -> str:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:  # pragma: no cover
        raise YouTubeApiError("Le paquet google-auth n'est pas installé.") from exc
    if not token_file.exists():
        raise YouTubeApiError("Compte YouTube non connecté : appelle connect_account sur ce canal.")
    creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if not creds.valid:
        if not creds.refresh_token:
            raise YouTubeApiError("Jeton YouTube expiré sans rafraîchissement : relance connect_account.")
        try:
            creds.refresh(Request())
        except Exception as exc:
            raise YouTubeApiError(f"Rafraîchissement du jeton YouTube impossible ({exc}) : relance connect_account.") from exc
        token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds.token


def channel_info(token: str, client: httpx.Client | None = None) -> dict[str, Any]:
    http = client or httpx.Client(timeout=30)
    try:
        resp = http.get(CHANNELS_URL, params={"part": "snippet", "mine": "true"},
                        headers={"Authorization": f"Bearer {token}"})
    finally:
        if client is None:
            http.close()
    if resp.status_code >= 400:
        raise YouTubeApiError(f"YouTube HTTP {resp.status_code} : {resp.text[:300]}")
    items = resp.json().get("items", [])
    if not items:
        return {"channel_id": None, "title": None, "message": "Aucune chaîne YouTube sur ce compte."}
    return {"channel_id": items[0]["id"], "title": items[0]["snippet"]["title"]}


# ---------------------------------------------------------------------------- upload
def build_metadata(post: YouTubePost, language: str, category_id: str) -> dict[str, Any]:
    status: dict[str, Any] = {"privacyStatus": post.privacy, "selfDeclaredMadeForKids": post.made_for_kids}
    if post.publish_at:
        status["privacyStatus"] = "private"  # exigé par YouTube pour une mise en ligne programmée
        status["publishAt"] = post.publish_at
    if post.contains_synthetic_media is not None:
        status["containsSyntheticMedia"] = post.contains_synthetic_media
    return {
        "snippet": {
            "title": post.title,
            "description": post.description,
            "tags": post.tags,
            "categoryId": category_id,
            "defaultLanguage": language,
            "defaultAudioLanguage": language,
        },
        "status": status,
    }


def upload(
    video: Path,
    metadata: dict[str, Any],
    token: str,
    client: httpx.Client | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    size = video.stat().st_size
    http = client or httpx.Client(timeout=300)
    auth = {"Authorization": f"Bearer {token}"}
    try:
        init = http.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={**auth, "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size),
                     "Content-Type": "application/json; charset=UTF-8"},
            content=json.dumps(metadata).encode("utf-8"),
        )
        if init.status_code >= 400:
            raise YouTubeApiError(_explain(init))
        session = init.headers.get("Location")
        if not session:
            raise YouTubeApiError("YouTube n'a pas renvoyé d'URL de session d'upload.")
        sent = 0
        with video.open("rb") as fh:
            while sent < size:
                chunk = fh.read(CHUNK)
                end = sent + len(chunk) - 1
                resp = http.put(session, content=chunk, headers={
                    **auth, "Content-Length": str(len(chunk)), "Content-Range": f"bytes {sent}-{end}/{size}"})
                if resp.status_code == 308:  # morceau reçu, on continue
                    rng = resp.headers.get("Range")
                    sent = int(rng.split("-")[1]) + 1 if rng else end + 1
                    fh.seek(sent)
                    if on_progress:
                        on_progress(sent, size)
                    continue
                if resp.status_code in (200, 201):
                    return resp.json()
                raise YouTubeApiError(_explain(resp))
    finally:
        if client is None:
            http.close()
    raise YouTubeApiError("Upload YouTube interrompu sans réponse finale.")


def _explain(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error", {})
        reason = (err.get("errors") or [{}])[0].get("reason", "")
        msg = err.get("message", "")
    except Exception:
        reason, msg = "", resp.text[:300]
    if reason in ("quotaExceeded", "uploadLimitExceeded"):
        return f"Quota YouTube atteint ({reason}) : réessaie demain."
    if resp.status_code == 401:
        return "Jeton YouTube refusé : relance connect_account."
    return f"YouTube HTTP {resp.status_code} {reason} : {msg}"


def publish_youtube_api(
    post: YouTubePost,
    channel_id: str,
    video: Path,
    token_file: Path,
    language: str,
    category_id: str,
    audited: bool,
    dry_run: bool = False,
    client: httpx.Client | None = None,
) -> PublishResult:
    if not audited and (post.privacy != "private" or post.publish_at):
        return PublishResult(
            channel=channel_id, platform="youtube", status="failed",
            message="Projet Google non audité : la vidéo serait verrouillée en privé pour toujours. Passe "
                    "l'audit de l'API YouTube puis mets `audited: true` sur le canal, ou utilise mode: manual. "
                    "(Un upload de test reste possible avec privacy: private.)")
    metadata = build_metadata(post, language, category_id)
    if dry_run:
        return PublishResult(channel=channel_id, platform="youtube", status="dry_run",
                             message=f"Simulation API YouTube : {json.dumps(metadata, ensure_ascii=False)[:300]}")
    try:
        token = access_token(token_file)
        res = upload(video, metadata, token, client)
    except (YouTubeApiError, httpx.HTTPError) as exc:
        return PublishResult(channel=channel_id, platform="youtube", status="failed", message=str(exc))
    vid = res.get("id")
    state = res.get("status", {})
    note = ""
    if post.publish_at:
        note = f" Mise en ligne programmée le {post.publish_at}."
    elif state.get("privacyStatus") != post.privacy:
        note = f" Attention : statut renvoyé {state.get('privacyStatus')} (projet non audité ?)."
    return PublishResult(channel=channel_id, platform="youtube", status="published", external_id=vid,
                         url=f"https://youtube.com/shorts/{vid}", message="Short envoyé sur YouTube." + note)
