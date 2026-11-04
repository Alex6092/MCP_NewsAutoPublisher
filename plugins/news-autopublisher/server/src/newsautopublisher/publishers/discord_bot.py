"""Bot Discord minimal : crosspost des annonces publiées par webhook, sans processus permanent.

Le bot doit être invité sur le serveur avec les permissions « Voir le salon », « Envoyer des messages »
et « Gérer les messages » (nécessaire pour publier un message qu'il n'a pas écrit lui-même, comme
ceux du webhook). Discord demande qu'un bot se soit connecté au moins une fois à la gateway :
`identify_once` s'en charge lors de connect_account.
"""

from __future__ import annotations

import json
import time

import httpx

API = "https://discord.com/api/v10"
GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
ANNOUNCEMENT_CHANNEL = 5


class DiscordBotError(Exception):
    pass


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bot {token}", "User-Agent": "DiscordBot (https://github.com/Alex6092/MCP_NewsAutoPublisher, 0.2)"}


def identify_once(token: str, timeout: float = 15) -> dict:
    """Connexion unique à la gateway (IDENTIFY puis fermeture). Renvoie l'utilisateur du bot."""
    try:
        import websocket
    except ImportError as exc:  # pragma: no cover
        raise DiscordBotError("Le paquet websocket-client n'est pas installé.") from exc
    ws = websocket.create_connection(GATEWAY, timeout=timeout)
    try:
        hello = json.loads(ws.recv())
        if hello.get("op") != 10:
            raise DiscordBotError("Réponse inattendue de la gateway Discord.")
        ws.send(json.dumps({"op": 2, "d": {"token": token, "intents": 0,
                                          "properties": {"os": "windows", "browser": "newsautopublisher",
                                                         "device": "newsautopublisher"}}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(ws.recv())
            if msg.get("op") == 0 and msg.get("t") == "READY":
                return msg["d"]["user"]
            if msg.get("op") == 9:
                raise DiscordBotError("Jeton du bot refusé par la gateway.")
        raise DiscordBotError("Pas de réponse READY de la gateway Discord.")
    except websocket.WebSocketException as exc:
        raise DiscordBotError(f"Gateway Discord : {exc}") from exc
    finally:
        try:
            ws.close()
        except Exception:
            pass


def channel_info(token: str, channel_id: str, client: httpx.Client | None = None) -> dict:
    http = client or httpx.Client(timeout=30)
    try:
        resp = http.get(f"{API}/channels/{channel_id}", headers=_headers(token))
    finally:
        if client is None:
            http.close()
    if resp.status_code == 401:
        raise DiscordBotError("Jeton du bot invalide.")
    if resp.status_code in (403, 404):
        raise DiscordBotError("Le bot ne voit pas ce salon : invite-le sur le serveur avec les bonnes permissions.")
    resp.raise_for_status()
    return resp.json()


def crosspost(token: str, channel_id: str, message_id: str, client: httpx.Client | None = None) -> str | None:
    """Publie le message aux serveurs abonnés. Renvoie None si OK, sinon une explication."""
    http = client or httpx.Client(timeout=30)
    try:
        for _ in range(3):
            resp = http.post(f"{API}/channels/{channel_id}/messages/{message_id}/crosspost", headers=_headers(token))
            if resp.status_code == 429:
                time.sleep(min(float(resp.json().get("retry_after", 2)), 30))
                continue
            break
    except httpx.HTTPError as exc:
        return f"crosspost impossible ({exc.__class__.__name__})"
    finally:
        if client is None:
            http.close()
    if resp.status_code < 300:
        return None
    if resp.status_code == 403:
        return "crosspost refusé : le bot doit avoir « Gérer les messages » dans ce salon."
    if resp.status_code == 400:
        return "crosspost refusé : le salon n'est pas un salon d'annonces."
    return f"crosspost HTTP {resp.status_code} : {resp.text[:200]}"
