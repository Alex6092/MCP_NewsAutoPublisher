"""Lecture de l'historique d'un dépôt git local (GitHub, GitLab… peu importe l'hébergeur)."""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

FIELD = "\x1f"
RECORD = "\x1e"
TRAILER = re.compile(
    r"^(Co-Authored-By|Signed-off-by|Claude-Session|Change-Id|Reviewed-by|Generated-by):",
    re.IGNORECASE,
)
DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}|\b(day|days|week|weeks|month|months|ago|jour|jours)\b")


class GitError(Exception):
    pass


def _git(repo: Path, *args: str, check: bool = True) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise GitError("git est introuvable dans le PATH.") from exc
    if check and proc.returncode != 0:
        raise GitError(proc.stderr.strip() or f"git {' '.join(args)} a échoué")
    return proc.stdout


def _is_commit(repo: Path, ref: str) -> bool:
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        capture_output=True,
        text=True,
    )
    return out.returncode == 0


def _clean_body(body: str, limit: int = 600) -> str:
    lines = [ln for ln in body.strip().splitlines() if not TRAILER.match(ln.strip())]
    text = "\n".join(lines).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def collect_changes(
    repo_path: str | Path,
    since: str | None = None,
    max_commits: int = 50,
) -> dict[str, Any]:
    """Résume les changements d'un dépôt.

    since : hash/tag/branche (plage since..HEAD), date ISO ou expression git ("2 weeks ago").
    None : les 30 derniers jours.
    """
    repo = Path(repo_path).expanduser()
    if not repo.exists():
        raise GitError(f"Dépôt introuvable : {repo}")
    if _git(repo, "rev-parse", "--is-inside-work-tree", check=False).strip() != "true":
        raise GitError(f"{repo} n'est pas un dépôt git.")

    head = _git(repo, "rev-parse", "HEAD", check=False).strip() or None
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD", check=False).strip() or None

    log_args = ["log", "--no-merges", f"-n{max_commits}", "--numstat",
                f"--format={RECORD}%H{FIELD}%an{FIELD}%aI{FIELD}%s{FIELD}%b{FIELD}"]
    if since and _is_commit(repo, since):
        mode, rng = "range", f"{since}..HEAD"
        log_args.append(rng)
    else:
        mode = "date"
        rng = since if since and DATE_LIKE.search(since) else "30 days ago"
        log_args.append(f"--since={rng}")

    commits: list[dict[str, Any]] = []
    files: Counter[str] = Counter()
    insertions = deletions = 0
    raw = _git(repo, *log_args, check=False) if head else ""
    for rec in raw.split(RECORD):
        if not rec.strip():
            continue
        parts = rec.split(FIELD)
        if len(parts) < 6:
            continue
        sha, author, date, subject, body, numstat = parts[:6]
        n_files = 0
        for line in numstat.strip().splitlines():
            cols = line.split("\t")
            if len(cols) != 3:
                continue
            add, rem, path = cols
            n_files += 1
            if add.isdigit() and rem.isdigit():
                files[path] += int(add) + int(rem)
                insertions += int(add)
                deletions += int(rem)
            else:
                files[path] += 1  # binaire (asset, texture…)
        commits.append(
            {
                "hash": sha[:10],
                "author": author,
                "date": date,
                "subject": subject.strip(),
                "body": _clean_body(body),
                "files": n_files,
            }
        )

    tags = []
    tag_out = _git(
        repo,
        "for-each-ref",
        "refs/tags",
        "--sort=-creatordate",
        "--count=5",
        "--format=%(refname:short)\x1f%(creatordate:iso-strict)",
        check=False,
    )
    for line in tag_out.splitlines():
        if FIELD in line:
            name, date = line.split(FIELD, 1)
            tags.append({"name": name, "date": date})

    status = _git(repo, "status", "--porcelain=v1", check=False).splitlines()
    uncommitted = {
        "count": len(status),
        "files": [ln[3:] for ln in status[:30]],
        "shortstat": _git(repo, "diff", "--shortstat", "HEAD", check=False).strip() if head else "",
    }

    return {
        "repo": str(repo),
        "branch": branch,
        "head": head,
        "mode": mode,
        "since": rng,
        "commit_count": len(commits),
        "truncated": len(commits) >= max_commits,
        "insertions": insertions,
        "deletions": deletions,
        "top_files": [{"path": p, "changes": c} for p, c in files.most_common(15)],
        "commits": commits,
        "recent_tags": tags,
        "uncommitted": uncommitted,
    }


def head_commit(repo_path: str | Path) -> str | None:
    try:
        out = _git(Path(repo_path).expanduser(), "rev-parse", "HEAD", check=False).strip()
    except GitError:
        return None
    return out or None
