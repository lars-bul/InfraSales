# Adding a site-specific extractor

Add one when the generic HTML extractor (trafilatura) reads a site badly. Signs of this are
missing text, or a menu, a banner or a "last updated" line in the text. A footer that changes
creates a new Source Version on every check. The work is one class, one URL pattern, and one
saved page with its expected output. This follows [ADR 03 §5](../adr/03_adr_scraper_sink.md).

Before you write code, check the Feed. If every document of one Feed needs the same extractor,
set the Feed's `extractor` instead of adding a URL pattern.

## 1. The class: `src/infrasales/extract/<site>.py`

```python
from infrasales.extract.extractor import Extracted, ExtractionError


class ExampleCloudExtractor:
    name = "beispielstadt"  # what a Feed may name, and what extracted.json records
    version = "1"  # raise it whenever the same page would give another output

    def extract(self, raw: bytes, url: str) -> Extracted:
        ...  # parse `raw` (bytes: let the parser detect the encoding)
        return Extracted(text=..., title=..., author=..., published_at=...)
```

- `extract` blocks and uses the CPU. The scrape job runs it in a thread, so do not do any network
  or file I/O in it.
- Raise `ExtractionError("reason")` for a page that you cannot read. The scrape job then skips
  that document, and its Feed goes on. The job also treats any other exception as a failure of
  that document only.
- `text` is what change detection compares. Leave out anything that changes without the content
  changing, such as dates of the page itself or counters.
- Raise `version` when the rules change. A re-check then tells an extractor upgrade apart from a
  content change.

## 2. The pattern: `src/infrasales/extract/registry.py`

Add the instance to `EXTRACTORS`. Then add `(re.compile(r"^https://rathaus\.beispielstadt\.de/bekanntmachungen"), "beispielstadt")`
to `URL_PATTERNS`. The first match wins. Put specific patterns before broad ones. The generic
extractor is the fallback, so it needs no pattern.

## 3. The test: `tests/extract/test_<site>.py`

1. Save the page as it was served (for example `curl -o`, or "Save page as… HTML only") to
   `tests/extract/pages/<site>.html`.
2. Write the expected `extracted.json` by hand to `tests/extract/pages/<site>.json`. Read the page
   and write down the text a reader of the project file would want. Do not copy the output of your extractor:
   then the test would only show that the code does what the code does.
3. Test the extractor on the saved page, and check that the pattern matches the site's URLs and no
   others:

```python
import json
from pathlib import Path

from infrasales.catalog.layout import extracted_json
from infrasales.extract import registry
from infrasales.extract.example_cloud import ExampleCloudExtractor

PAGES = Path(__file__).parent / "pages"


def test_the_saved_page_gives_the_expected_output() -> None:
    extractor = ExampleCloudExtractor()
    raw = (PAGES / "beispielstadt.html").read_bytes()

    extracted = extractor.extract(raw, "https://rathaus.beispielstadt.de/bekanntmachungen")

    assert json.loads(extracted_json(extractor, extracted)) == json.loads(
        (PAGES / "beispielstadt.json").read_text()
    )


def test_only_the_sites_urls_are_read_by_it() -> None:
    notes = registry.choose(None, "https://rathaus.beispielstadt.de/bekanntmachungen", "text/html")
    blog = registry.choose(None, "https://beispielstadt.de/aktuelles/stadtfest", "text/html")

    assert (notes.name, blog.name) == ("beispielstadt", "html")
```

`tests/jobs/test_scrape_extraction.py` runs a test-only extractor of this shape through the whole
scrape job (`NoticesExtractor`, with `tests/extract/pages/notices.html` and `.json`).

When the site changes its layout, save the new page next to the old one. Change the extractor so
that both pages pass, and raise its `version`.
