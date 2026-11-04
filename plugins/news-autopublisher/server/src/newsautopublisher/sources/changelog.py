"""Extraction des dernières sections d'un CHANGELOG Markdown (format Keep a Changelog ou proche)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

HEADING = re.compile(
    r"^##\s+\[?v?(?P<version>[0-9][\w.\-+]*|Unreleased|Non publié)\]?"
    r"(?:\s*[-–—]\s*(?P<date>\d{4}-\d{2}-\d{2}))?",
    re.IGNORECASE,
)


def read_changelog(path: str | Path, max_sections: int = 2) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = HEADING.match(line.strip())
        if m:
            if current:
                sections.append(current)
                if len(sections) >= max_sections:
                    current = None
                    break
            current = {"version": m.group("version"), "date": m.group("date"), "lines": []}
        elif current is not None:
            current["lines"].append(line)
    if current and len(sections) < max_sections:
        sections.append(current)
    return [
        {"version": s["version"], "date": s["date"], "body": "\n".join(s["lines"]).strip()}
        for s in sections
    ]
