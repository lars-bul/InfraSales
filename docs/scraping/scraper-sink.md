# Research: a data sink for scraped Sources

*Research run on 2026-10-16 for [ADR 03](../adr/03_adr_scraper_sink.md). Nine agents: one researcher per question (Q3–Q6), each followed by an adversarial fact-check against primary sources (code, docs, specs), then a synthesis. ADR 03 decides differently from this report in three places: fsspec behind a small interface instead of an own `BlobStore` with stdlib writes (Q5); the next stage reads the catalog, not run manifests (no `_runs/` folder); folders are named by the run's scheduled time, not by date alone.*


Scope: how the scrape stage stores Sources, indexes them, abstracts storage, and picks a scraper per Feed or URL. Every claim below was checked against primary sources (code, docs, specs) by an adversarial fact-check. Claims that check found wrong are corrected here. Claims nobody verified are marked *(unverified)*.

## Reference architectures

| Project | Link | What we take from it |
|---|---|---|
| Media Cloud story-indexer / metadata-lib | [metadata.md](https://github.com/mediacloud/story-indexer/blob/main/doc/metadata.md), [content.py](https://github.com/mediacloud/metadata-lib/blob/main/mcmetadata/content.py) | The closest analogue to us (feeds → stories → research corpus). Metadata grouped as discovery / http / content. A chain of generic extractors that records `extraction_method`. Feed values override HTML guesses (`overrides=`). |
| Media Cloud backend (archived 2023) | [store.py](https://github.com/mediacloud/backend/blob/master/apps/common/src/python/mediawords/dbi/downloads/store.py) | A Postgres `downloads` table with `state` and `path`. Raw bytes sit in a store that config can switch between Postgres and S3. |
| news-please (archived on GitHub) | [repo](https://github.com/fhamborg/news-please), [pipelines.py](https://github.com/fhamborg/news-please/blob/master/newsplease/pipeline/pipelines.py) | Raw HTML plus a JSON sidecar, partitioned by date and domain. A DB version chain for one URL (`CurrentVersions`/`ArchiveVersions`, ancestor/descendant). Re-parsing via `from_html`. Use as a pattern only, not a dependency. |
| changedetection.io | [Watch.py](https://github.com/dgtlmoon/changedetection.io/blob/master/changedetectionio/model/Watch.py) | Pages that change under one URL: hash the processed text, store a new snapshot only on change, write atomically (temp file, fsync, `os.replace`), prune old versions. Processor and fetcher are chosen per watch. |
| Scrapy | [media-pipeline](https://docs.scrapy.org/en/latest/topics/media-pipeline.html), [files.py](https://github.com/scrapy/scrapy/blob/master/scrapy/pipelines/files.py) | A storage protocol with two methods, one class per URI scheme (`file`/`s3`/`gs`/`ftp`). Its local store is **not** atomic (`write_bytes`), which we should avoid. Routing rules are first match wins. |
| Crawlee for Python | [storage clients](https://crawlee.dev/python/docs/guides/storage-clients), [router.py](https://github.com/apify/crawlee-python/blob/master/src/crawlee/router.py) | A swappable storage backend and atomic temp+replace writes. Its file-system client is documented as "not safe for concurrent access from multiple crawler processes". URL normalisation rules. Label routing with a default handler. |
| Fundus | [how_to_add_a_publisher](https://github.com/flairNLP/fundus/blob/master/docs/how_to_add_a_publisher.md), [base_parser.py](https://github.com/flairNLP/fundus/blob/master/src/fundus/parser/base_parser.py) | Listing types per publisher (RSS/Sitemap/NewsMap). Parsers versioned by crawl date (`VALID_UNTIL`). JSON-LD first. Test fixtures `html.gz` + expected `.json`. A daily live coverage CI job. |
| yt-dlp | [extractors.py](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/extractors.py) | An ordered extractor list where the first `_VALID_URL` match wins and the generic extractor comes **last** as fallback. A `_WORKING` flag. About 1,750 extractor classes. |
| WARC 1.1 / Common Crawl | [spec](https://iipc.github.io/warc-specifications/specifications/warc-format/warc-1.1/), [CC](https://commoncrawl.org/get-started) | Field semantics to copy: target URI, capture date, payload digest, "revisit" for identical content. Raw stays immutable and derivatives can be rebuilt. A small index row per capture. |
| Hadoop S3A committers | [committers](https://hadoop.apache.org/docs/stable/hadoop-aws/tools/hadoop-aws/committers.html) | Rename on S3 is "unsafe as well as horribly slow". Write the payload first and a completion marker last. |

---

## Q3: What goes into one Source

| Option | Trade-offs | Used by |
|---|---|---|
| A. Extracted text only (current draft) | Simplest. No re-extraction is possible, PDF/JSON/XML structure is lost, and an extractor upgrade looks like a content change. | newspaper-style library use |
| **B. One folder per Source: raw file + metadata.json + derived extracted.json** | Readable and greppable. Deleting one Source is `rm -r`. Re-extraction is a loop over raw files. Maps 1:1 to S3 keys. We must define our own metadata schema. No replay tooling. | news-please, [ArchiveBox](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#disk-layout), changedetection.io, Scrapy HTTP cache, Crawlee KVS |
| C. WARC (.warc.gz) as raw store | ISO standard, full HTTP fidelity, revisit records. Deleting one Source means rewriting the file (bad for deletion on request). Not browsable by hand. httpx decodes gzip by default, so you need `iter_raw()` ([httpx](https://www.python-httpx.org/quickstart/)). Media Cloud's own writer [documents the friction](https://github.com/mediacloud/story-indexer/blob/main/indexer/story_archive_writer.py) and rejected WACZ as "more complex". | Common Crawl, Internet Archive, Media Cloud archiver |
| D. WACZ | Everything from C plus zip packaging. Even harder to delete. | Browsertrix, scrapy-webarchive |

**Recommendation: B.** WARC can come later as an optional export via [warcio](https://github.com/webrecorder/warcio).
Reasons:
- Every mature news tool keeps the raw bytes and treats extracted text as derived. news-please stores the original HTML "in the default configuration" and can re-parse it.
- A copy may have to be deleted on its own: on request, or once a retention period is set (ADR 06 §7, §8). One folder per Source makes each copy deletable on its own.
- WARC solves replay and preservation at scales we do not have.

Corrections from the fact-check:
- Media Cloud's `arch-queuer` only re-imports metadata it already extracted. It does **not** re-parse raw HTML ([metadata.md, "archive"](https://github.com/mediacloud/story-indexer/blob/main/doc/metadata.md)). The precedents for re-extraction are news-please and Fundus.
- A date-first layout does **not** give version history "for free". The versions of one URL land in different date folders, so "previous capture" has to come from the catalog (Q4).
- Before comparing hashes, try a conditional GET (`If-None-Match` / `If-Modified-Since` with the stored ETag and Last-Modified). It saves bandwidth and is polite. Scrapy's `RFC2616Policy` does this ([docs](https://docs.scrapy.org/en/latest/topics/downloader-middleware.html)).
- Store `resp.content` (encoding-decoded bytes), never `resp.text`. Record the declared and the detected charset.
- trafilatura handles HTML only. PDFs need their own extractor (e.g. pypdf or pdfminer.six), recorded with its own name and version.
- BagIt ([RFC 8493](https://www.rfc-editor.org/rfc/rfc8493)) is the archival standard for "folder + checksum manifest". It is worth citing for B *(not inspected in this research)*.

## Q4: Filesystem-only contract vs files + DB catalog

| Option | Trade-offs | Used by |
|---|---|---|
| A. Filesystem only (scan partitions, `_SUCCESS` markers) | No schema, fully inspectable. Cross-run dedupe needs scans or hand-made index files. Several writers are unsafe. Rename-based completeness breaks on S3. | Crawlee FS client (single process), Scrapy JOBDIR, changedetection `history.txt` |
| **B. Files as payload + Postgres catalog** | Dedupe, versioning and retention become SQL. Reuses Postgres, Alembic and the scheduler. Two stores have to be reconciled. | Media Cloud backend, news-please SQL storage, Common Crawl (WARC + [CDX index](https://commoncrawl.org/blog/announcing-the-common-crawl-index)) |
| C. Everything in Postgres | One transactional store. Contradicts the decision for a file sink with a path to S3. Raw/PDF bloat in the DB. | Current draft, Media Cloud dev config |
| D. Files + file-based manifests / Delta-style log | No DB, S3-native. Dedupe needs every earlier manifest. Deleting means rewriting manifests. A commit protocol is too much for us. | Common Crawl Parquet index, Delta Lake |

**Recommendation: B, used as the scraper's own index.** The sink stays self-describing, so the catalog can be rebuilt from `metadata.json`.
Changes made by the fact-check:
- **Drop `UNIQUE(url_hash, content_hash)`.** It breaks when a page reverts (A → B → A): the third capture collides with the first and the B→A change is lost. Compare each fetch with the **latest** version for that URL. Put the constraint on `(url_hash, version_no)`.
- **Use Media Cloud's state column, not tmp-dir + rename + orphan hunting.** INSERT the row as `writing`, write the files, then UPDATE it to `committed`. Reconcile becomes one query: "rows stuck in `writing` older than N hours". This works the same way on S3.
- Deletion order: tombstone the row (`deleted_at`) first, then delete the files. changedetection.io does the reverse, so it is not a reference here.
- `SKIP LOCKED` gives "an inconsistent view of the data" ([Postgres docs](https://www.postgresql.org/docs/current/sql-select.html)). Use it only for claiming queue rows.
- news-please and Media Cloud backend are both archived. Cite them as patterns, not dependencies.

## Q5: Local filesystem now, S3 later, shared Docker volume

| Option | Trade-offs | Used by |
|---|---|---|
| **A. Own small `BlobStore` Protocol + stdlib/anyio local implementation; S3 implementation later** | No new dependencies. We control atomicity and fsync. About 60–100 lines plus tests to own. | Scrapy `FilesStoreProtocol`, Crawlee `StorageClient` |
| B. [obstore](https://developmentseed.org/obstore/latest/) for local and S3 | Native async. Atomic local writes. `mode='create'` maps to S3 `If-None-Match`. Pre-1.0 (0.12.0), so pin it. Python `LocalStore` has **no fsync option** ([source](https://github.com/developmentseed/obstore/blob/main/pyo3-object_store/src/local.rs)), so writes are atomic but not crash-durable. | arrow-rs object_store users (DataFusion, Polars) |
| C. fsspec + s3fs | Most widely adopted. Local writes are not atomic. Transactions stage in system `/tmp` and then `shutil.move` ([local.py](https://github.com/fsspec/filesystem_spec/blob/master/fsspec/implementations/local.py)). Async is awkward. | pandas, dask, HF datasets |
| D. Framework storage (Scrapy / Crawlee) | Battle-tested, but couples the sink contract to a crawler. Crawlee's FS client is single-process only. | Scrapy and Crawlee users |

**Recommendation: A, with obstore behind the same Protocol when S3 arrives.** The Protocol is the contract. Rules that hold on both POSIX and S3:
1. Keys are `/`-separated strings, never `Path`. Config holds one `SINK_URI` (`file:///data/sink` or `s3://bucket/prefix`).
2. Write-once. No rename, append or in-place edits. S3 has no rename ([docs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/copy-object.html)).
3. Local atomic write: temp file in the **same** directory, fsync, then `os.link` (create-only) or `os.replace`. `rename` fails with EXDEV across mount points ([rename(2)](https://man7.org/linux/man-pages/man2/rename.2.html)).
4. Retries vs create-only: each fetch attempt gets a fresh `source_id` (ULID), so a retry never collides. A janitor removes folders without a marker.
5. One named `local` volume on the VM. It is rw in the scraper and `:ro` in consumers ([Docker volumes](https://docs.docker.com/engine/storage/volumes/)). Create `/data/sink` as owned by UID 10001 with mode 0750.
6. S3 server choice: the MinIO repo is archived ("no longer maintained", [primary source](https://github.com/minio/minio)). SeaweedFS handles `If-None-Match: *`. **Garage shows no evidence of conditional PUT** ([compat page](https://garagehq.deuxfleurs.fr/documentation/reference-manual/s3-compatibility/)) and has no versioning, so do not default to it. Add a startup probe: a second create-only put must fail.
7. Turn bucket versioning off, or add a lifecycle rule. Otherwise a delete only adds a delete marker.

## Q6: Choosing the scraper for a Feed or URL

All mature projects split this into **listing** (Feed → URLs) and **extraction** (document → fields).

| Option | Trade-offs | Used by |
|---|---|---|
| A. Feed-bound: an explicit `kind` per Feed (rss / sitemap / html_listing / api:x) | Explicit and debuggable. Adding a Feed is a config change. Does not cover URLs found outside a Feed. | Fundus, news-please `crawler`, [changedetection processors](https://github.com/dgtlmoon/changedetection.io/blob/master/changedetectionio/processors/__init__.py) |
| B. URL-pattern registry, first match wins, generic last | Chooses by URL, as planned. Proven at scale. A broad pattern can shadow a specific one. | yt-dlp, [Scrapy rules](https://docs.scrapy.org/en/latest/topics/spiders.html), [web-poet](https://web-poet.readthedocs.io/en/stable/page-objects/rules.html) |
| C. Generic-only chain + quality gate | Least code. Weak on council information systems, authority pages and PDFs. | Media Cloud, news-please, trafilatura |
| D. Field-level override (a subclass of the generic extractor fixes only broken fields) | Site code stays tiny. Needs a clear field contract. | [zyte-spider-templates](https://github.com/zytedata/zyte-spider-templates/blob/main/docs/customization/pages.rst), Fundus JSON-LD-first |

**Recommendation: start with A + C. Add B + D only when the first site actually needs it.**
- Listing: a dict `{kind: Lister}`. Before writing HTML code for a new Feed, look for a structured feed or API first (GitHub `releases.atom`, EUR-Lex, vendor RSS).
- Extraction dispatch is by **Content-Type as well as URL**, from day one: HTML → trafilatura, PDF → PDF extractor, JSON/XML → passthrough.
- When B is added: a plain ordered list, first match wins, generic last (yt-dlp style), plus a unit test that maps known URLs to their expected extractor. web-poet only warns on *identical* patterns, not on overlaps, so this test is our own work.
- Quality gate: require a title and a minimum amount of text. Media Cloud's 200-character gate is weak, because its last fallbacks dump raw HTML text and almost always pass.
- Use date-versioned parsers (Fundus) only when a hand-written parser breaks.
- Do not use pluggy or entry points. Do not adopt Scrapy or Crawlee just for dispatch.
- Listing libraries to consider *(noted by the fact-check, not deeply verified)*: feedparser; ultimate-sitemap-parser (GPL-3.0, check the licence before handover); htmldate for dates.

---

## How the pieces fit

**Sink layout** (consumers read this):
```
/data/sink/
  2026-10-16/
    stadtwerke-press/
      01JA…ULID/
        raw.html            # resp.content, decoded transfer encoding
        rendered.html       # only if Playwright was used
        extracted.json      # derived, tagged with extractor+version
        metadata.json       # written LAST = Source is complete
    _runs/<run_id>/manifest.jsonl + _SUCCESS   # written last per run
```

**metadata.json:** `schema_version`, `source_id`, `run_id`, and these groups:
- `discovery`: feed_id, feed_url, listing kind, entry title, published and summary as the feed gave them.
- `fetch`: requested_url, final_url, redirects, status, whitelisted headers (content-type, etag, last-modified, content-encoding, content-language; no Set-Cookie), fetched_at in UTC, fetcher and version, user_agent, robots decision.
- `content`: media_type declared and sniffed, charset, size_bytes, raw_sha256, text_sha256.
- `extraction`: extractor, extractor_version, library version (e.g. trafilatura).
- `versioning`: url_normalized, version_no, previous_source_id.

**Catalog table `source`** (scraper's index):
- Columns: `id`, `feed_id`, `run_id`, `url`, `url_normalized`, `url_hash`, `version_no`, `previous_id`, `fetched_at`, `last_checked_at`, `http_status`, `media_type`, `etag`, `last_modified`, `raw_sha256`, `text_sha256`, `extractor_version`, `storage_key` (relative path), `state` (writing | committed | deleted), `retain_until`, `deleted_at`.
- Constraint: `UNIQUE(url_hash, version_no)`.
- An unchanged fetch (304, or the same `text_sha256` as the latest version with the same extractor version) only updates `last_checked_at`.

**Storage interface:**
```python
class BlobStore(Protocol):
    async def put(self, key: str, data: bytes, *, create_only: bool = True) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def exists(self, key: str) -> bool: ...
    def list(self, prefix: str) -> AsyncIterator[str]: ...
    async def delete_prefix(self, prefix: str) -> int: ...
```

**Dispatch:**
1. `Feed.kind` → Lister yields `DiscoveredItem(url, feed hints)`.
2. Fetch (httpx or Playwright, chosen per Feed; SSRF guard, robots and rate limit sit centrally).
3. Pick the extractor in this order: per-Feed override, then Content-Type, then ordered URL patterns, then generic.
4. Write the files, then `metadata.json`, then set the row to `committed`.

## Open questions / risks

1. **Who is the consumer contract: sink or DB?** You said the sink is the scrape stage's only contract. Q4 makes Postgres the downstream index. Proposal: consumers read run manifests + `metadata.json`, and the catalog is internal to the scraper. Decide this explicitly.
2. **Layout:** date-first scatters the versions of one URL, and a URL found by two Feeds gets two folders. Accept this (the catalog links versions), or key folders by `url_key/<fetched_at>`?
3. **Change signal:** which hash defines a new version? Extracted-text hashes depend on the extractor version, and raw hashes churn on ads and timestamps. Compare only like with like, and re-hash after upgrades.
4. **Retention**, once a period is set, has to reach every copy: sink folders, extracted text, catalog rows, the claims citing them and backups or snapshots. Re-extraction is only possible inside the retention window. Someone must own the retention period.
5. **Header whitelist and privacy:** agree on it up front.
6. **Size caps** for PDFs and large JSON, and a truncation flag in metadata.
7. **Rendered vs raw:** when Playwright is used, record which file the extraction ran on.
8. **Docker permissions:** check on the VM that UID 10001 can write a fresh named volume. Watch SELinux `:z` labels and rootless/userns setups. If the system ever spans several hosts, prefer S3 over NFS.
9. **S3 target:** confirm conditional-PUT support on whatever server we use. Pick a CI emulator (moto, LocalStack, or SeaweedFS; MinIO is unmaintained).
10. **Generic extraction quality** on council information systems and authority pages is unknown until the real Feed list is tested. Run a scheduled live smoke job that flags Feeds with 0 items or failed quality gates.
