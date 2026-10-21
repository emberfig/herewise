"""A dummy 200 Level list, shaped exactly like the department's own workbook.

Invented names, and matric numbers under DUMMY01 so they can never collide with a real one: a
device ID is permanent, so a test student holding 25/PHARM01/044 would take that ID away from the
real holder for good.

Two files:

    data/Dummy 200 Level.xlsx          120 students, nothing wrong with it
    data/Dummy 200 Level (messy).xlsx  the same list with four faults, to see the preview work

    python scripts/make_dummy_roster.py [folder]

The matric numbers are under DUMMY01 on purpose. A device ID is permanent and never reused, so a
test student given 25/PHARM01/044 would hold that ID for good and the real holder would never get
it.

One name carries Yoruba tone marks and one is far longer than the terminal's 24-character field,
because both of those have found real faults before (PDF glyphs, and the device name).
"""
import random
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

import sys

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "data"
random.seed(200)

SURNAMES = [
    "ADEBAYO", "ADEYEMI", "AFOLABI", "AGBAJE", "AKANNI", "AKINTOLA", "AMADI", "ANYANWU",
    "BALOGUN", "BASSEY", "CHUKWU", "DANJUMA", "EKANEM", "ELUEMUNOR", "EZE", "FALANA",
    "GARBA", "IBRAHIM", "IDOWU", "IGWE", "ILORI", "JIBRIL", "KAYODE", "LAWAL",
    "MADUKA", "MOHAMMED", "NDUKA", "NWACHUKWU", "OBI", "ODUYA", "OGUNDELE", "OKAFOR",
    "OKONKWO", "OLADIPO", "OLUWASEUN", "OMOTOSO", "ONYEKA", "OSAGIE", "SALAMI", "SANUSI",
    "SHEHU", "SULEIMAN", "TAIWO", "UCHE", "UDOH", "UGWU", "UZOMA", "YAKUBU",
]
GIVEN = [
    "Aisha", "Amaka", "Blessing", "Chiamaka", "Chidera", "Chinedu", "Damilola", "Ebube",
    "Emeka", "Fatima", "Folake", "Gbenga", "Halima", "Ifeoma", "Ikenna", "Joshua",
    "Kelechi", "Khadija", "Mercy", "Nneka", "Obinna", "Oluwaseun", "Precious", "Rukayat",
    "Samuel", "Temitope", "Takme", "Uche", "Victor", "Yusuf", "Zainab", "Emmanuel",
]
SECOND = [
    "Adaeze", "Ayomide", "Chinonso", "Ebunoluwa", "Enitan", "Ifeanyi", "Iretomiwa", "Kunle",
    "Ladipo", "Nkechi", "Oluwatobi", "Opeyemi", "Sodiq", "Tolulope", "Yewande", "",
]

# Two that have found faults before: tone marks, and a name longer than the terminal's field.
SPECIALS = [
    ("ỌLÁBÍSÍ", "Ṣẹgun Adétọ́kunbọ̀"),
    ("BEPUFIEZA-EPANEZO", "Wudizvifkiku Joshua Obovusigupase"),
    ("CHUKWUMA-AZUK", "Onooze"),
]


def people(count: int) -> list[tuple[str, str]]:
    made, seen = [], set()
    for surname, given in SPECIALS:
        made.append((surname, given))
        seen.add((surname, given))
    while len(made) < count:
        surname = random.choice(SURNAMES)
        given = random.choice(GIVEN)
        second = random.choice(SECOND)
        full = (surname, f"{given} {second}".strip())
        if full in seen:
            continue
        seen.add(full)
        made.append(full)
    return made


def workbook(rows: list[list], title: str) -> openpyxl.Workbook:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "200 Level"
    sheet.append(["EXAMPLE UNIVERSITY, EXAMPLE TOWN, COLLEGE OF PHARMACY,"])
    sheet.append(["  2026/2027 ACADEMIC SESSION"])
    sheet.append(["", title])
    sheet.append([])
    sheet.append([])
    sheet.append(["S/N", "NAMES", "MATRIC NO.", "GROUP"])
    for row in rows:
        sheet.append(row)
    sheet["A1"].font = Font(bold=True)
    sheet["B3"].font = Font(bold=True)
    for cell in sheet[6]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")
    for column, width in enumerate([6, 42, 20, 8], start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    return book


made = people(120)
rows = []
for number, (surname, given) in enumerate(made, start=1):
    group = "A" if number <= 40 else "B" if number <= 80 else "C"
    rows.append([number, f"{surname} {given}", f"25/DUMMY01/{number:03d}", group])

clean = OUT / "Dummy 200 Level.xlsx"
workbook(rows, "200 LEVEL STUDENTS' PRACTICAL GROUPINGS (DUMMY DATA)").save(clean)

# The same list with the faults the real file has, so the preview can be seen doing its job.
messy = [list(r) for r in rows]
messy[10][2] = ""                                   # no matric number
messy[11][2] = ""                                   # no matric number
messy[20][2] = "25/DUMMY01021"                      # missing a slash
messy[31][2] = messy[30][2]                         # two students, one matric number
messy_path = OUT / "Dummy 200 Level (messy).xlsx"
workbook(messy, "200 LEVEL STUDENTS' PRACTICAL GROUPINGS (DUMMY, WITH FAULTS)").save(messy_path)

print(f"{clean.name}: {len(rows)} students, all clean")
print(f"{messy_path.name}: the same, with")
print(f"   row 17 and 18: no matric number ({messy[10][1]}, {messy[11][1]})")
print(f"   row 27: {messy[20][2]}  (missing a slash)")
print(f"   row 37 and 38: both {messy[31][2]}")
print()
print("first three, and the two special names:")
for row in rows[:3]:
    print("  ", row)
