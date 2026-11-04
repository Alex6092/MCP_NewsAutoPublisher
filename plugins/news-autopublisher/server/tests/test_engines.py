"""Captures moteur : un faux éditeur Unity, un faux build et un faux Unreal produisent des images."""

import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest
import yaml
from conftest import needs_ffmpeg

from newsautopublisher.engines import unity, unreal
from newsautopublisher.service import App, UserError

SCENE = f"""%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &100
GameObject:
  m_Name: NapShot
--- !u!114 &200
MonoBehaviour:
  m_ObjectHideFlags: 0
  m_GameObject: {{fileID: 100}}
  m_Enabled: 1
  m_Script: {{fileID: 11500000, guid: {unity.NAPSHOT_GUID}, type: 3}}
  m_Name:
  shotName: hub_flyover
  description: "Survol du hub \\xE9pique"
  duration: 2
  captureCamera: {{fileID: 0}}
--- !u!114 &300
MonoBehaviour:
  m_Script: {{fileID: 11500000, guid: 0000000000000000000000000000abcd, type: 3}}
  shotName: pas_un_plan
"""

FAKE_ENGINE = textwrap.dedent('''
    """Faux moteur : lit une requête NewsAutoPublisher et écrit des images + result.json."""
    import json, subprocess, sys, os
    from pathlib import Path

    def produce(req):
        out = Path(req["outputDir"]); shots = []
        for name in list(req["shots"]) + [p["name"] for p in req.get("procedural", [])]:
            folder = out / name; folder.mkdir(parents=True, exist_ok=True)
            n = 1 if req["mode"] == "screenshot" else 10
            pattern = "still_%02d.jpg" if req["mode"] == "screenshot" else "frame_%05d.jpg"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            f"testsrc2=s=108x192:r={req['fps']}", "-frames:v", str(n), str(folder / pattern)], check=True)
            files = [str(p) for p in sorted(folder.glob("still_*.jpg"))]
            shots.append({"name": name, "description": "", "folder": str(folder), "frames": n, "fps": req["fps"],
                          "width": 108, "height": 192, "files": files})
        (out / "result.json").write_text(json.dumps({"id": req["id"], "status": "done", "shots": shots}))

    if __name__ == "__main__":
        args = sys.argv[1:]
        if "-napRequest" in args:  # build Unity
            produce(json.loads(Path(args[args.index("-napRequest") + 1]).read_text()))
        elif any(a.startswith("-ExecutePythonScript=") for a in args):  # Unreal, mode python
            script = Path(next(a for a in args if a.startswith("-ExecutePythonScript=")).split("=", 1)[1])
            assert script.exists() and script.name == "nap_unreal.py", script
            req = json.loads(Path(os.environ["NAP_UNREAL_REQUEST"]).read_text())
            if req["mode"] == "list_actors":
                result = {"status": "done", "actors": [{"label": "QuestBoard", "class": "StaticMeshActor"},
                                                       {"label": "Sky", "class": "SkyAtmosphere"}]}
            else:
                shots = []
                for shot in req["shots"]:
                    folder = Path(req["output_dir"]) / shot["name"]; folder.mkdir(parents=True, exist_ok=True)
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=108x192:r=30",
                                    "-frames:v", "6", "-start_number", "0", str(folder / "frame_%05d.png")], check=True)
                    shots.append({"name": shot["name"], "folder": str(folder)})
                result = {"status": "done", "shots": shots, "request": req}
            Path(req["result"]).write_text(json.dumps(result))
        else:  # Unreal CLI : écrit une séquence PNG dans Saved/MovieRenders
            uproject = Path(args[0])
            out = uproject.parent / "Saved" / "MovieRenders"; out.mkdir(parents=True, exist_ok=True)
            assert any(a.startswith("-LevelSequence=/Game/Cinematics/Demo.Demo") for a in args), args
            assert any(a.startswith("-MoviePipelineConfig=/Game/NAP/Vertical.Vertical") for a in args), args
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=192x108:r=24",
                            "-frames:v", "8", "-start_number", "0", str(out / "Demo.%04d.png")], check=True)
            print("LogMovieRenderPipeline: Finished rendering")
''')


@pytest.fixture
def unity_project(tmp_path):
    root = tmp_path / "ExodeUnity"
    (root / "Assets" / "Scenes").mkdir(parents=True)
    (root / "Assets" / "Scenes" / "Hub.unity").write_text(SCENE, encoding="utf-8")
    return root


def fake_exe(tmp_path: Path) -> Path:
    script = tmp_path / "fake_engine.py"
    script.write_text(FAKE_ENGINE, encoding="utf-8")
    exe = tmp_path / "fake_engine.sh"
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
    exe.chmod(0o755)
    return exe


def set_project(data_dir: Path, **project):
    cfg_file = data_dir / "config.yaml"
    cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    cfg["projects"]["exode"].update(project)
    cfg_file.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")


def test_scan_shots(unity_project):
    shots = unity.scan_shots(unity_project)
    assert shots == [{"name": "hub_flyover", "description": "Survol du hub épique", "duration": 2.0,
                      "scene": "Assets/Scenes/Hub.unity"}]
    assert not unity.editor_is_open(unity_project)


def test_unreal_command_and_output(tmp_path):
    cmd = unreal.build_command("UE.exe", "P.uproject", "/Game/Maps/Demo", "/Game/Cinematics/Demo",
                               "/Game/NAP/Vertical", 1280, 720, ["-dx12"])
    assert cmd[:4] == ["UE.exe", "P.uproject", "/Game/Maps/Demo", "-game"]
    assert "-LevelSequence=/Game/Cinematics/Demo.Demo" in cmd and "-MoviePipelineConfig=/Game/NAP/Vertical.Vertical" in cmd
    assert cmd[-1] == "-dx12"
    out = tmp_path / "MovieRenders"
    out.mkdir()
    for i in (2, 0, 1):
        (out / f"Demo.{i:04d}.png").write_bytes(b"x")
    (out / "Other.0000.png").write_bytes(b"x")
    frames, video = unreal.collect_output(out, since=time.time() - 60)
    assert [f.name for f in frames] == ["Demo.0000.png", "Demo.0001.png", "Demo.0002.png"] and video is None


@needs_ffmpeg
def test_unity_build_capture(data_dir, unity_project, tmp_path):
    set_project(data_dir, unity={"project_path": str(unity_project), "target": "build",
                                 "build_exe": str(fake_exe(tmp_path)), "fps": 10})
    app = App()
    listed = app.list_engine_shots("exode")
    assert listed["shots"][0]["name"] == "hub_flyover" and listed["build_found"]
    job = app.engine_capture("exode", ["hub_flyover"])
    status = app.engine_capture_status(job["id"], wait_seconds=60)
    assert status["status"] == "done", status
    assert len(status["media"]) == 1 and status["media"][0]["kind"] == "video"
    assert status["media"][0]["duration"] == pytest.approx(1.0, abs=0.15)  # 10 images à 10 i/s
    assert "unity:hub_flyover" in status["media"][0]["note"]
    with pytest.raises(UserError, match="introuvables"):
        app.engine_capture("exode", ["inconnu"])


@needs_ffmpeg
def test_unity_editor_capture_via_request_file(data_dir, unity_project, tmp_path):
    (unity_project / "Temp").mkdir()
    (unity_project / "Temp" / "UnityLockfile").write_text("")
    set_project(data_dir, unity={"project_path": str(unity_project)})
    app = App()
    request_path = unity.request_file(unity_project)

    def fake_editor():  # simule NapEditorBridge + NapCaptureDirector
        for _ in range(100):
            if request_path.exists():
                req = json.loads(request_path.read_text())
                request_path.unlink()
                ns = {}
                exec(FAKE_ENGINE.split("if __name__")[0], ns)
                ns["produce"](req)
                return
            time.sleep(0.1)

    with pytest.raises(UserError, match="mode Play"):  # règle par défaut : accord requis pour l'éditeur
        app.engine_capture("exode", mode="screenshot")
    threading.Thread(target=fake_editor, daemon=True).start()
    job = app.engine_capture("exode", mode="screenshot", user_requested=True)
    assert job["target"] == "editor"
    status = app.engine_capture_status(job["id"], wait_seconds=60)
    assert status["status"] == "done", status
    assert status["media"][0]["kind"] == "image"


def test_unity_editor_closed_without_build(data_dir, unity_project):
    set_project(data_dir, unity={"project_path": str(unity_project)})
    with pytest.raises(UserError, match="éditeur Unity"):
        App().engine_capture("exode")


@needs_ffmpeg
def test_unreal_mrq_capture(data_dir, tmp_path):
    uproject = tmp_path / "Demo" / "Demo.uproject"
    uproject.parent.mkdir()
    uproject.write_text("{}")
    set_project(data_dir, engine="unreal", unreal={
        "editor_cmd": str(fake_exe(tmp_path)), "uproject": str(uproject), "preset": "/Game/NAP/Vertical",
        "render_mode": "cli",
        "shots": {"demo": {"map": "/Game/Maps/Demo", "sequence": "/Game/Cinematics/Demo", "fps": 24,
                           "description": "Démo du graphe de quêtes"}},
    })
    app = App()
    assert app.list_engine_shots("exode")["shots"][0]["name"] == "demo"
    job = app.engine_capture("exode")
    status = app.engine_capture_status(job["id"], wait_seconds=60)
    assert status["status"] == "done", status
    media = status["media"][0]
    assert media["kind"] == "video" and media["width"] == 192
    assert media["duration"] == pytest.approx(8 / 24, abs=0.1)
    assert not list((uproject.parent / "Saved" / "MovieRenders").glob("*.png"))  # images nettoyées
    with pytest.raises(UserError, match="seul le mode vidéo"):
        app.engine_capture("exode", mode="screenshot")


def test_unreal_requires_preset(data_dir, tmp_path):
    uproject = tmp_path / "Demo.uproject"
    uproject.write_text("{}")
    set_project(data_dir, engine="unreal", unreal={
        "editor_cmd": sys.executable, "uproject": str(uproject), "render_mode": "cli",
        "shots": {"demo": {"map": "/Game/Maps/Demo", "sequence": "/Game/Seq/Demo"}},
    })
    with pytest.raises(UserError, match="Preset Movie Render Queue"):
        App().engine_capture("exode")
