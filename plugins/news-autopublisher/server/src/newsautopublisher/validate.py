"""Validation des brouillons : limites des plateformes et détection de fuites d'informations."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .config import AppConfig
from .models import Draft, Issue

X_LIMIT = 280
X_URL_WEIGHT = 23
DISCORD_CONTENT = 2000
DISCORD_TITLE = 256
DISCORD_DESCRIPTION = 4096
DISCORD_EMBED_TOTAL = 6000
YT_TITLE = 100
YT_DESCRIPTION_BYTES = 5000
YT_TAGS_TOTAL = 500
SHORT_MAX_SECONDS = 180

URL_RE = re.compile(
    r"(?:https?://[^\s<>\"]+)"
    r"|(?:\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:com|net|org|io|fr|dev|gg|app|co|me|tv|xyz|eu|be|ch|ca|ly|link|games?)\b(?:/[^\s<>\"]*)?)",
    re.IGNORECASE,
)

# Plages de poids 1 de twitter-text (le reste compte double : emoji, CJK…).
_X_LIGHT = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))
_ZERO_WIDTH = {0x200D, 0xFE0E, 0xFE0F} | set(range(0x1F3FB, 0x1F400))

LEAK_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("error", "jeton GitHub", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,})")),
    ("error", "jeton GitLab", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}")),
    ("error", "clé API", re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{20,}")),
    ("error", "jeton Slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("error", "clé AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("error", "webhook Discord", re.compile(r"discord(?:app)?\.com/api/webhooks/\d+/", re.I)),
    ("error", "clé privée", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "error",
        "secret en clair",
        re.compile(r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\s*[:=]\s*\S{8,}"),
    ),
    ("warning", "chemin local Windows", re.compile(r"\b[A-Za-z]:[\\/][^\s]+")),
    ("warning", "chemin local", re.compile(r"(?:/home/|/Users/|~/)[\w.\-]+")),
    ("warning", "adresse e-mail", re.compile(r"\b[\w.+\-]+@[\w\-]+\.[\w.\-]+\b")),
    (
        "warning",
        "adresse IP privée",
        re.compile(r"\b(?:10|127|192\.168|172\.(?:1[6-9]|2\d|3[01]))(?:\.\d{1,3}){2,3}\b"),
    ),
]


def x_weighted_length(text: str, extra_url: str | None = None) -> int:
    """Longueur pondérée façon X : URL = 23, emoji/CJK = 2, le reste = 1."""
    text = unicodedata.normalize("NFC", text)
    total = 0
    pos = 0
    for m in URL_RE.finditer(text):
        total += _weigh(text[pos : m.start()]) + X_URL_WEIGHT
        pos = m.end()
    total += _weigh(text[pos:])
    if extra_url:
        total += 1 + X_URL_WEIGHT
    return total


def _weigh(chunk: str) -> int:
    n = 0
    for ch in chunk:
        cp = ord(ch)
        if cp in _ZERO_WIDTH:
            continue
        n += 1 if any(lo <= cp <= hi for lo, hi in _X_LIGHT) else 2
    return n


def scan_leaks(text: str) -> list[tuple[str, str, str]]:
    """Renvoie (niveau, type, extrait) pour chaque fuite potentielle."""
    found = []
    for level, label, pat in LEAK_PATTERNS:
        for m in pat.finditer(text or ""):
            excerpt = m.group(0)
            if level == "error":
                excerpt = excerpt[:6] + "…"  # ne jamais recopier un secret en entier
            found.append((level, label, excerpt))
    return found


def _leak_issues(platform: str, field: str, text: str | None) -> list[Issue]:
    issues = []
    for level, label, excerpt in scan_leaks(text or ""):
        issues.append(
            Issue(
                level=level,  # type: ignore[arg-type]
                platform=platform,
                field=field,
                message=f"Fuite possible ({label}) : « {excerpt} ».",
            )
        )
    return issues


def _file_issues(platform: str, field: str, path: str | None, max_mb: float | None = None) -> list[Issue]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return [Issue(level="error", platform=platform, field=field, message=f"Fichier introuvable : {path}")]
    if max_mb is not None and p.stat().st_size > max_mb * 1024 * 1024:
        size = p.stat().st_size / 1024 / 1024
        return [
            Issue(
                level="error",
                platform=platform,
                field=field,
                message=f"{p.name} pèse {size:.1f} Mo (limite {max_mb:g} Mo).",
            )
        ]
    return []


def validate_draft(draft: Draft, cfg: AppConfig) -> list[Issue]:
    issues: list[Issue] = []
    platforms = {cfg.channels[c].platform for c in draft.channels if c in cfg.channels}
    posts = draft.posts

    for missing in sorted(platforms - {p for p in ("discord", "x", "youtube") if getattr(posts, p)}):
        issues.append(
            Issue(
                level="warning",
                platform=missing,
                field="post",
                message="Aucun contenu rédigé pour cette plateforme : ses canaux seront ignorés.",
            )
        )

    if posts.discord:
        d = posts.discord
        limits = min(
            (cfg.channels[c].max_upload_mb for c in draft.channels
             if c in cfg.channels and cfg.channels[c].platform == "discord"),
            default=10.0,
        )
        if len(d.content) > DISCORD_CONTENT:
            issues.append(Issue(level="error", platform="discord", field="content",
                                message=f"{len(d.content)} caractères (max {DISCORD_CONTENT})."))
        if d.title and len(d.title) > DISCORD_TITLE:
            issues.append(Issue(level="error", platform="discord", field="title",
                                message=f"{len(d.title)} caractères (max {DISCORD_TITLE})."))
        if d.description and len(d.description) > DISCORD_DESCRIPTION:
            issues.append(Issue(level="error", platform="discord", field="description",
                                message=f"{len(d.description)} caractères (max {DISCORD_DESCRIPTION})."))
        total = len(d.title or "") + len(d.description or "")
        if total > DISCORD_EMBED_TOTAL:
            issues.append(Issue(level="error", platform="discord", field="embed",
                                message=f"Embed de {total} caractères (max {DISCORD_EMBED_TOTAL})."))
        if not (d.content or d.title or d.description):
            issues.append(Issue(level="error", platform="discord", field="content",
                                message="Message vide."))
        for field, text in (("content", d.content), ("title", d.title), ("description", d.description)):
            issues += _leak_issues("discord", field, text)
        issues += _file_issues("discord", "image", d.image, limits)
        for a in d.attachments:
            issues += _file_issues("discord", "attachments", a, limits)
        if d.attach_short and draft.short.discord_path:
            issues += _file_issues("discord", "short", draft.short.discord_path, limits)

    if posts.x:
        x = posts.x
        n = x_weighted_length(x.text, x.url)
        if n > X_LIMIT:
            issues.append(Issue(level="error", platform="x", field="text",
                                message=f"{n} caractères pondérés (max {X_LIMIT}, URL = 23)."))
        if not x.text.strip():
            issues.append(Issue(level="error", platform="x", field="text", message="Texte vide."))
        if len(x.media) > 4:
            issues.append(Issue(level="error", platform="x", field="media", message="4 médias maximum."))
        issues += _leak_issues("x", "text", x.text)
        for m in x.media:
            issues += _file_issues("x", "media", m)
        x_channels = [c for c in draft.channels if c in cfg.channels and cfg.channels[c].platform == "x"]
        if x.url and any(cfg.channels[c].effective_mode == "api" for c in x_channels):
            issues.append(Issue(level="warning", platform="x", field="url",
                                message="Mode API : un post avec lien coûte environ 0,20 $ (contre 0,015 $)."))

    if posts.youtube:
        y = posts.youtube
        if not y.title.strip():
            issues.append(Issue(level="error", platform="youtube", field="title", message="Titre vide."))
        if len(y.title) > YT_TITLE:
            issues.append(Issue(level="error", platform="youtube", field="title",
                                message=f"{len(y.title)} caractères (max {YT_TITLE})."))
        for field, text in (("title", y.title), ("description", y.description)):
            if "<" in text or ">" in text:
                issues.append(Issue(level="error", platform="youtube", field=field,
                                    message="YouTube refuse les caractères < et >."))
            issues += _leak_issues("youtube", field, text)
        if len(y.description.encode("utf-8")) > YT_DESCRIPTION_BYTES:
            issues.append(Issue(level="error", platform="youtube", field="description",
                                message=f"Description > {YT_DESCRIPTION_BYTES} octets."))
        if sum(len(t) for t in y.tags) + max(len(y.tags) - 1, 0) > YT_TAGS_TOTAL:
            issues.append(Issue(level="error", platform="youtube", field="tags",
                                message=f"Tags > {YT_TAGS_TOTAL} caractères au total."))
        if "#shorts" not in (y.title + " " + y.description).lower():
            issues.append(Issue(level="warning", platform="youtube", field="description",
                                message="Ajoute #Shorts dans le titre ou la description."))
        if "youtube" in platforms:
            if not draft.short.path:
                issues.append(Issue(level="error", platform="youtube", field="video",
                                    message="Aucun short rendu : appelle render_short avant d'approuver."))
            else:
                issues += _file_issues("youtube", "video", draft.short.path)
                if draft.short.duration and draft.short.duration > SHORT_MAX_SECONDS:
                    issues.append(Issue(level="error", platform="youtube", field="video",
                                        message=f"Short de {draft.short.duration:.0f} s (max {SHORT_MAX_SECONDS} s)."))

    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(i.level == "error" for i in issues)
