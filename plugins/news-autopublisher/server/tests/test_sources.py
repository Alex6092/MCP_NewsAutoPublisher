from conftest import git

from newsautopublisher.sources.changelog import read_changelog
from newsautopublisher.sources.git import collect_changes


def test_collect_changes_date_mode(repo):
    res = collect_changes(repo)
    assert res["mode"] == "date"
    subjects = [c["subject"] for c in res["commits"]]
    assert subjects[0] == "Changelog 1.2.0"
    assert "Ajoute le système de quêtes" in subjects
    quest = next(c for c in res["commits"] if c["subject"].startswith("Ajoute"))
    assert "Dialogues" in quest["body"] and "Co-Authored-By" not in quest["body"]
    assert any(f["path"] == "Quests.cs" for f in res["top_files"])


def test_collect_changes_range_mode_and_uncommitted(repo):
    first = git(repo, "rev-list", "--max-parents=0", "HEAD").strip()
    (repo / "WIP.cs").write_text("// en cours\n")
    res = collect_changes(repo, since=first)
    assert res["mode"] == "range" and res["commit_count"] == 2
    assert res["uncommitted"]["count"] == 1 and "WIP.cs" in res["uncommitted"]["files"]


def test_changelog_sections(repo):
    secs = read_changelog(repo / "CHANGELOG.md")
    assert [s["version"] for s in secs] == ["1.2.0", "1.1.0"]
    assert secs[0]["date"] == "2026-11-01" and "Récompenses" in secs[0]["body"]
