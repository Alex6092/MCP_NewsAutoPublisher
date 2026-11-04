"""Assistant d'installation : détection des projets, édition sûre de config.yaml et des secrets."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML

from .config import AppConfig, ConfigError

SKIP_DIRS = {
    ".git", "node_modules", "Library", "Temp", "Logs", "obj", "bin", "Binaries", "Intermediate", "Saved",
    "DerivedDataCache", "Build", "Builds", ".venv", "venv", "__pycache__", ".idea", ".vs", "Packages",
    "AppData", "$RECYCLE.BIN", "Windows", "Program Files", "Program Files (x86)",
}
SECTIONS = {"projects", "channels", "voice", "obs", "video", "hints"}
SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


def default_roots() -> list[Path]:
    home = Path.home()
    cands = [home / "Dev", home / "dev", home / "Projects", home / "source" / "repos", home / "Documents" / "GitHub",
             home / "Documents" / "Unreal Projects", home / "Documents" / "Unity Projects", Path("D:/Dev"),
             Path("D:/Projects"), Path("C:/Dev"), Path("E:/Dev"), Path.cwd().parent]
    seen, out = set(), []
    for c in cands:
        try:
            key = str(c.resolve()).lower()
        except OSError:
            continue
        if c.is_dir() and key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _git(path: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _engine(path: Path) -> tuple[str, str | None, Path]:
    """(moteur, version, dossier du projet moteur) pour un dossier de dépôt."""
    for cand in [path] + [p for p in sorted(path.iterdir()) if p.is_dir() and p.name not in SKIP_DIRS][:30]:
        version_file = cand / "ProjectSettings" / "ProjectVersion.txt"
        if version_file.exists() and (cand / "Assets").is_dir():
            m = re.search(r"m_EditorVersion:\s*(\S+)", version_file.read_text(encoding="utf-8", errors="replace"))
            return "unity", m.group(1) if m else None, cand
        uprojects = list(cand.glob("*.uproject"))
        if uprojects:
            try:
                assoc = json.loads(uprojects[0].read_text(encoding="utf-8-sig")).get("EngineAssociation")
            except (json.JSONDecodeError, OSError):
                assoc = None
            return "unreal", assoc, uprojects[0]
    if (path / "package.json").exists() or (path / "index.html").exists():
        return "web", None, path
    return "other", None, path


def discover_projects(roots: list[str] | None, configured: dict[str, str], max_depth: int = 3,
                      limit: int = 60) -> list[dict[str, Any]]:
    """Dépôts git trouvés sous les dossiers racines, avec moteur, version, remote et CHANGELOG."""
    bases = [Path(r).expanduser() for r in roots] if roots else default_roots()
    found: list[dict[str, Any]] = []
    known = {os.path.normcase(str(Path(v).expanduser().resolve())): k for k, v in configured.items() if v}

    def walk(d: Path, depth: int) -> None:
        if len(found) >= limit or depth > max_depth:
            return
        if (d / ".git").exists():
            engine, version, engine_path = _engine(d)
            remote = _git(d, "config", "--get", "remote.origin.url")
            last = _git(d, "log", "-1", "--format=%cs")
            found.append({
                "path": str(d), "name": d.name, "engine": engine, "engine_version": version,
                "engine_path": str(engine_path), "remote": re.sub(r"//[^@/]+@", "//", remote) or None,
                "host": "github" if "github" in remote else ("gitlab" if "gitlab" in remote else None),
                "last_commit": last or None,
                "changelog": next((n for n in ("CHANGELOG.md", "Changelog.md", "CHANGES.md") if (d / n).exists()), None),
                "configured_as": known.get(os.path.normcase(str(d.resolve()))),
            })
            return
        try:
            children = sorted(p for p in d.iterdir() if p.is_dir() and p.name not in SKIP_DIRS and not p.name.startswith("."))
        except OSError:
            return
        for child in children:
            walk(child, depth + 1)

    for base in bases:
        walk(base, 0)
    found.sort(key=lambda r: r["last_commit"] or "", reverse=True)
    return found


# ---------------------------------------------------------------------------- config.yaml
def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 120
    return y


def _merge(target, value) -> None:
    for k, v in value.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _merge(target[k], v)
        else:
            target[k] = v


def _plain(node):
    return json.loads(json.dumps(node, default=str))


def validate_raw(raw: dict) -> AppConfig:
    try:
        cfg = AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Modification refusée, configuration invalide :\n{exc}") from exc
    for pkey, proj in cfg.projects.items():
        for lang, chans in proj.channels.items():
            for ch in chans:
                if ch not in cfg.channels:
                    raise ConfigError(f"Modification refusée : projet « {pkey} » ({lang}) utilise le canal « {ch} » "
                                      "absent de channels (ajoute d'abord le canal).")
    return cfg


def edit_config(config_file: Path, section: str, key: str | None, value: dict | None, remove: bool = False) -> dict:
    """Modifie une entrée de config.yaml en conservant les commentaires ; refuse toute config invalide."""
    if section not in SECTIONS:
        raise ConfigError(f"Section inconnue : {section} (sections : {', '.join(sorted(SECTIONS))}).")
    if section in ("projects", "channels") and not key:
        raise ConfigError(f"La section {section} demande une clé (id du projet ou du canal).")
    y = _yaml()
    doc = y.load(config_file.read_text(encoding="utf-8")) if config_file.exists() else None
    if doc is None:
        doc = y.load("{}")
    container = doc.setdefault(section, {}) if key else doc
    target_key = key or section
    if remove:
        if target_key not in container:
            raise ConfigError(f"{section}.{key} n'existe pas.")
        del container[target_key]
        action = "supprimé"
    else:
        if not isinstance(value, dict):
            raise ConfigError("value doit être un objet (dictionnaire) de réglages.")
        if target_key in container and isinstance(container[target_key], dict):
            _merge(container[target_key], value)
            action = "modifié"
        else:
            container[target_key] = value
            action = "ajouté"
    validate_raw(_plain(doc))
    buf = io.StringIO()
    y.dump(doc, buf)
    tmp = config_file.with_suffix(".tmp")
    tmp.write_text(buf.getvalue(), encoding="utf-8")
    tmp.replace(config_file)
    return {"section": section, "key": key, "action": action}


# ---------------------------------------------------------------------------- .env
def set_secret(env_file: Path, name: str, value: str) -> dict:
    if not SECRET_NAME.match(name):
        raise ConfigError("Nom de variable invalide (majuscules, chiffres et _ ; ex. DISCORD_WEBHOOK_EXODE).")
    value = value.strip()
    if not value or "\n" in value:
        raise ConfigError("Valeur vide ou sur plusieurs lignes.")
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    out, replaced = [], False
    for line in lines:
        if re.match(rf"^\s*{name}\s*=", line):
            out.append(f"{name}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{name}={value}")
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ[name] = value
    warning = None
    if name.startswith("DISCORD_WEBHOOK") and not re.match(r"^https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/", value):
        warning = "Ça ne ressemble pas à une URL de webhook Discord (https://discord.com/api/webhooks/…)."
    return {"name": name, "saved": True, "replaced": replaced, "warning": warning}
