"""The PDF extractor alone; PDFs through the scrape job: tests/jobs/test_scrape_extraction.py."""

import pytest
from pypdf.constants import UserAccessPermissions

from infrasales.extract.extractor import ExtractionError
from infrasales.extract.pdf import PdfExtractor
from tests.scrape.support import pdf_document

URL = "https://behoerde.test/report.pdf"
NO_EXTRACT = UserAccessPermissions.all() & ~UserAccessPermissions.EXTRACT


def test_a_pdf_that_opens_without_a_password_and_allows_extraction_is_read() -> None:
    raw = pdf_document("Final report.", user_password="", permissions=UserAccessPermissions.all())

    assert PdfExtractor().extract(raw, URL).text == "Final report."


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (pdf_document("Secret.", user_password="pw"), "encrypted PDF"),
        (
            pdf_document("No copying.", user_password="", permissions=NO_EXTRACT),
            "PDF forbids text extraction",
        ),
        (b"%PDF-1.7\nnot a PDF", "unreadable PDF (PdfStreamError)"),
    ],
)
def test_protected_and_broken_pdfs_are_not_read(raw: bytes, reason: str) -> None:
    """Never around technical protection (§ 95a UrhG): a password, or a ban on extraction."""
    with pytest.raises(ExtractionError) as raised:
        PdfExtractor().extract(raw, URL)

    assert raised.value.reason == reason


def test_pages_without_text_are_left_out_and_metadata_is_optional() -> None:
    extracted = PdfExtractor().extract(pdf_document("First.", " ", "Third."), URL)

    assert (extracted.text, extracted.title, extracted.author) == ("First.\n\nThird.", None, None)
