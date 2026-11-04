"""Logique métier (indépendante du protocole MCP, testable directement)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import desktop
from .capture import obs as obs_mod
from .capture import screen
from .capture.windows import CaptureError, is_windows, list_windows
from .config import (
    AppConfig,
    ConfigCache,
    ConfigError,
    ProjectConfig,
    UnityConfig,
    UnrealConfig,
    get_secret,
    init_data_dir,
)
from .ffmpeg import FFmpegError, find_ffmpeg, find_ffprobe, probe
from .models import (
    Draft,
    DraftPosts,
    DiscordPost,
    PublishResult,
    VoiceInfo,
    XPost,
    YouTubePost,
    utcnow,
)
from .paths import Paths, package_file
from .preview import write_preview
from .publishers import discord_bot, x_api, youtube_api
from .publishers.discord import publish_discord
from .publishers.x_intent import publish_x_intent
from .publishers.youtube_manual import publish_youtube_manual
from .sources.changelog import read_changelog
from .sources.git import GitError, collect_changes, head_commit
from .store import Store
from .validate import has_errors, validate_draft
from .engines import unity as unity_engine
from .engines import unreal as unreal_engine
from .engines import setup as engine_setup_mod
from .engines.jobs import EngineJob, JobManager
from .ffmpeg import run as run_ffmpeg
from .video.render import Brand, Renderer, RenderSettings
from .video.storyboard import Storyboard
from .voice import elevenlabs, piper_tts, recorded
from .voice.text import VoiceError, format_for_recording

USER_ERRORS = (ConfigError, GitError, CaptureError, FFmpegError, VoiceError)


class UserError(Exception):
    """Erreur à afficher telle quelle à l'utilisateur."""


def _dry_run_default() -> bool:
    return os.environ.get("NAP_DRY_RUN", "").strip().lower() in ("1", "true", "yes")


def _norm(p: str | Path) -> str:
    return os.path.normcase(str(Path(p).expanduser().resolve()))


class App:
    def __init__(self, paths: Paths | None = None):
        self.paths = paths or Paths.default()
        self.paths.ensure()
        self.store = Store(self.paths.db)
        self.config_cache = ConfigCache(self.paths)
        self.recordings: dict[str, screen.Recording] = {}
        self.jobs = JobManager()

    # ------------------------------------------------------------------ configuration
    @property
    def cfg(self) -> AppConfig:
        return self.config_cache.get()

    def init_config(self) -> dict[str, Any]:
        created = init_data_dir(self.paths)
        if created:
            desktop.open_path(self.paths.config_file)
        return {
            "data_dir": str(self.paths.root),
            "created": created,
            "next": "Complète config.yaml (projets, chemins des dépôts, canaux) et .env (URL des webhooks). "
            "Les changements sont pris en compte immédiatement.",
        }

    def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {"data_dir": str(self.paths.root), "platform": sys.platform,
                               "python": sys.executable}
        try:
            cfg = self.cfg
            out["config"] = "ok"
        except ConfigError as exc:
            out["config"] = str(exc)
            return out
        try:
            ff = find_ffmpeg(cfg.video.ffmpeg)
            out["ffmpeg"] = ff
        except FFmpegError as exc:
            out["ffmpeg"] = str(exc)
        out["projects"] = {
            k: {
                "name": p.name,
                "repo_path": p.repo_path,
                "repo_found": bool(p.repo_path and Path(p.repo_path).expanduser().exists()),
                "languages": p.languages,
                "channels": p.channels,
            }
            for k, p in cfg.projects.items()
        }
        def present(env: str | None) -> str:
            return "présent" if get_secret(env) else f"manquant ({env} dans .env)"

        chans = {}
        for k, c in cfg.channels.items():
            info: dict[str, Any] = {"type": c.type, "mode": c.effective_mode}
            if c.type == "discord_webhook":
                info["webhook"] = present(c.webhook_env)
                if c.crosspost:
                    info["bot"] = present(c.bot_token_env)
            elif c.type == "x" and c.effective_mode == "api":
                missing = [e for e in (c.api_key_env, c.api_secret_env, c.access_token_env, c.access_secret_env)
                           if not get_secret(e)]
                info["keys"] = "présentes" if not missing else f"manquantes : {', '.join(missing)}"
                info["budget"] = f"{self.store.spend_this_month(k):.3f} $ dépensés sur {c.monthly_budget_usd:.2f} $ ce mois-ci"
            elif c.type == "youtube" and c.effective_mode == "api":
                secret, token = self._yt_files(k, c)
                info["client_secret"] = "présent" if secret.exists() else f"manquant ({secret})"
                info["compte"] = "connecté" if token.exists() else "non connecté (connect_account)"
                info["audited"] = c.audited
            chans[k] = info
        out["channels"] = chans
        voices_dir = self.paths.models / "piper"
        out["piper_voices"] = sorted(p.stem for p in voices_dir.glob("*.onnx")) if voices_dir.exists() else []
        try:
            import faster_whisper  # noqa: F401

            out["whisper"] = "installé"
        except ImportError:
            out["whisper"] = (
                "absent : alignement de ta voix par détection des silences. Pour l'activer : "
                f'uv pip install --python "{sys.executable}" faster-whisper'
            )
        if cfg.obs.enabled:
            try:
                with obs_mod.OBS(cfg.obs) as o:
                    out["obs"] = f"connecté, scène « {o.current_scene()} »"
            except CaptureError as exc:
                out["obs"] = str(exc)
        out["dry_run"] = _dry_run_default()
        return out

    # ------------------------------------------------------------------ projets & sources
    def list_projects(self) -> list[dict[str, Any]]:
        cfg = self.cfg
        return [
            {"key": k, "name": p.name, "engine": p.engine, "languages": p.languages, "repo_path": p.repo_path,
             "pitch": p.pitch, "tone": p.tone, "audience": p.audience, "links": p.links,
             "hashtags": p.hashtags, "channels": p.channels}
            for k, p in cfg.projects.items()
        ]

    def detect_project(self, cwd: str) -> dict[str, Any]:
        target = _norm(cwd)
        best: tuple[int, str] | None = None
        for key, p in self.cfg.projects.items():
            if not p.repo_path:
                continue
            root = _norm(p.repo_path)
            if target == root or target.startswith(root.rstrip(os.sep) + os.sep):
                if best is None or len(root) > best[0]:
                    best = (len(root), key)
        if not best:
            return {"project": None, "message": "Aucun projet configuré ne contient ce dossier."}
        return {"project": best[1], "name": self.cfg.projects[best[1]].name}

    def collect_changes(self, project: str, since: str | None = "last_post", max_commits: int = 40) -> dict[str, Any]:
        p = self.cfg.project(project)
        if not p.repo_path:
            raise UserError(f"Le projet {project} n'a pas de repo_path dans config.yaml.")
        resolved = since
        if since in (None, "", "last_post"):
            resolved = self.store.last_published_commit(project)
        result = collect_changes(p.repo_path, resolved, max_commits)
        result["since_requested"] = since
        if p.changelog:
            result["changelog"] = read_changelog(Path(p.repo_path).expanduser() / p.changelog)
        recent = self.store.list_publications(project=project, limit=5)
        result["recent_publications"] = [
            {"draft_id": r["draft_id"], "channel": r["channel"], "status": r["status"], "url": r["url"],
             "date": r["created_at"]}
            for r in recent
        ]
        return result

    def publication_history(self, project: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        return self.store.list_publications(project=project, limit=limit)

    # ------------------------------------------------------------------ brouillons
    def _refresh(self, draft: Draft) -> Draft:
        draft.issues = validate_draft(draft, self.cfg)
        return self.store.save_draft(draft)

    def _get(self, draft_id: str) -> Draft:
        d = self.store.get_draft(draft_id)
        if not d:
            raise UserError(f"Brouillon introuvable : {draft_id}")
        return d

    def _resolve_media(self, value: str | None) -> str | None:
        if not value:
            return value
        if value.startswith("m") and not Path(value).exists():
            row = self.store.get_media(value)
            if row:
                return row["path"]
        return str(Path(value).expanduser())

    def _resolve_posts(self, posts: DraftPosts) -> DraftPosts:
        if posts.discord:
            posts.discord.image = self._resolve_media(posts.discord.image)
            posts.discord.attachments = [self._resolve_media(a) for a in posts.discord.attachments]
        if posts.x:
            posts.x.media = [self._resolve_media(m) for m in posts.x.media]
        return posts

    def create_draft(
        self,
        project: str,
        language: str,
        topic: str,
        discord: DiscordPost | None = None,
        x: XPost | None = None,
        youtube: YouTubePost | None = None,
        notes: str = "",
        channels: list[str] | None = None,
    ) -> Draft:
        cfg = self.cfg
        p = cfg.project(project)
        if language not in p.languages:
            raise UserError(f"Langue « {language} » non prévue pour {p.name} (langues : {', '.join(p.languages)}).")
        chans = channels if channels is not None else cfg.channels_for(project, language)
        for c in chans:
            cfg.channel(c)
        draft = Draft(
            id=self.store.new_draft_id(project, language),
            project=project,
            language=language,
            topic=topic,
            channels=chans,
            posts=self._resolve_posts(DraftPosts(discord=discord, x=x, youtube=youtube)),
            head_commit=head_commit(p.repo_path) if p.repo_path else None,
            notes=notes,
        )
        self.paths.draft_dir(draft.id).mkdir(parents=True, exist_ok=True)
        return self._refresh(draft)

    def update_draft(
        self,
        draft_id: str,
        topic: str | None = None,
        discord: DiscordPost | None = None,
        x: XPost | None = None,
        youtube: YouTubePost | None = None,
        notes: str | None = None,
        channels: list[str] | None = None,
        remove_platforms: list[str] | None = None,
    ) -> Draft:
        d = self._get(draft_id)
        if d.status in ("published", "discarded"):
            raise UserError(f"Le brouillon {draft_id} est {d.status} : crée-en un nouveau.")
        if topic is not None:
            d.topic = topic
        if notes is not None:
            d.notes = notes
        if channels is not None:
            for c in channels:
                self.cfg.channel(c)
            d.channels = channels
        posts = d.posts
        if discord is not None:
            posts.discord = discord
        if x is not None:
            posts.x = x
        if youtube is not None:
            posts.youtube = youtube
        for plat in remove_platforms or []:
            if plat in ("discord", "x", "youtube"):
                setattr(posts, plat, None)
        d.posts = self._resolve_posts(posts)
        if d.status == "approved":
            d.status = "draft"  # toute modification impose une nouvelle validation
            d.approved_at = None
        return self._refresh(d)

    def get_draft(self, draft_id: str) -> Draft:
        return self._refresh(self._get(draft_id))

    def list_drafts(self, project: str | None = None, status: str | None = None, limit: int = 20) -> list[dict]:
        return [
            {"id": d.id, "project": d.project, "language": d.language, "topic": d.topic, "status": d.status,
             "short": bool(d.short.path), "updated_at": d.updated_at}
            for d in self.store.list_drafts(project, status, limit)
        ]

    def discard_draft(self, draft_id: str) -> Draft:
        d = self._get(draft_id)
        if d.status == "published":
            raise UserError("Un brouillon déjà publié ne peut pas être abandonné.")
        d.status = "discarded"
        return self.store.save_draft(d)

    def render_preview(self, draft_id: str, open_browser: bool = True) -> dict[str, Any]:
        d = self._refresh(self._get(draft_id))
        path = write_preview(d, self.cfg, self.paths.draft_dir(d.id))
        opened = desktop.open_path(path) if open_browser else False
        return {"preview": str(path), "opened": opened, "issues": [i.model_dump() for i in d.issues]}

    # ------------------------------------------------------------------ médias & captures
    def _ffmpeg(self) -> tuple[str, str]:
        ff = find_ffmpeg(self.cfg.video.ffmpeg)
        return ff, find_ffprobe(ff)

    def _register(self, project: str, path: Path, source: str, note: str | None = None) -> dict[str, Any]:
        _, fp = self._ffmpeg()
        info = probe(path, fp)
        return self.store.add_media(project, path, info["kind"], source, info["width"], info["height"],
                                    info["duration"], note)

    def _media_path(self, project: str, kind: str, ext: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        d = self.paths.media_dir(project)
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{stamp}-{kind}{ext}"

    def _backend(self, p: ProjectConfig, backend: str | None) -> str:
        b = backend or p.capture.backend
        if b != "auto":
            return b
        if self.cfg.obs.enabled:
            try:
                with obs_mod.OBS(self.cfg.obs):
                    return "obs"
            except CaptureError:
                pass
        return "gdigrab"

    def list_windows(self) -> list[dict[str, Any]]:
        return [w.as_dict() for w in list_windows()]

    def capture_screenshot(self, project: str, window_title: str | None = None, backend: str | None = None,
                           note: str | None = None) -> dict[str, Any]:
        p = self.cfg.project(project)
        b = self._backend(p, backend)
        out = self._media_path(project, "screenshot", ".png")
        if b == "obs":
            with obs_mod.OBS(self.cfg.obs) as o:
                o.screenshot(out, p.capture.obs_scene)
        else:
            ff, _ = self._ffmpeg()
            screen.screenshot(ff, out, b, window_title or p.capture.window_title, p.capture.monitor)
        if not out.exists():
            raise UserError("La capture n'a produit aucun fichier.")
        return {**self._register(project, out, f"screenshot:{b}", note), "backend": b}

    def start_recording(self, project: str, window_title: str | None = None, max_seconds: float = 60,
                        backend: str | None = None) -> dict[str, Any]:
        p = self.cfg.project(project)
        b = self._backend(p, backend)
        rec_id = f"rec{int(time.time())}"
        if b == "obs":
            with obs_mod.OBS(self.cfg.obs) as o:
                o.start_record(p.capture.obs_scene)
            self.recordings[rec_id] = screen.Recording(rec_id, project, "obs", Path(), None)
        else:
            ff, _ = self._ffmpeg()
            out = self._media_path(project, "clip", ".mp4")
            self.recordings[rec_id] = screen.start_recording(
                ff, rec_id, project, out, b, window_title or p.capture.window_title, p.capture.fps,
                max_seconds, p.capture.monitor)
        return {"recording_id": rec_id, "backend": b,
                "message": f"Enregistrement lancé ({b}). Appelle stop_recording quand la séquence est finie"
                           + ("." if b == "obs" else f" (arrêt automatique après {max_seconds:.0f} s).")}

    def stop_recording(self, recording_id: str, note: str | None = None) -> dict[str, Any]:
        rec = self.recordings.pop(recording_id, None)
        if not rec:
            raise UserError(f"Enregistrement inconnu : {recording_id} (le serveur a peut-être redémarré).")
        if rec.backend == "obs":
            with obs_mod.OBS(self.cfg.obs) as o:
                src = o.stop_record()
            time.sleep(1.0)
            out = self._media_path(rec.project, "clip", src.suffix or ".mp4")
            shutil.copyfile(src, out)
        else:
            out = rec.stop()
        return {**self._register(rec.project, out, f"recording:{rec.backend}", note),
                "seconds": round(time.time() - rec.started, 1)}

    def save_replay(self, project: str, note: str | None = None) -> dict[str, Any]:
        self.cfg.project(project)
        with obs_mod.OBS(self.cfg.obs) as o:
            src = o.save_replay()
        out = self._media_path(project, "replay", src.suffix or ".mp4")
        shutil.copyfile(src, out)
        return self._register(project, out, "obs:replay", note)

    def import_media(self, project: str, path: str, note: str | None = None, copy: bool = True) -> dict[str, Any]:
        self.cfg.project(project)
        src = Path(path).expanduser()
        if not src.exists():
            raise UserError(f"Fichier introuvable : {src}")
        out = src
        if copy:
            out = self._media_path(project, "import", src.suffix.lower())
            shutil.copyfile(src, out)
        return self._register(project, out, "import", note or src.name)

    def list_media(self, project: str, kind: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        return self.store.list_media(project, kind, limit)

    # ------------------------------------------------------------------ captures moteur (phase 4)
    def _unity_root(self, p: ProjectConfig) -> Path:
        root = (p.unity.project_path if p.unity else None) or p.repo_path
        if not root:
            raise UserError("Projet Unity sans chemin : renseigne repo_path ou unity.project_path.")
        return Path(root).expanduser()

    def list_engine_shots(self, project: str) -> dict[str, Any]:
        p = self.cfg.project(project)
        if p.engine == "unity":
            root = self._unity_root(p)
            try:
                shots = unity_engine.scan_shots(root)
            except (FileNotFoundError, ValueError) as exc:
                raise UserError(str(exc)) from exc
            uc = p.unity
            build = uc.build_exe if uc else None
            return {
                "engine": "unity",
                "shots": shots,
                "editor_open": unity_engine.editor_is_open(root),
                "build_exe": build,
                "build_found": bool(build and Path(build).expanduser().exists()),
                "default_target": uc.target if uc else "editor",
                "hint": None if shots else "Aucun NapShot : installe le package Unity et crée des plans "
                                           "(clic droit > NewsAutoPublisher > Nap Shot).",
            }
        if p.engine == "unreal":
            rc = p.unreal
            if not rc or not rc.shots:
                raise UserError("Aucun plan Unreal configuré (section unreal.shots du projet dans config.yaml).")
            return {
                "engine": "unreal",
                "shots": [{"name": k, "map": v.map, "sequence": v.sequence, "fps": v.fps,
                           "description": v.description} for k, v in rc.shots.items()],
                "editor_cmd_found": bool(rc.editor_cmd and Path(rc.editor_cmd).exists()),
                "uproject_found": bool(rc.uproject and Path(rc.uproject).exists()),
                "preset": rc.preset,
            }
        raise UserError(f"Moteur « {p.engine} » sans capture automatique (unity ou unreal).")

    def list_engine_targets(self, project: str, scene: str | None = None, contains: str | None = None,
                            limit: int = 150) -> dict[str, Any]:
        p = self.cfg.project(project)
        if p.engine == "unity":
            root = self._unity_root(p)
            try:
                objects = unity_engine.scan_objects(root, scene, contains, limit)
            except FileNotFoundError as exc:
                raise UserError(str(exc)) from exc
            return {"engine": "unity", "objects": objects, "build_scenes": unity_engine.build_scenes(root),
                    "hint": "Utilise ces noms comme « target » de plans procéduraux (engine_capture)."}
        if p.engine == "unreal":
            rc = self._unreal_ready(p)
            map_path = scene or rc.default_map or next((s.map for s in rc.shots.values()), None)
            if not map_path:
                raise UserError("Précise la map (scene=/Game/Maps/…) ou unreal.default_map.")
            list_id = f"lst{datetime.now().strftime('%Y%m%d%H%M%S')}"
            job = EngineJob(list_id, project, "unreal", "python", "list", [],
                            str(self.paths.media_dir(project) / "engine" / list_id))
            req = {"mode": "list_actors", "map": map_path, "contains": contains, "limit": 3000}
            try:
                self.jobs.submit(job, lambda j: self._run_unreal_python(j, rc, req, None))
            except RuntimeError as exc:
                raise UserError(str(exc)) from exc
            return {**job.summary(), "next": "Unreal démarre (1 à 3 min) : engine_capture_status(job_id, "
                                              "wait_seconds=300) renverra la liste dans data.actors."}
        raise UserError(f"Moteur « {p.engine} » sans capture automatique.")

    def engine_setup(self, project: str, apply: bool = False) -> dict[str, Any]:
        p = self.cfg.project(project)
        if p.engine == "unity":
            return {"engine": "unity", **engine_setup_mod.unity_setup(self._unity_root(p), apply)}
        if p.engine == "unreal":
            rc = p.unreal or UnrealConfig()
            if not rc.uproject:
                raise UserError("Renseigne unreal.uproject (et unreal.editor_cmd) dans config.yaml.")
            return {"engine": "unreal", **engine_setup_mod.unreal_setup(Path(rc.uproject).expanduser(),
                                                                         rc.editor_cmd, apply)}
        raise UserError(f"Moteur « {p.engine} » non pris en charge.")

    def _unreal_ready(self, p: ProjectConfig) -> UnrealConfig:
        rc = p.unreal
        if not rc:
            raise UserError("Section unreal absente du projet dans config.yaml.")
        for path, label in ((rc.editor_cmd, "unreal.editor_cmd"), (rc.uproject, "unreal.uproject")):
            if not path or not Path(path).exists():
                raise UserError(f"{label} introuvable : {path}")
        return rc

    def _policy_refusal(self, p: ProjectConfig, editor: bool) -> str | None:
        policy = p.capture.engine_auto
        if policy == "never":
            return ("Captures automatiques désactivées (capture.engine_auto: never) : demande l'accord de "
                    "l'utilisateur, puis relance avec user_requested=true.")
        if editor and policy == "background":
            return ("Cette capture ferait passer l'éditeur Unity ouvert en mode Play : demande d'abord l'accord "
                    "de l'utilisateur, puis relance avec user_requested=true (ou configure unity.build_exe pour "
                    "des captures automatiques sans toucher à l'éditeur).")
        return None

    def engine_capture(self, project: str, shots: list[str] | None = None, mode: str = "video",
                       target: str | None = None, procedural: list[dict] | None = None, scene: str | None = None,
                       user_requested: bool = False) -> dict[str, Any]:
        p = self.cfg.project(project)
        job_id = f"cap{datetime.now().strftime('%Y%m%d%H%M%S')}"
        out_dir = self.paths.media_dir(project) / "engine" / job_id
        ff, _ = self._ffmpeg()
        procedural = list(procedural or [])
        names = [s["name"] for s in procedural]
        if len(set(names)) != len(names):
            raise UserError("Chaque plan procédural doit avoir un nom unique.")

        if p.engine == "unity":
            uc = p.unity or UnityConfig()
            root = self._unity_root(p)
            try:
                available = unity_engine.scan_shots(root)
            except ValueError:
                if not (procedural and scene):
                    raise
                available = []
            except FileNotFoundError as exc:
                raise UserError(str(exc)) from exc
            wanted = shots if shots is not None else ([] if procedural else [s["name"] for s in available])
            missing = [n for n in wanted if n not in {s["name"] for s in available}]
            if missing:
                raise UserError(f"Plans introuvables dans les scènes : {', '.join(missing)}.")
            if not wanted and not procedural:
                raise UserError("Rien à capturer : aucun NapShot dans le projet et aucun plan procédural demandé.")

            groups: dict[str, dict[str, list]] = {}
            for s in available:
                if s["name"] in wanted:
                    groups.setdefault(s["scene"], {"shots": [], "procedural": []})["shots"].append(s["name"])
            for spec in procedural:
                sc = scene or unity_engine.scene_for_target(root, spec["target"])
                if not sc:
                    raise UserError(f"Objet « {spec['target']} » introuvable dans les scènes : vérifie le nom "
                                    "(list_engine_targets) ou précise scene.")
                groups.setdefault(sc, {"shots": [], "procedural": []})["procedural"].append(spec)

            build_ok = bool(uc.build_exe and Path(uc.build_exe).expanduser().exists())
            tgt = target or uc.target
            notes = []
            if not user_requested:
                refusal = self._policy_refusal(p, editor=(tgt == "editor"))
                if refusal and tgt == "editor" and build_ok and p.capture.engine_auto == "background":
                    tgt, refusal = "build", None
                    notes.append("Capture automatique via le build, sans toucher à ton éditeur.")
                if refusal:
                    raise UserError(refusal)
            if tgt == "editor" and not unity_engine.editor_is_open(root):
                if build_ok:
                    tgt = "build"
                    notes.append("Éditeur Unity fermé : capture via le build.")
                else:
                    raise UserError("L'éditeur Unity n'a pas ce projet ouvert et aucun build_exe n'est configuré.")
            if tgt == "build":
                if not build_ok:
                    raise UserError(f"Build Unity introuvable : {uc.build_exe} (unity.build_exe).")
                stale = self._build_staleness(Path(uc.build_exe).expanduser(), p.repo_path)
                if stale:
                    notes.append(stale)
            descriptions = {s["name"]: s["description"] for s in available}
            descriptions.update({s["name"]: f"{s.get('move', 'orbit')} autour de {s['target']}" for s in procedural})
            job = EngineJob(job_id, project, "unity", tgt, mode, wanted + names, str(out_dir), message=" ".join(notes))
            work = lambda j: self._run_unity(j, uc, root, groups, descriptions, ff)  # noqa: E731

        elif p.engine == "unreal":
            rc = self._unreal_ready(p)
            if mode != "video":
                raise UserError("Unreal : seul le mode vidéo est pris en charge ; pour l'éditeur lui-même, "
                                "utilise capture_screenshot / start_recording sur sa fenêtre.")
            if not user_requested:
                refusal = self._policy_refusal(p, editor=False)
                if refusal:
                    raise UserError(refusal)
            wanted = shots if shots is not None else ([] if procedural else list(rc.shots))
            missing = [n for n in wanted if n not in rc.shots]
            if missing:
                raise UserError(f"Plans Unreal inconnus : {', '.join(missing)} (connus : {', '.join(rc.shots) or 'aucun'}).")
            if not wanted and not procedural:
                raise UserError("Rien à rendre : aucun plan configuré (unreal.shots) ni procédural demandé.")
            if rc.render_mode == "cli":
                if procedural:
                    raise UserError("Les plans procéduraux demandent render_mode: python (mode par défaut).")
                if not rc.preset and any(not rc.shots[n].preset for n in wanted):
                    raise UserError("Preset Movie Render Queue manquant (unreal.preset) : nécessaire en "
                                    "render_mode: cli (le mode python n'en a pas besoin).")
                job = EngineJob(job_id, project, "unreal", "cli", mode, wanted, str(out_dir))
                work = lambda j: self._run_unreal(j, rc, ff)  # noqa: E731
            else:
                default_map = scene or rc.default_map or next((s.map for s in rc.shots.values()), None)
                if procedural and not default_map:
                    raise UserError("Précise la map des plans procéduraux (scene=/Game/Maps/…) ou unreal.default_map.")
                specs = [{"name": n, "sequence": rc.shots[n].sequence, "map": rc.shots[n].map} for n in wanted]
                specs += [{**spec, "map": spec.get("map") or default_map} for spec in procedural]
                req = {"mode": "render", "map": default_map, "shots": specs}
                fps = {n: rc.shots[n].fps for n in wanted}
                descriptions = {n: rc.shots[n].description for n in wanted}
                descriptions.update({s["name"]: f"{s.get('move', 'orbit')} autour de {s['target']}" for s in procedural})
                job = EngineJob(job_id, project, "unreal", "python", mode, wanted + names, str(out_dir),
                                message="Démarrage d'Unreal (1 à 3 min) puis génération / rendu des plans…")
                work = lambda j: self._run_unreal_python(j, rc, req, (fps, descriptions, ff))  # noqa: E731
        else:
            raise UserError(f"Moteur « {p.engine} » sans capture automatique.")

        try:
            self.jobs.submit(job, work)
        except RuntimeError as exc:
            raise UserError(str(exc)) from exc
        return {**job.summary(), "next": "Suis l'avancement avec engine_capture_status(job_id, wait_seconds=…)."}

    def _build_staleness(self, exe: Path, repo: str | None) -> str | None:
        if not repo:
            return None
        try:
            out = subprocess.run(["git", "-C", str(Path(repo).expanduser()), "log", "-1", "--format=%ct"],
                                 capture_output=True, text=True, timeout=20).stdout.strip()
            last = int(out)
        except (ValueError, OSError, subprocess.SubprocessError):
            return None
        built = exe.stat().st_mtime
        if built + 60 < last:
            fmt = "%d/%m %H:%M"
            return (f"Attention : build du {datetime.fromtimestamp(built).strftime(fmt)}, plus ancien que le "
                    f"dernier commit ({datetime.fromtimestamp(last).strftime(fmt)}) : les nouveautés récentes "
                    "peuvent manquer à l'image.")
        return None

    def engine_capture_status(self, job_id: str, wait_seconds: float = 0) -> dict[str, Any]:
        job = self.jobs.get(job_id, self.paths.media)
        if not job:
            raise UserError(f"Capture inconnue : {job_id}")
        if wait_seconds > 0 and job_id in self.jobs.jobs:
            self.jobs.wait(job, wait_seconds)
        return job.summary()

    def _frames_to_media(self, job: EngineJob, name: str, frames: list[Path], fps: int, source: str,
                         note: str, keep: bool, work: Path) -> None:
        target = self._media_path(job.project, f"{job.engine}-{_safe(name)}", ".mp4")
        tmp = work / f"{_safe(name)}_seq"
        tmp.mkdir(parents=True, exist_ok=True)
        ext = frames[0].suffix.lower()
        for i, f in enumerate(frames, 1):
            shutil.copyfile(f, tmp / f"frame_{i:05d}{ext}")
        _assemble(self._ffmpeg()[0], tmp / f"frame_%05d{ext}", fps, target)
        shutil.rmtree(tmp, ignore_errors=True)
        if not keep:
            for f in frames:
                f.unlink(missing_ok=True)
        job.media.append(self._register(job.project, target, source, note))

    # --- Unity
    def _run_unity(self, job: EngineJob, uc: UnityConfig, root: Path, groups: dict[str, dict[str, list]],
                   descriptions: dict[str, str], ff: str) -> None:
        out = Path(job.out_dir)
        for index, (scene, group) in enumerate(groups.items()):
            sub = out / f"part{index + 1}"
            req = unity_engine.build_request(f"{job.id}-{index + 1}", sub, group["shots"], group["procedural"],
                                             scene, job.mode, uc.width, uc.height, uc.fps, uc.format,
                                             uc.warmup_seconds, uc.msaa, uc.include_ui)
            label = ", ".join(group["shots"] + [s["name"] for s in group["procedural"]])
            job.update(message=f"Capture de {label} ({scene}) via {job.target}…")
            if job.target == "editor":
                result = self._unity_editor_request(job, root, req, sub, uc.timeout_seconds)
            else:
                result = self._unity_build_request(job, uc, req, sub)
            for w in result.get("warnings") or []:
                job.message += f" {w}"
            if result.get("status") != "done":
                raise RuntimeError(f"Unity : {result.get('error') or 'capture échouée'}")
            job.update("assembling", "Assemblage des images…")
            for shot in result.get("shots", []):
                desc = descriptions.get(shot["name"])
                note = f"unity:{shot['name']}" + (f" — {desc}" if desc else "")
                if job.mode == "screenshot":
                    for f in shot.get("files", []):
                        job.media.append(self._register(job.project, Path(f), "unity:screenshot", note))
                    continue
                folder = Path(shot["folder"])
                frames = sorted(folder.glob(f"frame_*.{uc.format}"))
                if not frames:
                    raise RuntimeError(f"Aucune image produite pour le plan {shot['name']}.")
                self._frames_to_media(job, shot["name"], frames, shot.get("fps") or uc.fps, "unity:video",
                                      note, uc.keep_frames, out)
                if not uc.keep_frames:
                    shutil.rmtree(folder, ignore_errors=True)
            job.save()
        job.update("done", (job.message + " " if job.message else "")
                   + f"{len(job.media)} média(s) ajouté(s) à la médiathèque.")

    def _unity_editor_request(self, job: EngineJob, root: Path, req: dict, sub: Path, timeout: float) -> dict:
        request_path = unity_engine.request_file(root)
        unity_engine.write_json(request_path, req)
        start = time.time()
        while True:
            result = unity_engine.read_result(sub)
            if result and result.get("status") in ("done", "error"):
                return result
            waited = time.time() - start
            if request_path.exists() and waited > 120:
                request_path.unlink(missing_ok=True)
                raise RuntimeError("L'éditeur Unity n'a pas pris la requête en 2 minutes : package installé ? "
                                   "Compilation ou mode Play en cours ? Fenêtre bloquée par une boîte de dialogue ?")
            if waited > timeout:
                raise RuntimeError(f"Pas de résultat Unity après {timeout:.0f} s (garde la vue Game visible).")
            time.sleep(1.0)

    def _unity_build_request(self, job: EngineJob, uc: UnityConfig, req: dict, sub: Path) -> dict:
        sub.mkdir(parents=True, exist_ok=True)
        req_file = sub / "request.json"
        unity_engine.write_json(req_file, req)
        log = sub / "player.log"
        job.log = str(log)
        cmd = [str(Path(uc.build_exe).expanduser()), unity_engine.REQUEST_ARG, str(req_file), "-screen-fullscreen", "0",
               "-screen-width", str(uc.window[0]), "-screen-height", str(uc.window[1]), "-logFile", str(log),
               *uc.build_args]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            proc.wait(timeout=uc.timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RuntimeError(f"Le build Unity n'a pas terminé en {uc.timeout_seconds:.0f} s.")
        result = unity_engine.read_result(sub)
        if not result:
            tail = log.read_text(encoding="utf-8", errors="replace")[-800:] if log.exists() else ""
            raise RuntimeError("Le build s'est fermé sans result.json (package absent du build ? scène hors "
                               f"Build Settings ?). Fin du journal :\n{tail}")
        return result

    # --- Unreal
    def _run_unreal(self, job: EngineJob, rc: UnrealConfig, ff: str) -> None:
        out = Path(job.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        uproject = Path(rc.uproject)
        render_dir = Path(rc.output_dir).expanduser() if rc.output_dir else unreal_engine.default_output_dir(uproject)
        for name in job.shots:
            shot = rc.shots[name]
            log = out / f"{_safe(name)}.log"
            job.log = str(log)
            cmd = unreal_engine.build_command(rc.editor_cmd, str(uproject), shot.map, shot.sequence,
                                              shot.preset or rc.preset, rc.window[0], rc.window[1], rc.extra_args)
            job.update(message=f"Rendu Movie Render Queue de « {name} »…")
            start = time.time()
            with log.open("w", encoding="utf-8", errors="replace") as fh:
                proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    proc.wait(timeout=rc.timeout_seconds)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    raise RuntimeError(f"Rendu Unreal de « {name} » non terminé en {rc.timeout_seconds:.0f} s.")
            frames, video_file = unreal_engine.collect_output(render_dir, start)
            note = f"unreal:{name}" + (f" — {shot.description}" if shot.description else "")
            job.update("assembling", f"Assemblage de « {name} »…")
            target = self._media_path(job.project, f"unreal-{_safe(name)}", ".mp4")
            if frames:
                tmp = out / f"{_safe(name)}_frames"
                tmp.mkdir(exist_ok=True)
                ext = frames[0].suffix.lower()
                for i, f in enumerate(frames, 1):
                    shutil.copyfile(f, tmp / f"frame_{i:05d}{ext}")
                _assemble(ff, tmp / f"frame_%05d{ext}", shot.fps, target)
                shutil.rmtree(tmp, ignore_errors=True)
                if not rc.keep_frames:
                    for f in frames:
                        f.unlink(missing_ok=True)
            elif video_file:
                shutil.copyfile(video_file, target)
            else:
                tail = log.read_text(encoding="utf-8", errors="replace")[-1000:] if log.exists() else ""
                raise RuntimeError(f"Aucune image trouvée dans {render_dir} après le rendu de « {name} » "
                                   f"(code {proc.returncode}). Fin du journal :\n{tail}")
            job.media.append(self._register(job.project, target, "unreal:mrq", note))
            job.update("running")
        job.update("done", f"{len(job.media)} vidéo(s) ajoutée(s) à la médiathèque.")

    def _run_unreal_python(self, job: EngineJob, rc: UnrealConfig, req: dict, render: tuple | None) -> None:
        """Lance Unreal Editor avec nap_unreal.py (liste d'acteurs ou génération + rendu MRQ)."""
        out = Path(job.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        uproject = Path(rc.uproject)
        script_dir = uproject.parent / "Saved" / "NewsAutoPublisher"
        script_dir.mkdir(parents=True, exist_ok=True)
        script = script_dir / "nap_unreal.py"
        shutil.copyfile(package_file("engines", "nap_unreal.py"), script)
        frames_root = out / "frames"
        request = {
            "id": job.id, "result": str((out / "result.json").resolve()), "output_dir": str(frames_root.resolve()),
            "width": rc.width, "height": rc.height, "fps": rc.fps, "format": rc.format, "preset": rc.preset,
            "asset_dir": rc.asset_dir, **req,
        }
        req_path = out / "unreal_request.json"
        unity_engine.write_json(req_path, request)
        (out / "result.json").unlink(missing_ok=True)
        log = out / "unreal.log"
        job.log = str(log)
        cmd = [rc.editor_cmd, str(uproject), f"-ExecutePythonScript={_no_space_path(script)}", "-unattended",
               "-nosplash", "-log", *rc.extra_args]
        env = {**os.environ, "NAP_UNREAL_REQUEST": str(req_path.resolve())}
        with log.open("w", encoding="utf-8", errors="replace") as fh:
            proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                proc.wait(timeout=rc.timeout_seconds)
            except subprocess.TimeoutExpired:
                proc.kill()
                raise RuntimeError(f"Unreal n'a pas terminé en {rc.timeout_seconds:.0f} s (journal : {log}).")
        result = unity_engine.read_result(out)
        if not result:
            tail = log.read_text(encoding="utf-8", errors="replace")[-1500:] if log.exists() else ""
            raise RuntimeError("Unreal s'est fermé sans résultat : plugins Python / Sequencer Scripting / Movie "
                               f"Render Queue activés (engine_setup) ? Fin du journal :\n{tail}")
        if result.get("status") != "done":
            raise RuntimeError(f"Unreal : {result.get('error') or 'échec'} — {' | '.join(result.get('log', [])[-5:])}")
        if render is None:  # liste d'acteurs
            actors = result.get("actors", [])
            needle = (req.get("contains") or "").lower()
            job.data = {"map": req.get("map"),
                        "actors": [a for a in actors if not needle or needle in a["label"].lower()][:500]}
            job.update("done", f"{len(actors)} acteur(s) dans {req.get('map')}.")
            return
        fps_by_shot, descriptions, _ff = render
        job.update("assembling", "Assemblage des images…")
        for shot in result.get("shots", []):
            frames, video_file = unreal_engine.collect_output(Path(shot["folder"]), since=0)
            desc = descriptions.get(shot["name"])
            note = f"unreal:{shot['name']}" + (f" — {desc}" if desc else "")
            if frames:
                self._frames_to_media(job, shot["name"], frames, fps_by_shot.get(shot["name"], rc.fps),
                                      "unreal:mrq", note, rc.keep_frames, out)
            elif video_file:
                target = self._media_path(job.project, f"unreal-{_safe(shot['name'])}", video_file.suffix)
                shutil.copyfile(video_file, target)
                job.media.append(self._register(job.project, target, "unreal:mrq", note))
            else:
                raise RuntimeError(f"Aucune image rendue pour « {shot['name']} » (journal : {log}).")
            job.save()
        job.update("done", f"{len(job.media)} vidéo(s) ajoutée(s) à la médiathèque.")

    def probe_media(self, path: str) -> dict[str, Any]:
        _, fp = self._ffmpeg()
        return probe(self._resolve_media(path), fp)

    # ------------------------------------------------------------------ voix off
    def generate_voiceover(self, draft_id: str, script: str, engine: str | None = None,
                           voice: str | None = None) -> VoiceInfo:
        d = self._get(draft_id)
        cfg = self.cfg
        p = cfg.project(d.project)
        eng = engine or p.voice.engine or cfg.voice.default_engine
        out = self.paths.draft_dir(d.id) / "voice.wav"
        if eng == "piper":
            name = voice or p.voice.voices.get(d.language) or cfg.voice.piper.get(d.language)
            if not name:
                raise UserError(f"Aucune voix Piper configurée pour la langue {d.language} (voice.piper).")
            info = piper_tts.synthesize(script, name, self.paths.models, out, cfg.voice.piper_length_scale,
                                        cfg.voice.sentence_pause)
        elif eng == "elevenlabs":
            key = get_secret(cfg.voice.elevenlabs_key_env)
            vid = voice or p.voice.voices.get(d.language) or get_secret(cfg.voice.elevenlabs_voice_env)
            if not key or not vid:
                raise UserError(f"ElevenLabs : renseigne {cfg.voice.elevenlabs_key_env} et "
                                f"{cfg.voice.elevenlabs_voice_env} dans .env.")
            ff, _ = self._ffmpeg()
            info = elevenlabs.synthesize(script, key, vid, cfg.voice.elevenlabs_model, out, ff)
        elif eng == "recorded":
            raise UserError("Pour ta voix : appelle prepare_voice_recording puis import_voice_recording.")
        else:
            raise UserError("Moteur de voix « none » : pas de voix off pour ce projet.")
        d.short.voice = info
        self.store.save_draft(d)
        return info

    def prepare_voice_recording(self, draft_id: str, script: str) -> dict[str, Any]:
        d = self._get(draft_id)
        folder = self.paths.draft_dir(d.id)
        folder.mkdir(parents=True, exist_ok=True)
        text = format_for_recording(script)
        (folder / "script_voix.txt").write_text(script, encoding="utf-8")
        d.notes = (d.notes + "\n" if d.notes else "") + "Script voix en attente d'enregistrement."
        self.store.save_draft(d)
        return {
            "script_numerote": text,
            "fichier_script": str(folder / "script_voix.txt"),
            "depot_attendu": str(folder / "voix_enregistree.wav"),
            "conseils": [
                "Lis le texte exactement tel quel (les sous-titres suivent le script).",
                "Marque une courte pause entre chaque phrase numérotée.",
                "Pièce calme, micro à 15–20 cm ; WAV, MP3, M4A acceptés ; le début et la fin silencieux sont coupés.",
                "Dépose le fichier à l'emplacement indiqué ou donne son chemin à import_voice_recording.",
            ],
        }

    def import_voice_recording(self, draft_id: str, path: str | None = None, script: str | None = None) -> VoiceInfo:
        d = self._get(draft_id)
        folder = self.paths.draft_dir(d.id)
        src = Path(path).expanduser() if path else None
        if src is None:
            candidates = sorted(folder.glob("voix_enregistree.*"))
            if not candidates:
                raise UserError(f"Aucun enregistrement trouvé dans {folder} (voix_enregistree.wav).")
            src = candidates[0]
        script_file = folder / "script_voix.txt"
        text = script or (script_file.read_text(encoding="utf-8") if script_file.exists() else None)
        if not text:
            raise UserError("Script introuvable : passe le texte lu en paramètre script.")
        ff, fp = self._ffmpeg()
        info = recorded.import_recording(src, text, d.language, folder / "voice.wav", ff, fp,
                                         self.cfg.voice.whisper_model)
        d.short.voice = info
        self.store.save_draft(d)
        return info

    # ------------------------------------------------------------------ vidéo
    def render_short(self, draft_id: str, storyboard: Storyboard) -> dict[str, Any]:
        d = self._get(draft_id)
        cfg = self.cfg
        p = cfg.project(d.project)
        for sc in storyboard.scenes:
            sc.media = self._resolve_media(sc.media)
        ff, fp = self._ffmpeg()
        v = cfg.video
        brand = Brand(color=p.brand.color, accent=p.brand.accent, background=p.brand.background,
                      logo=p.brand.logo, music=p.brand.music, music_volume=p.brand.music_volume)
        renderer = Renderer(ff, fp, RenderSettings(v.width, v.height, v.fps, v.crf, v.preset, v.max_seconds), brand)
        folder = self.paths.draft_dir(d.id)
        result = renderer.render(storyboard, d.short.voice, folder / "render", folder / "short.mp4", seed=d.id)

        limits = [cfg.channels[c].max_upload_mb for c in d.channels
                  if c in cfg.channels and cfg.channels[c].platform == "discord"]
        discord_path = renderer.discord_variant(Path(result["path"]), min(limits)) if limits else None
        d.short.path = result["path"]
        d.short.discord_path = str(discord_path) if discord_path else None
        d.short.duration = result["duration"]
        d.short.storyboard = storyboard.model_dump()
        d.short.rendered_at = utcnow()
        if d.status == "approved":
            d.status = "draft"
            d.approved_at = None
        d = self._refresh(d)
        result["discord_path"] = d.short.discord_path
        result["warnings"] = renderer.warnings
        return result

    # ------------------------------------------------------------------ validation & publication
    def approve_draft(self, draft_id: str) -> Draft:
        d = self._refresh(self._get(draft_id))
        if d.status in ("published", "discarded"):
            raise UserError(f"Brouillon {d.status}.")
        if has_errors(d.issues):
            errs = "; ".join(f"{i.platform}.{i.field} : {i.message}" for i in d.issues if i.level == "error")
            raise UserError(f"Impossible d'approuver, erreurs à corriger : {errs}")
        if d.status == "draft":
            d.status = "approved"
            d.approved_at = utcnow()
        return self.store.save_draft(d)

    def publish(self, draft_id: str, channels: list[str] | None = None, dry_run: bool | None = None) -> dict[str, Any]:
        cfg = self.cfg
        d = self._refresh(self._get(draft_id))
        dry = _dry_run_default() if dry_run is None else dry_run
        if d.status not in ("approved", "partial"):
            raise UserError("Le brouillon doit être approuvé (approve_draft) après accord explicite de l'utilisateur.")
        if has_errors(d.issues):
            raise UserError("Le brouillon contient des erreurs : corrige-les puis approuve à nouveau.")
        targets = channels or d.channels
        unknown = [c for c in targets if c not in d.channels]
        if unknown:
            raise UserError(f"Canaux hors du brouillon : {', '.join(unknown)}")

        p = cfg.project(d.project)
        folder = self.paths.draft_dir(d.id)
        results: list[PublishResult] = []
        for ch_id in targets:
            ch = cfg.channel(ch_id)
            prev = self.store.get_publication(d.id, ch_id)
            if prev and prev["status"] in ("published", "pending_manual") and not dry:
                results.append(PublishResult(channel=ch_id, platform=ch.platform, status="skipped",
                                             url=prev["url"], message=f"Déjà traité ({prev['status']})."))
                continue
            post = getattr(d.posts, ch.platform)
            if post is None:
                results.append(PublishResult(channel=ch_id, platform=ch.platform, status="skipped",
                                             message="Aucun contenu pour cette plateforme."))
                continue
            res = self._publish_one(d, p, ch_id, ch, post, folder, dry)
            results.append(res)
            if res.status != "dry_run":
                self.store.record_publication(d, res)

        if not dry:
            statuses = {}
            for c in d.channels:
                row = self.store.get_publication(d.id, c)
                statuses[c] = row["status"] if row else None
            done = [c for c, s in statuses.items() if s == "published"]
            if done and len(done) == len(d.channels):
                d.status = "published"
            elif any(s in ("published", "pending_manual") for s in statuses.values()):
                d.status = "partial"
            self.store.save_draft(d)
        return {"draft_id": d.id, "status": d.status, "dry_run": dry,
                "results": [r.model_dump() for r in results]}

    def _publish_one(self, d: Draft, p: ProjectConfig, ch_id: str, ch, post, folder: Path, dry: bool) -> PublishResult:
        mode = ch.effective_mode
        if ch.platform == "discord":
            url = get_secret(ch.webhook_env)
            if not url and not dry:
                return PublishResult(channel=ch_id, platform="discord", status="failed",
                                     message=f"Webhook absent : renseigne {ch.webhook_env} dans .env.")
            bot = None
            if ch.crosspost:
                bot = get_secret(ch.bot_token_env)
                if not bot and not dry:
                    return PublishResult(channel=ch_id, platform="discord", status="failed",
                                         message=f"crosspost activé mais {ch.bot_token_env} absent du .env.")
            files: list[Path] = []
            if post.image:
                files.append(Path(post.image))
            files += [Path(a) for a in post.attachments]
            if post.attach_short and d.short.discord_path:
                files.append(Path(d.short.discord_path))
            return publish_discord(post, ch_id, ch, url or "https://discord.invalid/webhook", files,
                                   p.brand.color, footer=p.name, dry_run=dry, bot_token=bot)

        if ch.platform == "x":
            media = [Path(m) for m in post.media]
            if mode == "intent":
                if post.attach_short and d.short.path:
                    media.append(Path(d.short.path))
                return publish_x_intent(post, ch_id, media, dry_run=dry)
            if mode != "api":
                return PublishResult(channel=ch_id, platform="x", status="failed", message=f"Mode X inconnu : {mode}")
            if post.attach_short and d.short.path:
                media = [self._renderer(p).x_variant(Path(d.short.path))]  # la vidéo remplace les images
            media = media[:1] if any(m.suffix.lower() in (".mp4", ".mov") for m in media) else media[:4]
            cost = x_api.estimate_cost(post, len(media), ch.cost_post_usd, ch.cost_post_url_usd, ch.cost_media_usd)
            spent = self.store.spend_this_month(ch_id)
            if spent + cost > ch.monthly_budget_usd + 1e-9:
                return PublishResult(
                    channel=ch_id, platform="x", status="failed",
                    message=f"Budget X dépassé : {spent:.3f} $ déjà dépensés + {cost:.3f} $ estimés > "
                            f"{ch.monthly_budget_usd:.2f} $ (monthly_budget_usd). Utilise mode intent ou augmente le budget.")
            creds = self._x_creds(ch)
            if not creds and not dry:
                return PublishResult(channel=ch_id, platform="x", status="failed",
                                     message="Clés X manquantes dans .env (X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, "
                                             "X_ACCESS_TOKEN_SECRET).")
            return x_api.publish_x_api(post, ch_id, media, creds or x_api.XCredentials("", "", "", ""), cost,
                                       ch.handle, dry_run=dry)

        if ch.platform == "youtube":
            if not d.short.path:
                return PublishResult(channel=ch_id, platform="youtube", status="failed", message="Aucun short rendu.")
            if mode == "manual":
                return publish_youtube_manual(post, ch_id, Path(d.short.path), folder, dry_run=dry)
            if mode != "api":
                return PublishResult(channel=ch_id, platform="youtube", status="failed",
                                     message=f"Mode YouTube inconnu : {mode}")
            _, token = self._yt_files(ch_id, ch)
            if not token.exists() and not dry:
                return PublishResult(channel=ch_id, platform="youtube", status="failed",
                                     message="Compte YouTube non connecté : appelle connect_account sur ce canal.")
            return youtube_api.publish_youtube_api(post, ch_id, Path(d.short.path), token, d.language,
                                                   ch.category_id, ch.audited, dry_run=dry)
        return PublishResult(channel=ch_id, platform=ch.platform, status="failed", message="Plateforme inconnue.")

    # ------------------------------------------------------------------ comptes (phase 3)
    def _renderer(self, p: ProjectConfig) -> Renderer:
        ff, fp = self._ffmpeg()
        v = self.cfg.video
        return Renderer(ff, fp, RenderSettings(v.width, v.height, v.fps, v.crf, v.preset, v.max_seconds), Brand())

    def _x_creds(self, ch) -> x_api.XCredentials | None:
        values = [get_secret(e) for e in (ch.api_key_env, ch.api_secret_env, ch.access_token_env, ch.access_secret_env)]
        return x_api.XCredentials(*values) if all(values) else None

    def _yt_files(self, ch_id: str, ch) -> tuple[Path, Path]:
        secret = Path(ch.client_secret_file).expanduser() if ch.client_secret_file else \
            self.paths.credentials / "youtube_client_secret.json"
        safe = "".join(c if c.isalnum() else "_" for c in ch_id)
        return secret, self.paths.credentials / f"youtube_token_{safe}.json"

    def connect_account(self, channel: str) -> dict[str, Any]:
        """Vérifie / établit la connexion d'un canal en mode API (YouTube : consentement OAuth)."""
        ch = self.cfg.channel(channel)
        if ch.type == "youtube":
            secret, token = self._yt_files(channel, ch)
            try:
                info = youtube_api.connect(secret, token, open_browser=desktop.enabled())
            except youtube_api.YouTubeApiError as exc:
                raise UserError(str(exc)) from exc
            info["audited"] = ch.audited
            if not ch.audited:
                info["attention"] = ("Projet non audité : les uploads API resteront privés. Demande l'audit "
                                     "(formulaire « YouTube API Services - Audit and Quota Extension ») avant de "
                                     "passer audited: true.")
            return info
        if ch.type == "x":
            creds = self._x_creds(ch)
            if not creds:
                raise UserError("Renseigne X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN et X_ACCESS_TOKEN_SECRET dans .env.")
            client = x_api.XClient(creds)
            try:
                me = client.me()
            except x_api.XApiError as exc:
                raise UserError(str(exc)) from exc
            finally:
                client.close()
            return {"username": me.get("username"), "name": me.get("name"),
                    "budget_mensuel_usd": ch.monthly_budget_usd,
                    "depense_ce_mois_usd": self.store.spend_this_month(channel)}
        if ch.type == "discord_webhook":
            token = get_secret(ch.bot_token_env)
            if not token:
                raise UserError(f"Renseigne {ch.bot_token_env} dans .env (bot nécessaire seulement pour le crosspost).")
            try:
                user = discord_bot.identify_once(token)
            except discord_bot.DiscordBotError as exc:
                raise UserError(str(exc)) from exc
            out: dict[str, Any] = {"bot": user.get("username"), "gateway": "connexion initiale effectuée"}
            hook = get_secret(ch.webhook_env)
            if hook:
                import httpx

                try:
                    chan_id = httpx.get(hook, timeout=20).json().get("channel_id")
                    info = discord_bot.channel_info(token, chan_id)
                    out["salon"] = info.get("name")
                    out["salon_annonces"] = info.get("type") == discord_bot.ANNOUNCEMENT_CHANNEL
                except (discord_bot.DiscordBotError, httpx.HTTPError) as exc:
                    out["salon"] = f"vérification impossible : {exc}"
            return out
        raise UserError(f"Type de canal inconnu : {ch.type}")

    def mark_published(self, draft_id: str, channel: str, url: str) -> dict[str, Any]:
        d = self._get(draft_id)
        ch = self.cfg.channel(channel)
        if channel not in d.channels:
            raise UserError(f"{channel} ne fait pas partie des canaux du brouillon.")
        self.store.record_publication(
            d, PublishResult(channel=channel, platform=ch.platform, status="published", url=url,
                             message="Confirmé par l'utilisateur."))
        statuses = [(self.store.get_publication(d.id, c) or {}).get("status") for c in d.channels]
        d.status = "published" if all(s == "published" for s in statuses) else "partial"
        self.store.save_draft(d)
        return {"draft_id": d.id, "status": d.status, "channel": channel, "url": url}


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name) or "plan"


def _assemble(ffmpeg: str, pattern: Path, fps: int, out: Path) -> None:
    run_ffmpeg([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(fps), "-i", str(pattern),
                "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2,format=yuv420p", "-c:v", "libx264", "-preset", "medium",
                "-crf", "16", "-movflags", "+faststart", str(out)])


def _no_space_path(path: Path) -> str:
    """Chemin sans espace pour la ligne de commande d'Unreal (nom court 8.3 sous Windows)."""
    p = str(path.resolve())
    if " " not in p or sys.platform != "win32":
        return p.replace("\\", "/")
    import ctypes

    buf = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024):  # type: ignore[attr-defined]
        return buf.value.replace("\\", "/")
    return p.replace("\\", "/")
