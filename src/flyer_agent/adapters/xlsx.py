"""Read/write the review spreadsheet (`Revisione.xlsx`) with openpyxl.

Drive opens `.xlsx` files in Google Sheets and saves edits back to the same file, so the approver can edit
from the browser and the change reaches the agent through Drive desktop sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
EDITABLE_FILL = PatternFill("solid", fgColor="FFF4C2")  # yellow: "you can write here"
HEADER_FONT = Font(bold=True, color="FFFFFF")
WIDE = {"Testo": 70, "Nome": 34, "Da controllare": 50, "Modifica richiesta": 40, "Codice": 22}


@dataclass
class Tab:
    name: str
    headers: list[str]
    rows: list[list[Any]]
    editable: set[str]
    intro: str = ""  # one line above the table explaining what to do


def write(path: Path, tabs: list[Tab]) -> None:
    """Write the workbook atomically (temp file + rename) so a sync never picks up half a file."""
    wb = Workbook()
    wb.remove(wb.active)
    for tab in tabs:
        ws = wb.create_sheet(tab.name)
        start = 1
        if tab.intro:
            ws.cell(row=1, column=1, value=tab.intro).font = Font(italic=True, color="555555")
            start = 3
        for c, h in enumerate(tab.headers, 1):
            cell = ws.cell(row=start, column=c, value=h)
            cell.fill, cell.font = HEADER_FILL, HEADER_FONT
            ws.column_dimensions[get_column_letter(c)].width = WIDE.get(h, 14)
        for r, row in enumerate(tab.rows, start + 1):
            for c, (h, v) in enumerate(zip(tab.headers, row, strict=True), 1):
                cell = ws.cell(row=r, column=c, value=v)
                cell.alignment = Alignment(wrap_text=h in WIDE, vertical="top")
                if h in tab.editable:
                    cell.fill = EDITABLE_FILL
        ws.freeze_panes = ws.cell(row=start + 1, column=1)
    tmp = path.with_name(f".{path.name}.tmp")
    wb.save(tmp)
    tmp.replace(path)


def read(path: Path, tab: str, headers: list[str]) -> list[dict[str, Any]]:
    """Rows of one tab as {header: value}. The header row is found by its first column name."""
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if tab not in wb.sheetnames:
            return []
        rows = list(wb[tab].iter_rows(values_only=True))
    finally:
        wb.close()
    head = next((i for i, r in enumerate(rows) if r and r[0] == headers[0]), None)
    if head is None:
        return []
    names = [str(h) if h is not None else "" for h in rows[head]]
    return [dict(zip(names, r, strict=False)) for r in rows[head + 1:] if r and any(v not in (None, "") for v in r)]
