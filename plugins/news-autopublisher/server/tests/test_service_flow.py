import httpx
import pytest
import respx
from conftest import git

from newsautopublisher.models import DiscordPost, XPost, YouTubePost
from newsautopublisher.service import App, UserError

HOOK = "https://discord.com/api/webhooks/123/abc"


@pytest.fixture
def app(data_dir):
    return App()


def make_draft(app, youtube=True):
    return app.create_draft(
        "exode", "fr", "Les quêtes arrivent",
        discord=DiscordPost(title="Devlog #12", description="Les **quêtes** arrivent !"),
        x=XPost(text="Les quêtes arrivent dans Exode ! #Exode #gamedev", url="https://discord.gg/exode"),
        youtube=YouTubePost(title="Les quêtes arrivent dans Exode #Shorts", description="Devlog") if youtube else None,
    )


def test_detect_project(app, repo):
    assert app.detect_project(str(repo / "Assets"))["project"] == "exode"
    assert app.detect_project(str(repo.parent))["project"] is None


def test_draft_requires_short_for_youtube(app):
    d = make_draft(app)
    assert d.channels == ["discord.test", "x.main", "youtube.main"]
    assert any(i.platform == "youtube" and i.level == "error" for i in d.issues)
    with pytest.raises(UserError, match="Impossible d'approuver"):
        app.approve_draft(d.id)


def test_publish_requires_approval(app):
    d = make_draft(app, youtube=False)
    with pytest.raises(UserError, match="approuvé"):
        app.publish(d.id)


def test_update_after_approval_requires_new_approval(app):
    d = make_draft(app, youtube=False)
    d = app.update_draft(d.id, channels=["discord.test", "x.main"])
    assert app.approve_draft(d.id).status == "approved"
    d = app.update_draft(d.id, x=XPost(text="Nouveau texte"))
    assert d.status == "draft" and d.approved_at is None


def test_leak_blocks_approval(app):
    d = app.create_draft("exode", "fr", "Fuite", channels=["discord.test"],
                         discord=DiscordPost(content="voici ghp_ABCDEFGHIJKLMNOPQRSTUVWX0123"))
    with pytest.raises(UserError, match="jeton GitHub"):
        app.approve_draft(d.id)


@respx.mock
def test_full_publication_flow(app, repo):
    d = make_draft(app, youtube=False)
    d = app.update_draft(d.id, channels=["discord.test", "x.main"])
    app.approve_draft(d.id)

    dry = app.publish(d.id, dry_run=True)
    assert {r["status"] for r in dry["results"]} == {"dry_run"}
    assert app.get_draft(d.id).status == "approved"

    route = respx.post(HOOK).mock(return_value=httpx.Response(200, json={"id": "9", "channel_id": "5"}))
    respx.get(HOOK).mock(return_value=httpx.Response(200, json={"guild_id": "7"}))
    res = app.publish(d.id)
    by_channel = {r["channel"]: r for r in res["results"]}
    assert by_channel["discord.test"]["status"] == "published"
    assert by_channel["discord.test"]["url"] == "https://discord.com/channels/7/5/9"
    assert by_channel["x.main"]["status"] == "pending_manual"
    assert by_channel["x.main"]["url"].startswith("https://x.com/intent/post?text=")
    assert res["status"] == "partial"

    again = app.publish(d.id)  # idempotent : rien n'est renvoyé deux fois
    assert {r["status"] for r in again["results"]} == {"skipped"}
    assert route.call_count == 1

    done = app.mark_published(d.id, "x.main", "https://x.com/exode/status/1")
    assert done["status"] == "published"

    head = git(repo, "rev-parse", "HEAD").strip()
    assert app.store.last_published_commit("exode") == head
    (repo / "New.cs").write_text("x")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "Nouvelle fonctionnalité")
    changes = app.collect_changes("exode")
    assert changes["mode"] == "range" and [c["subject"] for c in changes["commits"]] == ["Nouvelle fonctionnalité"]
    assert changes["changelog"][0]["version"] == "1.2.0"


def test_missing_webhook_secret_fails_cleanly(app, monkeypatch):
    monkeypatch.delenv("NAP_TEST_WEBHOOK")
    d = app.create_draft("exode", "fr", "x", channels=["discord.test"], discord=DiscordPost(content="Salut"))
    app.approve_draft(d.id)
    res = app.publish(d.id)
    assert res["results"][0]["status"] == "failed" and "NAP_TEST_WEBHOOK" in res["results"][0]["message"]


def test_preview_written(app):
    d = make_draft(app)
    out = app.render_preview(d.id, open_browser=False)
    html = open(out["preview"], encoding="utf-8").read()
    assert "Les quêtes arrivent" in html and "Short non rendu" in html and "x.com" not in html.split("<style>")[0]
