import json
from pathlib import Path

import httpx
import pytest
import respx
import yaml

from newsautopublisher.models import DiscordPost, XPost, YouTubePost
from newsautopublisher.publishers import discord_bot, x_api, youtube_api
from newsautopublisher.service import App

X = "https://api.x.com"
CREDS = x_api.XCredentials("ck", "cs", "at", "as")


# ---------------------------------------------------------------------------- X API
def test_estimate_cost():
    assert x_api.estimate_cost(XPost(text="Salut"), 0, 0.015, 0.2, 0.0) == 0.015
    assert x_api.estimate_cost(XPost(text="Salut", url="https://a.io"), 1, 0.015, 0.2, 0.01) == 0.21
    assert x_api.estimate_cost(XPost(text="voir fab.com/x"), 0, 0.015, 0.2, 0.0) == 0.2


@respx.mock
def test_x_chunked_video_upload_and_post(tmp_path):
    video = tmp_path / "short_x.mp4"
    video.write_bytes(b"\x00" * (x_api.CHUNK + 10))  # 2 morceaux
    init = respx.post(f"{X}/2/media/upload/initialize").mock(
        return_value=httpx.Response(200, json={"data": {"id": "77"}}))
    append = respx.post(f"{X}/2/media/upload/77/append").mock(return_value=httpx.Response(204))
    respx.post(f"{X}/2/media/upload/77/finalize").mock(return_value=httpx.Response(
        200, json={"data": {"id": "77", "processing_info": {"state": "pending", "check_after_secs": 1}}}))
    status = respx.get(f"{X}/2/media/upload").mock(return_value=httpx.Response(
        200, json={"data": {"id": "77", "processing_info": {"state": "succeeded"}}}))
    tweet = respx.post(f"{X}/2/tweets").mock(return_value=httpx.Response(201, json={"data": {"id": "999"}}))

    client = x_api.XClient(CREDS, poll_sleep=lambda s: None)
    res = x_api.publish_x_api(XPost(text="Les quêtes arrivent", url="https://discord.gg/exode"), "x.main",
                              [video], CREDS, 0.2, handle="@exode_game", client=client)
    assert res.status == "published" and res.url == "https://x.com/exode_game/status/999"
    assert res.cost_usd == 0.2
    body = json.loads(init.calls[0].request.content)
    assert body == {"media_type": "video/mp4", "total_bytes": x_api.CHUNK + 10, "media_category": "tweet_video"}
    assert append.call_count == 2 and b'name="segment_index"' in append.calls[1].request.content
    assert status.calls[0].request.url.params["command"] == "STATUS"
    sent = json.loads(tweet.calls[0].request.content)
    assert sent == {"text": "Les quêtes arrivent\nhttps://discord.gg/exode", "media": {"media_ids": ["77"]}}
    auth = tweet.calls[0].request.headers["Authorization"]
    assert auth.startswith("OAuth ") and 'oauth_consumer_key="ck"' in auth and 'oauth_token="at"' in auth


@respx.mock
def test_x_errors_are_explained():
    respx.post(f"{X}/2/tweets").mock(return_value=httpx.Response(403, json={"title": "Forbidden"}))
    client = x_api.XClient(CREDS)
    res = x_api.publish_x_api(XPost(text="x"), "x.main", [], CREDS, 0.015, client=client)
    assert res.status == "failed" and "Read and write" in res.message


# ---------------------------------------------------------------------------- YouTube API
def test_youtube_metadata_scheduling():
    post = YouTubePost(title="T #Shorts", description="D", tags=["a"], publish_at="2030-01-01T10:00:00Z",
                       contains_synthetic_media=False)
    meta = youtube_api.build_metadata(post, "fr", "20")
    assert meta["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                              "publishAt": "2030-01-01T10:00:00Z", "containsSyntheticMedia": False}
    assert meta["snippet"]["defaultLanguage"] == "fr" and meta["snippet"]["categoryId"] == "20"


@respx.mock
def test_youtube_resumable_upload(tmp_path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"\x01" * (youtube_api.CHUNK + 5))
    session = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=abc"
    init = respx.post(youtube_api.UPLOAD_URL).mock(return_value=httpx.Response(200, headers={"Location": session}))
    put = respx.put(session).mock(side_effect=[
        httpx.Response(308, headers={"Range": f"bytes=0-{youtube_api.CHUNK - 1}"}),
        httpx.Response(200, json={"id": "vid123", "status": {"privacyStatus": "public"}}),
    ])
    res = youtube_api.upload(video, {"snippet": {"title": "t"}}, "tok")
    assert res["id"] == "vid123"
    assert init.calls[0].request.headers["X-Upload-Content-Length"] == str(youtube_api.CHUNK + 5)
    assert put.calls[1].request.headers["Content-Range"] == (
        f"bytes {youtube_api.CHUNK}-{youtube_api.CHUNK + 4}/{youtube_api.CHUNK + 5}")


def test_youtube_refuses_public_upload_when_not_audited(tmp_path):
    res = youtube_api.publish_youtube_api(YouTubePost(title="t #Shorts"), "youtube.main", tmp_path / "v.mp4",
                                          tmp_path / "tok.json", "fr", "20", audited=False)
    assert res.status == "failed" and "audit" in res.message


# ---------------------------------------------------------------------------- Discord crosspost
@respx.mock
def test_crosspost_messages():
    url = f"{discord_bot.API}/channels/5/messages/9/crosspost"
    route = respx.post(url).mock(return_value=httpx.Response(200, json={}))
    assert discord_bot.crosspost("tok", "5", "9") is None
    assert route.calls[0].request.headers["Authorization"] == "Bot tok"
    respx.post(url).mock(return_value=httpx.Response(403, json={}))
    assert "Gérer les messages" in discord_bot.crosspost("tok", "5", "9")


# ---------------------------------------------------------------------------- intégration service
@pytest.fixture
def api_app(data_dir, monkeypatch):
    cfg_file = data_dir / "config.yaml"
    cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    cfg["channels"]["x.api"] = {"type": "x", "mode": "api", "monthly_budget_usd": 0.25, "handle": "@exode"}
    cfg["channels"]["discord.test"]["crosspost"] = True
    cfg["projects"]["exode"]["channels"]["fr"] = ["discord.test", "x.api"]
    cfg_file.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    for k, v in {"X_API_KEY": "ck", "X_API_SECRET": "cs", "X_ACCESS_TOKEN": "at",
                 "X_ACCESS_TOKEN_SECRET": "as", "DISCORD_BOT_TOKEN": "bot"}.items():
        monkeypatch.setenv(k, v)
    return App()


@respx.mock
def test_budget_guard_and_crosspost_flow(api_app):
    hook = "https://discord.com/api/webhooks/123/abc"
    respx.post(hook).mock(return_value=httpx.Response(200, json={"id": "9", "channel_id": "5"}))
    respx.get(hook).mock(return_value=httpx.Response(200, json={"guild_id": "7"}))
    cross = respx.post(f"{discord_bot.API}/channels/5/messages/9/crosspost").mock(
        return_value=httpx.Response(200, json={}))
    tweets = respx.post(f"{X}/2/tweets").mock(return_value=httpx.Response(201, json={"data": {"id": "1"}}))

    d = api_app.create_draft("exode", "fr", "News", discord=DiscordPost(content="Salut"),
                             x=XPost(text="Nouveauté !", url="https://discord.gg/exode", attach_short=False))
    assert any(i.field == "cost" for i in d.issues)
    api_app.approve_draft(d.id)
    res = {r["channel"]: r for r in api_app.publish(d.id)["results"]}
    assert res["discord.test"]["status"] == "published" and "abonnés" in res["discord.test"]["message"]
    assert cross.called
    assert res["x.api"]["status"] == "published" and res["x.api"]["cost_usd"] == 0.2
    assert api_app.store.spend_this_month("x.api") == pytest.approx(0.2)

    d2 = api_app.create_draft("exode", "fr", "News 2", channels=["x.api"],
                              x=XPost(text="Encore !", url="https://discord.gg/exode", attach_short=False))
    api_app.approve_draft(d2.id)
    r2 = api_app.publish(d2.id)["results"][0]
    assert r2["status"] == "failed" and "Budget X dépassé" in r2["message"]
    assert tweets.call_count == 1


def test_x_api_without_budget_cannot_be_approved(api_app, data_dir):
    cfg_file = data_dir / "config.yaml"
    cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    cfg["channels"]["x.api"]["monthly_budget_usd"] = 0
    cfg_file.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    d = api_app.create_draft("exode", "fr", "News", channels=["x.api"], x=XPost(text="Hello"))
    assert any(i.field == "budget" and i.level == "error" for i in d.issues)


def test_status_reports_phase3_channels(api_app):
    st = api_app.status()
    assert st["channels"]["x.api"]["keys"] == "présentes"
    assert "dépensés" in st["channels"]["x.api"]["budget"]
    assert st["channels"]["discord.test"]["bot"] == "présent"
    assert Path(st["data_dir"]).exists()


def test_unaudited_youtube_api_is_flagged_before_approval(api_app, data_dir):
    cfg_file = data_dir / "config.yaml"
    cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    cfg["channels"]["youtube.main"]["mode"] = "api"
    cfg_file.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    d = api_app.create_draft("exode", "fr", "News", channels=["youtube.main"],
                             youtube=YouTubePost(title="T #Shorts"))
    assert any(i.field == "privacy" and i.level == "error" for i in d.issues)
    d = api_app.update_draft(d.id, youtube=YouTubePost(title="T #Shorts", privacy="private"))
    assert not any(i.field == "privacy" for i in d.issues)
