"""Automatisation des captures : plans procéduraux, règle de déclenchement, installation, Unreal en mode python."""

import json
import math
import os
import time
from pathlib import Path

import pytest
import yaml
from conftest import git, needs_ffmpeg
from test_engines import SCENE, fake_exe, set_project

from newsautopublisher.engines import nap_unreal, setup, unity
from newsautopublisher.service import App, UserError

HUB_OBJECTS = """
--- !u!1 &400
GameObject:
  m_ObjectHideFlags: 0
  m_Component:
  - component: {fileID: 401}
  m_Layer: 0
  m_Name: QuestBoard
--- !u!1001 &500
PrefabInstance:
  m_Modification:
    m_Modifications:
    - target: {fileID: 1, guid: abc, type: 3}
      propertyPath: m_Name
      value: Forgeron_PNJ
      objectReference: {fileID: 0}
"""


@pytest.fixture
def unity_project(tmp_path):
    root = tmp_path / "ExodeUnity"
    (root / "Assets" / "Scenes").mkdir(parents=True)
    (root / "Assets" / "Scenes" / "Hub.unity").write_text(SCENE + HUB_OBJECTS, encoding="utf-8")
    (root / "ProjectSettings").mkdir()
    (root / "ProjectSettings" / "EditorBuildSettings.asset").write_text(
        "EditorBuildSettings:\n  m_Scenes:\n  - enabled: 0\n    path: Assets/Scenes/Old.unity\n"
        "  - enabled: 1\n    path: Assets/Scenes/Hub.unity\n")
    (root / "ProjectSettings" / "EditorSettings.asset").write_text("EditorSettings:\n  m_SerializationMode: 2\n")
    (root / "Packages").mkdir()
    (root / "Packages" / "manifest.json").write_text(json.dumps({"dependencies": {"com.unity.ugui": "1.0.0"}}, indent=2))
    return root


# ---------------------------------------------------------------------------- Unity : lecture des scènes
def test_scan_objects_and_scenes(unity_project):
    names = {o["name"] for o in unity.scan_objects(unity_project)}
    assert {"NapShot", "QuestBoard", "Forgeron_PNJ"} <= names
    assert [o["name"] for o in unity.scan_objects(unity_project, contains="quest")] == ["QuestBoard"]
    assert unity.build_scenes(unity_project) == ["Assets/Scenes/Hub.unity"]
    assert unity.scene_for_target(unity_project, "Forgeron") == "Assets/Scenes/Hub.unity"
    assert unity.scene_for_target(unity_project, "Inexistant") is None


# ---------------------------------------------------------------------------- règle de déclenchement
@needs_ffmpeg
def test_auto_capture_uses_build_and_procedural_shots(data_dir, unity_project, tmp_path, repo):
    (unity_project / "Temp").mkdir()
    (unity_project / "Temp" / "UnityLockfile").write_text("")  # éditeur ouvert
    exe = fake_exe(tmp_path)
    os.utime(exe, (time.time() - 86400, time.time() - 86400))  # build d'hier
    set_project(data_dir, unity={"project_path": str(unity_project), "build_exe": str(exe), "fps": 10})
    app = App()
    job = app.engine_capture("exode", procedural=[{"name": "board", "target": "QuestBoard", "move": "orbit"}])
    assert job["target"] == "build"  # éditeur ouvert épargné : capture automatique via le build
    assert "build" in job["message"] and "plus ancien que le dernier commit" in job["message"]
    status = app.engine_capture_status(job["id"], wait_seconds=60)
    assert status["status"] == "done", status
    assert status["shots"] == ["board"] and "orbit autour de QuestBoard" in status["media"][0]["note"]
    req = json.loads((Path(job["out_dir"]) / "part1" / "request.json").read_text())
    assert req["shots"] == [] and req["procedural"][0]["target"] == "QuestBoard"
    assert req["scene"] == "Assets/Scenes/Hub.unity"


def test_policy_never_and_unknown_target(data_dir, unity_project, tmp_path):
    set_project(data_dir, unity={"project_path": str(unity_project), "build_exe": str(fake_exe(tmp_path)),
                                 "target": "build"},
                capture={"engine_auto": "never"})
    app = App()
    with pytest.raises(UserError, match="désactivées"):
        app.engine_capture("exode", procedural=[{"name": "a", "target": "QuestBoard"}])
    with pytest.raises(UserError, match="introuvable"):
        app.engine_capture("exode", procedural=[{"name": "a", "target": "Dragon"}], user_requested=True)


# ---------------------------------------------------------------------------- installation automatique
def test_unity_setup_adds_package(unity_project):
    diag = setup.unity_setup(unity_project, apply=False)
    assert not diag["ok"] and diag["changes"]
    assert "com.newsautopublisher.capture" not in (unity_project / "Packages" / "manifest.json").read_text()
    done = setup.unity_setup(unity_project, apply=True)
    manifest = json.loads((unity_project / "Packages" / "manifest.json").read_text())
    assert manifest["dependencies"]["com.newsautopublisher.capture"].endswith("?path=/engines/unity/com.newsautopublisher.capture")
    assert manifest["dependencies"]["com.unity.ugui"] == "1.0.0" and done["ok"]


def test_unreal_setup_enables_plugins(tmp_path):
    up = tmp_path / "Demo.uproject"
    up.write_text(json.dumps({"EngineAssociation": "5.5", "Plugins": [{"Name": "PythonScriptPlugin", "Enabled": False},
                                                                     {"Name": "Other", "Enabled": True}]}))
    res = setup.unreal_setup(up, None, apply=True)
    plugins = {p["Name"]: p["Enabled"] for p in json.loads(up.read_text())["Plugins"]}
    assert all(plugins[n] for n in setup.UNREAL_PLUGINS) and plugins["Other"]
    assert res["checks"][0]["detail"] == "5.5"


# ---------------------------------------------------------------------------- Unreal en mode python
@needs_ffmpeg
def test_unreal_python_mode_generates_and_lists(data_dir, tmp_path):
    uproject = tmp_path / "DQM Demo" / "DQM.uproject"  # espace dans le chemin
    uproject.parent.mkdir()
    uproject.write_text("{}")
    set_project(data_dir, engine="unreal", unreal={
        "editor_cmd": str(fake_exe(tmp_path)), "uproject": str(uproject), "default_map": "/Game/Maps/Demo",
        "shots": {"demo": {"map": "/Game/Maps/Demo", "sequence": "/Game/Cinematics/Demo", "fps": 30}},
    })
    app = App()
    job = app.engine_capture("exode", shots=["demo"],
                             procedural=[{"name": "board", "target": "QuestBoard", "move": "dolly"}])
    status = app.engine_capture_status(job["id"], wait_seconds=60)
    assert status["status"] == "done", status
    assert len(status["media"]) == 2 and all(m["kind"] == "video" for m in status["media"])
    assert (uproject.parent / "Saved" / "NewsAutoPublisher" / "nap_unreal.py").exists()
    req = json.loads((Path(job["out_dir"]) / "unreal_request.json").read_text())
    assert req["shots"][0] == {"name": "demo", "sequence": "/Game/Cinematics/Demo", "map": "/Game/Maps/Demo"}
    assert req["shots"][1]["target"] == "QuestBoard" and req["shots"][1]["map"] == "/Game/Maps/Demo"
    assert req["width"] == 1080 and req["height"] == 1920

    listing = app.list_engine_targets("exode", contains="quest")
    actors = app.engine_capture_status(listing["id"], wait_seconds=60)
    assert actors["status"] == "done" and actors["data"]["actors"] == [{"label": "QuestBoard", "class": "StaticMeshActor"}]


# ---------------------------------------------------------------------------- trajectoires Unreal (pur Python)
def test_unreal_camera_paths():
    center = (100.0, 200.0, 50.0)
    frames, keys = nap_unreal.camera_keys({"move": "orbit", "duration": 4, "arc": 180, "elevation": 20},
                                          center, 100.0, 0.0, 30, 40.0, 70.0)
    assert frames == 120 and keys[0][0] == 0 and keys[-1][0] == 120
    dists = [math.dist(pos, center) for _, pos, _ in keys]
    assert max(dists) - min(dists) < 1e-6  # orbite : distance constante
    for _, pos, (roll, pitch, yaw) in keys:
        assert roll == 0 and pitch < 0  # caméra au-dessus : elle regarde vers le bas
    yaws = [k[2][2] for k in keys]
    assert all(abs(b - a) < 90 for a, b in zip(yaws, yaws[1:]))  # pas de saut de 360°
    _, dolly = nap_unreal.camera_keys({"move": "dolly", "duration": 2}, center, 100.0, 0.0, 30, 40.0, 70.0)
    assert math.dist(dolly[0][1], center) > math.dist(dolly[-1][1], center)  # on avance vers la cible
    assert nap_unreal.object_path("/Game/Maps/Demo") == "/Game/Maps/Demo.Demo"
    assert round(nap_unreal.fov_from_lens(24, 36), 1) == 73.7
