"""Which municipality a place lies in: from its post code and town, as notices give them.

A post code may span several municipalities (1,465 of 8,159 do): the town decides, else the one
with most of the post code's streets. Post codes come from OpenPLZ (streets of OpenStreetMap with
their post code and regional key, ODbL: attribution "© OpenStreetMap contributors, OpenPLZ API").
Without a post code, a town is matched by name, within the Land its NUTS code names.
"""

import csv
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

AGS_DIGITS = 8
POST_CODE_AND_TOWN = re.compile(r"^\s*(?P<post_code>\d{5})\s+(?P<town>.+)$")
# A buyer named after its town: a municipality, its administration or its utility.
BUYER_TOWN = re.compile(
    r"^(?:Stadt|Gemeinde|Markt|Große Kreisstadt|Hansestadt|Universitätsstadt|Kreisstadt|"
    r"Stadtwerke|Gemeindewerke|Stadtverwaltung|Gemeindeverwaltung)\s+"
    r"(?P<town>[A-ZÄÖÜ][\w.\- ]+?)(?:\s+(?:GmbH|AG|KG|mbH|AöR|eG|Eigenbetrieb|SE)\b.*)?$"
)
# The Land of a NUTS 1 region, as the AGS starts.
NUTS_LAND = {
    "DE1": "08", "DE2": "09", "DE3": "11", "DE4": "12", "DE5": "04", "DE6": "02", "DE7": "06",
    "DE8": "13", "DE9": "03", "DEA": "05", "DEB": "07", "DEC": "10", "DED": "14", "DEE": "15",
    "DEF": "01", "DEG": "16",
}  # fmt: skip
NOISE = re.compile(
    r"\(.*?\)|,.*$|\b(stadt|gemeinde|hansestadt|landeshauptstadt|kreisstadt|grosse|universitätsstadt"
    r"|markt|flecken|samtgemeinde|verbandsgemeinde|amt)\b"
)


def normalized(name: str) -> str:
    """A place name compared loosely: lower case, ß as ss, no brackets, no "Stadt", one space."""
    text = unicodedata.normalize("NFKC", name).lower().replace("ß", "ss")
    text = NOISE.sub(" ", text)
    text = re.sub(r"[^\w]+", " ", text)
    return " ".join(text.split())


@dataclass(frozen=True, slots=True)
class PostCodeArea:
    post_code: str
    locality: str
    ags: str
    streets: int


def read_streets(path: Path) -> Iterator[PostCodeArea]:
    """OpenPLZ's streets (`streets.csv`) summed up: per post code, locality and municipality."""
    counts: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    with path.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            key = row.get("RegionalKey") or ""
            if len(key) == AGS_DIGITS and key.isdigit() and row.get("PostalCode"):
                counts[row["PostalCode"], row.get("Locality") or "", key] += 1
    for (post_code, locality, ags), streets in sorted(counts.items()):
        yield PostCodeArea(post_code, locality, ags, streets)


@dataclass(slots=True)
class Resolver:
    """Resolves post codes and towns to AGS, from the municipalities and the post code areas."""

    names: dict[str, str]  # AGS → normalised name
    areas: dict[str, list[PostCodeArea]] = field(default_factory=dict[str, list[PostCodeArea]])
    by_name: dict[str, list[str]] = field(default_factory=dict[str, list[str]])

    @classmethod
    def of(
        cls, municipalities: Iterable[tuple[str, str]], areas: Iterable[PostCodeArea]
    ) -> Resolver:
        names = {ags: normalized(name) for ags, name in municipalities}
        by_post_code: defaultdict[str, list[PostCodeArea]] = defaultdict(list)
        for area in areas:
            by_post_code[area.post_code].append(area)
        by_name: defaultdict[str, list[str]] = defaultdict(list)
        for ags, name in names.items():
            by_name[name].append(ags)
        return cls(names, dict(by_post_code), dict(by_name))

    def resolve(
        self, post_code: str | None, city: str | None, nuts: str | None = None
    ) -> str | None:
        """The AGS of a place, or None when neither post code nor town identify one.

        A town given with its post code in one field ("78050 Villingen-Schwenningen") is split.
        """
        if not post_code and city and (joined := POST_CODE_AND_TOWN.match(city)):
            post_code, city = joined["post_code"], joined["town"]
        town = normalized(city) if city else ""
        code = (post_code or "").strip()[:5]
        if candidates := self.areas.get(code):
            totals: defaultdict[str, int] = defaultdict(int)
            for area in candidates:
                totals[area.ags] += area.streets
            if town:
                named = {
                    area.ags
                    for area in candidates
                    if town in {normalized(area.locality), self.names.get(area.ags, "")}
                }
                if len(named) == 1:
                    return named.pop()
            return max(totals, key=lambda ags: (totals[ags], ags))
        if town and (matches := self.by_name.get(town)):
            land = NUTS_LAND.get((nuts or "")[:3])
            in_land = [ags for ags in matches if land is None or ags.startswith(land)]
            if len(in_land) == 1:
                return in_land[0]
        return None

    def resolve_buyer(self, name: str | None, nuts: str | None = None) -> str | None:
        """The municipality a buyer's name names: "Stadt Rheinsberg", "Stadtwerke Tübingen GmbH"."""
        if not name or not (named := BUYER_TOWN.match(name.strip())):
            return None
        return self.resolve(None, named["town"], nuts)
