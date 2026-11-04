import subprocess

from conftest import needs_ffmpeg

from newsautopublisher.ffmpeg import probe
from newsautopublisher.models import VoiceInfo, Word
from newsautopublisher.video.render import Brand, Renderer, RenderSettings
from newsautopublisher.video.storyboard import Storyboard


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


@needs_ffmpeg
def test_render_small_short(tmp_path):
    clip, img, voice, logo = tmp_path / "c.mp4", tmp_path / "i.png", tmp_path / "v.wav", tmp_path / "logo.png"
    ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=15:d=2", "-pix_fmt", "yuv420p", str(clip))
    ff("-f", "lavfi", "-i", "mandelbrot=s=320x180", "-frames:v", "1", str(img))
    ff("-f", "lavfi", "-i", "sine=f=300:d=3", str(voice))
    ff("-f", "lavfi", "-i", "color=c=red:s=100x40", "-frames:v", "1", str(logo))
    sb = Storyboard.model_validate({
        "headline": "Test",
        "scenes": [
            {"type": "title", "text": "Bonjour", "duration": 1},
            {"type": "clip", "media": str(clip), "zoom": 1.4},
            {"type": "image", "media": str(img), "duration": 1},
            {"type": "outro", "text": "Fin", "subtext": "lien", "duration": 1},
        ],
    })
    v = VoiceInfo(engine="test", audio_path=str(voice), duration=3.0, script="Un deux trois",
                  words=[Word(text="Un", start=0, end=1), Word(text="deux", start=1, end=2),
                         Word(text="trois", start=2, end=3)])
    r = Renderer("ffmpeg", "ffprobe", RenderSettings(width=270, height=480, fps=15, preset="ultrafast"),
                 Brand(logo=str(logo)))
    res = r.render(sb, v, tmp_path / "work", tmp_path / "short.mp4")
    info = probe(res["path"], "ffprobe")
    assert (info["width"], info["height"]) == (270, 480)
    assert info["has_audio"]
    assert abs(info["duration"] - res["duration"]) < 0.3
    assert res["duration"] >= 5.0  # 1 + 2 + 1 + 1
    assert (tmp_path / "short_cover.jpg").exists()
    small = r.discord_variant(tmp_path / "short.mp4", 0.05)
    assert small.name == "short_discord.mp4"


@needs_ffmpeg
def test_fit_to_voice_extends_scenes(tmp_path):
    voice = tmp_path / "v.wav"
    ff("-f", "lavfi", "-i", "sine=f=300:d=6", str(voice))
    sb = Storyboard.model_validate({"scenes": [{"type": "title", "text": "A", "duration": 1},
                                               {"type": "outro", "text": "B", "duration": 1}]})
    v = VoiceInfo(engine="test", audio_path=str(voice), duration=6.0, script="x")
    r = Renderer("ffmpeg", "ffprobe", RenderSettings(width=270, height=480, fps=15), Brand())
    plan = r.plan(sb, v)
    total = sum(d for _, d, _ in plan)
    assert abs(total - (sb.voice_offset + 6.0 + sb.tail)) < 0.01
