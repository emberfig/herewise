import importlib.util
import itertools
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("palette", ROOT / "design" / "palette.py")
palette = importlib.util.module_from_spec(spec)
spec.loader.exec_module(palette)

# Floors from the research. Present against absent is the pair eligibility depends on, so it gets more room.
MIN_ANY_PAIR = {"deutan": 0.035, "protan": 0.06, "greyscale": 0.04}
MIN_PRESENT_ABSENT = {"deutan": 0.10, "protan": 0.10, "greyscale": 0.10}


def test_every_text_and_ui_pairing_meets_its_contrast_floor():
    _, failures = palette.build()
    assert failures == []


def test_statuses_stay_apart_for_colour_blind_readers_and_on_photocopies():
    for theme, tokens in palette.THEMES.items():
        lin = {k: palette.oklch_to_srgb(L, palette.gamut_map(L, C, h), h) for k, (L, C, h) in tokens.items()}
        views = {"deutan": lambda x: palette.simulate(x, "deutan"),
                 "protan": lambda x: palette.simulate(x, "protan"),
                 "greyscale": palette.grey}
        for view, f in views.items():
            worst = min(palette.delta_ok(f(lin[a]), f(lin[b]))
                        for a, b in itertools.combinations(palette.STATUSES, 2))
            assert worst >= MIN_ANY_PAIR[view], (theme, view, worst)
            present_absent = palette.delta_ok(f(lin["present"]), f(lin["absent"]))
            assert present_absent >= MIN_PRESENT_ABSENT[view], (theme, view, present_absent)


def test_generated_tokens_match_the_source(tmp_path):
    palette.write_tokens(tmp_path)
    for name in ("tokens.css", "tokens.json"):
        assert (tmp_path / name).read_text(encoding="utf-8") == (ROOT / "design" / name).read_text(encoding="utf-8")
    served = ROOT / "rollcall" / "static" / "css" / "tokens.css"
    assert served.read_text(encoding="utf-8") == (tmp_path / "tokens.css").read_text(encoding="utf-8")


def test_no_pure_white_or_black():
    report, _ = palette.build()
    for data in report.values():
        for t in data["tokens"].values():
            assert t["hex"] not in ("#FFFFFF", "#000000")
