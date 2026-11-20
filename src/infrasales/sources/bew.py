"""Projects funded under BEW Modul 1 (feasibility studies, transformation plans).

There is no database of the Bundesförderung für effiziente Wärmenetze; its projects are listed in
the federal government's answers to parliamentary questions. Drucksache 20/13968 (26 November
2024) attaches, as Anlage 2, every Modul 1 project with its applicant, project, post code, town,
Land and grant. Each row is an early signal: a study of a heat network was funded there. The text
of the PDF runs a row over several lines; a row ends with its Land and its grant in euros.
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pypdf import PdfReader

LAENDER = (
    "Baden-Württemberg", "Bayern", "Berlin", "Brandenburg", "Bremen", "Hamburg", "Hessen",
    "Mecklenburg-Vorpommern", "Niedersachsen", "Nordrhein-Westfalen", "Rheinland-Pfalz",
    "Saarland", "Sachsen-Anhalt", "Sachsen", "Schleswig-Holstein", "Thüringen",
)  # fmt: skip
_LAND = "|".join(re.escape(land).replace(r"\-", r"-\s*") for land in LAENDER)
ROW = re.compile(
    rf"(?:^|\s)(?P<number>\d{{1,4}})\s+(?P<text>.+?)\s+(?P<post_code>\d{{5}})\s+(?P<town>[^\d]+?)\s+"
    rf"(?P<land>{_LAND})\s+(?P<grant>\d{{1,3}}(?:\.\d{{3}})*,\d{{2}})",
    re.DOTALL,
)
HEADER = re.compile(r"Anlage 2.*?Bundesland\s+Fördersumme(?: in Euro)?", re.DOTALL)


@dataclass(frozen=True, slots=True)
class FundedProject:
    number: int
    text: str  # applicant and project, as the table runs them together
    post_code: str
    town: str
    land: str
    grant_eur: float


def read(path: Path) -> list[FundedProject]:
    """The rows of Anlage 2 (BEW Modul 1) of the Drucksache at `path`."""
    return parse([page.extract_text() or "" for page in PdfReader(path).pages])


def parse(pages: list[str]) -> list[FundedProject]:
    """The rows of Anlage 2 in the text of a Drucksache's pages."""
    start = next((i for i, text in enumerate(pages) if "Anlage 2" in text), None)
    if start is None:
        return []
    end = next((i for i in range(start + 1, len(pages)) if "Anlage 3" in pages[i]), len(pages))
    text = "\n".join(pages[start:end])
    text = re.sub(r"Anlage 2\s+Drucksache [^\n]*\n", "\n", text)
    text = HEADER.sub("\n", text)
    return [
        FundedProject(
            number=int(match["number"]),
            text=" ".join(match["text"].split()),
            post_code=match["post_code"],
            town=" ".join(match["town"].split()),
            land=re.sub(r"-\s+", "-", match["land"]),
            grant_eur=float(match["grant"].replace(".", "").replace(",", ".")),
        )
        for match in ROW.finditer(text)
    ]


DRUCKSACHE_20_13968 = date(2024, 11, 26)  # when the list became public
