import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

os.environ["NAP_NO_OPEN"] = "1"

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg absent")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "Exode"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "dev@example.invalid")
    git(r, "config", "user.name", "Dev")
    (r / "README.md").write_text("Exode\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "Initial commit")
    (r / "Quests.cs").write_text("class Quest {}\n" * 10)
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "Ajoute le système de quêtes",
        "-m", "Dialogues à embranchements.\n\nCo-Authored-By: Bot <bot@example.invalid>")
    (r / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [1.2.0] - 2026-11-01\n- Quêtes\n- Récompenses\n\n## [1.1.0] - 2026-10-01\n- Dialogues\n\n"
        "## [1.0.0] - 2026-09-01\n- Sortie\n"
    )
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "Changelog 1.2.0")
    return r


@pytest.fixture
def data_dir(tmp_path: Path, repo: Path, monkeypatch) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    cfg = {
        "projects": {
            "exode": {
                "name": "Exode",
                "repo_path": str(repo),
                "engine": "unity",
                "languages": ["fr"],
                "changelog": "CHANGELOG.md",
                "hashtags": ["#Exode"],
                "channels": {"fr": ["discord.test", "x.main", "youtube.main"]},
            }
        },
        "channels": {
            "discord.test": {"type": "discord_webhook", "webhook_env": "NAP_TEST_WEBHOOK", "max_upload_mb": 8},
            "x.main": {"type": "x", "mode": "intent"},
            "youtube.main": {"type": "youtube", "mode": "manual"},
        },
        "obs": {"enabled": False},
    }
    (d / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("NAP_TEST_WEBHOOK", "https://discord.com/api/webhooks/123/abc")
    monkeypatch.setenv("NAP_DATA_DIR", str(d))
    monkeypatch.delenv("NAP_DRY_RUN", raising=False)
    return d
