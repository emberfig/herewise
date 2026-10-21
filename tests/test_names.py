import csv

from conftest import ROSTER
from rollcall.names import DEVICE_NAME_LIMIT, clean, device_name, fold, split_name


def test_two_word_surname():
    parsed = split_name("TAKME ORUBUPO Oluwanifemi Precious")
    assert parsed.surname == "TAKME ORUBUPO"
    assert parsed.other_names == "Oluwanifemi Precious"


def test_backtick_and_comma_from_real_roster():
    assert split_name("GOSAFU` Wavasloguifoze Cbsao").surname == "GOSAFU"
    parsed = split_name("OZAN-DELE Emmanuel Chibueze, Xuziil")
    assert parsed.surname == "OZAN-DELE"
    assert parsed.other_names == "Emmanuel Chibueze Xuziil"


def test_no_capitalised_surname_is_flagged():
    parsed = split_name("Asukagki Joshua")
    assert parsed.surname == "Asukagki"
    assert parsed.warnings


def test_trailing_given_names_become_initials():
    assert device_name("EFIKOSLI", "Opazsitofo Erimalsilke") == "EFIKOSLI Opazsitofo E."


def test_short_name_untouched():
    assert device_name("DOTE", "Udeeepfisu Dote") == "DOTE Udeeepfisu Dote"


def test_every_real_roster_name_fits_without_cutting_a_word():
    with open(ROSTER, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 258
    for row in rows:
        parsed = split_name(row["name"])
        name = device_name(parsed.surname, parsed.other_names)
        assert len(name.encode("utf-8")) <= DEVICE_NAME_LIMIT, name
        source_tokens = (parsed.surname + " " + parsed.other_names).split()
        for token in name.split():
            is_initial = len(token) == 2 and token.endswith(".")
            assert token in source_tokens or is_initial, (row["name"], name)
        assert name.startswith(parsed.surname)


def test_overlong_surname_is_cut_as_last_resort():
    name = device_name("A" * 30, "Given")
    assert len(name) == DEVICE_NAME_LIMIT


def test_a_name_is_stored_one_way_however_it_was_typed():
    decomposed = "O\u0323LA\u0301BI\u0301SI\u0301 Olu"      # O, combining dot below, and so on
    assert clean(decomposed) == "\u1eccL\u00c1B\u00cdS\u00cd Olu"  # composed: "ỌLÁBÍSÍ Olu"
    assert split_name(decomposed).surname == "\u1eccL\u00c1B\u00cdS\u00cd"


def test_fold_finds_names_without_their_accents_and_case():
    assert fold("\u1eccl\u00e1b\u00ed s\u00ed") == "olabi si"          # "Ọlábí sí"
    assert fold("\u1ecc\u0300K\u1ecc\u0300R\u1ecc\u0300") == "okoro"  # "Ọ̀KỌ̀RỌ̀"
    assert fold("M\u00dcLLER") == "muller" and fold("Stra\u00dfe") == "strasse"
