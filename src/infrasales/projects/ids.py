"""Public project IDs: short, unambiguous to read aloud, and never given out twice (ADR 06 §2).

Random rather than counted, so an ID tells nobody how many projects there are. Crockford's
base 32 leaves out I, L, O and U; reading accepts them as 1, 1, 0 and V, and any case and
hyphens, so an ID typed from a phone call still finds its project.
"""

import re
import secrets

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_GROUP = 4
_LENGTH = 8  # 40 bits: a collision is refused by the unique key and a new ID drawn
_PREFIX = "P-"
_READ = str.maketrans({"I": "1", "L": "1", "O": "0", "U": "V", "-": None, " ": None})
_FORMAT = re.compile(rf"^[{_ALPHABET}]{{{_LENGTH}}}$")


def new_public_id() -> str:
    """A new random ID, such as `P-7K2M-9XQ4`."""
    code = "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))
    return _PREFIX + code[:_GROUP] + "-" + code[_GROUP:]


def parse_public_id(text: str) -> str | None:
    """The ID `text` names, written as `new_public_id` writes it; None if it names none."""
    written = "".join(text.split()).upper()
    if written.startswith(_PREFIX):  # with its prefix, the rest is the whole code
        written = written.removeprefix(_PREFIX)
    elif len(written.translate(_READ)) == _LENGTH + 1 and written.startswith("P"):
        written = written[1:]  # "P7K2M9XQ4": the prefix without its hyphen
    code = written.translate(_READ)
    if not _FORMAT.fullmatch(code):
        return None
    return _PREFIX + code[:_GROUP] + "-" + code[_GROUP:]
