import json
import time
import subprocess
import sys

import yaml
from conftest import git

from newsautopublisher.hints import build_hint
from newsautopublisher.models import DiscordPost, XPost
from newsautopublisher.paths import Paths
from newsautopublisher.service import App


def commits(repo, n, prefix="feat"):
    for i in range(n):
        (repo / f"{prefix}{i}.txt").write_text(str(i))
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", f"{prefix} {i}")


def settings(data_dir, **hints):
    f = data_dir / "config.yaml"
    cfg = yaml.safe_load(f.read_text(encoding="utf-8"))
    cfg["hints"] = hints
    f.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")


def test_session_hint_threshold_cooldown_tag_and_snooze(data_dir, repo):
    settings(data_dir, min_commits=5, cooldown_hours=24)
    paths, payload = Paths.default(), {"cwd": str(repo)}
    t0 = time.time()
    assert build_hint("session", payload, paths, now=t0) is None  # 3 commits seulement

    commits(repo, 4)
    hint = build_hint("session", payload, paths, now=t0)
    assert "7 commits non annoncés" in hint and "propose en UNE phrase" in hint and "sans son accord" in hint
    assert build_hint("session", payload, paths, now=t0 + 3600) is None  # délai entre deux rappels

    git(repo, "tag", "v1.2.0")
    assert "tag v1.2.0" in build_hint("git", {**payload, "tool_input": {"command": "git tag v1.2.0"}}, paths, now=t0 + 7200)
    assert build_hint("git", {**payload, "tool_input": {"command": "git push --tags"}}, paths, now=t0 + 7300) is None

    App().snooze_hints("exode", 7)
    assert build_hint("session", payload, paths, now=t0 + 2 * 86400) is None


def test_git_hint_only_for_commit_or_push_and_after_publication(data_dir, repo):
    settings(data_dir, min_commits=2, cooldown_hours=1)
    paths, payload = Paths.default(), {"cwd": str(repo / "Assets")}
    t0 = time.time()
    assert build_hint("git", {**payload, "tool_input": {"command": "git status"}}, paths, now=t0) is None
    assert "3 commits" in build_hint("git", {**payload, "tool_input": {"command": "git commit -m x"}}, paths, now=t0)

    # Une news publiée remet le compteur à zéro.
    app = App()
    d = app.create_draft("exode", "fr", "News", channels=["x.main"], x=XPost(text="Hello"))
    app.approve_draft(d.id)
    app.publish(d.id)
    app.mark_published(d.id)
    assert build_hint("git", {**payload, "tool_input": {"command": "git commit -m y"}}, paths, now=t0 + 7200) is None
    commits(repo, 2, "fix")
    assert "2 commits non annoncés depuis la dernière news" in build_hint(
        "git", {**payload, "tool_input": {"command": "git push"}}, paths, now=t0 + 14400)


def test_pending_drafts_reminder_and_outside_project(data_dir, repo, tmp_path):
    settings(data_dir, min_commits=50)
    app = App()
    app.create_draft("exode", "fr", "Les quêtes arrivent", channels=["discord.test"], discord=DiscordPost(content="x"))
    hint = build_hint("session", {"cwd": str(repo)}, Paths.default(), now=time.time())
    assert "Brouillons NewsAutoPublisher en attente" in hint and "Les quêtes arrivent" in hint and "à relire" in hint
    assert build_hint("session", {"cwd": str(tmp_path)}, Paths.default()) is None
    settings(data_dir, enabled=False)
    assert build_hint("session", {"cwd": str(repo)}, Paths.default(), now=time.time() + 30 * 86400) is None


def test_hook_entry_point_outputs_hook_json(data_dir, repo):
    settings(data_dir, min_commits=1)
    out = subprocess.run([sys.executable, "-m", "newsautopublisher.hints", "session"],
                         input=json.dumps({"cwd": str(repo), "hook_event_name": "SessionStart"}),
                         capture_output=True, text=True, timeout=60)
    data = json.loads(out.stdout)
    assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "commits non annoncés" in data["hookSpecificOutput"]["additionalContext"]
    garbage = subprocess.run([sys.executable, "-m", "newsautopublisher.hints", "git"], input="pas du json",
                             capture_output=True, text=True, timeout=60)
    assert garbage.returncode == 0 and garbage.stdout == ""  # silencieux en cas d'erreur
