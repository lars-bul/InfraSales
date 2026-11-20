"""The cells of an XLSX workbook as text, with the standard library: enough for statistical tables.

An XLSX file is a ZIP of XML parts: the workbook names the sheets, `sharedStrings.xml` holds the
texts cells refer to by index, and each sheet lists its rows of cells with their column letters.
"""

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RELS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PACKAGE_RELS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
COLUMN = re.compile(r"[A-Z]+")


def _column(reference: str) -> int:
    """The 0-based column of a cell reference: "A1" is 0, "AB7" is 27."""
    letters = COLUMN.match(reference)
    number = 0
    for letter in letters[0] if letters else "A":
        number = number * 26 + ord(letter) - ord("A") + 1
    return number - 1


def sheets(path: Path) -> dict[str, list[list[str]]]:
    """Every sheet's rows, by sheet name; a row's cells by column, empty ones as ""."""
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))  # noqa: S314  # a statistics office's workbook
            shared = [
                "".join(t.text or "" for t in item.iter(f"{MAIN}t"))
                for item in root.iter(f"{MAIN}si")
            ]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))  # noqa: S314
        relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))  # noqa: S314
        targets = {
            r.get("Id"): r.get("Target", "") for r in relations.iter(f"{PACKAGE_RELS}Relationship")
        }
        result: dict[str, list[list[str]]] = {}
        for sheet in workbook.iter(f"{MAIN}sheet"):
            target = targets.get(sheet.get(f"{RELS}id"), "").lstrip("/")
            part = target if target.startswith("xl/") else f"xl/{target}"
            rows: list[list[str]] = []
            for row in ET.fromstring(archive.read(part)).iter(f"{MAIN}row"):  # noqa: S314
                cells: list[str] = []
                for cell in row.iter(f"{MAIN}c"):
                    value = cell.find(f"{MAIN}v")
                    text = value.text if value is not None and value.text is not None else ""
                    if cell.get("t") == "s" and text:
                        text = shared[int(text)]
                    elif cell.get("t") == "inlineStr":
                        text = "".join(t.text or "" for t in cell.iter(f"{MAIN}t"))
                    column = _column(cell.get("r", "A"))
                    cells.extend([""] * (column - len(cells)))
                    cells.append(text)
                rows.append(cells)
            result[sheet.get("name", part)] = rows
        return result
