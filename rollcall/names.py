"""Name handling for the roster (PRD section 7).

Source names arrive as "SURNAME Given Names" with the surname in capitals. Surnames can be more
than one word ("TAKME ORUBUPO Oluwanifemi Precious"), so the split is on leading all-caps tokens,
not on the first space. The K40 stores 24 bytes for a name and cuts anything longer mid-word
without an error (verified on device 2026-09-15), so the device name is shortened here first.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

DEVICE_NAME_LIMIT = 24

# A direct-entry student has no matric number yet, and is written "DE" where the number would go
# (the lecturer's own convention, 2026-09-23). It is shown, never stored: matric_no is unique, so
# twenty-four students cannot all hold "DE". Stored, it is NULL, the student is recognised by name, and
# the real number replaces it when it comes.
DIRECT_ENTRY = "DE"
_DIRECT_ENTRY = re.compile(r"^\s*(?:d\s*\.?\s*e\s*\.?|direct[\s-]*entry)\s*$", re.IGNORECASE)

_STRIP_CHARS = re.compile(r"[,`]")
_SPACES = re.compile(r"\s+")


@dataclass
class ParsedName:
    surname: str
    other_names: str
    warnings: list[str] = field(default_factory=list)


def clean(raw: str) -> str:
    """Remove commas and backticks (both occur in the real roster), collapse whitespace, and compose.

    Composed (NFC) so that one name is stored one way: "Ọ" typed as one character and "O" plus a
    combining dot below are otherwise different strings that look the same.
    """
    composed = unicodedata.normalize("NFC", raw or "")
    return _SPACES.sub(" ", _STRIP_CHARS.sub(" ", composed)).strip()


def is_direct_entry(value: str | None) -> bool:
    """"DE", "D.E.", "de" or "Direct entry" in a matric number column: no number yet."""
    return bool(value) and bool(_DIRECT_ENTRY.match(str(value)))


def matric_or_none(value: str | None) -> str | None:
    """A matric number as typed, cleaned, or None for a blank or a direct-entry marker."""
    text = " ".join(str(value or "").split())
    return None if not text or is_direct_entry(text) else text


def matric_text(value: str | None) -> str:
    """What a matric number reads as on a page or in an export: the number, or DE."""
    return value or DIRECT_ENTRY


def fold(value: str | None) -> str:
    """The form names are searched in: accents dropped and case folded, for any script.

    "olabisi" finds "Ọlábísí", and "ọlá" finds "ỌLÁ". SQLite's LIKE folds ASCII case only, so without
    this neither worked. Registered in SQLite as fold() by db.connect.
    """
    decomposed = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _letters(token: str) -> str:
    return "".join(ch for ch in token if ch.isalpha())


def _is_surname_token(token: str) -> bool:
    letters = _letters(token)
    # A single capital letter is an initial, not a surname.
    return len(letters) >= 2 and letters.isupper()


def split_name(raw: str) -> ParsedName:
    tokens = clean(raw).split(" ") if clean(raw) else []
    if not tokens:
        return ParsedName("", "", ["name is empty"])

    count = 0
    for token in tokens:
        if _is_surname_token(token):
            count += 1
        else:
            break

    warnings: list[str] = []
    if count == 0:
        count = 1
        warnings.append("no capitalised surname found, first word used as surname")
    elif count == len(tokens) and len(tokens) > 1:
        count = 1
        warnings.append("whole name is capitalised, first word used as surname")

    surname = " ".join(tokens[:count])
    other = " ".join(tokens[count:])
    return ParsedName(surname, other, warnings)


def _fits(text: str, limit: int) -> bool:
    # The device field is bytes, not characters.
    return len(text.encode("utf-8")) <= limit


def _initial(token: str) -> str:
    letters = _letters(token)
    return (letters[0].upper() + ".") if letters else ""


def device_name(surname: str, other_names: str, limit: int = DEVICE_NAME_LIMIT) -> str:
    """Build the name stored on the device, abbreviating given names before cutting anything.

    Order of fallbacks:
      1. full name
      2. trailing given names to initials, last first, keeping the first given name whole
      3. first given name to an initial as well
      4. drop initials from the end
      5. cut the surname (only reached by a surname longer than the limit)
    """
    surname = clean(surname)
    given = clean(other_names).split(" ") if clean(other_names) else []

    def build(parts: list[str]) -> str:
        return " ".join([surname] + [p for p in parts if p])

    parts = list(given)
    if _fits(build(parts), limit):
        return build(parts)

    for i in range(len(parts) - 1, 0, -1):
        parts[i] = _initial(parts[i])
        if _fits(build(parts), limit):
            return build(parts)

    if parts:
        parts[0] = _initial(parts[0])
        if _fits(build(parts), limit):
            return build(parts)

    while parts:
        parts.pop()
        if _fits(build(parts), limit):
            return build(parts)

    encoded = surname.encode("utf-8")[:limit]
    return encoded.decode("utf-8", errors="ignore").rstrip()
