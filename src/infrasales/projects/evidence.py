"""Checks on evidence: whether a quote stands in the document a claim cites (ADR 06 §2).

A model quotes what it read; a quote that is not in the document makes its claim uncertain,
whatever else the model says. PDF text breaks words at line ends ("Wärme-" on one line, "netz"
on the next), so a word broken there is joined again before comparing.
"""

import re
import unicodedata

MIN_QUOTE_WORDS = 6
_LEVELLED = str.maketrans(
    {
        "\u200b": None,
        "\u200c": None,
        "\u200d": None,
        "\ufeff": None,
        "\u00ad": None,
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u00ab": '"',
        "\u00bb": '"',
        "\u2013": "-",
        "\u2014": "-",
    }
)
# A word broken at a line end: a letter, a hyphen, the line break, a lower-case letter. Not a
# hyphen that stands for a word left out ("Nah- und Fernwärme"), which a conjunction follows.
_BROKEN_WORD = re.compile(
    r"(?<=[^\W\d_])-[ \t]*\r?\n\s*(?=[a-zäöüß])(?!(?:und|oder|bzw|sowie|bis)\b)"
)


def fence(text: str) -> str:
    """No closing tag inside untrusted text can end its element early in a prompt."""
    return text.replace("</", "<\u200b/")


def _levelled(text: str) -> str:
    joined = _BROKEN_WORD.sub("", text)
    return " ".join(unicodedata.normalize("NFKC", joined).translate(_LEVELLED).casefold().split())


def found(quote: str, text: str, *, min_words: int = MIN_QUOTE_WORDS) -> bool:
    """Whether `quote` is copied from `text`, whatever its whitespace, case, quotes and dashes.

    A quote shorter than `min_words` words proves nothing: a word or two stand in almost any
    text ("Wärmenetz", "ab 2028"), so only a sentence or most of one counts. An empty quote never
    does.
    """
    wanted = _levelled(quote)
    return len(wanted.split()) >= max(min_words, 1) and wanted in _levelled(text)
