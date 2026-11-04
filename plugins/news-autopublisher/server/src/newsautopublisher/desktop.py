"""Interactions avec le bureau de l'utilisateur : navigateur, Explorateur, presse-papiers.

Désactivées si NAP_NO_OPEN=1 (tests, sessions sans bureau).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path


def enabled() -> bool:
    return os.environ.get("NAP_NO_OPEN", "").strip() not in ("1", "true", "yes")


def open_url(url: str) -> bool:
    if not enabled():
        return False
    try:
        return webbrowser.open(url, new=2)
    except Exception:
        return False


def open_path(path: str | Path) -> bool:
    if not enabled():
        return False
    p = str(Path(path).resolve())
    try:
        if sys.platform == "win32":
            os.startfile(p)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        elif shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            return False
        return True
    except Exception:
        return False


def reveal(path: str | Path) -> bool:
    """Ouvre le dossier du fichier en le sélectionnant (Explorateur Windows)."""
    if not enabled():
        return False
    p = Path(path).resolve()
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", f"/select,{p}"])
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(p)])
            return True
    except Exception:
        return False
    return open_path(p.parent)


def copy_to_clipboard(text: str) -> bool:
    if not enabled():
        return False
    try:
        if sys.platform == "win32":
            # clip.exe accepte l'UTF-16 avec BOM : conserve les accents et les emoji.
            subprocess.run(["clip"], input=text.encode("utf-16"), check=True)
            return True
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
            return True
        for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"]):
            if shutil.which(cmd[0]):
                subprocess.run(cmd, input=text.encode("utf-8"), check=True)
                return True
    except Exception:
        return False
    return False
