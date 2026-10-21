"""The app palette, derived in OKLCH and tested, never hand-picked (vault 30-Playbooks/Design and UX).

Tests, run by tests/test_palette.py:
  * WCAG 2.2 contrast for every text pairing (4.5:1, 7:1 for body ink) and non-text UI (3:1)
  * separation between the four status colours under protanopia, deuteranopia, tritanopia
    (Machado, Oliveira and Fernandes 2009, severity 1.0) and in greyscale, for photocopied sheets
Status lightness was chosen by search for that separation, not by eye. Colour is never the only cue:
every status also has a glyph and a word. Reasoning: vault 50-Research "Roll Call name, logo and
palette research 2026-09-15".

Run:  python design/palette.py      prints the report and rewrites design/tokens.json and tokens.css
"""
import json
import math

NEWLINE = chr(10)

# ---------- colour maths ----------

def oklch_to_srgb(L, C, h):
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return r, g, bl  # linear


def in_gamut(lin):
    return all(-1e-4 <= c <= 1 + 1e-4 for c in lin)


def gamut_map(L, C, h):
    """Reduce chroma until the colour fits sRGB, keeping lightness and hue."""
    lo, hi = 0.0, C
    if in_gamut(oklch_to_srgb(L, C, h)):
        return C
    for _ in range(40):
        mid = (lo + hi) / 2
        if in_gamut(oklch_to_srgb(L, mid, h)):
            lo = mid
        else:
            hi = mid
    return lo


def encode(c):
    c = min(max(c, 0.0), 1.0)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def decode(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def to_hex(lin):
    return "#" + "".join(f"{round(encode(c) * 255):02X}" for c in lin)


def hex_to_lin(hx):
    return tuple(decode(int(hx[i:i + 2], 16) / 255) for i in (1, 3, 5))


def luminance(lin):
    r, g, b = (min(max(c, 0), 1) for c in lin)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def lin_to_oklab(lin):
    r, g, b = (min(max(c, 0), 1) for c in lin)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in (l, m, s))
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def delta_ok(a, b):
    return math.dist(lin_to_oklab(a), lin_to_oklab(b))


# Machado, Oliveira and Fernandes 2009, severity 1.0, applied to linear RGB.
CVD = {
    "protan": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
    "deutan": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
    "tritan": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602), (0.004733, 0.691367, 0.303900)),
}


def simulate(lin, kind):
    m = CVD[kind]
    return tuple(sum(m[i][j] * lin[j] for j in range(3)) for i in range(3))


def grey(lin):
    y = luminance(lin)
    return (y, y, y)

# ---------- the palette ----------

WARM = 80       # paper hue: a warm, faintly yellow off-white, like the lecturer's printed register
INK_H = 264     # accent hue: blue-black ink

THEMES = {
    "light": {
        "paper":        (0.975, 0.007, WARM),
        "surface":      (0.992, 0.004, WARM),
        "sunken":       (0.950, 0.009, WARM),
        "rule":         (0.885, 0.010, WARM),
        "rule-strong":  (0.600, 0.012, WARM),
        "ink":          (0.235, 0.014, WARM),
        "ink-muted":    (0.470, 0.014, WARM),
        "accent":       (0.420, 0.115, INK_H),
        "accent-hover": (0.360, 0.110, INK_H),
        "accent-soft":  (0.935, 0.030, INK_H),
        "on-accent":    (0.985, 0.005, INK_H),
        "present":      (0.480, 0.100, 172),
        "present-soft": (0.930, 0.040, 172),
        "absent":       (0.360, 0.160, 36),
        "absent-soft":  (0.930, 0.040, 36),
        "excused":      (0.440, 0.020, 60),
        "excused-soft": (0.920, 0.016, 60),
        "review":       (0.400, 0.100, 310),
        "review-soft":  (0.930, 0.040, 310),
        "focus":        (0.560, 0.150, INK_H),
    },
    "dark": {
        "paper":        (0.185, 0.008, WARM),
        "surface":      (0.225, 0.009, WARM),
        "sunken":       (0.160, 0.008, WARM),
        "rule":         (0.315, 0.010, WARM),
        "rule-strong":  (0.580, 0.012, WARM),
        "ink":          (0.940, 0.010, WARM),
        "ink-muted":    (0.740, 0.012, WARM),
        "accent":       (0.760, 0.095, INK_H),
        "accent-hover": (0.820, 0.080, INK_H),
        "accent-soft":  (0.300, 0.045, INK_H),
        "on-accent":    (0.190, 0.020, INK_H),
        "present":      (0.900, 0.110, 172),
        "present-soft": (0.290, 0.045, 172),
        "absent":       (0.680, 0.120, 36),
        "absent-soft":  (0.290, 0.045, 36),
        "excused":      (0.780, 0.020, 60),
        "excused-soft": (0.310, 0.014, 60),
        "review":       (0.860, 0.080, 310),
        "review-soft":  (0.290, 0.040, 310),
        "focus":        (0.720, 0.130, INK_H),
    },
}

TEXT_PAIRS = [  # (foreground, background, minimum ratio)
    ("ink", "paper", 7.0), ("ink", "surface", 7.0), ("ink", "sunken", 7.0),
    ("ink-muted", "paper", 4.5), ("ink-muted", "surface", 4.5), ("ink-muted", "sunken", 4.5),
    ("accent", "paper", 4.5), ("accent", "surface", 4.5), ("accent", "accent-soft", 4.5),
    ("on-accent", "accent", 4.5), ("on-accent", "accent-hover", 4.5),
    ("present", "surface", 4.5), ("present", "present-soft", 4.5),
    ("absent", "surface", 4.5), ("absent", "absent-soft", 4.5),
    ("excused", "surface", 4.5), ("excused", "excused-soft", 4.5),
    ("review", "surface", 4.5), ("review", "review-soft", 4.5),
    ("ink", "present-soft", 7.0), ("ink", "absent-soft", 7.0), ("ink", "excused-soft", 7.0), ("ink", "review-soft", 7.0),
    ("rule-strong", "surface", 3.0), ("focus", "surface", 3.0), ("focus", "paper", 3.0),
]
PROJECTION_PAIRS = [("ink", "surface", 12.0), ("accent", "surface", 7.0), ("present", "surface", 4.5),
                    ("absent", "surface", 4.5)]
STATUSES = ["present", "absent", "excused", "review"]


def build():
    out, failures = {}, []
    for theme, tokens in THEMES.items():
        lin, hexes = {}, {}
        for name, (L, C, h) in tokens.items():
            c = gamut_map(L, C, h)
            lin[name] = oklch_to_srgb(L, c, h)
            hexes[name] = {"hex": to_hex(lin[name]), "oklch": f"oklch({L:.3f} {c:.3f} {h})",
                           "chroma_mapped": round(C - c, 3) > 0.001}
        rows = []
        for fg, bg, need in TEXT_PAIRS:
            ratio = contrast(lin[fg], lin[bg])
            rows.append((fg, bg, round(ratio, 2), need))
            if ratio < need:
                failures.append(f"{theme}: {fg} on {bg} = {ratio:.2f}, needs {need}")
        seps = {}
        for kind in ("normal", "protan", "deutan", "tritan", "greyscale"):
            f = (lambda x: x) if kind == "normal" else (grey if kind == "greyscale" else (lambda x, k=kind: simulate(x, k)))
            worst = min(((delta_ok(f(lin[a]), f(lin[b])), a, b) for i, a in enumerate(STATUSES)
                         for b in STATUSES[i + 1:]))
            seps[kind] = (round(worst[0], 3), worst[1], worst[2])
        out[theme] = {"tokens": hexes, "contrast": rows, "status_separation": seps}
    return out, failures


def write_tokens(folder) -> None:
    from pathlib import Path

    folder = Path(folder)
    report, _ = build()
    tokens = {theme: {name: t["hex"] for name, t in data["tokens"].items()} for theme, data in report.items()}
    payload = {"generated_by": "design/palette.py", "colour": tokens}
    (folder / "tokens.json").write_text(json.dumps(payload, indent=2) + NEWLINE, encoding="utf-8")

    def block(theme, indent):
        return NEWLINE.join(f"{indent}--hw-{name}: {value};" for name, value in tokens[theme].items())

    parts = [
        "/* Generated by design/palette.py. Do not edit by hand: change the OKLCH values there and re-run. */",
        ":root {", block("light", "  "), "}",
        "@media (prefers-color-scheme: dark) {", "  :root:not([data-theme=\"light\"]) {", block("dark", "    "), "  }", "}",
        # data-theme on any element themes that subtree, so one page can show both side by side.
        ":root[data-theme=\"dark\"], [data-theme=\"dark\"] {", block("dark", "  "), "}",
        "[data-theme=\"light\"] {", block("light", "  "), "}",
    ]
    (folder / "tokens.css").write_text(NEWLINE.join(parts) + NEWLINE, encoding="utf-8")


if __name__ == "__main__":
    from pathlib import Path

    report, failures = build()
    for theme, data in report.items():
        print(f"== {theme}")
        for name, t in data["tokens"].items():
            print(f"  {name:13} {t['hex']}  {t['oklch']}{'  (chroma reduced to fit sRGB)' if t['chroma_mapped'] else ''}")
        print("  contrast:")
        for fg, bg, r, need in data["contrast"]:
            print(f"    {fg:12} on {bg:12} {r:5.2f}  (min {need}){'  FAIL' if r < need else ''}")
        print("  worst status separation (OKLab distance):", data["status_separation"])
    print("FAILURES:", failures or "none")
    here = Path(__file__).resolve().parent
    write_tokens(here)
    # The app serves only rollcall/static, so the stylesheet is written there too, from the same source.
    served = here.parent / "rollcall" / "static" / "css"
    served.mkdir(exist_ok=True)
    (served / "tokens.css").write_text((here / "tokens.css").read_text(encoding="utf-8"), encoding="utf-8")
