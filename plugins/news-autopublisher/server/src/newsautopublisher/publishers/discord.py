"""Publication Discord via webhook (gratuit, aucun bot nécessaire)."""

from __future__ import annotations

import json
import mimetypes
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import ChannelConfig
from ..models import DiscordPost, PublishResult


def _color_int(color: str | None) -> int | None:
    if not color:
        return None
    return int(color.lstrip("#"), 16)


def build_payload(
    post: DiscordPost,
    channel: ChannelConfig,
    files: list[Path],
    default_color: str,
    footer: str | None = None,
) -> dict[str, Any]:
    content = post.content.strip()
    allowed: dict[str, Any] = {"parse": []}  # aucune notification par défaut
    if channel.mention:
        content = f"{channel.mention} {content}".strip()
        if channel.mention in ("@everyone", "@here"):
            allowed = {"parse": ["everyone"]}
        elif channel.mention.startswith("<@&"):
            allowed = {"parse": [], "roles": [channel.mention.strip("<@&>")]}

    payload: dict[str, Any] = {"content": content, "allowed_mentions": allowed}
    if channel.username:
        payload["username"] = channel.username
    if channel.avatar_url:
        payload["avatar_url"] = channel.avatar_url

    if post.title or post.description or post.image:
        embed: dict[str, Any] = {"color": _color_int(post.color or default_color)}
        if post.title:
            embed["title"] = post.title
        if post.description:
            embed["description"] = post.description
        if post.url:
            embed["url"] = post.url
        if footer:
            embed["footer"] = {"text": footer}
        if post.image:
            embed["image"] = {"url": f"attachment://{Path(post.image).name}"}
        payload["embeds"] = [embed]

    if files:
        payload["attachments"] = [{"id": i, "filename": f.name} for i, f in enumerate(files)]
    return payload


def publish_discord(
    post: DiscordPost,
    channel_id: str,
    channel: ChannelConfig,
    webhook_url: str,
    files: list[Path],
    default_color: str,
    footer: str | None = None,
    dry_run: bool = False,
    client: httpx.Client | None = None,
) -> PublishResult:
    payload = build_payload(post, channel, files, default_color, footer)
    if dry_run:
        return PublishResult(
            channel=channel_id,
            platform="discord",
            status="dry_run",
            message=f"Simulation : {len(files)} fichier(s), payload {json.dumps(payload, ensure_ascii=False)[:400]}",
        )

    own = client is None
    client = client or httpx.Client(timeout=120)
    try:
        for attempt in range(3):
            handles = [f.open("rb") for f in files]
            try:
                multipart = {
                    f"files[{i}]": (f.name, h, mimetypes.guess_type(f.name)[0] or "application/octet-stream")
                    for i, (f, h) in enumerate(zip(files, handles))
                }
                if multipart:
                    resp = client.post(
                        webhook_url,
                        params={"wait": "true"},
                        data={"payload_json": json.dumps(payload, ensure_ascii=False)},
                        files=multipart,
                    )
                else:
                    resp = client.post(webhook_url, params={"wait": "true"}, json=payload)
            finally:
                for h in handles:
                    h.close()
            if resp.status_code == 429 and attempt < 2:
                retry = float(resp.json().get("retry_after", 2))
                time.sleep(min(retry, 30))
                continue
            break

        if resp.status_code >= 400:
            detail = resp.text[:300]
            if resp.status_code == 413:
                detail = "fichiers trop lourds pour ce serveur Discord (413)."
            return PublishResult(channel=channel_id, platform="discord", status="failed",
                                 message=f"Discord HTTP {resp.status_code} : {detail}")

        msg = resp.json()
        url = None
        try:
            info = client.get(webhook_url).json()
            if info.get("guild_id"):
                url = f"https://discord.com/channels/{info['guild_id']}/{msg['channel_id']}/{msg['id']}"
        except Exception:
            pass
        return PublishResult(channel=channel_id, platform="discord", status="published",
                             url=url, external_id=str(msg.get("id")), message="Publié sur Discord.")
    except httpx.HTTPError as exc:
        return PublishResult(channel=channel_id, platform="discord", status="failed",
                             message=f"Erreur réseau Discord : {exc.__class__.__name__}")
    finally:
        if own:
            client.close()
