"""Ta propre voix : import d'un enregistrement, nettoyage, puis alignement des sous-titres.

Alignement : faster-whisper s'il est installé (mot à mot précis), sinon détection des silences
entre les phrases, sinon répartition proportionnelle.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from ..ffmpeg import probe, run
from ..models import VoiceInfo, Word
from .text import VoiceError, estimate_words, normalize_token, split_sentences

CLEAN_FILTER = (
    "highpass=f=70,"
    "silenceremove=start_periods=1:start_silence=0.15:start_threshold=-45dB,"
    "areverse,silenceremove=start_periods=1:start_silence=0.25:start_threshold=-45dB,areverse,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)


def clean_recording(src: Path, out_wav: Path, ffmpeg: str) -> Path:
    if not src.exists():
        raise VoiceError(f"Enregistrement introuvable : {src}")
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-vn",
         "-af", CLEAN_FILTER, "-ar", "48000", "-ac", "1", str(out_wav)])
    return out_wav


def detect_silences(audio: Path, ffmpeg: str, noise_db: int = -35, min_d: float = 0.22) -> list[tuple[float, float]]:
    proc = run([ffmpeg, "-hide_banner", "-nostats", "-i", str(audio),
                "-af", f"silencedetect=noise={noise_db}dB:d={min_d}", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    return list(zip(starts, ends))


def align_by_silences(script: str, duration: float, silences: list[tuple[float, float]]) -> list[Word]:
    sentences = split_sentences(script)
    if not sentences:
        return []
    inner = [s for s in silences if 0.1 < s[0] < duration - 0.1]
    # Les N-1 silences les plus longs séparent (probablement) les N phrases.
    gaps = sorted(sorted(inner, key=lambda s: s[1] - s[0], reverse=True)[: len(sentences) - 1])
    if len(gaps) < len(sentences) - 1:
        return estimate_words(" ".join(sentences), 0.0, duration)
    words: list[Word] = []
    start = 0.0
    for i, sentence in enumerate(sentences):
        end = gaps[i][0] if i < len(gaps) else duration
        words += estimate_words(sentence, start, end)
        if i < len(gaps):
            start = gaps[i][1]
    return words


def map_to_script(script: str, heard: list[Word]) -> list[Word]:
    """Recale les mots reconnus par Whisper sur le texte exact du script (orthographe, ponctuation)."""
    script_words = script.split()
    a = [normalize_token(w) for w in script_words]
    b = [normalize_token(w.text) for w in heard]
    times: list[tuple[float, float] | None] = [None] * len(script_words)
    for block in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks():
        for k in range(block.size):
            h = heard[block.b + k]
            times[block.a + k] = (h.start, h.end)
    # Interpolation des mots non reconnus entre leurs voisins connus.
    out: list[Word] = []
    n = len(script_words)
    for i, w in enumerate(script_words):
        if times[i] is None:
            prev_t = next((times[j][1] for j in range(i - 1, -1, -1) if times[j]), 0.0)
            nxt_i = next((j for j in range(i + 1, n) if times[j]), None)
            next_t = times[nxt_i][0] if nxt_i is not None else (heard[-1].end if heard else prev_t + 0.4)
            gap_count = (nxt_i if nxt_i is not None else n) - i
            step = max((next_t - prev_t) / (gap_count + 1), 0.05)
            times[i] = (prev_t, prev_t + step)
        s, e = times[i]
        out.append(Word(text=w, start=round(s, 3), end=round(max(e, s + 0.05), 3)))
    return out


def align_with_whisper(audio: Path, script: str, language: str, model_name: str) -> list[Word] | None:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(audio), language=language, word_timestamps=True,
                                       initial_prompt=script[:200])
    heard = [Word(text=w.word.strip(), start=w.start, end=w.end)
             for seg in segments for w in (seg.words or [])]
    return map_to_script(script, heard) if heard else None


def import_recording(
    src: Path,
    script: str,
    language: str,
    out_wav: Path,
    ffmpeg: str,
    ffprobe: str,
    whisper_model: str = "small",
) -> VoiceInfo:
    clean_recording(src, out_wav, ffmpeg)
    duration = float(probe(out_wav, ffprobe)["duration"] or 0)
    if duration <= 0.3:
        raise VoiceError("L'enregistrement semble vide après nettoyage (silence ?).")
    words = None
    alignment = "whisper"
    try:
        words = align_with_whisper(out_wav, script, language, whisper_model)
    except Exception:
        words = None
    if not words:
        alignment = "silences"
        words = align_by_silences(script, duration, detect_silences(out_wav, ffmpeg))
    return VoiceInfo(engine="recorded", audio_path=str(out_wav), duration=round(duration, 3),
                     script=script, alignment=alignment, words=words)
