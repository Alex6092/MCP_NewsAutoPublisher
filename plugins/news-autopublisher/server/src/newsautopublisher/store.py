"""Persistance SQLite : brouillons, publications, médias."""

from __future__ import annotations

import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Draft, PublishResult, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    language TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS drafts_project ON drafts(project, created_at);

CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id TEXT NOT NULL,
    project TEXT NOT NULL,
    channel TEXT NOT NULL,
    platform TEXT NOT NULL,
    status TEXT NOT NULL,
    url TEXT,
    external_id TEXT,
    message TEXT,
    cost_usd REAL NOT NULL DEFAULT 0,
    head_commit TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS publications_draft ON publications(draft_id, channel);
CREATE INDEX IF NOT EXISTS publications_project ON publications(project, created_at);

CREATE TABLE IF NOT EXISTS media (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    duration REAL,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS media_project ON media(project, created_at);
"""

ACTIVE_PUBLICATION = ("published", "pending_manual")


class Store:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as conn, conn:
            conn.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------ brouillons
    def new_draft_id(self, project: str, language: str) -> str:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"{day}-{project}-{language}-{secrets.token_hex(2)}"

    def save_draft(self, draft: Draft) -> Draft:
        draft.updated_at = utcnow()
        with closing(self._conn()) as conn, conn:
            conn.execute(
                "INSERT INTO drafts(id, project, language, status, created_at, updated_at, data)"
                " VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET status=excluded.status,"
                " updated_at=excluded.updated_at, data=excluded.data",
                (
                    draft.id,
                    draft.project,
                    draft.language,
                    draft.status,
                    draft.created_at,
                    draft.updated_at,
                    draft.model_dump_json(),
                ),
            )
        return draft

    def get_draft(self, draft_id: str) -> Draft | None:
        with closing(self._conn()) as conn:
            row = conn.execute("SELECT data FROM drafts WHERE id=?", (draft_id,)).fetchone()
        return Draft.model_validate_json(row["data"]) if row else None

    def list_drafts(
        self, project: str | None = None, status: str | None = None, limit: int = 20
    ) -> list[Draft]:
        sql, args = "SELECT data FROM drafts WHERE 1=1", []
        if project:
            sql += " AND project=?"
            args.append(project)
        if status:
            sql += " AND status=?"
            args.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with closing(self._conn()) as conn:
            rows = conn.execute(sql, args).fetchall()
        return [Draft.model_validate_json(r["data"]) for r in rows]

    # ------------------------------------------------------------------ publications
    def record_publication(
        self, draft: Draft, result: PublishResult, head_commit: str | None = None
    ) -> int:
        now = utcnow()
        with closing(self._conn()) as conn, conn:
            existing = conn.execute(
                "SELECT id FROM publications WHERE draft_id=? AND channel=?"
                " ORDER BY id DESC LIMIT 1",
                (draft.id, result.channel),
            ).fetchone()
            values = (
                result.status,
                result.url,
                result.external_id,
                result.message,
                result.cost_usd,
                head_commit or draft.head_commit,
                now,
            )
            if existing:
                conn.execute(
                    "UPDATE publications SET status=?, url=?, external_id=?, message=?,"
                    " cost_usd=?, head_commit=?, updated_at=? WHERE id=?",
                    (*values, existing["id"]),
                )
                return int(existing["id"])
            cur = conn.execute(
                "INSERT INTO publications(status, url, external_id, message, cost_usd,"
                " head_commit, updated_at, draft_id, project, channel, platform, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (*values, draft.id, draft.project, result.channel, result.platform, now),
            )
            return int(cur.lastrowid)

    def get_publication(self, draft_id: str, channel: str) -> dict[str, Any] | None:
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT * FROM publications WHERE draft_id=? AND channel=? ORDER BY id DESC LIMIT 1",
                (draft_id, channel),
            ).fetchone()
        return dict(row) if row else None

    def list_publications(
        self, project: str | None = None, draft_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM publications WHERE 1=1", []
        if project:
            sql += " AND project=?"
            args.append(project)
        if draft_id:
            sql += " AND draft_id=?"
            args.append(draft_id)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with closing(self._conn()) as conn:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]

    def last_published_commit(self, project: str) -> str | None:
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT head_commit FROM publications WHERE project=? AND status='published'"
                " AND head_commit IS NOT NULL ORDER BY id DESC LIMIT 1",
                (project,),
            ).fetchone()
        return row["head_commit"] if row else None

    def spend_this_month(self, channel: str) -> float:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd),0) AS s FROM publications"
                " WHERE channel=? AND status='published' AND substr(created_at,1,7)=?",
                (channel, month),
            ).fetchone()
        return float(row["s"])

    # ------------------------------------------------------------------ médias
    def add_media(
        self,
        project: str,
        path: Path,
        kind: str,
        source: str,
        width: int | None = None,
        height: int | None = None,
        duration: float | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        media_id = f"m{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{secrets.token_hex(2)}"
        row = {
            "id": media_id,
            "project": project,
            "path": str(path),
            "kind": kind,
            "source": source,
            "width": width,
            "height": height,
            "duration": duration,
            "note": note,
            "created_at": utcnow(),
        }
        with closing(self._conn()) as conn, conn:
            conn.execute(
                "INSERT INTO media(id, project, path, kind, source, width, height, duration, note,"
                " created_at) VALUES (:id,:project,:path,:kind,:source,:width,:height,:duration,"
                ":note,:created_at)",
                row,
            )
        return row

    def get_media(self, media_id: str) -> dict[str, Any] | None:
        with closing(self._conn()) as conn:
            row = conn.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
        return dict(row) if row else None

    def list_media(
        self, project: str, kind: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM media WHERE project=?", [project]
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with closing(self._conn()) as conn:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]

