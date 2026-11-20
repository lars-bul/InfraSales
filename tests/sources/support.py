"""Small files in the sources' own formats: a workbook, a month's export, OpenPLZ's streets."""

import csv
import io
import zipfile
from collections.abc import Sequence
from pathlib import Path

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships"


def _column(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return letters


def workbook(path: Path, sheets: dict[str, Sequence[Sequence[str]]]) -> Path:
    """An XLSX file with `sheets`, every cell a shared string (as Destatis writes them)."""
    strings: list[str] = []
    parts: dict[str, str] = {}
    for number, (_, rows) in enumerate(sheets.items(), start=1):
        xml_rows: list[str] = []
        for r, row in enumerate(rows, start=1):
            cells: list[str] = []
            for c, value in enumerate(row):
                if value == "":
                    continue
                strings.append(value)
                cells.append(f'<c r="{_column(c)}{r}" t="s"><v>{len(strings) - 1}</v></c>')
            xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
        parts[f"xl/worksheets/sheet{number}.xml"] = (
            f'<worksheet xmlns="{MAIN}"><sheetData>{"".join(xml_rows)}</sheetData></worksheet>'
        )
    sheet_list = "".join(
        f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>'
        for i, name in enumerate(sheets, start=1)
    )
    relations = "".join(
        f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml" Type="worksheet"/>'
        for i in range(1, len(sheets) + 1)
    )
    shared = "".join(f"<si><t>{text}</t></si>" for text in strings)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{MAIN}" xmlns:r="{RELS}"><sheets>{sheet_list}</sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{PACKAGE}">{relations}</Relationships>',
        )
        archive.writestr("xl/sharedStrings.xml", f'<sst xmlns="{MAIN}">{shared}</sst>')
        for name, xml in parts.items():
            archive.writestr(name, xml)
    return path


def export(path: Path, tables: dict[str, list[dict[str, str]]]) -> Path:
    """A month's CSV export: one table per file, as the Datenservice zips them."""
    with zipfile.ZipFile(path, "w") as archive:
        for name, rows in tables.items():
            text = io.StringIO()
            writer = csv.DictWriter(
                text, fieldnames=list(rows[0]) if rows else ["noticeIdentifier"]
            )
            writer.writeheader()
            writer.writerows(rows)
            archive.writestr(name if name.endswith(".csv") else f"{name}.csv", text.getvalue())
    return path


def streets(path: Path, rows: Sequence[tuple[str, str, str, str]]) -> Path:
    """OpenPLZ's streets: name, post code, locality, regional key."""
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["Name", "PostalCode", "Locality", "RegionalKey", "Borough", "Suburb"])
        writer.writerows([(*row, "", "") for row in rows])
    return path


def gemeindeverzeichnis(path: Path) -> Path:
    """The directory with a title, a Land's row and three municipalities' rows."""
    title = (
        "Gemeinden in Deutschland nach Fläche, Bevölkerung und Postleitzahl am 31.12.2024 (Jahr)"
    )
    rows = [
        [title],
        [],
        ["Satzart"],
        [],
        [],
        ["10", "", "08", "", "", "", "", "Baden-Württemberg"],
        [
            "60",
            "61",
            "08",
            "2",
            "21",
            "0000",
            "000",
            "Heidelberg, Stadt",
            "108.83",
            "162273",
            "",
            "",
            "",
            "69117",
            "8,69079",
            "49,40768",
            "",
            "",
            "1",
            "dicht",
        ],
        [
            "60",
            "61",
            "08",
            "4",
            "21",
            "0000",
            "000",
            "Ulm, Universitätsstadt",
            "118.69",
            "128928",
            "",
            "",
            "",
            "89073",
            "9,99155",
            "48,39841",
            "",
            "",
            "1",
            "dicht",
        ],
        [
            "60",
            "64",
            "08",
            "2",
            "26",
            "0095",
            "095",
            "Walldorf, Stadt",
            "19.88",
            "15803",
            "",
            "",
            "",
            "69190",
            "8,64215",
            "49,30637",
            "",
            "",
            "2",
            "mittel",
        ],
    ]
    return workbook(
        path, {"Inhalt": [["Gemeindeverzeichnis"]], "Onlineprodukt_Gemeinden31122024": rows}
    )
