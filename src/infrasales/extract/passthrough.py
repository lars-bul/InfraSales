"""The passthrough extractor: a JSON or XML document is its own text, kept as it is.

Structured documents (API answers, XML notices) lose nothing worth losing to extraction, and
keeping them whole lets the next stage parse them itself. The bytes are only decoded: UTF-8 (JSON
must be, RFC 8259; XML is by default), unless a byte order mark or an XML declaration says else.
"""

import codecs
import re

from infrasales.extract.extractor import Extracted

_DECLARED = re.compile(rb"""\s*<\?xml[^>]*?\bencoding\s*=\s*["']([A-Za-z][\w.-]*)["']""")


class PassthroughExtractor:
    name = "passthrough"
    version = "1"

    def extract(self, raw: bytes, url: str) -> Extracted:
        del url
        return Extracted(text=raw.decode(_encoding(raw), errors="replace"))


def _encoding(raw: bytes) -> str:
    if raw.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    declared = _DECLARED.match(raw)
    if declared:
        try:
            return codecs.lookup(declared[1].decode()).name
        except LookupError:
            pass  # an encoding Python does not know: UTF-8, replacing what does not fit
    return "utf-8"
