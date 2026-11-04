"""Serveur MCP NewsAutoPublisher (stdio)."""

from __future__ import annotations

import functools
import logging
import sys
import traceback
from typing import Any, Callable, Literal

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from .models import DiscordPost, ProceduralShot, XPost, YouTubePost
from .service import USER_ERRORS, App, UserError
from .video.storyboard import Storyboard

log = logging.getLogger("newsautopublisher")

INSTRUCTIONS = """\
NewsAutoPublisher prépare et publie les news des projets de l'utilisateur (Discord, X, YouTube Shorts).
Déroulé : detect_project / list_projects -> collect_changes -> create_draft (un brouillon par langue)
-> [captures : capture_screenshot / start_recording / save_replay / import_media]
-> [voix : generate_voiceover, ou prepare_voice_recording + import_voice_recording]
-> render_short -> render_preview -> l'utilisateur relit -> approve_draft -> publish -> mark_published.
RÈGLE ABSOLUE : n'appelle approve_draft et publish qu'après un accord explicite de l'utilisateur
sur la prévisualisation (« ok », « publie »…). Ne publie jamais de ta propre initiative.
Selon la config des canaux : X en mode intent (l'utilisateur clique « Poster ») ou api (payant, plafonné
par monthly_budget_usd) ; YouTube en mode manuel (upload dans Studio) ou api (après audit Google).
Pour les canaux en attente manuelle, demande les URL à l'utilisateur et enregistre-les avec mark_published.
Un canal en mode api se connecte une fois avec connect_account.
Captures moteur : list_engine_targets / list_engine_shots puis engine_capture (plans existants ou
procéduraux autour d'objets), suivies avec engine_capture_status. La règle capture.engine_auto décide
de ce qui peut partir sans accord ; user_requested=true seulement après accord explicite de l'utilisateur.
"""

mcp = MCPServer("newsautopublisher", instructions=INSTRUCTIONS, version="0.5.0")
_app: App | None = None

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
LOCAL = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
CAPTURE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
PUBLISH = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)


def app() -> App:
    global _app
    if _app is None:
        _app = App()
    return _app


async def _run(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Exécute la logique dans un thread et transforme les erreurs en messages lisibles."""
    try:
        return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))
    except (UserError, *USER_ERRORS) as exc:
        raise ToolError(str(exc)) from exc
    except Exception as exc:  # erreur inattendue : on garde un message utile pour le modèle
        traceback.print_exc(file=sys.stderr)
        raise ToolError(f"Erreur interne ({exc.__class__.__name__}) : {exc}") from exc


def _draft_out(d) -> dict[str, Any]:
    out = d.model_dump()
    out["preview_hint"] = "Appelle render_preview pour montrer le brouillon à l'utilisateur."
    return out


# ---------------------------------------------------------------------------- configuration
@mcp.tool(annotations=READ)
async def status() -> dict[str, Any]:
    """État de l'installation : config, ffmpeg, OBS, secrets présents (jamais leur valeur), voix Piper."""
    return await _run(lambda: app().status())


@mcp.tool(annotations=LOCAL)
async def init_config() -> dict[str, Any]:
    """Crée le dossier de données (~/.newsautopublisher) avec config.yaml et .env d'exemple s'ils manquent."""
    return await _run(lambda: app().init_config())


# ---------------------------------------------------------------------------- assistant d'installation
SETUP = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)


@mcp.tool(annotations=READ)
async def discover_projects(
    roots: list[str] | None = Field(None, description="Dossiers à explorer ; défaut : ~/Dev, D:/Dev, Documents/GitHub…"),
    max_depth: int = Field(3, ge=1, le=6),
) -> list[dict[str, Any]]:
    """Trouve les dépôts git de l'utilisateur : moteur (Unity / Unreal + version), remote GitHub/GitLab,
    dernier commit, CHANGELOG, et s'ils sont déjà configurés. Sert à pré-remplir config.yaml."""
    return await _run(app().discover_projects, roots, max_depth)


@mcp.tool(annotations=SETUP)
async def edit_config(
    section: Literal["projects", "channels", "voice", "obs", "video", "hints"],
    key: str | None = Field(None, description="Id du projet ou du canal (obligatoire pour projects / channels)."),
    value: dict[str, Any] | None = Field(None, description="Réglages à ajouter / fusionner (même structure que config.yaml)."),
    remove: bool = Field(False, description="Supprimer l'entrée (ex. projets d'exemple inutilisés)."),
) -> dict[str, Any]:
    """Modifie config.yaml en conservant les commentaires. Toute modification qui rendrait la configuration
    invalide est refusée. Jamais de secret ici : utilise set_secret."""
    return await _run(app().edit_config, section, key, value, remove)


@mcp.tool(annotations=SETUP)
async def set_secret(
    name: str = Field(..., description="Nom de la variable (ex. DISCORD_WEBHOOK_EXODE)."),
    value: str = Field(..., description="Valeur (URL de webhook, clé…). Elle n'est jamais renvoyée."),
) -> dict[str, Any]:
    """Enregistre un secret dans le .env local (hors dépôts). Préfère open_config_file('env') pour que
    l'utilisateur colle lui-même ses secrets ; à n'utiliser que s'il les a déjà donnés dans la conversation."""
    return await _run(app().set_secret, name, value)


@mcp.tool(annotations=SETUP)
async def open_config_file(which: Literal["config", "env"] = "config") -> dict[str, Any]:
    """Ouvre config.yaml ou .env dans l'éditeur par défaut de l'utilisateur."""
    return await _run(app().open_config_file, which)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
async def test_channel(
    channel: str,
    send_test: bool = Field(False, description="Discord : poste un court message de test (avec l'accord de l'utilisateur)."),
) -> dict[str, Any]:
    """Vérifie qu'un canal fonctionne : webhook Discord valide (et message de test si demandé), clés X,
    connexion YouTube. Les modes intent / manuel n'ont rien à tester."""
    return await _run(app().test_channel, channel, send_test)


@mcp.tool(annotations=SETUP)
async def snooze_news_hints(
    project: str,
    days: float = Field(7, ge=0.5, le=90, description="Durée pendant laquelle ne plus suggérer de news."),
) -> dict[str, Any]:
    """Met en pause les suggestions proactives de news pour un projet (quand l'utilisateur dit « pas maintenant »)."""
    return await _run(app().snooze_hints, project, days)


# ---------------------------------------------------------------------------- projets & sources
@mcp.tool(annotations=READ)
async def list_projects() -> list[dict[str, Any]]:
    """Projets configurés : nom, langues, ton, public, liens, hashtags, canaux par langue."""
    return await _run(lambda: app().list_projects())


@mcp.tool(annotations=READ)
async def detect_project(cwd: str = Field(..., description="Dossier de travail courant de la session.")) -> dict[str, Any]:
    """Trouve le projet dont le dépôt contient ce dossier."""
    return await _run(app().detect_project, cwd)


@mcp.tool(annotations=READ)
async def collect_changes(
    project: str,
    since: str | None = Field(
        "last_post",
        description="'last_post' (depuis la dernière news publiée), un commit/tag, une date ISO ou '2 weeks ago'.",
    ),
    max_commits: int = Field(40, ge=1, le=200),
) -> dict[str, Any]:
    """Commits, fichiers les plus modifiés, tags, changements non commités et CHANGELOG du dépôt local."""
    return await _run(app().collect_changes, project, since, max_commits)


@mcp.tool(annotations=READ)
async def publication_history(project: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Historique des publications (canal, statut, URL)."""
    return await _run(app().publication_history, project, limit)


# ---------------------------------------------------------------------------- brouillons
@mcp.tool(annotations=LOCAL)
async def create_draft(
    project: str,
    language: str = Field(..., description="Code langue du brouillon (fr, en…) ; un brouillon par langue."),
    topic: str = Field(..., description="Sujet en une ligne (titre interne)."),
    discord: DiscordPost | None = None,
    x: XPost | None = None,
    youtube: YouTubePost | None = None,
    notes: str = "",
    channels: list[str] | None = Field(None, description="Par défaut : canaux du projet pour cette langue."),
    group: str | None = Field(
        None, description="Id du premier brouillon de la même nouveauté (autre langue) : une seule validation pour tout."
    ),
) -> dict[str, Any]:
    """Crée un brouillon de news pour une langue (posts par plateforme) et le valide (limites, fuites, fichiers).
    Pour un projet bilingue : crée la 1re langue, puis les autres avec group=<id du 1er>."""
    d = await _run(app().create_draft, project, language, topic, discord, x, youtube, notes, channels, group)
    return _draft_out(d)


@mcp.tool(annotations=LOCAL)
async def update_draft(
    draft_id: str,
    topic: str | None = None,
    discord: DiscordPost | None = None,
    x: XPost | None = None,
    youtube: YouTubePost | None = None,
    notes: str | None = None,
    channels: list[str] | None = None,
    remove_platforms: list[Literal["discord", "x", "youtube"]] | None = None,
) -> dict[str, Any]:
    """Modifie un brouillon (remplace les posts fournis). Un brouillon approuvé repasse en brouillon."""
    d = await _run(app().update_draft, draft_id, topic, discord, x, youtube, notes, channels, remove_platforms)
    return _draft_out(d)


@mcp.tool(annotations=READ)
async def get_draft(draft_id: str) -> dict[str, Any]:
    """Contenu complet d'un brouillon et résultat de la validation."""
    return _draft_out(await _run(app().get_draft, draft_id))


@mcp.tool(annotations=READ)
async def list_drafts(project: str | None = None, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Brouillons récents (filtrables par projet / statut)."""
    return await _run(app().list_drafts, project, status, limit)


@mcp.tool(annotations=LOCAL)
async def discard_draft(draft_id: str) -> dict[str, Any]:
    """Abandonne un brouillon non publié."""
    d = await _run(app().discard_draft, draft_id)
    return {"id": d.id, "status": d.status}


@mcp.tool(annotations=LOCAL)
async def render_preview(draft_id: str, open_browser: bool = True) -> dict[str, Any]:
    """Génère la page HTML de prévisualisation (maquettes Discord / X / Shorts) et l'ouvre dans le navigateur."""
    return await _run(app().render_preview, draft_id, open_browser)


# ---------------------------------------------------------------------------- captures & médias
@mcp.tool(annotations=READ)
async def list_windows() -> list[dict[str, Any]]:
    """Fenêtres visibles (Windows) : titre, position, taille. Utile pour cibler le jeu ou l'éditeur."""
    return await _run(lambda: app().list_windows())


@mcp.tool(annotations=CAPTURE)
async def capture_screenshot(
    project: str,
    window_title: str | None = Field(None, description="Sous-chaîne du titre ; défaut : capture.window_title."),
    backend: Literal["obs", "gdigrab", "ddagrab"] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Capture d'écran du jeu / de l'éditeur (OBS si disponible, sinon ffmpeg) rangée dans la médiathèque."""
    return await _run(app().capture_screenshot, project, window_title, backend, note)


@mcp.tool(annotations=CAPTURE)
async def start_recording(
    project: str,
    window_title: str | None = None,
    max_seconds: float = Field(60, gt=1, le=600),
    backend: Literal["obs", "gdigrab", "ddagrab"] | None = None,
) -> dict[str, Any]:
    """Démarre l'enregistrement vidéo (OBS ou fenêtre via ffmpeg). L'utilisateur joue / fait la démo."""
    return await _run(app().start_recording, project, window_title, max_seconds, backend)


@mcp.tool(annotations=CAPTURE)
async def stop_recording(recording_id: str, note: str | None = None) -> dict[str, Any]:
    """Arrête l'enregistrement et range le clip dans la médiathèque du projet."""
    return await _run(app().stop_recording, recording_id, note)


@mcp.tool(annotations=CAPTURE)
async def save_replay(project: str, note: str | None = None) -> dict[str, Any]:
    """Sauvegarde le tampon de relecture d'OBS (« garde les dernières secondes ») dans la médiathèque."""
    return await _run(app().save_replay, project, note)


@mcp.tool(annotations=LOCAL)
async def import_media(project: str, path: str, note: str | None = None, copy: bool = True) -> dict[str, Any]:
    """Ajoute un fichier existant (clip OBS/ShadowPlay, capture, rendu Unity/Unreal) à la médiathèque."""
    return await _run(app().import_media, project, path, note, copy)


@mcp.tool(annotations=READ)
async def list_media(
    project: str, kind: Literal["image", "video", "audio"] | None = None, limit: int = 30
) -> list[dict[str, Any]]:
    """Médias du projet (id m…, chemin, type, dimensions, durée, note), du plus récent au plus ancien."""
    return await _run(app().list_media, project, kind, limit)


@mcp.tool(annotations=READ)
async def list_engine_shots(project: str) -> dict[str, Any]:
    """Plans capturables par le moteur : NapShot des scènes Unity (lus dans les fichiers .unity) ou
    Level Sequences Unreal configurées. Indique aussi si l'éditeur Unity est ouvert / le build trouvé."""
    return await _run(app().list_engine_shots, project)


@mcp.tool(annotations=READ)
async def list_engine_targets(
    project: str,
    scene: str | None = Field(None, description="Unity : Assets/…/Scene.unity ; Unreal : /Game/Maps/… (défaut : unreal.default_map)."),
    contains: str | None = Field(None, description="Filtre sur le nom (ex. « Quest »)."),
    limit: int = Field(150, ge=1, le=1000),
) -> dict[str, Any]:
    """Objets filmables : noms des GameObjects des scènes Unity (lecture directe des fichiers), ou acteurs d'une
    map Unreal (lance Unreal en arrière-plan : résultat via engine_capture_status, champ data.actors)."""
    return await _run(app().list_engine_targets, project, scene, contains, limit)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
async def engine_setup(
    project: str,
    apply: bool = Field(False, description="false : diagnostic seul ; true : applique les changements."),
) -> dict[str, Any]:
    """Prépare le projet pour les captures automatiques : Unity (ajoute le package NewsAutoPublisher Capture au
    manifest, vérifie la sérialisation texte) ; Unreal (active Python, Sequencer Scripting, Editor Scripting et
    Movie Render Queue dans le .uproject). Modifie des fichiers du projet : apply=true seulement avec accord."""
    return await _run(app().engine_setup, project, apply)


@mcp.tool(annotations=CAPTURE)
async def engine_capture(
    project: str,
    shots: list[str] | None = Field(None, description="Plans existants (NapShot / séquences configurées) ; défaut : tous s'il n'y a pas de procéduraux."),
    procedural: list[ProceduralShot] | None = Field(None, description="Plans générés autour d'objets : aucun placement manuel nécessaire."),
    scene: str | None = Field(None, description="Unity : scène à charger (sinon celle qui contient la cible) ; Unreal : map par défaut."),
    mode: Literal["video", "screenshot"] = Field("video", description="video : plan animé ; screenshot : images fixes (Unity)."),
    target: Literal["editor", "build"] | None = Field(None, description="Unity : editor (éditeur ouvert) ou build (exécutable)."),
    user_requested: bool = Field(
        False, description="true UNIQUEMENT si l'utilisateur a demandé ou accepté cette capture dans la conversation."
    ),
) -> dict[str, Any]:
    """Capture des plans par le moteur, en tâche de fond (Unity : package NapShot ; Unreal : séquence générée
    ou existante + Movie Render Queue). Les vidéos arrivent dans la médiathèque. Sans user_requested, la règle
    capture.engine_auto s'applique : par défaut, automatique pour Unreal et le build Unity, accord requis pour
    l'éditeur Unity ouvert."""
    specs = [s.model_dump() for s in procedural] if procedural else None
    return await _run(app().engine_capture, project, shots, mode, target, specs, scene, user_requested)


@mcp.tool(annotations=READ)
async def engine_capture_status(
    job_id: str,
    wait_seconds: float = Field(0, ge=0, le=600, description="Attendre la fin jusqu'à N secondes."),
) -> dict[str, Any]:
    """État d'une capture moteur (running / assembling / done / error) et médias produits (ids m…)."""
    return await _run(app().engine_capture_status, job_id, wait_seconds)


@mcp.tool(annotations=READ)
async def probe_media(path: str = Field(..., description="Chemin ou id de média.")) -> dict[str, Any]:
    """Caractéristiques d'un fichier : type, dimensions, durée, codecs, poids."""
    return await _run(app().probe_media, path)


# ---------------------------------------------------------------------------- voix off
@mcp.tool(annotations=LOCAL)
async def generate_voiceover(
    draft_id: str,
    script: str = Field(..., description="Texte lu, phrases courtes (≈ 2,5 mots/s ; 20–45 s au total)."),
    engine: Literal["piper", "elevenlabs"] | None = None,
    voice: str | None = Field(None, description="Voix Piper (ex. fr_FR-siwis-medium) ou id ElevenLabs."),
) -> dict[str, Any]:
    """Synthétise la voix off (Piper local par défaut) avec minutage des mots pour les sous-titres."""
    info = await _run(app().generate_voiceover, draft_id, script, engine, voice)
    return {k: v for k, v in info.model_dump().items() if k != "words"} | {"word_count": len(info.words)}


@mcp.tool(annotations=LOCAL)
async def prepare_voice_recording(draft_id: str, script: str) -> dict[str, Any]:
    """Prépare l'enregistrement de la voix de l'utilisateur : script numéroté, conseils, emplacement du fichier."""
    return await _run(app().prepare_voice_recording, draft_id, script)


@mcp.tool(annotations=LOCAL)
async def import_voice_recording(
    draft_id: str,
    path: str | None = Field(None, description="Fichier audio ; défaut : voix_enregistree.* dans le dossier du brouillon."),
    script: str | None = None,
) -> dict[str, Any]:
    """Importe l'enregistrement de l'utilisateur : nettoyage, normalisation, alignement des sous-titres."""
    info = await _run(app().import_voice_recording, draft_id, path, script)
    return {k: v for k, v in info.model_dump().items() if k != "words"} | {"word_count": len(info.words)}


# ---------------------------------------------------------------------------- vidéo
@mcp.tool(annotations=LOCAL)
async def render_short(draft_id: str, storyboard: Storyboard) -> dict[str, Any]:
    """Monte le short vertical 1080×1920 (scènes, textes, sous-titres, voix, musique) + version Discord.

    Prend 1 à 3 minutes. La voix off du brouillon (generate_voiceover / import_voice_recording)
    doit être prête avant si le short en a une.
    """
    return await _run(app().render_short, draft_id, storyboard)


# ---------------------------------------------------------------------------- publication
@mcp.tool(annotations=LOCAL)
async def approve_draft(draft_id: str) -> dict[str, Any]:
    """Approuve la nouveauté entière (toutes ses langues). UNIQUEMENT après accord explicite de l'utilisateur."""
    members = await _run(app().approve_draft, draft_id)
    return {"drafts": [{"id": d.id, "language": d.language, "status": d.status} for d in members]}


@mcp.tool(annotations=PUBLISH)
async def publish(
    draft_id: str,
    channels: list[str] | None = Field(None, description="Sous-ensemble des canaux du brouillon (défaut : tous)."),
    dry_run: bool | None = Field(None, description="Simulation sans rien envoyer (défaut : NAP_DRY_RUN)."),
) -> dict[str, Any]:
    """Publie la nouveauté approuvée, toutes langues comprises : Discord, X, YouTube selon les modes des canaux."""
    return await _run(app().publish, draft_id, channels, dry_run)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
async def connect_account(
    channel: str = Field(..., description="Id du canal (ex. youtube.main, x.main, discord.exode)."),
) -> dict[str, Any]:
    """Connecte / vérifie un canal en mode API : YouTube (consentement OAuth dans le navigateur, une fois),
    X (vérifie les clés, affiche le compte et le budget), Discord (connexion initiale du bot pour le crosspost)."""
    return await _run(app().connect_account, channel)


@mcp.tool(annotations=LOCAL)
async def mark_published(
    draft_id: str,
    channel: str | None = Field(None, description="Canal confirmé ; vide = tout ce qui est en attente (« c'est posté »)."),
    url: str | None = Field(None, description="URL du post si l'utilisateur la donne (facultatif)."),
) -> dict[str, Any]:
    """Confirme les publications faites à la main (X intent, YouTube manuel) pour toute la nouveauté."""
    return await _run(app().mark_published, draft_id, channel, url)


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    mcp.run()


if __name__ == "__main__":
    main()
