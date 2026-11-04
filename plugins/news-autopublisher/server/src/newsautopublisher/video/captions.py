"""Génération du fichier de sous-titres ASS (textes de scènes + sous-titres mot à mot)."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Word
from .storyboard import Scene, Storyboard

FONT_CAPTION = "Inter ExtraBold"
FONT_TITLE = "Inter Black"
PUNCT_BREAK = (".", ",", "!", "?", ";", ":", "…")


@dataclass
class TimedScene:
    scene: Scene
    start: float
    end: float


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR (format ASS)."""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_time(t: float) -> str:
    t = max(t, 0.0)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def escape(text: str) -> str:
    return (
        text.replace("\\", "/")
        .replace("{", "(")
        .replace("}", ")")
        .replace("\r", "")
        .replace("\n", "\\N")
    )


def chunk_words(words: list[Word], max_words: int = 3, max_chars: int = 20) -> list[list[Word]]:
    chunks: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        candidate = " ".join(x.text for x in cur + [w])
        if cur and (len(cur) >= max_words or len(candidate) > max_chars):
            chunks.append(cur)
            cur = []
        cur.append(w)
        if w.text.endswith(PUNCT_BREAK):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(
    sb: Storyboard,
    timeline: list[TimedScene],
    words: list[Word],
    width: int,
    height: int,
    color: str,
    accent: str,
    has_logo: bool = False,
) -> str:
    cx = width // 2
    white, black = "&H00FFFFFF", "&H00000000"
    box = ass_color(color)
    styles = [
        # Name, Font, Size, Primary, Secondary, Outline, Back, Bold, Italic, Underline, StrikeOut,
        # ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
        f"Style: Caption,{FONT_CAPTION},78,{white},{white},{black},&H80000000,0,0,0,0,100,100,0,0,1,6,2,5,80,80,0,1",
        f"Style: Headline,{FONT_TITLE},64,{white},{white},{box},{box},0,0,0,0,100,100,0,0,3,16,0,8,110,110,190,1",
        f"Style: Big,{FONT_TITLE},104,{white},{white},{black},&H96000000,0,0,0,0,100,100,0,0,1,7,4,5,90,90,0,1",
        f"Style: Sub,{FONT_CAPTION},56,{ass_color(accent)},{white},{black},&H96000000,0,0,0,0,100,100,0,0,1,5,2,5,90,90,0,1",
    ]
    events: list[str] = []

    def dialogue(start: float, end: float, style: str, text: str, layer: int = 0) -> None:
        if end - start < 0.05:
            return
        events.append(f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{text}")

    big_y = int(height * 0.445)
    for ts in timeline:
        s = ts.scene
        a, b = ts.start + 0.05, ts.end - 0.02
        if s.type in ("title", "text", "outro"):
            y = int(height * 0.53) if (s.type == "outro" and has_logo) else big_y
            if s.text:
                dialogue(a, b, "Big", f"{{\\an5\\pos({cx},{y})\\fad(180,120)}}{escape(s.text)}", 2)
            if s.subtext:
                dialogue(a + 0.15, b, "Sub", f"{{\\an5\\pos({cx},{y + 210})\\fad(200,120)}}{escape(s.subtext)}", 2)
        else:
            top = s.text or sb.headline
            if top:
                dialogue(a, b, "Headline", f"{{\\fad(150,100)}}{escape(top)}", 2)
            if s.subtext:
                dialogue(a, b, "Sub", f"{{\\an5\\pos({cx},{int(height * 0.6)})\\fad(150,100)}}{escape(s.subtext)}", 2)

    if sb.captions and words:
        cap_y = int(height * 0.68)
        hl = ass_color(accent)
        chunks = chunk_words(words)
        for ci, chunk in enumerate(chunks):
            next_start = chunks[ci + 1][0].start if ci + 1 < len(chunks) else None
            chunk_end = chunk[-1].end + 0.25
            if next_start is not None:
                chunk_end = min(chunk_end, next_start)
            for wi, w in enumerate(chunk):
                start = w.start
                end = chunk[wi + 1].start if wi + 1 < len(chunk) else chunk_end
                parts = []
                for k, x in enumerate(chunk):
                    t = escape(x.text)
                    parts.append(f"{{\\c{hl}\\fscx106\\fscy106}}{t}{{\\r}}" if k == wi else t)
                pop = "\\fscx88\\fscy88\\t(0,90,\\fscx100\\fscy100)" if wi == 0 else ""
                dialogue(start, end, "Caption", f"{{\\an5\\pos({cx},{cap_y}){pop}}}" + " ".join(parts), 3)

    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        + "\n".join(styles)
        + "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    return header + "\n".join(events) + "\n"
