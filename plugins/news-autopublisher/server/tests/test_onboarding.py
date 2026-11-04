import json
import os

import pytest
from newsautopublisher.config import ConfigError
from newsautopublisher.onboarding import discover_projects, edit_config, set_secret
from newsautopublisher.service import App


def test_discover_projects(tmp_path, repo):
    dev = tmp_path / "Dev"
    unity_repo = dev / "Exode"
    (unity_repo / "Client" / "ProjectSettings").mkdir(parents=True)
    (unity_repo / "Client" / "Assets").mkdir()
    (unity_repo / "Client" / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.0.23f1\n")
    os.system(f'git init -q "{unity_repo}"')
    os.system(f'git -C "{unity_repo}" remote add origin https://user:tok@github.com/Alex/Exode.git')
    ue = dev / "Plugins" / "DQM"
    ue.mkdir(parents=True)
    os.system(f'git init -q "{ue}"')
    (ue / "DQM.uproject").write_text(json.dumps({"EngineAssociation": "5.5"}))
    (ue / "CHANGELOG.md").write_text("## [1.0.0]\n")
    (dev / "node_modules" / "x" / ".git").mkdir(parents=True)  # ignoré

    found = {p["name"]: p for p in discover_projects([str(dev)], {"dqm": str(ue)})}
    assert set(found) == {"Exode", "DQM"}
    assert found["Exode"]["engine"] == "unity" and found["Exode"]["engine_version"] == "6000.0.23f1"
    assert found["Exode"]["engine_path"].endswith("Client")
    assert found["Exode"]["remote"] == "https://github.com/Alex/Exode.git"  # identifiants retirés
    assert found["Exode"]["host"] == "github"
    assert found["DQM"]["engine"] == "unreal" and found["DQM"]["engine_version"] == "5.5"
    assert found["DQM"]["changelog"] == "CHANGELOG.md" and found["DQM"]["configured_as"] == "dqm"


def test_edit_config_keeps_comments_and_validates(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("# Mes réglages\nprojects: {}\nchannels:\n  discord.a:  # salon annonces\n"
                   "    type: discord_webhook\n    webhook_env: HOOK_A\n", encoding="utf-8")
    edit_config(cfg, "projects", "exode", {"name": "Exode", "languages": ["fr"], "channels": {"fr": ["discord.a"]}})
    edit_config(cfg, "projects", "exode", {"brand": {"color": "#112233"}})
    text = cfg.read_text(encoding="utf-8")
    assert "# Mes réglages" in text and "# salon annonces" in text
    assert "color: '#112233'" in text or 'color: "#112233"' in text
    with pytest.raises(ConfigError, match="absent de channels"):
        edit_config(cfg, "projects", "exode", {"channels": {"fr": ["discord.inconnu"]}})
    with pytest.raises(ConfigError, match="invalide"):
        edit_config(cfg, "channels", "x.main", {"type": "myspace"})
    assert "discord.inconnu" not in cfg.read_text(encoding="utf-8")  # fichier inchangé après refus
    edit_config(cfg, "projects", "exode", None, remove=True)
    edit_config(cfg, "channels", "discord.a", None, remove=True)
    assert "exode" not in cfg.read_text(encoding="utf-8")


def test_set_secret(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# secrets\nOTHER=1\nDISCORD_WEBHOOK_A=\n", encoding="utf-8")
    res = set_secret(env, "DISCORD_WEBHOOK_A", "https://discord.com/api/webhooks/1/abc")
    assert res["replaced"] and res["warning"] is None and "abc" not in json.dumps(res)
    assert set_secret(env, "DISCORD_WEBHOOK_B", "pas-une-url")["warning"]
    text = env.read_text(encoding="utf-8")
    assert "# secrets" in text and "OTHER=1" in text and "DISCORD_WEBHOOK_A=https://discord.com/api/webhooks/1/abc" in text
    with pytest.raises(ConfigError):
        set_secret(env, "bad name", "x")


def test_service_setup_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("NAP_DATA_DIR", str(tmp_path / "data"))
    app = App()
    app.edit_config("channels", "discord.test", {"type": "discord_webhook", "webhook_env": "HOOK_T"})
    app.edit_config("projects", "demo", {"name": "Demo", "languages": ["fr"], "channels": {"fr": ["discord.test"]}})
    assert "demo" in app.cfg.projects and app.cfg.channels_for("demo", "fr") == ["discord.test"]
    assert app.test_channel("x.main")["ok"]  # canal d'exemple en mode intent : rien à tester
