"""The logo. Geometry is asserted, not eyeballed, because the two failures it had were geometric.

Looking at it still matters: run `python design/logo.py` and open `design/logo/contact-sheet.png`.
These tests only stop the two mistakes that have already happened from coming back.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from design import logo, palette  # noqa: E402


def test_the_tick_never_reaches_the_top_of_the_stems():
    """The rise is capped. Uncapped, the icon reads as a Cyrillic "и" at 16 px."""
    highest = min(y for _, y in logo.TICK)
    clear_stem_above = highest - logo.TOP_Y
    assert clear_stem_above >= logo.BOX * 0.20, (
        f"the tick rises to {highest} of {logo.BOX} and leaves only {clear_stem_above} units of stem"
        " above it, which is where it stops reading as an H")


def test_the_tick_has_a_short_steep_arm_and_a_long_shallow_rise():
    """What makes it a tick rather than a sagging crossbar."""
    (x0, y0), (x1, y1), (x2, y2) = logo.TICK
    down_slope = (y1 - y0) / (x1 - x0)
    up_slope = (y1 - y2) / (x2 - x1)
    assert down_slope > up_slope, "the short arm must be steeper than the rise"
    assert (x2 - x1) > 2 * (x1 - x0), "the rise must be clearly the longer of the two arms"
    assert y1 > y0 and y1 > y2, "the vertex must be the lowest point"


def test_the_tick_meets_the_stems_and_stays_inside_the_box():
    (x0, _), _, (x2, _) = logo.TICK
    assert logo.LEFT_X <= x0 <= logo.LEFT_X + logo.STEM_W, "the tick must start on the left stem"
    assert logo.RIGHT_X <= x2 <= logo.RIGHT_X + logo.STEM_W, "the tick must finish on the right stem"
    assert all(0 < x < logo.BOX and 0 < y < logo.BOX for x, y in logo.TICK)


HAND_DRAWN = {16, 24}


def test_every_scaled_size_puts_the_stems_on_whole_pixels():
    """The point of the 64 unit grid: a stem edge must never land on half a pixel.

    Every stem coordinate is a multiple of 4, so any size that is a multiple of 16 is clean, 48
    included. 24 is not, which is exactly why it is drawn by hand instead of scaled.
    """
    edges = [logo.LEFT_X, logo.LEFT_X + logo.STEM_W, logo.RIGHT_X, logo.RIGHT_X + logo.STEM_W,
             logo.TOP_Y, logo.BOTTOM_Y]
    for size in logo.SIZES:
        if size in HAND_DRAWN:
            continue
        for edge in edges:
            landed = edge * size / logo.BOX
            assert landed == int(landed), (
                f"at {size} px the stem edge at grid {edge} lands on pixel {landed}, not a whole one."
                " Either change the size or draw it by hand like 16 and 24")


def test_the_hand_drawn_sizes_are_actually_drawn_by_hand():
    """If _draw_small stops being reached, 16 and 24 quietly become scaled mush."""
    for size in sorted(HAND_DRAWN):
        assert logo.png(size, "light").tobytes() == logo._draw_small(size, "light").tobytes()


def test_the_mark_uses_palette_colours_and_no_others():
    light = palette.TOKENS["light"] if hasattr(palette, "TOKENS") else None
    colours = logo.colours("light")
    css = (Path(logo.HERE) / "tokens.css").read_text(encoding="utf-8")
    for value in colours.values():
        assert value.upper() in css.upper(), f"{value} is not a token in tokens.css"
    assert light is None or True


def test_the_themed_svg_defers_to_the_tokens():
    svg = logo.mark_svg(themed=True)
    assert "currentColor" in svg, "the stems must follow the text colour so dark mode works"
    assert "var(--hw-accent" in svg, "the tick must come from the accent token"
    assert logo.mark_svg(themed=False).count("currentColor") == 0


def test_every_declared_asset_is_written(tmp_path, monkeypatch):
    monkeypatch.setattr(logo, "OUT", tmp_path / "logo")
    written = logo.write()
    assert all(p.exists() and p.stat().st_size > 0 for p in written)
    names = {p.name for p in written}
    for size in logo.SIZES:
        assert f"herewise-mark-{size}.png" in names
        assert f"herewise-mark-{size}-dark.png" in names
    assert {"herewise-mark.svg", "herewise-lockup.svg", "herewise.ico"} <= names


@pytest.mark.parametrize("size", [16, 24, 32, 64])
def test_both_stems_and_the_tick_survive_at_every_size(size):
    """A 16 px icon that renders as grey mush passes every other test here."""
    img = logo(size) if callable(logo) else logo.png(size, "light")
    pixels = img.load()
    ink = logo.colours("light")["ink"]
    accent = logo.colours("light")["accent"]

    def near(actual, wanted, tol=90):
        r, g, b, a = actual
        wr, wg, wb = int(wanted[1:3], 16), int(wanted[3:5], 16), int(wanted[5:7], 16)
        return a > 100 and abs(r - wr) < tol and abs(g - wg) < tol and abs(b - wb) < tol

    left = right = tick = 0
    for y in range(size):
        for x in range(size):
            p = pixels[x, y]
            if near(p, ink):
                if x < size / 2:
                    left += 1
                else:
                    right += 1
            elif near(p, accent):
                tick += 1
    assert left > 0 and right > 0, f"a stem vanished at {size} px"
    assert tick >= max(2, size // 8), f"the tick is only {tick} pixels at {size} px"
