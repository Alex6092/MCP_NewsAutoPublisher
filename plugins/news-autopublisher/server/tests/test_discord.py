import json

import httpx
import respx

from newsautopublisher.config import ChannelConfig
from newsautopublisher.models import DiscordPost
from newsautopublisher.publishers.discord import build_payload, publish_discord

HOOK = "https://discord.com/api/webhooks/123/abc"


def test_payload_no_mentions_by_default(tmp_path):
    img = tmp_path / "cover.png"
    img.write_bytes(b"png")
    post = DiscordPost(content="Salut", title="Devlog", description="**Nouveau**", image=str(img))
    p = build_payload(post, ChannelConfig(type="discord_webhook"), [img], "#7C5CFF", footer="Exode")
    assert p["allowed_mentions"] == {"parse": []}
    assert p["embeds"][0]["color"] == 0x7C5CFF
    assert p["embeds"][0]["image"]["url"] == "attachment://cover.png"
    assert p["attachments"] == [{"id": 0, "filename": "cover.png"}]


def test_payload_role_mention():
    ch = ChannelConfig(type="discord_webhook", mention="<@&42>")
    p = build_payload(DiscordPost(content="News"), ch, [], "#000000")
    assert p["content"] == "<@&42> News"
    assert p["allowed_mentions"] == {"parse": [], "roles": ["42"]}
    assert "attachments" not in p and "embeds" not in p


@respx.mock
def test_publish_success_with_file_and_link(tmp_path):
    f = tmp_path / "short.mp4"
    f.write_bytes(b"\x00" * 100)
    route = respx.post(HOOK).mock(return_value=httpx.Response(200, json={"id": "999", "channel_id": "55"}))
    respx.get(HOOK).mock(return_value=httpx.Response(200, json={"guild_id": "77", "channel_id": "55"}))
    res = publish_discord(DiscordPost(content="News"), "discord.test", ChannelConfig(type="discord_webhook"),
                          HOOK, [f], "#7C5CFF")
    assert res.status == "published"
    assert res.url == "https://discord.com/channels/77/55/999"
    req = route.calls[0].request
    assert req.url.params["wait"] == "true"
    assert b"payload_json" in req.content and b"short.mp4" in req.content


@respx.mock
def test_publish_json_body_without_files():
    route = respx.post(HOOK).mock(return_value=httpx.Response(200, json={"id": "1", "channel_id": "2"}))
    respx.get(HOOK).mock(return_value=httpx.Response(200, json={}))
    res = publish_discord(DiscordPost(content="Hello"), "d", ChannelConfig(type="discord_webhook"), HOOK, [], "#FFFFFF")
    assert res.status == "published" and res.url is None
    assert json.loads(route.calls[0].request.content)["content"] == "Hello"


@respx.mock
def test_publish_retries_on_rate_limit(monkeypatch):
    monkeypatch.setattr("newsautopublisher.publishers.discord.time.sleep", lambda s: None)
    respx.post(HOOK).mock(side_effect=[
        httpx.Response(429, json={"retry_after": 0.1}),
        httpx.Response(200, json={"id": "1", "channel_id": "2"}),
    ])
    respx.get(HOOK).mock(return_value=httpx.Response(200, json={"guild_id": "3"}))
    res = publish_discord(DiscordPost(content="x"), "d", ChannelConfig(type="discord_webhook"), HOOK, [], "#FFFFFF")
    assert res.status == "published"


@respx.mock
def test_publish_failure_is_reported():
    respx.post(HOOK).mock(return_value=httpx.Response(413, text="too big"))
    res = publish_discord(DiscordPost(content="x"), "d", ChannelConfig(type="discord_webhook"), HOOK, [], "#FFFFFF")
    assert res.status == "failed" and "413" in res.message


def test_dry_run_sends_nothing():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(HOOK)
        res = publish_discord(DiscordPost(content="x"), "d", ChannelConfig(type="discord_webhook"), HOOK, [],
                              "#FFFFFF", dry_run=True)
        assert res.status == "dry_run" and not route.called
