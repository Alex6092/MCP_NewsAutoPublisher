"""Découpage du script en phrases et en mots, minutage estimé."""

from __future__ import annotations

import re
import unicodedata

from ..models import Word

SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n+")


class VoiceError(Exception):
    pass


def split_sentences(script: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE_END.split(script.strip()) if p and p.strip()]
    return parts


def words_of(sentence: str) -> list[str]:
    return sentence.split()


def normalize_token(token: str) -> str:
    token = unicodedata.normalize("NFKD", token.lower())
    token = "".join(c for c in token if not unicodedata.combining(c))
    return re.sub(r"[^\w]", "", token)


def estimate_words(sentence: str, start: float, end: float) -> list[Word]:
    """Répartit les mots d'une phrase sur [start, end] au prorata de leur longueur."""
    words = words_of(sentence)
    if not words:
        return []
    weights = [len(normalize_token(w)) + 2 for w in words]
    total = sum(weights)
    span = max(end - start, 0.05)
    out, t = [], start
    for w, wt in zip(words, weights):
        d = span * wt / total
        out.append(Word(text=w, start=round(t, 3), end=round(t + d, 3)))
        t += d
    return out


def format_for_recording(script: str) -> str:
    """Script numéroté phrase par phrase, avec consignes, pour un enregistrement au micro."""
    lines = [f"{i}. {s}" for i, s in enumerate(split_sentences(script), 1)]
    return "\n".join(lines)
