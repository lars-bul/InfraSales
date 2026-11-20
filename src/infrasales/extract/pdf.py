"""The PDF extractor: the text layer of every page, by pypdf.

pypdf: BSD-3-Clause, pure Python (no native code to build or patch), maintained by py-pdf with
monthly releases, and it bounds decompression (zip-bomb limits). A scanned PDF without a text
layer gives no text: OCR is out of scope.

A PDF is technical protection only when encrypted. One that opens without a password (an empty
user password) is read only if its permissions allow extracting text, as xpdf's `pdftotext`
does; one that needs a password is never read (§ 95a UrhG, ADR 03 §6).
"""

from importlib.metadata import version
from io import BytesIO

from pypdf import PasswordType, PdfReader
from pypdf.constants import UserAccessPermissions
from pypdf.errors import PyPdfError

from infrasales.core.text import stripped
from infrasales.extract.extractor import Extracted, ExtractionError

_RULES = 1  # raise when the rules below change what the same file gives
_PAGE_BREAK = "\n\n"


class PdfExtractor:
    name = "pdf"
    version = f"{_RULES}+pypdf-{version('pypdf')}"

    def extract(self, raw: bytes, url: str) -> Extracted:
        del url
        try:
            reader = PdfReader(BytesIO(raw))
            _check_permitted(reader)
            pages = [page.extract_text().strip() for page in reader.pages]
            title = reader.metadata.title if reader.metadata else None
            author = reader.metadata.author if reader.metadata else None
        except PyPdfError as error:
            msg = f"unreadable PDF ({type(error).__name__})"
            raise ExtractionError(msg) from error
        return Extracted(
            text=_PAGE_BREAK.join(page for page in pages if page),
            title=stripped(title),
            author=stripped(author),
        )


def _check_permitted(reader: PdfReader) -> None:
    if not reader.is_encrypted:
        return
    opened = reader.decrypt("")
    if opened == PasswordType.NOT_DECRYPTED:
        msg = "encrypted PDF"
        raise ExtractionError(msg)
    permissions = reader.user_access_permissions
    if (
        opened == PasswordType.USER_PASSWORD
        and permissions is not None
        and not permissions & UserAccessPermissions.EXTRACT
    ):
        msg = "PDF forbids text extraction"
        raise ExtractionError(msg)
