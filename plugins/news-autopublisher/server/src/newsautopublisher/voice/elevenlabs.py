"""Voix off ElevenLabs (payant) avec minutage caractère par caractère fourni par l'API."""

from __future__ import annotations

import base64
from pathlib import Path

import httpx

from ..ffmpeg import run
from ..models import VoiceInfo, Word
from .text import VoiceError

API = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"


def words_from_alignment(chars: list[str], starts: list[float], ends: list[float]) -> list[Word]:
    words: list[Word] = []
    current, w_start, w_end = "", None, None
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if current:
                words.append(Word(text=current, start=w_start, end=w_end))
            current, w_start, w_end = "", None, None
            continue
        if not current:
            w_start = s
        current += ch
        w_end = e
    if current:
        words.append(Word(text=current, start=w_start, end=w_end))
    return words


def synthesize(
    script: str,
    api_key: str,
    voice_id: str,
    model_id: str,
    out_wav: Path,
    ffmpeg: str,
    client: httpx.Client | None = None,
) -> VoiceInfo:
    own = client is None
    client = client or httpx.Client(timeout=180)
    try:
        resp = client.post(
            API.format(voice_id=voice_id),
            headers={"xi-api-key": api_key},
            params={"output_format": "mp3_44100_128"},
            json={"text": script, "model_id": model_id},
        )
    except httpx.HTTPError as exc:
        raise VoiceError(f"ElevenLabs injoignable : {exc.__class__.__name__}") from exc
    finally:
        if own:
            client.close()
    if resp.status_code != 200:
        raise VoiceError(f"ElevenLabs HTTP {resp.status_code} : {resp.text[:300]}")
    data = resp.json()
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    mp3 = out_wav.with_suffix(".mp3")
    mp3.write_bytes(base64.b64decode(data["audio_base64"]))
    run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(mp3), "-ar", "48000", "-ac", "1", str(out_wav)])
    al = data.get("alignment") or data.get("normalized_alignment") or {}
    words = words_from_alignment(
        al.get("characters", []),
        al.get("character_start_times_seconds", []),
        al.get("character_end_times_seconds", []),
    )
    duration = words[-1].end if words else 0.0
    return VoiceInfo(engine="elevenlabs", audio_path=str(out_wav), duration=round(duration + 0.2, 3),
                     script=script, alignment="provider", words=words)
