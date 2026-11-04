"""Logique métier (indépendante du protocole MCP, testable directement)."""

from __future__ import annotations

import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import desktop
from .capture import obs as obs_mod
from .capture import screen
from .capture.windows import CaptureError, is_windows, list_windows
from .config import AppConfig, ConfigCache, ConfigError, ProjectConfig, get_secret, init_data_dir
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
from .paths import Paths
from .preview import write_preview
from .publishers.discord import publish_discord
from .publishers.x_intent import publish_x_intent
from .publishers.youtube_manual import publish_youtube_manual
from .sources.changelog import read_changelog
from .sources.git import GitError, collect_changes, head_commit
from .store import Store
from .validate import has_errors, validate_draft
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
        chans = {}
        for k, c in cfg.channels.items():
            info = {"type": c.type, "mode": c.effective_mode}
            if c.type == "discord_webhook":
                info["secret"] = "présent" if get_secret(c.webhook_env) else f"manquant ({c.webhook_env} dans .env)"
            if c.type in ("x", "youtube") and c.effective_mode == "api":
                info["warning"] = "mode API pas encore disponible (phase 3) : utilise intent / manual"
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
            files: list[Path] = []
            if post.image:
                files.append(Path(post.image))
            files += [Path(a) for a in post.attachments]
            if post.attach_short and d.short.discord_path:
                files.append(Path(d.short.discord_path))
            return publish_discord(post, ch_id, ch, url or "https://discord.invalid/webhook", files,
                                   p.brand.color, footer=p.name, dry_run=dry)
        if ch.platform == "x":
            if mode != "intent":
                return PublishResult(channel=ch_id, platform="x", status="failed",
                                     message="Mode API X pas encore disponible : utilise mode: intent.")
            media = [Path(m) for m in post.media]
            if post.attach_short and d.short.path:
                media.append(Path(d.short.path))
            return publish_x_intent(post, ch_id, media, dry_run=dry)
        if ch.platform == "youtube":
            if mode != "manual":
                return PublishResult(channel=ch_id, platform="youtube", status="failed",
                                     message="Mode API YouTube pas encore disponible (audit requis) : mode: manual.")
            if not d.short.path:
                return PublishResult(channel=ch_id, platform="youtube", status="failed",
                                     message="Aucun short rendu.")
            return publish_youtube_manual(post, ch_id, Path(d.short.path), folder, dry_run=dry)
        return PublishResult(channel=ch_id, platform=ch.platform, status="failed", message="Plateforme inconnue.")

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
