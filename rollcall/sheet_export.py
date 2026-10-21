"""Render the attendance sheet in the lecturer's own layout, as Excel and as PDF.

Layout copied from 200L_Pharmacy_Attendance.pdf: landscape Letter, title and COURSE centred at the
top, a LECTURER'S SIGNATURE box above each week, then S/N, MATRIC NO., FULL NAME and one column per
week, 38 students a page, and on the last page NO. OF STUDENTS PRESENT, NO. OF STUDENTS ABSENT and
TOTAL REGISTERED. A week with more than one class gets a numbered box per class under its heading.

Marks: a tick for present, a cross for absent in a class that took place, E for an excused absence,
blank for a class that has not happened yet. Carry-over students follow the home level's students
under a CARRY-OVER STUDENTS row.

A course with groups prints a sheet per group, each with its group under the course line and its own
page numbers; every group in one file is each group's pages one after another in the PDF and a
worksheet per group in the spreadsheet. A box for a class a student was not in the group for (they
moved) is shaded, the way a week with no class is: it is not theirs, not an absence.
"""
from __future__ import annotations

import io
import re

from . import NAME, names

TICK = "✓"
CROSS = "✗"
EXCUSED = "E"
NOT_THEIRS = "elsewhere"
NO_GROUP_LABEL = "STUDENTS IN NO GROUP"
CARRY_OVER_LABEL = "CARRY-OVER STUDENTS"
ROWS_PER_PAGE = 38


def _columns(sheet: dict) -> list[dict]:
    """One entry per printed box: week, slot, and whether it is the first box of its week."""
    cols = []
    for week in sheet["weeks"]:
        if week["classes"] == 0:
            cols.append({"week": week, "slot": None, "first": True, "span": 1})
            continue
        for i, slot in enumerate(week["slots"]):
            cols.append({"week": week, "slot": slot, "first": i == 0, "span": week["classes"]})
    return cols


def _mark(student: dict, week_number: int, slot_number: int | None) -> str:
    if slot_number is None:
        return ""
    for cell in student["cells"]:
        if cell["week"] == week_number and cell["slot"] == slot_number:
            if cell["state"] == NOT_THEIRS:
                return NOT_THEIRS
            # "waiting" is a student in a class still taking attendance who has not scanned yet:
            # blank, because nobody is absent until the lecturer ends the class. A cross here would
            # put an absence on paper that the register does not hold.
            if cell["state"] in ("upcoming", "not_held", "waiting"):
                return ""
            if cell["state"] == "excused":
                return EXCUSED
            return TICK if cell.get("ticked") else CROSS
    return ""


def _rows(sheet: dict) -> list[dict]:
    """Students in sheet order, with a label row before the first carry-over student."""
    rows, labelled = [], False
    for student in sheet["students"]:
        if student.get("kind") == "carry_over" and not labelled:
            rows.append({"label": CARRY_OVER_LABEL})
            labelled = True
        rows.append(student)
    return rows


def _course_line(t: dict, sheet: dict | None = None) -> str:
    title = f" {t['course_title']}" if t.get("course_title") else ""
    line = f"COURSE: {t.get('course_code') or ''}{title}".rstrip()
    group = _group_label(sheet or {})
    return f"{line}, {group}" if group else line


def _group_label(sheet: dict) -> str | None:
    """The group a sheet is for, in the heading's capitals; None for a course without groups."""
    if "groups" not in sheet:
        return None
    return sheet["group"]["name"].upper() if sheet.get("group") else NO_GROUP_LABEL


def _total_line(sheet: dict) -> str:
    text = f"TOTAL REGISTERED: {sheet['total_registered']}"
    if sheet.get("carry_over"):
        text += f" (INCLUDING {sheet['carry_over']} CARRY-OVER)"
    return text


def filename(sheet: dict, extension: str, every_group: bool = False) -> str:
    t = sheet["template"]
    group = "every group" if every_group else (_group_label(sheet) or "").title()
    base = f"{t['title']} {group} {t['academic_session']}".replace("  ", " ")
    return re.sub(r"[^A-Za-z0-9 ._-]+", "-", base).strip() + f".{extension}"


def _worksheet_title(sheet: dict, taken: set[str]) -> str:
    """A worksheet's name: the group's, within Excel's 31 characters and without its forbidden ones."""
    base = re.sub(r"[\\/*?:\[\]]", "-", (_group_label(sheet) or "Attendance").title())[:31] or "Attendance"
    name, n = base, 2
    while name.casefold() in taken:
        name = f"{base[:28]} {n}"
        n += 1
    taken.add(name.casefold())
    return name


# -- Excel ---------------------------------------------------------------------------------------

def to_xlsx(sheet: dict, paper: str = "a4") -> bytes:
    return to_xlsx_many([sheet], paper)


def to_xlsx_many(sheets: list[dict], paper: str = "a4") -> bytes:
    """One worksheet per sheet: a course's own, or each of its groups'."""
    from openpyxl import Workbook

    wb = Workbook()
    taken: set[str] = set()
    for n, sheet in enumerate(sheets):
        ws = wb.active if n == 0 else wb.create_sheet()
        ws.title = _worksheet_title(sheet, taken) if "groups" in sheet else "Attendance"
        _xlsx_sheet(ws, sheet, paper)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _xlsx_sheet(ws, sheet: dict, paper: str) -> None:
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    t = sheet["template"]
    cols = _columns(sheet)
    multi = any(c["span"] > 1 for c in cols)
    first_week_col = 4
    last_col = first_week_col + len(cols) - 1

    thin = Side(style="thin", color="000000")
    thick = Side(style="medium", color="000000")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    bold = Font(name="Arial", bold=True, size=8)
    normal = Font(name="Arial", size=8)
    mark_font = Font(name="Segoe UI Symbol", size=10)
    centre = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")
    grey = PatternFill("solid", fgColor="E7E6E6")

    ws.column_dimensions["A"].width = 4.5
    ws.column_dimensions["B"].width = 15
    ws.column_dimensions["C"].width = 33
    for i, c in enumerate(cols):
        ws.column_dimensions[get_column_letter(first_week_col + i)].width = 8.5 / max(1, c["span"]) + (1 if c["span"] > 1 else 0)

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    ws.cell(1, 1, t["title"]).font = Font(name="Arial", bold=True, size=12)
    ws.cell(1, 1).alignment = centre
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_col)
    ws.cell(2, 1, _course_line(t, sheet)).font = Font(name="Arial", bold=True, size=10)
    ws.cell(2, 1).alignment = centre

    # Row 3: signature boxes, one per week.
    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=3)
    ws.cell(3, 1, "LECTURER'S SIGNATURE").font = bold
    ws.cell(3, 1).alignment = centre
    ws.row_dimensions[3].height = 22
    header_row = 4
    for i, c in enumerate(cols):
        col = first_week_col + i
        if c["first"] and c["span"] > 1:
            ws.merge_cells(start_row=3, start_column=col, end_row=3, end_column=col + c["span"] - 1)
            ws.merge_cells(start_row=header_row, start_column=col, end_row=header_row, end_column=col + c["span"] - 1)
        if c["first"]:
            ws.cell(header_row, col, c["week"]["label"])

    for col, text in ((1, "S/N"), (2, "MATRIC NO."), (3, "FULL NAME")):
        ws.cell(header_row, col, text)
    data_row = header_row + 1
    if multi:
        for col in (1, 2, 3):
            ws.merge_cells(start_row=header_row, start_column=col, end_row=header_row + 1, end_column=col)
        for i, c in enumerate(cols):
            ws.cell(header_row + 1, first_week_col + i, c["slot"]["slot"] if c["slot"] else "-")
        data_row += 1

    for r in range(3, data_row):
        for col in range(1, last_col + 1):
            cell = ws.cell(r, col)
            cell.border = box
            cell.font = bold
            cell.alignment = centre

    items = _rows(sheet)
    for n, student in enumerate(items):
        r = data_row + n
        if "label" in student:
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=last_col)
            ws.cell(r, 1, student["label"]).font = bold
            ws.cell(r, 1).alignment = left
            ws.cell(r, 1).fill = grey
            continue
        ws.cell(r, 1, student["sn"]).alignment = centre
        ws.cell(r, 2, names.matric_text(student["matric_no"])).alignment = centre
        ws.cell(r, 3, student["full_name"]).alignment = left
        for col in (1, 2, 3):
            ws.cell(r, col).font = normal
            ws.cell(r, col).border = box
        for i, c in enumerate(cols):
            mark = _mark(student, c["week"]["week_number"], c["slot"]["slot"] if c["slot"] else None)
            cell = ws.cell(r, first_week_col + i, None if mark == NOT_THEIRS else mark)
            cell.font = mark_font
            cell.alignment = centre
            cell.border = box
            if c["slot"] is None or mark == NOT_THEIRS:
                cell.fill = grey

    last_student_row = data_row + len(items) - 1
    footer = last_student_row + 1
    for offset, label, symbol in ((0, "NO. OF STUDENTS PRESENT", TICK), (1, "NO. OF STUDENTS ABSENT", CROSS)):
        r = footer + offset
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3)
        ws.cell(r, 1, label).font = bold
        ws.cell(r, 1).alignment = centre
        for col in range(1, last_col + 1):
            ws.cell(r, col).border = Border(left=thin, right=thin, bottom=thin, top=thick if offset == 0 else thin)
        for i, c in enumerate(cols):
            if c["slot"] and c["slot"]["session_id"]:
                letter = get_column_letter(first_week_col + i)
                cell = ws.cell(r, first_week_col + i,
                               f'=COUNTIF({letter}{data_row}:{letter}{last_student_row},"{symbol}")')
                cell.font = bold
                cell.alignment = centre
    total = ws.cell(footer + 2, last_col, _total_line(sheet))
    total.font = bold
    total.alignment = Alignment(horizontal="right")

    # By its address, not its cell: when the first row is the merged CARRY-OVER STUDENTS line (a
    # sheet with only carry-over students, such as a group's "in no group" sheet) that cell is a
    # MergedCell, which openpyxl cannot freeze at (found by check_exports.mjs, 2026-09-29).
    ws.freeze_panes = f"{get_column_letter(first_week_col)}{data_row}"
    ws.print_title_rows = f"1:{data_row - 1}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4 if paper == "a4" else ws.PAPERSIZE_LETTER
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.oddHeader.right.text = "PAGE &P"
    ws.oddHeader.right.color = "CC0000"


# -- PDF -----------------------------------------------------------------------------------------

def paginate(count: int, multi: bool) -> list[tuple[int, int]]:
    """Student ranges per page. 38 a page like the original; 37 when weeks carry a row of class
    numbers. The last page keeps 3 rows free for the present, absent and total lines."""
    per_page = ROWS_PER_PAGE - (1 if multi else 0)
    footer_rows = 3
    ranges, start = [], 0
    while count - start > per_page:
        ranges.append((start, start + per_page))
        start += per_page
    if count - start > per_page - footer_rows:
        # The totals would not fit under these rows: give the last few rows a page of their own.
        split = start + per_page - footer_rows
        ranges.append((start, split))
        start = split
    ranges.append((start, count))
    return ranges


def to_pdf(sheet: dict, paper: str = "a4") -> bytes:
    return to_pdf_many([sheet], paper)


def to_pdf_many(sheets: list[dict], paper: str = "a4") -> bytes:
    """Each sheet's pages in turn, numbered from 1 for each: a group's pages are that group's paper."""
    from reportlab.lib.pagesizes import landscape
    from reportlab.pdfgen import canvas

    from .pdf_fonts import page_size

    page_w, page_h = landscape(page_size(paper))
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(page_w, page_h))
    pdf.setTitle(sheets[0]["template"]["title"])
    pdf.setAuthor(NAME)
    for sheet in sheets:
        _pdf_sheet(pdf, sheet, page_w, page_h)
    pdf.save()
    return buffer.getvalue()


def _pdf_sheet(pdf, sheet: dict, page_w: float, page_h: float) -> None:
    """The sheet on landscape A4 or Letter. The lecturer's original is Letter; most of the world prints A4.

    Measurements follow the page: 39 rows (header rows plus students) fill the height below the
    signature boxes, which is 13.6 pt on Letter as in the original and 13.15 pt on A4.
    """
    from reportlab.lib.colors import Color, black
    from reportlab.pdfbase.pdfmetrics import stringWidth

    from .pdf_fonts import families, text

    regular, bold = families()
    t = sheet["template"]
    cols = _columns(sheet)
    multi = any(c["span"] > 1 for c in cols)
    left_x, right_x = 16.0, page_w - 22.0
    sn_w, matric_w, name_w = 18.0, 69.0, 148.0
    weeks_x = left_x + sn_w + matric_w + name_w
    box_w = (right_x - weeks_x) / max(1, len(cols))
    row_h = (page_h - 82.0) / (ROWS_PER_PAGE + 1)
    red = Color(0.8, 0, 0)
    grey = Color(0.9, 0.9, 0.9)
    mid = Color(0.45, 0.45, 0.45)

    items = _rows(sheet)
    pages = [items[a:b] for a, b in paginate(len(items), multi)]

    def y(top: float) -> float:
        return page_h - top

    def text_fit(value: str, x: float, top: float, width: float, size: float, font: str = regular,
                 align: str = "left") -> None:
        value = text(value)
        while size > 4 and stringWidth(value, font, size) > width - 3:
            size -= 0.3
        pdf.setFont(font, size)
        baseline = y(top) - row_h / 2 - size / 3
        if align == "centre":
            pdf.drawCentredString(x + width / 2, baseline, value)
        else:
            pdf.drawString(x + 2, baseline, value)

    # Marks save and restore the drawing state, or their pen width and colour leak into the grid lines.
    def tick(cx: float, cy: float) -> None:
        pdf.saveState()
        pdf.setStrokeColor(black)
        pdf.setLineWidth(1.1)
        pdf.line(cx - 3.2, cy, cx - 1, cy - 2.6)
        pdf.line(cx - 1, cy - 2.6, cx + 3.6, cy + 3.4)
        pdf.restoreState()

    def cross(cx: float, cy: float) -> None:
        pdf.saveState()
        pdf.setStrokeColor(mid)
        pdf.setLineWidth(0.7)
        pdf.line(cx - 2.4, cy - 2.4, cx + 2.4, cy + 2.4)
        pdf.line(cx - 2.4, cy + 2.4, cx + 2.4, cy - 2.4)
        pdf.restoreState()

    def week_spans():
        x = weeks_x
        for c in cols:
            if c["first"]:
                yield c, x, box_w * (c["span"] if c["slot"] else 1)
            x += box_w

    for page_number, rows in enumerate(pages, start=1):
        last_page = page_number == len(pages)
        pdf.setFillColor(black)
        pdf.setFont(bold, 10)
        pdf.drawCentredString(page_w / 2, y(26), text(t["title"]))
        pdf.setFont(bold, 9.5)
        pdf.drawCentredString(page_w / 2, y(39), text(_course_line(t, sheet)))
        pdf.setFillColor(red)
        pdf.setFont(regular, 14)
        pdf.drawString(page_w - 240, y(29), f"PAGE {page_number}")
        pdf.setFillColor(black)

        top = 57.0
        pdf.setLineWidth(1.2)
        pdf.line(left_x, y(top), right_x, y(top))
        sig_h = 17.0
        text_fit("LECTURER'S SIGNATURE", left_x, top + (sig_h - row_h) / 2, weeks_x - left_x, 6.1,
                 bold, "centre")
        pdf.setLineWidth(0.6)
        for _, x, width in week_spans():
            pdf.rect(x, y(top + sig_h), width, sig_h)
        top += sig_h + 2

        header_h = row_h * (2 if multi else 1)
        pdf.setLineWidth(1.2)
        pdf.line(left_x, y(top), right_x, y(top))
        pdf.setLineWidth(0.6)
        for x, width, label in ((left_x, sn_w, "S/N"), (left_x + sn_w, matric_w, "MATRIC NO."),
                                (left_x + sn_w + matric_w, name_w, "FULL NAME")):
            pdf.rect(x, y(top + header_h), width, header_h)
            text_fit(label, x, top + (header_h - row_h) / 2, width, 6.4 if label != "FULL NAME" else 7.1,
                     bold, "centre")
        for c, x, width in week_spans():
            pdf.rect(x, y(top + row_h), width, row_h)
            text_fit(c["week"]["label"], x, top, width, 6.1, bold, "centre")
        if multi:
            x = weeks_x
            for c in cols:
                pdf.rect(x, y(top + 2 * row_h), box_w, row_h)
                text_fit(str(c["slot"]["slot"]) if c["slot"] else "-", x, top + row_h, box_w, 6, bold,
                         "centre")
                x += box_w
        top += header_h

        for student in rows:
            if "label" in student:
                pdf.setFillColor(grey)
                pdf.rect(left_x, y(top + row_h), right_x - left_x, row_h, fill=1)
                pdf.setFillColor(black)
                text_fit(student["label"], left_x, top, weeks_x - left_x, 6.4, bold)
                top += row_h
                continue
            pdf.setLineWidth(0.5)
            pdf.rect(left_x, y(top + row_h), sn_w, row_h)
            pdf.rect(left_x + sn_w, y(top + row_h), matric_w, row_h)
            pdf.rect(left_x + sn_w + matric_w, y(top + row_h), name_w, row_h)
            text_fit(str(student["sn"]), left_x, top, sn_w, 5.3, align="centre")
            text_fit(names.matric_text(student["matric_no"]), left_x + sn_w, top, matric_w, 6.1, align="centre")
            text_fit(student["full_name"], left_x + sn_w + matric_w, top, name_w, 7.1)
            x = weeks_x
            for c in cols:
                if c["slot"] is None:
                    pdf.setFillColor(grey)
                    pdf.rect(x, y(top + row_h), box_w, row_h, fill=1)
                    pdf.setFillColor(black)
                else:
                    mark = _mark(student, c["week"]["week_number"], c["slot"]["slot"])
                    if mark == NOT_THEIRS:
                        pdf.setFillColor(grey)
                        pdf.rect(x, y(top + row_h), box_w, row_h, fill=1)
                        pdf.setFillColor(black)
                    else:
                        pdf.rect(x, y(top + row_h), box_w, row_h)
                    cx, cy = x + box_w / 2, y(top + row_h / 2)
                    if mark == TICK:
                        tick(cx, cy)
                    elif mark == CROSS:
                        cross(cx, cy)
                    elif mark == EXCUSED:
                        text_fit(EXCUSED, x, top, box_w, 7, bold, "centre")
                x += box_w
            top += row_h

        if last_page:
            pdf.setLineWidth(1.2)
            pdf.line(left_x, y(top), right_x, y(top))
            pdf.setLineWidth(0.6)
            for key, label in (("present", "NO. OF STUDENTS PRESENT"), ("absent", "NO. OF STUDENTS ABSENT")):
                text_fit(label, left_x, top, weeks_x - left_x, 6.1, bold, "centre")
                x = weeks_x
                for c in cols:
                    pdf.rect(x, y(top + row_h), box_w, row_h)
                    if c["slot"] and c["slot"]["session_id"]:
                        # A class still taking attendance has no absent figure until it is ended.
                        still_open = c["slot"].get("state") == "open" and key == "absent"
                        text_fit("" if still_open else str(c["slot"].get(key, "")), x, top, box_w, 6.5,
                                 bold, "centre")
                    x += box_w
                top += row_h
            pdf.setFont(bold, 6.1)
            pdf.drawRightString(right_x - 2, y(top + 8), _total_line(sheet))
        pdf.showPage()
