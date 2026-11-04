"""Page HTML locale de prévisualisation d'un brouillon (maquettes Discord, X, YouTube Shorts)."""

from __future__ import annotations

import html
import re
from pathlib import Path

from .config import AppConfig
from .models import Draft
from .validate import x_weighted_length

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}


def _uri(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    return p.resolve().as_uri() if p.exists() else None


def _media_tag(path: str | None, cls: str = "") -> str:
    uri = _uri(path)
    if not uri:
        return f'<div class="missing">Fichier manquant : {html.escape(path or "")}</div>' if path else ""
    if Path(path).suffix.lower() in VIDEO_EXT:  # type: ignore[arg-type]
        return f'<video class="{cls}" src="{uri}" controls playsinline></video>'
    return f'<img class="{cls}" src="{uri}" alt="">'


def _md(text: str | None) -> str:
    """Markdown minimal (gras, italique, code, liens, titres, puces) pour la maquette Discord."""
    if not text:
        return ""
    out = html.escape(text)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", out)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"(?m)^#{1,3}\s+(.+)$", r"<strong class='h'>\1</strong>", out)
    out = re.sub(r"(?m)^[-*]\s+", "• ", out)
    return out.replace("\n", "<br>")


def _x_html(text: str) -> str:
    out = html.escape(text)
    out = re.sub(r"(https?://\S+)", r'<a href="\1">\1</a>', out)
    out = re.sub(r"(?<![\w&])([#@][\wÀ-ſ]+)", r'<span class="tag">\1</span>', out)
    return out.replace("\n", "<br>")


def build_preview(draft: Draft, cfg: AppConfig) -> str:
    proj = cfg.projects.get(draft.project)
    color = (proj.brand.color if proj else "#7C5CFF")
    channels = []
    for ch in draft.channels:
        c = cfg.channels.get(ch)
        channels.append(f"<li><code>{html.escape(ch)}</code> — {html.escape(c.label or c.type) if c else '?'}"
                        f"{' (' + c.effective_mode + ')' if c else ''}</li>")

    issues = "".join(
        f'<li class="{i.level}"><b>{i.platform}.{i.field}</b> : {html.escape(i.message)}</li>'
        for i in draft.issues
    ) or '<li class="ok">Aucun problème détecté.</li>'

    cards = []
    p = draft.posts
    if p.discord:
        d = p.discord
        embed_color = d.color or color
        files = list(d.attachments)
        if d.attach_short and draft.short.discord_path:
            files.append(draft.short.discord_path)
        cards.append(f"""
<section class="card discord">
  <h2>Discord</h2>
  <div class="dc-msg">
    <div class="dc-avatar" style="background:{embed_color}"></div>
    <div class="dc-body">
      <div class="dc-name">{html.escape(proj.name if proj else draft.project)} <span class="bot">APP</span></div>
      <div class="dc-content">{_md(d.content)}</div>
      {'<div class="dc-embed" style="border-color:' + embed_color + '">' if (d.title or d.description or d.image) else ''}
        {f'<div class="dc-title">' + (f'<a href="{html.escape(d.url)}">' if d.url else '') + html.escape(d.title) + ('</a>' if d.url else '') + '</div>' if d.title else ''}
        {f'<div class="dc-desc">{_md(d.description)}</div>' if d.description else ''}
        {_media_tag(d.image, 'dc-image')}
      {'</div>' if (d.title or d.description or d.image) else ''}
      {''.join(_media_tag(f, 'dc-file') for f in files)}
    </div>
  </div>
</section>""")
    if p.x:
        x = p.x
        media = list(x.media)
        if x.attach_short and draft.short.path:
            media.append(draft.short.path)
        n = x_weighted_length(x.text, x.url)
        full = x.text + (("\n" if not x.text.endswith("\n") else "") + x.url if x.url else "")
        cards.append(f"""
<section class="card x">
  <h2>X <small class="{'bad' if n > 280 else ''}">{n}/280</small></h2>
  <div class="x-post">
    <div class="x-head"><span class="x-avatar" style="background:{color}"></span>
      <b>{html.escape(proj.name if proj else draft.project)}</b></div>
    <div class="x-text">{_x_html(full)}</div>
    <div class="x-media">{''.join(_media_tag(m, 'x-m') for m in media)}</div>
  </div>
</section>""")
    if p.youtube:
        y = p.youtube
        cards.append(f"""
<section class="card yt">
  <h2>YouTube Shorts <small>{html.escape(y.privacy)}</small></h2>
  <div class="yt-wrap">
    <div class="yt-phone">{_media_tag(draft.short.path, 'yt-video') or '<div class="missing">Short non rendu</div>'}
      <div class="yt-overlay">{html.escape(y.title)}</div></div>
    <div class="yt-meta"><div class="yt-title">{html.escape(y.title)}</div>
      <pre class="yt-desc">{html.escape(y.description)}</pre>
      <div class="yt-tags">{' '.join('<span>' + html.escape(t) + '</span>' for t in y.tags)}</div></div>
  </div>
</section>""")

    voice = draft.short.voice
    script = (f"<section class='card'><h2>Script voix off ({html.escape(voice.engine)}, "
              f"{voice.duration:.1f} s)</h2><pre>{html.escape(voice.script)}</pre></section>") if voice else ""

    return f"""<!doctype html>
<html lang="{html.escape(draft.language)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Brouillon {html.escape(draft.id)}</title>
<style>
:root {{ --bg:#f4f4f7; --fg:#18181b; --muted:#6b6b76; --card:#fff; --line:#e3e3ea; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#111114; --fg:#ececf1; --muted:#9a9aa6; --card:#1b1b20; --line:#2c2c34; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; font:15px/1.5 system-ui, "Segoe UI", sans-serif; background:var(--bg); color:var(--fg); }}
main {{ max-width:1100px; margin:0 auto; padding:24px 16px 64px; }}
header h1 {{ margin:0 0 4px; font-size:22px }}
.meta {{ color:var(--muted); margin:0 0 16px }}
.status {{ display:inline-block; padding:2px 10px; border-radius:99px; background:{color}; color:#fff; font-weight:600 }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:16px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; overflow:hidden }}
.card h2 {{ margin:0 0 12px; font-size:16px }} .card h2 small {{ color:var(--muted); font-weight:500 }}
small.bad {{ color:#e5484d !important }}
ul.issues {{ padding-left:18px }} .error {{ color:#e5484d }} .warning {{ color:#d97706 }} .ok {{ color:#16a34a }}
.missing {{ padding:12px; border:1px dashed #e5484d; color:#e5484d; border-radius:8px; font-size:13px }}
pre {{ white-space:pre-wrap; word-break:break-word; margin:0; font:13px/1.5 ui-monospace, Consolas, monospace }}
.discord .dc-msg {{ display:flex; gap:12px; background:#313338; color:#dbdee1; padding:14px; border-radius:8px }}
.dc-avatar {{ width:40px; height:40px; border-radius:50%; flex:none }}
.dc-body {{ min-width:0; flex:1 }} .dc-name {{ font-weight:600; color:#fff }}
.bot {{ background:#5865f2; color:#fff; font-size:10px; padding:1px 4px; border-radius:3px; vertical-align:middle }}
.dc-embed {{ margin-top:6px; background:#2b2d31; border-left:4px solid; border-radius:4px; padding:10px 14px }}
.dc-title {{ font-weight:700; color:#fff; margin-bottom:6px }} .dc-title a {{ color:#00a8fc }}
.dc-desc {{ font-size:14px }} .dc-desc .h {{ display:block; color:#fff; margin-top:6px }}
.dc-image, .dc-file {{ display:block; max-width:100%; max-height:360px; margin-top:10px; border-radius:6px }}
.discord a {{ color:#00a8fc }} code {{ background:rgba(127,127,127,.2); padding:0 4px; border-radius:4px }}
.x-post {{ border:1px solid var(--line); border-radius:12px; padding:12px }}
.x-head {{ display:flex; align-items:center; gap:8px; margin-bottom:6px }}
.x-avatar {{ width:36px; height:36px; border-radius:50% }}
.x-text a, .x-text .tag {{ color:#1d9bf0 }}
.x-m {{ display:block; max-width:100%; max-height:360px; margin-top:10px; border-radius:12px }}
.yt-wrap {{ display:flex; gap:14px; flex-wrap:wrap }}
.yt-phone {{ position:relative; width:220px; aspect-ratio:9/16; background:#000; border-radius:14px; overflow:hidden; flex:none }}
.yt-video {{ width:100%; height:100%; object-fit:cover }}
.yt-overlay {{ position:absolute; left:10px; right:40px; bottom:64px; color:#fff; font-size:12px; font-weight:600; text-shadow:0 1px 3px #000; pointer-events:none }}
.yt-meta {{ flex:1; min-width:200px }} .yt-title {{ font-weight:700; margin-bottom:8px }}
.yt-tags span {{ display:inline-block; background:rgba(127,127,127,.15); border-radius:6px; padding:1px 6px; margin:4px 4px 0 0; font-size:12px }}
.full {{ grid-column:1/-1 }}
</style></head>
<body><main>
<header>
  <h1>{html.escape(draft.topic)}</h1>
  <p class="meta"><span class="status">{html.escape(draft.status)}</span>
  &nbsp;{html.escape(proj.name if proj else draft.project)} · {html.escape(draft.language.upper())} · <code>{html.escape(draft.id)}</code></p>
</header>
<div class="grid">
  <section class="card"><h2>Validation</h2><ul class="issues">{issues}</ul></section>
  <section class="card"><h2>Canaux</h2><ul>{''.join(channels) or '<li>Aucun canal configuré pour cette langue.</li>'}</ul></section>
  {''.join(cards)}
  {script}
</div>
</main></body></html>"""


def write_preview(draft: Draft, cfg: AppConfig, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "preview.html"
    path.write_text(build_preview(draft, cfg), encoding="utf-8")
    return path
