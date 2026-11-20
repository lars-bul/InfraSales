"""Firm names compared loosely: one firm, however its notices write it.

Award notices write a winner's name as its buyer typed it: "Müller Rohrleitungsbau GmbH & Co.
KG", "MÜLLER Rohrleitungsbau GmbH u. Co KG". Legal forms, punctuation and case are dropped, so
both are one firm in the market (`infrasales.forecast.winners`).
"""

import re
import unicodedata

LEGAL_FORMS = re.compile(
    r"\b(gmbh|mbh|ag|kg|kgaa|ohg|gbr|ug|haftungsbeschränkt|se|eg|ev|e v|co|und|u|cie|ltd|bv|sa|"
    r"sarl|spa|gesellschaft|mit beschränkter haftung|aktiengesellschaft|kommanditgesellschaft)\b"
)


def firm_key(name: str) -> str:
    """A firm's name for comparison: lower case, no legal form, no punctuation, one space."""
    text = unicodedata.normalize("NFKC", name).lower().replace("ß", "ss")
    text = re.sub(r"[&+.,;:/()\"'\-]", " ", text)
    text = LEGAL_FORMS.sub(" ", text)
    return " ".join(text.split())
