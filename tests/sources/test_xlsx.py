from pathlib import Path

from infrasales.sources.xlsx import sheets
from tests.sources.support import workbook


def test_a_workbook_reads_as_sheets_of_rows_of_text(tmp_path: Path) -> None:
    path = workbook(tmp_path / "book.xlsx", {"Eins": [["a", "", "c"], ["d"]], "Zwei": [["x"]]})

    assert sheets(path) == {"Eins": [["a", "", "c"], ["d"]], "Zwei": [["x"]]}


def test_cells_beyond_column_z_keep_their_place(tmp_path: Path) -> None:
    row = [""] * 27 + ["AB"]
    path = workbook(tmp_path / "wide.xlsx", {"S": [row]})

    assert sheets(path)["S"][0][27] == "AB"
