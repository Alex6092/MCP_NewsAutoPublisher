"""Vérification et préparation automatique des projets Unity / Unreal pour les captures."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

UNITY_PACKAGE = "com.newsautopublisher.capture"
UNITY_PACKAGE_URL = (
    "https://github.com/Alex6092/MCP_NewsAutoPublisher.git?path=/engines/unity/com.newsautopublisher.capture"
)
UNREAL_PLUGINS = ["PythonScriptPlugin", "SequencerScripting", "EditorScriptingUtilities", "MovieRenderPipeline"]


def unity_setup(project: Path, apply: bool) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    changes: list[str] = []
    manifest = project / "Packages" / "manifest.json"
    if not manifest.exists():
        return {"ok": False, "checks": [{"check": "Packages/manifest.json", "ok": False,
                                          "detail": f"introuvable dans {project} : est-ce bien un projet Unity ?"}]}
    raw = manifest.read_text(encoding="utf-8")
    data = json.loads(raw)
    deps = data.setdefault("dependencies", {})
    if UNITY_PACKAGE in deps:
        checks.append({"check": "package de capture", "ok": True, "detail": deps[UNITY_PACKAGE]})
    else:
        changes.append(f"Ajout de {UNITY_PACKAGE} dans Packages/manifest.json")
        if apply:
            deps[UNITY_PACKAGE] = UNITY_PACKAGE_URL
            indent = 2 if '\n  "' in raw else 4
            manifest.write_text(json.dumps(data, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")
        checks.append({"check": "package de capture", "ok": apply,
                       "detail": "ajouté (Unity l'installera au prochain focus de l'éditeur)" if apply else "absent"})

    editor_settings = project / "ProjectSettings" / "EditorSettings.asset"
    mode = None
    if editor_settings.exists():
        m = re.search(r"m_SerializationMode: (\d)", editor_settings.read_text(encoding="utf-8", errors="replace"))
        mode = m.group(1) if m else None
    checks.append({"check": "sérialisation Force Text", "ok": mode in (None, "2"),
                   "detail": "ok" if mode in (None, "2") else
                   "Project Settings > Editor > Asset Serialization : Force Text (nécessaire pour lire les scènes)"})
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "changes": changes, "applied": apply}


def unreal_setup(uproject: Path, editor_cmd: str | None, apply: bool) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    changes: list[str] = []
    if not uproject.exists():
        return {"ok": False, "checks": [{"check": "uproject", "ok": False, "detail": f"introuvable : {uproject}"}]}
    raw = uproject.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    checks.append({"check": "version", "ok": True, "detail": data.get("EngineAssociation", "?")})
    checks.append({"check": "UnrealEditor-Cmd", "ok": bool(editor_cmd and Path(editor_cmd).exists()),
                   "detail": editor_cmd or "unreal.editor_cmd non renseigné"})
    plugins = data.setdefault("Plugins", [])
    by_name = {p.get("Name"): p for p in plugins}
    missing = [n for n in UNREAL_PLUGINS if not by_name.get(n, {}).get("Enabled")]
    if missing:
        changes.append("Activation des plugins : " + ", ".join(missing))
        if apply:
            for n in missing:
                if n in by_name:
                    by_name[n]["Enabled"] = True
                else:
                    plugins.append({"Name": n, "Enabled": True})
            uproject.write_text(json.dumps(data, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8")
    checks.append({"check": "plugins (Python, Sequencer Scripting, Editor Scripting, Movie Render Queue)",
                   "ok": not missing or apply,
                   "detail": "activés" if not missing else
                   ("activés : redémarre l'éditeur Unreal s'il est ouvert" if apply else f"à activer : {', '.join(missing)}")})
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "changes": changes, "applied": apply}
