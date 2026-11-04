"""Rendu d'un short vertical avec ffmpeg.

Étapes : une vidéo intermédiaire par scène (format identique) -> concaténation -> passe finale
(sous-titres ASS incrustés + mixage voix / musique avec ducking + normalisation -14 LUFS).
Les commandes sont lancées depuis le dossier de travail avec des chemins relatifs pour éviter
les problèmes d'échappement des chemins Windows (C:\\...) dans les filtres ffmpeg.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..ffmpeg import FFmpegError, probe, run
from ..models import VoiceInfo, Word
from ..paths import fonts_dir
from .captions import TimedScene, build_ass
from .storyboard import DEFAULT_DURATION, Scene, Storyboard

AUDIO_EXT = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus"}


@dataclass
class RenderSettings:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 20
    preset: str = "medium"
    max_seconds: float = 60.0


@dataclass
class Brand:
    color: str = "#7C5CFF"
    accent: str = "#FFD166"
    background: str = "#0E0B1A"
    logo: str | None = None
    music: str | None = None
    music_volume: float = 0.18


def _even(n: float) -> int:
    n = int(round(n))
    return n - (n % 2)


def _mix(c1: str, c2: str, t: float) -> str:
    a = [int(c1.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    b = [int(c2.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    return "0x" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b))


def pick_music(music: str | None, seed: str) -> Path | None:
    if not music or music.lower() == "none":
        return None
    p = Path(music).expanduser()
    if p.is_file():
        return p
    if p.is_dir():
        tracks = sorted(f for f in p.iterdir() if f.suffix.lower() in AUDIO_EXT)
        if tracks:
            idx = int(hashlib.sha1(seed.encode()).hexdigest(), 16) % len(tracks)
            return tracks[idx]
    return None


class Renderer:
    def __init__(self, ffmpeg: str, ffprobe: str, settings: RenderSettings, brand: Brand):
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.s = settings
        self.brand = brand
        self.warnings: list[str] = []

    # ------------------------------------------------------------------ minutage
    def plan(self, sb: Storyboard, voice: VoiceInfo | None) -> list[tuple[Scene, float, dict | None]]:
        items: list[tuple[Scene, float, dict | None]] = []
        for sc in sb.scenes:
            info = probe(sc.media, self.ffprobe) if sc.media else None
            if sc.type in ("clip", "image") and not info:
                raise FFmpegError(f"La scène {sc.type} nécessite un média.")
            if sc.type == "clip" and info and info["kind"] != "video":
                raise FFmpegError(f"{Path(sc.media).name} n'est pas une vidéo (scène clip).")
            dur = sc.duration
            if dur is None:
                dur = DEFAULT_DURATION[sc.type]
                if sc.type == "clip" and info and info["duration"]:
                    dur = min(max(info["duration"] - sc.start, 0.5), 6.0)
            items.append((sc, float(dur), info))

        total = sum(d for _, d, _ in items)
        if voice and sb.fit_to_voice:
            needed = sb.voice_offset + voice.duration + sb.tail
            if needed > total:
                factor = needed / total
                items = [(sc, d * factor, info) for sc, d, info in items]
        total = sum(d for _, d, _ in items)
        if total > 180:
            raise FFmpegError(f"Short de {total:.0f} s : YouTube Shorts accepte 180 s maximum.")
        if total > self.s.max_seconds:
            self.warnings.append(
                f"Durée {total:.1f} s > {self.s.max_seconds:.0f} s recommandées : raccourcis le script."
            )
        return items

    # ------------------------------------------------------------------ scènes
    def _composite(self, src: str, fit: str, zoom: float, out: str, blur_strong: bool = False) -> str:
        W, H = self.s.width, self.s.height
        if fit == "cover":
            chain = f"[{src}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
            if blur_strong:
                chain += ",gblur=sigma=18,eq=brightness=-0.25"
            return chain + f"[{out}]"
        sw, sh = W // 4, H // 4
        fgw = _even(W * zoom)
        bg = (f"[{src}_a]scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
              f"gblur=sigma={10 if blur_strong else 6},scale={W}:{H},eq=brightness=-0.2:saturation=1.15[{out}_bg]")
        fg = f"[{src}_b]scale={fgw}:-2,crop='min(iw,{W})':'min(ih,{H})'[{out}_fg]"
        return (f"[{src}]split=2[{src}_a][{src}_b];{bg};{fg};"
                f"[{out}_bg][{out}_fg]overlay=(W-w)/2:(H-h)/2,setsar=1[{out}]")

    def _encode_args(self, dur: float) -> list[str]:
        return ["-t", f"{dur:.3f}", "-r", str(self.s.fps), "-an", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "16", "-pix_fmt", "yuv420p", "-video_track_timescale", str(self.s.fps * 1000)]

    def render_scene(self, sc: Scene, dur: float, info: dict | None, out: Path) -> None:
        W, H, fps = self.s.width, self.s.height, self.s.fps
        base = [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
        is_card = sc.type in ("title", "text", "outro")

        if info and info["kind"] == "video":
            avail = max((info["duration"] or dur) - sc.start, 0.1)
            inputs = ["-ss", f"{sc.start:.3f}", "-t", f"{min(dur, avail):.3f}", "-i", sc.media]
            pad = max(dur - avail, 0)
            graph = f"[0:v]fps={fps},setpts=PTS-STARTPTS[src];"
            graph += self._composite("src", "cover" if is_card else sc.fit, sc.zoom, "c", blur_strong=is_card)
            graph += f";[c]tpad=stop_mode=clone:stop_duration={pad + 0.1:.3f},format=yuv420p[v]"
        elif info and info["kind"] == "image":
            frames = max(int(dur * fps), 1)
            inputs = ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", sc.media]
            graph = "[0:v]setsar=1[src];"
            graph += self._composite("src", "cover" if is_card else sc.fit, sc.zoom, "c", blur_strong=is_card)
            amt = 0.0 if is_card else sc.ken_burns
            if amt > 0:
                graph += (f";[c]scale={W * 2}:{H * 2},zoompan=z='1+{amt}*on/{frames}'"
                          f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={fps},format=yuv420p[v]")
            else:
                graph += ";[c]format=yuv420p[v]"
        else:
            c0 = "0x" + self.brand.background.lstrip("#")
            c1 = _mix(self.brand.background, self.brand.color, 0.55)
            inputs = ["-f", "lavfi", "-i",
                      f"gradients=s={W}x{H}:r={fps}:d={dur:.3f}:c0={c0}:c1={c1}:nb_colors=2"
                      f":x0=0:y0=0:x1={W}:y1={H}:speed=0.006"]
            graph = "[0:v]vignette=PI/5,format=yuv420p[v]"

        if sc.type == "outro" and self.brand.logo and Path(self.brand.logo).exists():
            inputs += ["-i", self.brand.logo]
            logo_w = _even(W * 0.5)
            graph = graph[: graph.rfind("[v]")] + "[bgv];"
            graph += (f"[1:v]scale={logo_w}:-1,format=rgba[lg];"
                      f"[bgv][lg]overlay=(W-w)/2:{int(H * 0.2)},format=yuv420p[v]")

        run(base + inputs + ["-filter_complex", graph, "-map", "[v]"] + self._encode_args(dur) + [str(out)])

    # ------------------------------------------------------------------ assemblage
    def render(
        self,
        sb: Storyboard,
        voice: VoiceInfo | None,
        work: Path,
        out: Path,
        seed: str = "",
    ) -> dict:
        work.mkdir(parents=True, exist_ok=True)
        for old in work.glob("seg_*.mp4"):
            old.unlink()
        items = self.plan(sb, voice)

        timeline: list[TimedScene] = []
        t = 0.0
        concat_lines = []
        for i, (sc, dur, info) in enumerate(items):
            seg = work / f"seg_{i:03d}.mp4"
            self.render_scene(sc, dur, info, seg)
            concat_lines.append(f"file '{seg.name}'")
            timeline.append(TimedScene(sc, t, t + dur))
            t += dur
        total = t
        (work / "concat.txt").write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
        run([self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", "concat.txt", "-c", "copy", "video.mp4"], cwd=work)

        words: list[Word] = []
        if voice:
            words = [Word(text=w.text, start=w.start + sb.voice_offset, end=w.end + sb.voice_offset)
                     for w in voice.words]
        has_logo = bool(self.brand.logo and Path(self.brand.logo).exists())
        ass = build_ass(sb, timeline, words, self.s.width, self.s.height, self.brand.color,
                        self.brand.accent, has_logo)
        (work / "captions.ass").write_text(ass, encoding="utf-8")
        fdir = work / "fonts"
        fdir.mkdir(exist_ok=True)
        for f in fonts_dir().glob("*.otf"):
            if not (fdir / f.name).exists():
                shutil.copyfile(f, fdir / f.name)

        music = pick_music(sb.music if sb.music is not None else self.brand.music, seed)
        mvol = sb.music_volume if sb.music_volume is not None else self.brand.music_volume
        inputs = ["-i", "video.mp4"]
        filters = ["[0:v]subtitles=captions.ass:fontsdir=fonts,format=yuv420p[v]"]
        fade_st = max(total - 1.2, 0)
        norm = "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000"
        delay_ms = int(sb.voice_offset * 1000)
        if voice:
            inputs += ["-i", str(Path(voice.audio_path).resolve())]
            v = (f"[1:a]aresample=48000,aformat=channel_layouts=stereo,adelay={delay_ms}|{delay_ms},"
                 f"apad,atrim=0:{total:.3f}")
            if music:
                inputs += ["-stream_loop", "-1", "-i", str(music.resolve())]
                filters += [
                    f"{v},asplit=2[vo][sc]",
                    f"[2:a]aresample=48000,aformat=channel_layouts=stereo,volume={mvol:.3f},atrim=0:{total:.3f}[mu]",
                    "[mu][sc]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=400[duck]",
                    f"[vo][duck]amix=inputs=2:duration=first:normalize=0,afade=t=out:st={fade_st:.3f}:d=1.2,{norm}[a]",
                ]
            else:
                filters.append(f"{v},{norm}[a]")
        elif music:
            inputs += ["-stream_loop", "-1", "-i", str(music.resolve())]
            filters.append(f"[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={max(mvol, 0.6):.3f},"
                           f"atrim=0:{total:.3f},afade=t=out:st={fade_st:.3f}:d=1.2,{norm}[a]")
        else:
            inputs += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            filters.append("[1:a]anull[a]")

        out.parent.mkdir(parents=True, exist_ok=True)
        run([self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *inputs,
             "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", self.s.preset, "-crf", str(self.s.crf), "-pix_fmt", "yuv420p",
             "-r", str(self.s.fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
             "-movflags", "+faststart", "-t", f"{total:.3f}", str(out.resolve())], cwd=work)

        cover = out.with_name(out.stem + "_cover.jpg")
        first_card = next((ts for ts in timeline if ts.scene.type == "title"), timeline[0])
        at = min(first_card.start + (first_card.end - first_card.start) * 0.6, total - 0.1)
        run([self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{at:.3f}", "-i", str(out),
             "-frames:v", "1", "-q:v", "3", str(cover)])

        return {
            "path": str(out),
            "cover": str(cover),
            "duration": round(total, 2),
            "size_mb": round(out.stat().st_size / 1024 / 1024, 2),
            "music": str(music) if music else None,
            "timeline": [{"type": ts.scene.type, "start": round(ts.start, 2), "end": round(ts.end, 2),
                          "text": ts.scene.text} for ts in timeline],
            "warnings": self.warnings,
        }

    def x_variant(self, src: Path) -> Path:
        """Copie 720×1280 pour X (portrait limité à 1200×1900, 140 s maximum)."""
        info = probe(src, self.ffprobe)
        if (info["duration"] or 0) > 140:
            raise FFmpegError(f"Vidéo de {info['duration']:.0f} s : X accepte 140 s maximum.")
        out = src.with_name(src.stem + "_x.mp4")
        if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
            return out
        run([self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
             "-vf", "scale=720:1280:flags=lanczos", "-r", "30", "-c:v", "libx264", "-preset", "medium",
             "-crf", "21", "-maxrate", "5000k", "-bufsize", "10000k", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", str(out)])
        return out

    def discord_variant(self, src: Path, max_mb: float) -> Path:
        """Copie ≤ max_mb pour l'upload Discord (720×1280, débit calculé)."""
        size_mb = src.stat().st_size / 1024 / 1024
        if size_mb <= max_mb * 0.97:
            return src
        info = probe(src, self.ffprobe)
        dur = max(info["duration"] or 1.0, 1.0)
        out = src.with_name(src.stem + "_discord.mp4")
        budget = max_mb * 0.92
        for _ in range(3):
            v_kbps = max(int(budget * 8 * 1024 / dur - 96), 250)
            run([self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
                 "-vf", "scale=720:1280:flags=lanczos", "-c:v", "libx264", "-preset", "medium",
                 "-b:v", f"{v_kbps}k", "-maxrate", f"{int(v_kbps * 1.2)}k", "-bufsize", f"{v_kbps * 2}k",
                 "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out)])
            if out.stat().st_size / 1024 / 1024 <= max_mb * 0.98:
                return out
            budget *= 0.8
        self.warnings.append(f"Impossible de descendre sous {max_mb:g} Mo pour Discord.")
        return out
