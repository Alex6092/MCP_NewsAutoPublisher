"""X en mode API (payant à l'usage) : OAuth 1.0a utilisateur, upload v2 par morceaux, POST /2/tweets.

Endpoints (SDK officiel xdk) :
  POST /2/media/upload/initialize        JSON {media_type, total_bytes, media_category}
  POST /2/media/upload/{id}/append       multipart {segment_index, media}
  POST /2/media/upload/{id}/finalize
  GET  /2/media/upload?command=STATUS&media_id=…
  POST /2/tweets                         JSON {text, media: {media_ids}}
"""

from __future__ import annotations

import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from oauthlib.oauth1 import Client as OAuth1Client

from ..models import PublishResult, XPost
from ..validate import URL_RE

API = "https://api.x.com"
CHUNK = 4 * 1024 * 1024
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
               ".gif": "image/gif"}


class XApiError(Exception):
    pass


@dataclass
class XCredentials:
    api_key: str
    api_secret: str
    access_token: str
    access_secret: str


def estimate_cost(post: XPost, n_media: int, cost_post: float, cost_url: float, cost_media: float) -> float:
    has_url = bool(post.url) or bool(URL_RE.search(post.text))
    return round((cost_url if has_url else cost_post) + n_media * cost_media, 4)


class XClient:
    def __init__(self, creds: XCredentials, client: httpx.Client | None = None, poll_sleep=time.sleep):
        self.oauth = OAuth1Client(creds.api_key, client_secret=creds.api_secret,
                                  resource_owner_key=creds.access_token,
                                  resource_owner_secret=creds.access_secret)
        self.http = client or httpx.Client(timeout=120)
        self._sleep = poll_sleep

    def _request(self, method: str, path: str, params: dict | None = None, json: Any = None,
                 files: dict | None = None, data: dict | None = None) -> dict:
        url = API + path
        signed_url = str(httpx.URL(url, params=params)) if params else url
        # Corps JSON ou multipart : non inclus dans la signature OAuth 1.0a (seuls les formulaires le sont).
        _, headers, _ = self.oauth.sign(signed_url, http_method=method)
        resp = self.http.request(method, url, params=params, json=json, files=files, data=data, headers=headers)
        if resp.status_code == 429:
            reset = resp.headers.get("x-rate-limit-reset")
            raise XApiError(f"Limite de débit X atteinte{f' (réinitialisation à {reset})' if reset else ''}.")
        if resp.status_code >= 400:
            detail = resp.text[:400]
            if resp.status_code == 401:
                detail = "authentification refusée : vérifie les 4 clés OAuth 1.0a dans .env."
            elif resp.status_code == 402:
                detail = "crédits insuffisants sur le compte développeur X."
            elif resp.status_code == 403:
                detail = ("accès refusé : l'app X doit avoir les permissions « Read and write » et le jeton "
                          "d'accès doit être régénéré après ce changement. " + resp.text[:200])
            raise XApiError(f"X HTTP {resp.status_code} : {detail}")
        return resp.json() if resp.content else {}

    def me(self) -> dict:
        return self._request("GET", "/2/users/me").get("data", {})

    def upload(self, path: Path) -> str:
        ext = path.suffix.lower()
        is_video = ext in (".mp4", ".mov")
        media_type = "video/mp4" if ext == ".mp4" else ("video/quicktime" if ext == ".mov" else
                                                        IMAGE_TYPES.get(ext) or mimetypes.guess_type(path.name)[0])
        if not media_type:
            raise XApiError(f"Type de média non pris en charge : {path.name}")
        size = path.stat().st_size
        init = self._request("POST", "/2/media/upload/initialize", json={
            "media_type": media_type,
            "total_bytes": size,
            "media_category": "tweet_video" if is_video else ("tweet_gif" if ext == ".gif" else "tweet_image"),
        })
        media_id = (init.get("data") or {}).get("id")
        if not media_id:
            raise XApiError(f"Réponse inattendue à l'initialisation : {init}")
        with path.open("rb") as fh:
            index = 0
            while chunk := fh.read(CHUNK):
                self._request("POST", f"/2/media/upload/{media_id}/append",
                              data={"segment_index": str(index)},
                              files={"media": (path.name, chunk, "application/octet-stream")})
                index += 1
        fin = self._request("POST", f"/2/media/upload/{media_id}/finalize")
        info = (fin.get("data") or {}).get("processing_info")
        deadline = time.time() + 600
        while info and info.get("state") in ("pending", "in_progress"):
            if time.time() > deadline:
                raise XApiError("Le traitement de la vidéo par X dépasse 10 minutes.")
            self._sleep(max(int(info.get("check_after_secs") or 2), 1))
            st = self._request("GET", "/2/media/upload", params={"command": "STATUS", "media_id": media_id})
            info = (st.get("data") or {}).get("processing_info")
        if info and info.get("state") == "failed":
            raise XApiError(f"X a rejeté la vidéo : {info.get('error') or info}")
        return str(media_id)

    def post(self, text: str, media_ids: list[str]) -> dict:
        body: dict[str, Any] = {"text": text}
        if media_ids:
            body["media"] = {"media_ids": media_ids}
        return self._request("POST", "/2/tweets", json=body).get("data", {})

    def close(self) -> None:
        self.http.close()


def full_text(post: XPost) -> str:
    if not post.url:
        return post.text
    sep = "" if post.text.endswith(("\n", " ")) else "\n"
    return f"{post.text}{sep}{post.url}"


def publish_x_api(
    post: XPost,
    channel_id: str,
    media: list[Path],
    creds: XCredentials,
    cost: float,
    handle: str | None = None,
    dry_run: bool = False,
    client: XClient | None = None,
) -> PublishResult:
    # X refuse de mélanger vidéo et images : la vidéo l'emporte.
    videos = [m for m in media if m.suffix.lower() in (".mp4", ".mov")]
    media = videos[:1] if videos else media[:4]
    if dry_run:
        return PublishResult(channel=channel_id, platform="x", status="dry_run",
                             message=f"Simulation API X : {len(media)} média(s), coût estimé {cost:.3f} $.")
    own = client is None
    client = client or XClient(creds)
    try:
        ids = [client.upload(m) for m in media]
        data = client.post(full_text(post), ids)
    except (XApiError, httpx.HTTPError) as exc:
        return PublishResult(channel=channel_id, platform="x", status="failed", message=str(exc))
    finally:
        if own:
            client.close()
    post_id = data.get("id")
    who = handle.lstrip("@") if handle else "i/web"
    return PublishResult(channel=channel_id, platform="x", status="published", external_id=post_id,
                         url=f"https://x.com/{who}/status/{post_id}", cost_usd=cost,
                         message=f"Publié sur X via l'API (coût estimé {cost:.3f} $).")
