"""Fonts and paper for the PDF exports.

reportlab's built-in Helvetica covers only Western European letters. Anything else, such as the Yoruba
and Igbo letters in "Ọlábísí Ṣẹ́gun", is swapped for a ZapfDingbats black square, so a signed sheet
would carry "■lábísí ■■■gun". Checked on 2026-09-19 by drawing the name and reading the PDF back.

Segoe UI and Arial ship with every Windows since Vista, cover Latin Extended Additional (Yoruba, Igbo,
Vietnamese), the Hausa hooked letters and combining accents, and both allow embedding in documents
(OS/2 fsType 8). They are read from the Windows fonts folder, never bundled or fetched: redistributing
them is not allowed, embedding a subset in a PDF is. Helvetica remains the fallback off Windows.
"""
from __future__ import annotations

import os
import unicodedata
from functools import lru_cache
from pathlib import Path

# First family found wins. (regular, bold) file names in the Windows fonts folder.
CANDIDATES = (("Segoe UI", "segoeui.ttf", "segoeuib.ttf"), ("Arial", "arial.ttf", "arialbd.ttf"))
FALLBACK = ("Helvetica", "Helvetica-Bold")

PAPER_SIZES = ("a4", "letter")


def fonts_folder() -> Path:
    return Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


@lru_cache(maxsize=None)
def families(folder: str | None = None) -> tuple[str, str]:
    """(regular, bold) font names registered with reportlab for PDF text."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    base = Path(folder) if folder else fonts_folder()
    for family, regular, bold in CANDIDATES:
        paths = (base / regular, base / bold)
        if all(p.is_file() for p in paths):
            names = (f"Herewise-{family}", f"Herewise-{family}-Bold")
            for name, path in zip(names, paths):
                if name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(name, str(path)))
            return names
    return FALLBACK


def text(value: str) -> str:
    """The name as the PDF can draw it: composed, then without any accent that could not join its letter.

    Composing turns "O" plus a dot below into "Ọ", which the fonts have. A tone mark on a letter that
    already carries a dot, as in Yoruba "ẹ́", has no composed form, and reportlab cannot place a
    combining mark, so it printed after the letter ("Ṣẹ´gun"). Only the PDF drops it; the stored name
    keeps it. Placing it properly needs a text shaper (HarfBuzz), which is not installed.
    """
    composed = unicodedata.normalize("NFC", value)
    return "".join(ch for ch in composed if not unicodedata.combining(ch))


def page_size(paper: str) -> tuple[float, float]:
    from reportlab.lib.pagesizes import A4, letter

    return {"a4": A4, "letter": letter}[paper]
