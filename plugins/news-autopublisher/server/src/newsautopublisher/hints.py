"""Suggestions proactives de news, appelées par les hooks du plugin (SessionStart, PostToolUse git).

Le script lit l'événement du hook sur stdin et, si une news semble mériter d'être préparée, renvoie
un contexte additionnel qui invite Claude à le *proposer* à l'utilisateur. Il ne prépare et ne publie
jamais rien lui-même. Toute erreur est silencieuse : un hook ne doit jamais gêner la session.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import ConfigCache, ConfigError
from .paths import Paths
from .store import Store

STATE_FILE = "hints.json"


def _git(repo: str, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _load_state(paths: Paths) -> dict[str, Any]:
    try:
        return json.loads((paths.root / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(paths: Paths, state: dict[str, Any]) -> None:
    try:
        (paths.root / STATE_FILE).write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


def snooze(paths: Paths, project: str, days: float) -> dict[str, Any]:
    state = _load_state(paths)
    entry = state.setdefault(project, {})
    entry["snoozed_until"] = time.time() + days * 86400
    _save_state(paths, state)
    return {"project": project, "snoozed_until": datetime.fromtimestamp(entry["snoozed_until"]).isoformat(timespec="minutes")}


def detect(cfg, cwd: str) -> str | None:
    import os

    target = os.path.normcase(str(Path(cwd).resolve()))
    best = None
    for key, p in cfg.projects.items():
        if not p.repo_path:
            continue
        root = os.path.normcase(str(Path(p.repo_path).expanduser().resolve()))
        if target == root or target.startswith(root.rstrip(os.sep) + os.sep):
            if best is None or len(root) > best[0]:
                best = (len(root), key)
    return best[1] if best else None


def unannounced(store: Store, project: str, repo: str) -> dict[str, Any]:
    last = store.last_published_commit(project)
    if last and _git(repo, "cat-file", "-t", last) == "commit":
        count = int(_git(repo, "rev-list", "--count", f"{last}..HEAD") or 0)
        since = _git(repo, "log", "-1", "--format=%cs", last)
    else:
        count = int(_git(repo, "rev-list", "--count", "--since=30 days ago", "HEAD") or 0)
        since = None
    tag = _git(repo, "describe", "--tags", "--abbrev=0", "HEAD") or None
    new_tag = None
    if tag:
        tag_commit = _git(repo, "rev-list", "-n", "1", tag)
        if not last or (tag_commit != last and subprocess.run(
                ["git", "-C", repo, "merge-base", "--is-ancestor", last, tag_commit], capture_output=True).returncode == 0):
            new_tag = tag
    return {"commits": count, "since": since, "new_tag": new_tag, "last_published": last}


def pending_drafts(store: Store, project: str) -> list[str]:
    out = []
    for d in store.list_drafts(project, None, 30):
        if d.status in ("draft", "approved", "partial") and (d.group or d.id) == d.id:
            label = {"draft": "à relire", "approved": "approuvé, pas encore publié",
                     "partial": "publication manuelle à confirmer"}[d.status]
            out.append(f"« {d.topic} » ({d.id}, {label})")
    return out[:3]


def build_hint(event: str, payload: dict[str, Any], paths: Paths, now: float | None = None) -> str | None:
    now = now or time.time()
    try:
        cfg = ConfigCache(paths).get()
    except ConfigError:
        return None
    if not cfg.hints.enabled:
        return None
    cwd = payload.get("cwd") or str(Path.cwd())
    project = detect(cfg, cwd)
    if not project:
        return None
    p = cfg.projects[project]
    store = Store(paths.db)
    state = _load_state(paths)
    entry = state.setdefault(project, {})
    if entry.get("snoozed_until", 0) > now:
        return None

    info = unannounced(store, project, p.repo_path)
    command = ((payload.get("tool_input") or {}).get("command") or "") if event == "git" else ""
    parts: list[str] = []
    reason = None
    if info["new_tag"] and entry.get("last_tag_hinted") != info["new_tag"]:
        reason = f"le tag {info['new_tag']} n'a pas encore été annoncé"
        entry["last_tag_hinted"] = info["new_tag"]
    elif info["commits"] >= cfg.hints.min_commits and now - entry.get("last_hint", 0) > cfg.hints.cooldown_hours * 3600:
        if event == "session" or "commit" in command or "push" in command:
            since = f" depuis la dernière news ({info['since']})" if info["since"] else " ces 30 derniers jours"
            reason = f"{info['commits']} commits non annoncés{since}"
    if reason:
        entry["last_hint"] = now
        parts.append(
            f"Suggestion NewsAutoPublisher pour {p.name} : {reason}. Quand la tâche en cours sera terminée (pas "
            "avant), propose en UNE phrase à l'utilisateur de préparer une news (skill news). Ne lance rien sans "
            "son accord. S'il dit « pas maintenant », appelle snooze_news_hints pour ne plus le relancer.")
    if event == "session" and cfg.hints.remind_pending:
        pending = pending_drafts(store, project)
        if pending and now - entry.get("last_pending_hint", 0) > cfg.hints.cooldown_hours * 3600:
            entry["last_pending_hint"] = now
            parts.append("Brouillons NewsAutoPublisher en attente pour " + p.name + " : " + "; ".join(pending)
                         + ". Mentionne-le brièvement à l'utilisateur au bon moment (skill publish).")
    _save_state(paths, state)
    return " ".join(parts) or None


def main() -> None:
    event = sys.argv[1] if len(sys.argv) > 1 else "session"
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        payload = json.loads(raw) if raw.strip() else {}
        hint = build_hint(event, payload, Paths.default())
    except Exception:  # noqa: BLE001 — un hook ne doit jamais casser la session
        return
    if hint:
        hook_event = "SessionStart" if event == "session" else "PostToolUse"
        print(json.dumps({"hookSpecificOutput": {"hookEventName": hook_event, "additionalContext": hint}},
                         ensure_ascii=False))


if __name__ == "__main__":
    main()
