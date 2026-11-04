"""Unreal Engine : rendu de Level Sequences avec Movie Render Queue en ligne de commande.

Commande (procédure officielle de rendu MRQ hors éditeur) :
  UnrealEditor-Cmd.exe Projet.uproject /Game/Maps/Carte -game
      -LevelSequence=/Game/Cinematics/Seq.Seq -MoviePipelineConfig=/Game/…/Preset.Preset
      -windowed -resx=1280 -resy=720 -log -Unattended -NoLoadingScreen -NoSplash
Le preset (créé une fois dans la fenêtre Movie Render Queue) fixe la résolution, le format
(PNG/JPG conseillé) et le dossier de sortie (par défaut <projet>/Saved/MovieRenders).
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

FRAME = re.compile(r"^(?P<prefix>.*?)(?P<num>\d+)\.(?P<ext>png|jpe?g|bmp)$", re.IGNORECASE)
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv"}


def object_path(path: str) -> str:
    """'/Game/Cinematics/Seq' -> '/Game/Cinematics/Seq.Seq' (forme attendue par MRQ)."""
    if "." in path.rsplit("/", 1)[-1]:
        return path
    name = path.rstrip("/").rsplit("/", 1)[-1]
    return f"{path}.{name}"


def build_command(
    editor_cmd: str,
    uproject: str,
    map_path: str,
    sequence: str,
    preset: str | None,
    resx: int,
    resy: int,
    extra: list[str],
) -> list[str]:
    cmd = [editor_cmd, uproject, map_path, "-game", f"-LevelSequence={object_path(sequence)}"]
    if preset:
        cmd.append(f"-MoviePipelineConfig={object_path(preset)}")
    cmd += ["-windowed", f"-resx={resx}", f"-resy={resy}", "-log", "-Unattended", "-NoLoadingScreen",
            "-NoSplash"]
    return cmd + list(extra)


def default_output_dir(uproject: Path) -> Path:
    return uproject.parent / "Saved" / "MovieRenders"


def collect_output(output_dir: Path, since: float) -> tuple[list[Path], Path | None]:
    """Images (séquence la plus longue) ou vidéo produites après `since` (horodatage)."""
    if not output_dir.exists():
        return [], None
    groups: dict[tuple[str, str], list[tuple[int, Path]]] = defaultdict(list)
    videos: list[Path] = []
    for f in output_dir.rglob("*"):
        if not f.is_file() or f.stat().st_mtime < since - 1:
            continue
        if f.suffix.lower() in VIDEO_EXT:
            videos.append(f)
            continue
        m = FRAME.match(f.name)
        if m:
            groups[(str(f.parent), m["prefix"])].append((int(m["num"]), f))
    video = max(videos, key=lambda p: p.stat().st_size) if videos else None
    if not groups:
        return [], video
    best = max(groups.values(), key=len)
    return [p for _, p in sorted(best)], video
