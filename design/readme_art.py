"""Draws the pictures the README shows: the cover, the download buttons, the facts, how it works and
the social preview. Run:

    uv run --no-project --python 3.11 --with fonttools --with brotli --with uharfbuzz python design/readme_art.py

Every colour comes from design/tokens.json and every letter from the app's own Inter and Instrument
Serif, turned into outlines here. That last part is not decoration: GitHub shows an SVG as an image,
and an image cannot load a web font, so live text would fall back to whatever the reader's computer
has. Each picture is drawn twice, light and dark, and the README swaps them with <picture>.

The cover's sheet is the app's living sheet (design/components/living-sheet.md) drawn small: ticks in
ink, absences in the absent colour, a strong rule after the names, and the class still taking
attendance tinted and ruled in the accent. The names are bars, so no student is in the picture.

The font tools are only needed here, so they are not in requirements-dev.txt.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "readme"
FONTS = ROOT / "rollcall" / "static" / "fonts"

import logo                                   # design/logo.py, beside this file: the mark's numbers

THEMES = ("light", "dark")


def tokens(theme: str) -> dict:
    return json.loads((HERE / "tokens.json").read_text(encoding="utf-8"))["colour"][theme]


def version() -> str:
    text = (ROOT / "rollcall" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'VERSION\s*=\s*"([^"]+)"', text).group(1)


def num(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


# -- type, as outlines --------------------------------------------------------------------------------

class Face:
    """One font at one weight: shaped by HarfBuzz (kerning, ligatures), drawn by fontTools."""

    def __init__(self, file: str, weight: int | None = None):
        import uharfbuzz as hb
        from fontTools.ttLib import TTFont

        woff = TTFont(FONTS / file)
        woff.flavor = None
        buf = io.BytesIO()
        woff.save(buf)
        self.data = buf.getvalue()
        self.tt = TTFont(io.BytesIO(self.data))
        self.upem = self.tt["head"].unitsPerEm
        self.order = self.tt.getGlyphOrder()
        self.weight = weight
        self.hb = hb.Font(hb.Face(hb.Blob(self.data)))
        self.variable = "fvar" in self.tt

    def _location(self, size: float) -> dict | None:
        if not self.variable:
            return None
        # Inter's optical size runs 14 to 32: text gets the open text cut, headings the tight one.
        return {"wght": self.weight or 400, "opsz": max(14.0, min(32.0, size))}

    def _shape(self, text: str, size: float):
        import uharfbuzz as hb

        loc = self._location(size)
        if loc:
            self.hb.set_variations(loc)
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb, buf, {"kern": True, "liga": True})
        return buf.glyph_infos, buf.glyph_positions, loc

    def width(self, text: str, size: float, tracking: float = 0) -> float:
        _, positions, _ = self._shape(text, size)
        scale = size / self.upem
        return sum(p.x_advance for p in positions) * scale + tracking * max(0, len(positions) - 1)

    def path(self, text: str, size: float, x: float, y: float, fill: str, tracking: float = 0,
             anchor: str = "start") -> str:
        from fontTools.pens.svgPathPen import SVGPathPen
        from fontTools.pens.transformPen import TransformPen

        infos, positions, loc = self._shape(text, size)
        glyphs = self.tt.getGlyphSet(location=loc) if loc else self.tt.getGlyphSet()
        scale = size / self.upem
        total = self.width(text, size, tracking)
        if anchor == "middle":
            x -= total / 2
        elif anchor == "end":
            x -= total
        pen = SVGPathPen(glyphs, ntos=num)
        cursor = x
        for info, pos in zip(infos, positions):
            name = self.order[info.codepoint]
            glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, cursor + pos.x_offset * scale,
                                                 y - pos.y_offset * scale)))
            cursor += pos.x_advance * scale + tracking
        d = pen.getCommands()
        return f'<path fill="{fill}" d="{d}"/>' if d else ""


_faces: dict[str, Face] = {}


def face(key: str) -> Face:
    if key not in _faces:
        _faces[key] = {
            "semibold": lambda: Face("Inter-Variable.woff2", 600),
            "medium": lambda: Face("Inter-Variable.woff2", 500),
            "regular": lambda: Face("Inter-Variable.woff2", 400),
            "serif-italic": lambda: Face("InstrumentSerif-Italic.woff2"),
        }[key]()
    return _faces[key]


def wrap(text: str, key: str, size: float, width: float) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and face(key).width(trial, size) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + ([line] if line else [])


# -- shared pieces ------------------------------------------------------------------------------------

def svg(width: int, height: int, body: str, label: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
            f'height="{height}" role="img" aria-label="{label}">\n<title>{label}</title>\n{body}\n</svg>\n')


def mark(x: float, y: float, size: float, c: dict) -> str:
    """The Herewise mark (design/logo.py) at any size, in the theme's ink and accent."""
    k = size / logo.BOX
    points = " ".join(f"{num(x + px * k)} {num(y + py * k)}" for px, py in logo.TICK)
    stem_h = (logo.BOTTOM_Y - logo.TOP_Y) * k
    return (f'<rect x="{num(x + logo.LEFT_X * k)}" y="{num(y + logo.TOP_Y * k)}" width="{num(logo.STEM_W * k)}" '
            f'height="{num(stem_h)}" fill="{c["ink"]}"/>'
            f'<rect x="{num(x + logo.RIGHT_X * k)}" y="{num(y + logo.TOP_Y * k)}" width="{num(logo.STEM_W * k)}" '
            f'height="{num(stem_h)}" fill="{c["ink"]}"/>'
            f'<polyline points="{points}" fill="none" stroke="{c["accent"]}" stroke-width="{num(logo.TICK_W * k)}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')


def tick(cx: float, cy: float, s: float, colour: str, w: float) -> str:
    return (f'<polyline points="{num(cx - s * .45)} {num(cy + s * .02)} {num(cx - s * .12)} {num(cy + s * .34)} '
            f'{num(cx + s * .48)} {num(cy - s * .36)}" fill="none" stroke="{colour}" stroke-width="{num(w)}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')


def cross(cx: float, cy: float, s: float, colour: str, w: float) -> str:
    h = s * .32
    return (f'<path d="M{num(cx - h)} {num(cy - h)}L{num(cx + h)} {num(cy + h)}M{num(cx + h)} {num(cy - h)}'
            f'L{num(cx - h)} {num(cy + h)}" stroke="{colour}" stroke-width="{num(w)}" stroke-linecap="round"/>')


# The sheet's pattern: 1 present, 0 absent, None not yet scanned (the open class only).
SHEET = [
    [1, 1, 1, 1, 1, 1],
    [1, 0, 1, 1, 1, 1],
    [1, 1, 1, 0, 1, None],
    [1, 1, 1, 1, 1, 1],
    [0, 1, 1, 1, 0, None],
    [1, 1, 1, 1, 1, 1],
]
NAME_BARS = [0.78, 0.62, 0.9, 0.55, 0.72, 0.66]


def sheet(x: float, y: float, w: float, h: float, c: dict) -> str:
    """The living sheet in miniature."""
    # Everything inside is clipped to the card, so the accent rule cannot square off its corner.
    out = [f'<clipPath id="sheet-card"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14"/></clipPath>',
           f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{c["surface"]}"/>',
           '<g clip-path="url(#sheet-card)">']
    weeks = len(SHEET[0])
    head_h, total_h = 46, 46
    row_h = (h - head_h - total_h) / len(SHEET)
    frozen = w * 0.27
    col = (w - frozen) / weeks
    open_x = x + frozen + col * (weeks - 1)
    # the class still taking attendance: tinted, and ruled in the accent down both sides
    out.append(f'<rect x="{num(open_x)}" y="{y + 1}" width="{num(col)}" height="{num(h - 2)}" fill="{c["accent-soft"]}"/>')
    for i in range(1, len(SHEET)):
        ry = y + head_h + row_h * i
        out.append(f'<line x1="{x}" y1="{num(ry)}" x2="{x + w}" y2="{num(ry)}" stroke="{c["rule"]}"/>')
    out.append(f'<line x1="{x}" y1="{y + head_h}" x2="{x + w}" y2="{y + head_h}" stroke="{c["rule"]}"/>')
    for j in range(1, weeks):
        cx = x + frozen + col * j
        out.append(f'<line x1="{num(cx)}" y1="{y}" x2="{num(cx)}" y2="{y + h}" stroke="{c["rule"]}"/>')
    for edge in (open_x, open_x + col):
        out.append(f'<line x1="{num(edge)}" y1="{y}" x2="{num(edge)}" y2="{y + h}" stroke="{c["accent"]}" stroke-width="2"/>')
    # totals, under the sheet's strong rule
    ty = y + h - total_h
    out.append(f'<line x1="{x}" y1="{ty}" x2="{x + w}" y2="{ty}" stroke="{c["rule-strong"]}" stroke-width="2"/>')
    out.append(f'<line x1="{num(x + frozen)}" y1="{y}" x2="{num(x + frozen)}" y2="{y + h}" stroke="{c["rule-strong"]}" stroke-width="2"/>')
    small = face("semibold")
    out.append(small.path("STUDENT", 13, x + 20, y + 29, c["ink-muted"], tracking=0.9))
    for j in range(weeks):
        label = f"WK {j + 1}"
        colour = c["accent"] if j == weeks - 1 else c["ink-muted"]
        out.append(small.path(label, 13, x + frozen + col * (j + .5), y + 29, colour, tracking=0.5, anchor="middle"))
    for i, row in enumerate(SHEET):
        cy = y + head_h + row_h * (i + .5)
        out.append(face("medium").path(f"{i + 1:02d}", 13, x + 20, cy + 4.5, c["ink-muted"]))
        bar_w = (frozen - 66) * NAME_BARS[i]
        out.append(f'<rect x="{x + 48}" y="{num(cy - 4)}" width="{num(bar_w)}" height="8" rx="4" fill="{c["rule"]}"/>')
        for j, state in enumerate(row):
            cx = x + frozen + col * (j + .5)
            if state == 1:
                out.append(tick(cx, cy, 16, c["ink"], 2.4))
            elif state == 0:
                out.append(cross(cx, cy, 16, c["absent"], 2.4))
    out.append(small.path("PRESENT", 13, x + 20, ty + 28, c["ink"], tracking=0.9))
    for j in range(weeks):
        n = sum(1 for row in SHEET if row[j] == 1)
        out.append(small.path(str(n), 15, x + frozen + col * (j + .5), ty + 29, c["ink"], anchor="middle"))
    out.append("</g>")
    out.append(f'<rect x="{x + .5}" y="{y + .5}" width="{w - 1}" height="{h - 1}" rx="14" fill="none" stroke="{c["rule"]}"/>')
    return "\n".join(out)


def lockup(x: float, y: float, size: float, c: dict) -> str:
    """Mark and wordmark: `herewise` in Inter 600, lowercase, tracking -0.02em (design/logo.py)."""
    word = face("semibold")
    word_size = size * 0.86
    baseline = y + size * (logo.BOTTOM_Y / logo.BOX)
    return (mark(x, y, size, c)
            + word.path("herewise", word_size, x + size * 1.18, baseline, c["ink"], tracking=-0.02 * word_size))


# -- the pictures -------------------------------------------------------------------------------------

TAGLINE = ["Lecture attendance from the fingerprint", "terminal, kept on the lecturer's own computer."]
BYLINE = "BY EMBERFIG  ·  FREE SOFTWARE UNDER THE GNU GPL"


def cover(theme: str) -> str:
    c = tokens(theme)
    w, h = 1280, 420
    body = [f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="20" fill="{c["paper"]}" stroke="{c["rule"]}"/>',
            lockup(72, 64, 84, c)]
    serif = face("serif-italic")
    for i, line in enumerate(TAGLINE):
        body.append(serif.path(line, 42, 74, 236 + i * 50, c["ink"]))
    body.append(face("semibold").path(BYLINE, 15, 76, 356, c["ink-muted"], tracking=1.4))
    body.append(sheet(812, 52, 404, 316, c))
    return svg(w, h, "\n".join(body), "Herewise: lecture attendance from the fingerprint terminal")


def social() -> str:
    """1280 by 640, the size GitHub asks for. Light only: a link preview has no dark variant."""
    c = tokens("light")
    w, h = 1280, 640
    body = [f'<rect width="{w}" height="{h}" fill="{c["paper"]}"/>',
            lockup(80, 96, 104, c)]
    serif = face("serif-italic")
    for i, line in enumerate(["Lecture attendance from the", "fingerprint terminal, kept on", "the lecturer's own computer."]):
        body.append(serif.path(line, 50, 84, 300 + i * 60, c["ink"]))
    body.append(face("semibold").path("OFFLINE  ·  WINDOWS  ·  ZKTECO K40  ·  GPL", 17, 86, 520, c["ink-muted"], tracking=1.5))
    body.append(face("medium").path("github.com/emberfig/herewise", 20, 86, 572, c["accent"]))
    body.append(sheet(800, 120, 400, 400, c))
    return svg(w, h, "\n".join(body), "Herewise")


def download_button(theme: str, size_mb: int | None) -> str:
    c = tokens(theme)
    w, h = 440, 84
    v = version()
    sub = f"Herewise {v}  ·  64-bit installer" + (f"  ·  {size_mb} MB" if size_mb else "")
    body = [f'<rect width="{w}" height="{h}" rx="16" fill="{c["accent"]}"/>',
            # a downward arrow into a tray, drawn on the same 2.4 stroke family as the sheet's marks
            f'<path d="M44 26V50M33 40L44 51L55 40M30 58H58" fill="none" stroke="{c["on-accent"]}" '
            f'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>',
            face("semibold").path("Download for Windows", 23, 82, 40, c["on-accent"], tracking=-0.2),
            face("medium").path(sub, 14, 82, 63, c["on-accent"])]
    return svg(w, h, "\n".join(body), "Download Herewise for Windows")


def secondary_button(theme: str, label: str, sub: str, alt: str) -> str:
    c = tokens(theme)
    w, h = 440, 84
    body = [f'<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="15" fill="{c["surface"]}" stroke="{c["rule-strong"]}" stroke-width="1.5"/>',
            # a document with lines: the source and the checksums are both something to read
            f'<path d="M34 22H50L58 30V62H34Z M50 22V30H58 M40 40H52M40 47H52M40 54H48" fill="none" '
            f'stroke="{c["ink"]}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>',
            face("semibold").path(label, 23, 82, 40, c["ink"], tracking=-0.2),
            face("medium").path(sub, 14, 82, 63, c["ink-muted"])]
    return svg(w, h, "\n".join(body), alt)


FACTS = [  # (text, tone): the app's status pairs, each a soft fill with its own ink
    ("Works with no internet", "present"),
    ("Windows 10 and 11", "accent"),
    ("ZKTeco K40 over Ethernet", "excused"),
    ("GPL-2.0-or-later", "review"),
]


def facts(theme: str) -> str:
    c = tokens(theme)
    size, pad, gap, h = 17, 22, 12, 44
    f = face("semibold")
    widths = [f.width(t, size) + pad * 2 + 22 for t, _ in FACTS]
    w = int(sum(widths) + gap * (len(FACTS) - 1) + 2)
    body, x = [], 1.0
    for (text, tone), cw in zip(FACTS, widths):
        ink, soft = c[tone], c[f"{tone}-soft"]
        body.append(f'<rect x="{num(x)}" y="1" width="{num(cw)}" height="{h - 2}" rx="{(h - 2) / 2}" fill="{soft}"/>')
        body.append(f'<circle cx="{num(x + pad + 4)}" cy="{h / 2}" r="5" fill="{ink}"/>')
        body.append(f.path(text, size, x + pad + 22, h / 2 + 6, ink))
        x += cw + gap
    return svg(w, h, "\n".join(body), " · ".join(t for t, _ in FACTS))


STEPS = [
    ("Scan", "Students put a finger on the K40 as they come in. Nothing else to carry or sign."),
    ("Read", "Herewise reads the scans over a direct Ethernet cable. No router, no internet."),
    ("Sheet", "Each class fills in the lecturer's own attendance sheet, ready as PDF or Excel."),
    ("Decide", "The examination eligibility list follows from the sheet, with every correction noted."),
]


def how_it_works(theme: str) -> str:
    c = tokens(theme)
    w, h = 1280, 296
    gap, arrow = 40, 0
    card_w = (w - gap * (len(STEPS) - 1)) / len(STEPS)
    body = []
    for i, (title, text) in enumerate(STEPS):
        x = i * (card_w + gap)
        body.append(f'<rect x="{num(x + 1)}" y="1" width="{num(card_w - 2)}" height="{h - 2}" rx="16" '
                    f'fill="{c["surface"]}" stroke="{c["rule"]}"/>')
        body.append(f'<circle cx="{num(x + 50)}" cy="56" r="22" fill="{c["accent-soft"]}"/>')
        body.append(face("semibold").path(str(i + 1), 21, x + 50, 63.5, c["accent"], anchor="middle"))
        body.append(face("semibold").path(title, 30, x + 28, 132, c["ink"], tracking=-0.4))
        for k, line in enumerate(wrap(text, "regular", 20, card_w - 56)):
            body.append(face("regular").path(line, 20, x + 28, 178 + k * 30, c["ink-muted"]))
        if i < len(STEPS) - 1:
            ax = x + card_w + gap / 2
            body.append(f'<path d="M{num(ax - 6)} {h / 2 - 10}L{num(ax + 4)} {h / 2}L{num(ax - 6)} {h / 2 + 10}" '
                        f'fill="none" stroke="{c["accent"]}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
    return svg(w, h, "\n".join(body), "How it works: " + "; ".join(f"{t}. {x}" for t, x in STEPS))


def installer_size_mb() -> int | None:
    found = sorted((ROOT / "dist").glob(f"Herewise-Setup-{version()}.exe"))
    return round(found[0].stat().st_size / 1_000_000) if found else None


def main() -> None:
    OUT.mkdir(exist_ok=True)
    size = installer_size_mb()
    written = {"social-preview.svg": social()}
    for theme in THEMES:
        written[f"cover-{theme}.svg"] = cover(theme)
        written[f"download-{theme}.svg"] = download_button(theme, size)
        written[f"releases-{theme}.svg"] = secondary_button(
            theme, "Source and checksums", "Every release, with its source and SHA-256",
            "Every release, with its source and checksums")
        written[f"facts-{theme}.svg"] = facts(theme)
        written[f"how-it-works-{theme}.svg"] = how_it_works(theme)
    for name, text in written.items():
        (OUT / name).write_text(text, encoding="utf-8")
        print(f"  {name}  {len(text) / 1000:.0f} kB")


if __name__ == "__main__":
    main()
