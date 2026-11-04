"""Script exécuté DANS Unreal Editor (-ExecutePythonScript) par NewsAutoPublisher.

Modes (requête JSON dont le chemin est dans la variable d'environnement NAP_UNREAL_REQUEST) :
  - list_actors : liste les acteurs d'une map (libellé, classe, position, taille) ;
  - render      : pour chaque plan, utilise une Level Sequence existante ou en GÉNÈRE une (caméra
                  CineCamera en orbite / travelling / survol autour d'un acteur), puis rend le tout
                  avec Movie Render Queue (exécuteur PIE, configuration créée par script : aucun
                  preset nécessaire) et ferme l'éditeur.
Le résultat est écrit dans le fichier « result » de la requête.

Plugins requis dans le projet : Python Editor Script Plugin, Sequencer Scripting,
Editor Scripting Utilities, Movie Render Queue (engine_setup les active).
Les calculs de trajectoire n'utilisent pas le module unreal : ils sont testables hors de l'éditeur.
"""

from __future__ import annotations

import json
import math
import os
import traceback

try:  # absent hors d'Unreal (tests)
    import unreal  # type: ignore
except ImportError:  # pragma: no cover
    unreal = None

MOVES = ("orbit", "dolly", "pullback", "flyover", "static")


# ----------------------------------------------------------------------------- trajectoires (pur Python)
def smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def fov_from_lens(focal_mm: float, sensor_mm: float) -> float:
    return math.degrees(2 * math.atan(sensor_mm / (2 * focal_mm)))


def orbit_point(center, distance, yaw_deg, elevation_deg):
    yaw, el = math.radians(yaw_deg), math.radians(max(-80.0, min(85.0, elevation_deg)))
    cx, cy, cz = center
    return (cx + distance * math.cos(el) * math.cos(yaw),
            cy + distance * math.cos(el) * math.sin(yaw),
            cz + distance * math.sin(el))


def look_at(position, target):
    """(roll, pitch, yaw) en degrés pour regarder target depuis position (repère Unreal : X avant, Z haut)."""
    dx, dy, dz = (target[i] - position[i] for i in range(3))
    yaw = math.degrees(math.atan2(dy, dx))
    pitch = math.degrees(math.atan2(dz, math.hypot(dx, dy)))
    return (0.0, pitch, yaw)


def camera_keys(spec: dict, center, radius: float, forward_yaw: float, fps: int, hfov: float, vfov: float):
    """Clés (frame, position, rotation) d'un plan généré autour d'une sphère (center, radius)."""
    move = spec.get("move", "orbit")
    if move not in MOVES:
        move = "orbit"
    duration = max(0.5, float(spec.get("duration", 5)))
    frames = max(1, int(round(duration * fps)))
    fit = max(radius, 1.0) / math.sin(math.radians(min(hfov, vfov)) / 2) * 1.05
    d = fit * float(spec.get("distance") or 1.0)
    el = float(spec.get("elevation", 15))
    yaw0 = forward_yaw + float(spec.get("angle", 25))
    arc = float(spec.get("arc") or 90)

    def pose(u: float):
        if move == "dolly":
            return orbit_point(center, d * (1.5 - 0.65 * u), yaw0, el)
        if move == "pullback":
            return orbit_point(center, d * (0.85 + 0.75 * u), yaw0, el + 10 * u)
        if move == "flyover":
            return orbit_point(center, d * 1.6, yaw0 - 40 + 80 * u, max(el, 50))
        if move == "static":
            return orbit_point(center, d * (1.03 - 0.03 * u), yaw0, el)
        return orbit_point(center, d, yaw0 - arc / 2 + arc * u, el)

    step = max(1, fps // 4)  # une clé tous les 1/4 s, interpolation automatique entre les clés
    marks = list(range(0, frames, step)) + [frames]
    keys, last_yaw = [], None
    for f in marks:
        pos = pose(smoothstep(f / frames))
        roll, pitch, yaw = look_at(pos, center)
        if last_yaw is not None:  # pas de saut de 360° entre deux clés
            while yaw - last_yaw > 180:
                yaw -= 360
            while yaw - last_yaw < -180:
                yaw += 360
        last_yaw = yaw
        keys.append((f, pos, (roll, pitch, yaw)))
    return frames, keys


def object_path(path: str) -> str:
    if "." in path.rsplit("/", 1)[-1]:
        return path
    return f"{path}.{path.rstrip('/').rsplit('/', 1)[-1]}"


def safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name) or "plan"


# ----------------------------------------------------------------------------- partie Unreal
STATE: dict = {"ticks": 0, "handle": None, "executor": None, "req": None, "log": []}


def log(msg: str) -> None:
    STATE["log"].append(msg)
    unreal.log(f"[NewsAutoPublisher] {msg}")


def write_result(status: str, **extra) -> None:
    req = STATE["req"] or {}
    data = {"id": req.get("id"), "status": status, "log": STATE["log"][-50:], **extra}
    path = req.get("result")
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)


def finish(status: str, **extra) -> None:
    try:
        write_result(status, **extra)
    finally:
        unreal.SystemLibrary.quit_editor()


def load_level(map_path: str) -> None:
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(map_path):
        raise RuntimeError(f"Impossible de charger la map {map_path}")


def all_actors():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()


def find_actor(query: str):
    actors = list(all_actors())
    q = query.lower()
    for test in (lambda a: a.get_actor_label() == query, lambda a: a.get_actor_label().lower() == q,
                 lambda a: a.get_name().lower() == q, lambda a: q in a.get_actor_label().lower()):
        for a in actors:
            if test(a):
                return a
    raise RuntimeError(f"Acteur introuvable : « {query} »")


def bounds_of(actor):
    origin, extent = actor.get_actor_bounds(False, True)
    radius = math.sqrt(extent.x ** 2 + extent.y ** 2 + extent.z ** 2)
    return (origin.x, origin.y, origin.z), max(radius, 50.0)


def add_spawnable_camera(seq):
    try:  # UE 5.6+ : API de l'éditeur de séquences
        sub = unreal.get_editor_subsystem(unreal.LevelSequenceEditorSubsystem)
        binding = sub.add_spawnable_from_class(seq, unreal.CineCameraActor)
        if binding:
            return binding
    except Exception as exc:  # noqa: BLE001
        log(f"add_spawnable_from_class (subsystem) indisponible : {exc}")
    return unreal.MovieSceneSequenceExtensions.add_spawnable_from_class(seq, unreal.CineCameraActor)


def binding_id(seq, binding):
    ext = unreal.MovieSceneSequenceExtensions
    try:
        return ext.get_portable_binding_id(seq, seq, binding)
    except Exception:  # noqa: BLE001
        return ext.get_binding_id(seq, binding)


def transform_channels(section):
    ext = unreal.MovieSceneSectionExtensions
    try:
        chans = list(ext.get_channels_by_type(section, unreal.MovieSceneScriptingDoubleChannel))
    except Exception:  # noqa: BLE001
        chans = []
    if not chans:
        chans = list(ext.get_all_channels(section))
    names = [str(c.channel_name()) for c in chans]
    wanted = ["Location.X", "Location.Y", "Location.Z", "Rotation.X", "Rotation.Y", "Rotation.Z"]
    if all(w in names for w in wanted):
        return [chans[names.index(w)] for w in wanted]
    log(f"Noms de canaux inattendus {names[:9]} : ordre par défaut utilisé.")
    return chans[:6]


def add_key(channel, frame: int, value: float) -> None:
    fn = unreal.FrameNumber(int(frame))
    try:
        channel.add_key(fn, float(value), interpolation=unreal.MovieSceneKeyInterpolation.AUTO)
    except TypeError:
        channel.add_key(fn, float(value))


def configure_camera(binding, focal: float, vertical: bool):
    cam = binding.get_object_template()
    comp = cam.get_cine_camera_component()
    if vertical:
        fb = comp.get_editor_property("filmback")
        fb.sensor_width, fb.sensor_height = 18.66, 33.18  # 9:16
        comp.set_editor_property("filmback", fb)
    comp.set_editor_property("current_focal_length", focal)
    fs = comp.get_editor_property("focus_settings")
    fs.focus_method = unreal.CameraFocusMethod.DISABLE  # pas de flou de profondeur de champ
    comp.set_editor_property("focus_settings", fs)
    fb = comp.get_editor_property("filmback")
    return fb.sensor_width, fb.sensor_height


def build_sequence(req: dict, shot: dict, map_path: str) -> str:
    fps, width, height = int(req.get("fps", 30)), int(req.get("width", 1080)), int(req.get("height", 1920))
    load_level(map_path)
    actor = find_actor(shot["target"])
    center, radius = bounds_of(actor)
    fwd = actor.get_actor_forward_vector()
    forward_yaw = math.degrees(math.atan2(fwd.y, fwd.x))

    folder = req.get("asset_dir") or "/Game/NewsAutoPublisher/Auto"
    name = "NAP_" + safe_name(shot["name"])
    full = f"{folder}/{name}"
    eal = unreal.EditorAssetLibrary
    if eal.does_asset_exist(full):
        eal.delete_asset(full)
    seq = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, folder, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    ext = unreal.MovieSceneSequenceExtensions
    ext.set_display_rate(seq, unreal.FrameRate(fps, 1))

    binding = add_spawnable_camera(seq)
    focal = float(shot.get("focal_length") or 24.0)
    sw, sh = configure_camera(binding, focal, vertical=height > width)
    hfov, vfov = fov_from_lens(focal, sw), fov_from_lens(focal, sh)
    frames, keys = camera_keys(shot, center, radius, forward_yaw, fps, hfov, vfov)
    ext.set_playback_start(seq, 0)
    ext.set_playback_end(seq, frames)

    secx = unreal.MovieSceneSectionExtensions
    cut_track = ext.add_track(seq, unreal.MovieSceneCameraCutTrack)
    cut = cut_track.add_section()
    secx.set_range(cut, 0, frames)
    cut.set_camera_binding_id(binding_id(seq, binding))

    track = binding.add_track(unreal.MovieScene3DTransformTrack)
    section = track.add_section()
    secx.set_range(section, 0, frames)
    channels = transform_channels(section)
    for frame, (x, y, z), (roll, pitch, yaw) in keys:
        for channel, value in zip(channels, (x, y, z, roll, pitch, yaw)):
            add_key(channel, frame, value)

    eal.save_loaded_asset(seq, False)
    log(f"Séquence générée {full} : {shot.get('move', 'orbit')} autour de {actor.get_actor_label()} "
        f"({frames} images, rayon {radius:.0f} cm).")
    return seq.get_path_name()


def set_prop(obj, name: str, value) -> None:
    try:
        obj.set_editor_property(name, value)
    except Exception as exc:  # noqa: BLE001
        log(f"Propriété {type(obj).__name__}.{name} non réglée : {exc}")


def start_render(req: dict, jobs: list) -> None:
    sub = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
    queue = sub.get_queue()
    queue.delete_all_jobs()
    fps = int(req.get("fps", 30))
    png = req.get("format", "png") == "png"
    for name, seq_path, map_path, out_dir in jobs:
        job = queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
        job.set_editor_property("job_name", name)
        job.set_editor_property("sequence", unreal.SoftObjectPath(object_path(seq_path)))
        job.set_editor_property("map", unreal.SoftObjectPath(object_path(map_path)))
        if req.get("preset"):
            job.set_configuration(unreal.load_asset(object_path(req["preset"])))
        cfg = job.get_configuration()
        out = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
        set_prop(out, "output_directory", unreal.DirectoryPath(out_dir))
        set_prop(out, "file_name_format", "frame_{frame_number}")
        set_prop(out, "zero_pad_frame_numbers", 5)
        set_prop(out, "override_existing_output", True)
        if not req.get("preset") or req.get("force_resolution", True):
            set_prop(out, "output_resolution", unreal.IntPoint(int(req.get("width", 1080)), int(req.get("height", 1920))))
            set_prop(out, "use_custom_frame_rate", True)
            set_prop(out, "output_frame_rate", unreal.FrameRate(fps, 1))
        cfg.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
        cfg.find_or_add_setting_by_class(
            unreal.MoviePipelineImageSequenceOutput_PNG if png else unreal.MoviePipelineImageSequenceOutput_JPG)
        aa = cfg.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
        set_prop(aa, "engine_warm_up_count", 32)  # laisse le temps au streaming et à la TAA de se stabiliser
    executor = sub.render_queue_with_executor(unreal.MoviePipelinePIEExecutor)
    STATE["executor"] = executor
    STATE["jobs"] = jobs

    def on_finished(_executor, success):
        shots = [{"name": n, "folder": o} for n, _s, _m, o in STATE["jobs"]]
        finish("done" if success else "error", shots=shots,
               error="" if success else "Movie Render Queue a signalé un échec (voir le journal).")

    executor.on_executor_finished_delegate.add_callable_unique(on_finished)
    log(f"Rendu Movie Render Queue lancé ({len(jobs)} plan(s)).")


def run(req: dict) -> None:
    mode = req.get("mode", "render")
    if mode == "list_actors":
        load_level(req["map"])
        actors = []
        for a in list(all_actors())[: int(req.get("limit", 3000))]:
            try:
                center, radius = bounds_of(a)
            except Exception:  # noqa: BLE001
                center, radius = (0, 0, 0), 0
            actors.append({"label": a.get_actor_label(), "class": a.get_class().get_name(),
                           "location": [round(v) for v in center], "radius_cm": round(radius)})
        finish("done", actors=actors)
        return

    jobs = []
    for shot in req.get("shots", []):
        map_path = shot.get("map") or req.get("map")
        if not map_path:
            raise RuntimeError(f"Map manquante pour le plan {shot.get('name')}")
        out_dir = os.path.join(req["output_dir"], safe_name(shot["name"]))
        os.makedirs(out_dir, exist_ok=True)
        seq_path = shot.get("sequence") or build_sequence(req, shot, map_path)
        jobs.append((shot["name"], seq_path, map_path, out_dir))
    if not jobs:
        raise RuntimeError("Aucun plan à rendre.")
    start_render(req, jobs)


def on_tick(_delta: float) -> None:
    # Attend que l'éditeur et le registre d'assets soient prêts avant de travailler.
    STATE["ticks"] += 1
    if STATE["ticks"] < 30:
        return
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    if registry.is_loading_assets() and STATE["ticks"] < 3000:
        return
    unreal.unregister_slate_post_tick_callback(STATE["handle"])
    try:
        run(STATE["req"])
    except Exception as exc:  # noqa: BLE001
        log(traceback.format_exc())
        finish("error", error=f"{exc.__class__.__name__}: {exc}")


def main() -> None:
    path = os.environ.get("NAP_UNREAL_REQUEST")
    if not path or not os.path.exists(path):
        unreal.log_error("[NewsAutoPublisher] NAP_UNREAL_REQUEST manquant : rien à faire.")
        return
    with open(path, encoding="utf-8") as fh:
        STATE["req"] = json.load(fh)
    STATE["handle"] = unreal.register_slate_post_tick_callback(on_tick)


if unreal is not None:
    main()
