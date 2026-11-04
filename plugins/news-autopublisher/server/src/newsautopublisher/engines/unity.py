"""Unity : recherche des plans NapShot dans les scènes et protocole requête / résultat du package.

Le package Unity (engines/unity/com.newsautopublisher.capture) lit une requête JSON :
  - éditeur ouvert : <projet>/Library/NewsAutoPublisher/request.json (NapEditorBridge) ;
  - build : argument « -napRequest <fichier> ».
Il écrit <outputDir>/result.json puis des images dans <outputDir>/<plan>/.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

REQUEST_ARG = "-napRequest"
# GUID fixe de NapShot.cs (voir NapShot.cs.meta dans le package).
NAPSHOT_GUID = "4aa4b1d3463649cbb3bd630023872691"
FIELD = re.compile(r"^\s{2}(shotName|description|duration):\s?(.*)$", re.M)


def _yaml_scalar(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        try:
            value = yaml.safe_load(raw)  # gère les échappements YAML (\xE9, \u00E9, '')
            return value if isinstance(value, str) else raw[1:-1]
        except yaml.YAMLError:
            return raw[1:-1]
    return raw


def scan_shots(project: Path, max_files: int = 400) -> list[dict[str, Any]]:
    """Plans NapShot trouvés dans les scènes (sérialisation texte « Force Text »)."""
    assets = project / "Assets"
    if not assets.exists():
        raise FileNotFoundError(f"Dossier Assets introuvable dans {project}")
    shots: list[dict[str, Any]] = []
    binary_scenes = 0
    for i, scene in enumerate(sorted(assets.rglob("*.unity"))):
        if i >= max_files:
            break
        try:
            text = scene.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not text.startswith("%YAML"):
            binary_scenes += 1
            continue
        if NAPSHOT_GUID not in text:
            continue
        rel = scene.relative_to(project).as_posix()
        for block in text.split("\n--- !u!"):
            if NAPSHOT_GUID not in block or "MonoBehaviour:" not in block:
                continue
            fields = {k: _yaml_scalar(v) for k, v in FIELD.findall(block)}
            try:
                duration = float(fields.get("duration") or 5)
            except ValueError:
                duration = 5.0
            shots.append({
                "name": fields.get("shotName") or "plan",
                "description": fields.get("description", ""),
                "duration": duration,
                "scene": rel,
            })
    if binary_scenes and not shots:
        raise ValueError(
            f"{binary_scenes} scène(s) en sérialisation binaire : active Project Settings > Editor > "
            "Asset Serialization : Force Text pour que Claude puisse lire les plans."
        )
    return shots


def editor_is_open(project: Path) -> bool:
    # Unity crée Temp/UnityLockfile tant que le projet est ouvert dans l'éditeur.
    return (project / "Temp" / "UnityLockfile").exists()


def request_file(project: Path) -> Path:
    return project / "Library" / "NewsAutoPublisher" / "request.json"


def active_file(project: Path) -> Path:
    return project / "Library" / "NewsAutoPublisher" / "active.json"


def build_request(
    job_id: str,
    output_dir: Path,
    shots: list[str],
    procedural: list[dict[str, Any]],
    scene: str,
    mode: str,
    width: int,
    height: int,
    fps: int,
    fmt: str,
    warmup: float,
    msaa: int,
    include_ui: bool,
    supersize: int = 1,
) -> dict[str, Any]:
    return {
        "id": job_id,
        "mode": mode,
        "shots": shots,
        "procedural": procedural,
        "scene": scene,
        "width": width,
        "height": height,
        "fps": fps,
        "supersize": supersize,
        "warmupSeconds": warmup,
        "outputDir": str(output_dir.resolve()),
        "format": fmt,
        "msaa": msaa,
        "includeUi": include_ui,
        "quitWhenDone": True,
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # écriture atomique : l'éditeur ne lit jamais un fichier à moitié écrit


def read_result(output_dir: Path) -> dict[str, Any] | None:
    path = output_dir / "result.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None  # en cours d'écriture


M_NAME = re.compile(r"^\s{2}m_Name: (.*)$", re.M)
PREFAB_NAME = re.compile(r"propertyPath: m_Name\n\s+value: (.*)$", re.M)


def scene_files(project: Path, scene: str | None = None, max_files: int = 400) -> list[Path]:
    if scene:
        p = project / scene
        if not p.exists():
            raise FileNotFoundError(f"Scène introuvable : {scene}")
        return [p]
    return sorted((project / "Assets").rglob("*.unity"))[:max_files]


def scan_objects(project: Path, scene: str | None = None, contains: str | None = None,
                 limit: int = 150) -> list[dict[str, Any]]:
    """Noms des GameObjects (et instances de prefabs renommées) par scène, filtrés par sous-chaîne."""
    needle = (contains or "").lower()
    counts: dict[tuple[str, str], int] = {}
    for f in scene_files(project, scene):
        text = f.read_text(encoding="utf-8", errors="replace")
        if not text.startswith("%YAML"):
            continue
        rel = f.relative_to(project).as_posix()
        names = []
        for block in text.split("\n--- !u!"):
            if block.startswith("1 &") and "\nGameObject:" in block[:80]:
                m = M_NAME.search(block)
                if m:
                    names.append(_yaml_scalar(m.group(1)))
            elif block.startswith("1001 &"):  # instance de prefab : nom surchargé
                names += [_yaml_scalar(n) for n in PREFAB_NAME.findall(block)]
        for n in names:
            if n and (not needle or needle in n.lower()):
                counts[(rel, n)] = counts.get((rel, n), 0) + 1
    out = [{"scene": sc, "name": n, "count": c} for (sc, n), c in counts.items()]
    out.sort(key=lambda o: (o["scene"], o["name"].lower()))
    return out[:limit]


def build_scenes(project: Path) -> list[str]:
    """Scènes activées dans les Build Settings, dans l'ordre."""
    f = project / "ProjectSettings" / "EditorBuildSettings.asset"
    if not f.exists():
        return []
    scenes, enabled = [], None
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("- enabled:"):
            enabled = s.endswith("1")
        elif s.startswith("path:") and enabled:
            scenes.append(s.split(":", 1)[1].strip())
    return scenes


def scene_for_target(project: Path, target: str) -> str | None:
    """Première scène contenant un objet de ce nom (exact, puis partiel)."""
    exact = [o for o in scan_objects(project, contains=target, limit=1000) if o["name"] == target]
    if exact:
        return exact[0]["scene"]
    partial = scan_objects(project, contains=target, limit=1)
    return partial[0]["scene"] if partial else None
