"""Voix off locale avec Piper (gratuit, hors ligne une fois le modèle téléchargé)."""

from __future__ import annotations

import io
import re
import wave
from pathlib import Path

import httpx

from ..models import VoiceInfo, Word
from .text import VoiceError, estimate_words, split_sentences

HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
VOICE_NAME = re.compile(r"^(?P<lang>(?P<family>[a-z]{2,3})_[A-Z]{2})-(?P<name>[\w]+)-(?P<quality>x_low|low|medium|high)$")


def model_urls(voice: str) -> tuple[str, str]:
    m = VOICE_NAME.match(voice)
    if not m:
        raise VoiceError(f"Nom de voix Piper invalide : {voice} (ex. fr_FR-siwis-medium).")
    base = f"{HF_BASE}/{m['family']}/{m['lang']}/{m['name']}/{m['quality']}/{voice}"
    return f"{base}.onnx", f"{base}.onnx.json"


def ensure_model(voice: str, models_dir: Path) -> Path:
    """Renvoie le chemin du modèle .onnx, téléchargé depuis Hugging Face au premier usage."""
    if voice.lower().endswith(".onnx"):
        p = Path(voice).expanduser()
        if not p.exists():
            raise VoiceError(f"Modèle Piper introuvable : {p}")
        return p
    target_dir = models_dir / "piper"
    target_dir.mkdir(parents=True, exist_ok=True)
    onnx, cfg = target_dir / f"{voice}.onnx", target_dir / f"{voice}.onnx.json"
    if onnx.exists() and cfg.exists():
        return onnx
    onnx_url, cfg_url = model_urls(voice)
    try:
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            for url, dest in ((cfg_url, cfg), (onnx_url, onnx)):
                tmp = dest.with_suffix(dest.suffix + ".part")
                with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        raise VoiceError(f"Téléchargement de la voix {voice} impossible (HTTP {resp.status_code}).")
                    with tmp.open("wb") as fh:
                        for chunk in resp.iter_bytes(1 << 20):
                            fh.write(chunk)
                tmp.replace(dest)
    except httpx.HTTPError as exc:
        raise VoiceError(f"Téléchargement de la voix {voice} impossible : {exc.__class__.__name__}") from exc
    return onnx


def synthesize(
    script: str,
    voice: str,
    models_dir: Path,
    out_wav: Path,
    length_scale: float = 1.0,
    sentence_pause: float = 0.28,
) -> VoiceInfo:
    try:
        from piper import PiperVoice, SynthesisConfig
    except ImportError as exc:  # pragma: no cover
        raise VoiceError("Le paquet piper-tts n'est pas installé.") from exc

    sentences = split_sentences(script)
    if not sentences:
        raise VoiceError("Script vide.")
    model = PiperVoice.load(ensure_model(voice, models_dir))
    syn = SynthesisConfig(length_scale=length_scale)

    frames: list[bytes] = []
    words: list[Word] = []
    params = None
    t = 0.0
    for sentence in sentences:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            model.synthesize_wav(sentence, wf, syn_config=syn)
        buf.seek(0)
        with wave.open(buf, "rb") as rf:
            params = rf.getparams()
            data = rf.readframes(rf.getnframes())
            dur = rf.getnframes() / rf.getframerate()
        # Piper laisse un court silence en début/fin de phrase : on resserre légèrement le minutage.
        words += estimate_words(sentence, t + 0.05, t + max(dur - 0.08, 0.1))
        frames.append(data)
        t += dur
        silence = int(params.framerate * sentence_pause) * params.sampwidth * params.nchannels
        frames.append(b"\x00" * silence)
        t += sentence_pause

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(params.nchannels)
        wf.setsampwidth(params.sampwidth)
        wf.setframerate(params.framerate)
        wf.writeframes(b"".join(frames))
    return VoiceInfo(engine="piper", audio_path=str(out_wav), duration=round(t, 3), script=script,
                     alignment="estimated", words=words)
