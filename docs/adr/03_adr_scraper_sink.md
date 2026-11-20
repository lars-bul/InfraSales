# ADR 03: Collecting Sources into a file sink with a catalog

Status: **Accepted**. Amended by [ADR 06](06_adr_infrasales.md): the stage after collecting is the
project file's pipeline, and Source Versions are kept for good unless a period is set.

This ADR decides how InfraSales collects Sources from its Feeds and hands them to the next stage
of the pipeline. Terms (Feed, Source, Source Version) are defined in [CONTEXT.md](../../CONTEXT.md). The
facts behind the decisions are in the [research report](../scraping/scraper-sink.md).

## Context

The pipeline has two stages that we want to keep apart:

1. **Collect:** read the Feeds, fetch new documents and store each one as a Source.
2. **Read:** turn Source Versions into projects, claims and status events (ADR 06 §5). This
   stage must not depend on how the first one works inside.

The first stage collects from any number of Feeds, lets admins add more, and stores what it
collects for good. It collects lawfully and politely (ADR 06 §8).

What we know:

- **Where it runs.** A VM with PostgreSQL, but no object storage. Possibly several containers.
  S3-compatible storage may come later.
- **Feeds forget fast.** On 2026-10-16 the Tiefbau Aktuell feed held 20 items, about one day of news;
  the Heizwerk Journal held 10 items, about two days. A weekly scrape would miss most articles.
- **Some outlets block bots.** One trade feed answered our user agent with `429` and a
  "Vercel Security Checkpoint" page. Some trade journals are paywalled.
- **Pages change under the same address.** Plans, council documents and project pages are
  edited in place. For the project file the change itself is evidence: a heat plan revised after
  a council decision, a project page that names a new contractor.

## Decision

### 1. One contract between the stages: a file sink plus a catalog

The collect stage writes each Source Version as **files in a sink** and records it in **catalog
tables** in PostgreSQL. The next stage asks the catalog which Source Versions are new and
complete, then reads their files. These two things are the whole contract: the folder format and
the `source` and `source_version` tables. Everything else in the collect stage can change without the next stage
noticing.

As built: the catalog lists the committed versions after a cursor, the ID of the last version the
next stage read, oldest first and a page at a time (`infrasales.catalog.versions.committed_after`).
IDs are UUIDv7 and one scrape attempt at a time makes and commits its versions one after another
(section 3), so no version commits behind the cursor. Replaced versions are listed too.

The files hold the content; the catalog answers questions: what do we have, is it complete, which
version is the newest, when must it be deleted. Without the catalog these answers need folder
scans, and de-duplication across runs needs index files of our own. Media Cloud, the closest
project to ours, works the same way: a table with a state and a path, raw content in a store that
can be the database or S3 ([research, Q4](../scraping/scraper-sink.md#q4-filesystem-only-contract-vs-files--db-catalog)).

### 2. One folder per Source Version

```
<sink>/
  2026-10-16T060000Z/            the run's scheduled time (UTC); all retries of a run share it
    tiefbau-aktuell/                  the Feed
      0199f0c2-…/                the Source Version (UUIDv7, like every ID in InfraSales)
        raw.html                 the bytes as fetched (raw.pdf, raw.json, …)
        extracted.json           text, title, author, dates; names the extractor and its version
        metadata.json            written last
```

- **Raw is kept, text is derived.** Every mature news tool does this. When the extractor
  improves, we re-extract from `raw` instead of fetching again.
- **`metadata.json`** repeats the catalog rows, so the sink describes itself and the catalog
  could be rebuilt from it. Its groups: *discovery* (Feed, kind, what the Feed said: title, date,
  summary), *fetch* (requested and final URL, status, selected headers, time, robots decision),
  *content* (media type, charset, size, hashes of raw and text), *extraction* (extractor and
  version) and *identity* (Source ID, Source Version ID, normalised URL). It holds no version
  number: that is given only at commit (section 3); a rebuild orders the versions of a Source by
  fetch time.
- **A run folder uses the run's scheduled time,** not the time of writing. A "run now" uses the
  time it was requested. Two runs on one day get two folders; a retry of a run reuses its folder.
- **A URL listed by two Feeds** is fetched once and filed under the first.

### 3. The catalog: Sources and their versions

Two tables, so that "the page at this address" and "what it said at one time" stay apart:

| Table | One row per | Holds |
|---|---|---|
| `source` | address (normalised URL) | the URL and its hash (unique), the Feed that first listed it, first seen, last checked, `ETag` and `Last-Modified` of the last fetch, `latest_version_id` |
| `source_version` | text of a Source at one time | the Source, `version_no`, run, Feed, fetch time, HTTP status, media type, hashes of raw and text, extractor version, the folder (`storage_key`), `partial`, `state`, `superseded_at`, `retain_until` |

`(source_id, version_no)` is unique. Claims refer to a `source_version`, so they show what a
page said when it was read. A version has no link to the
one before it: `version_no` gives the order, and a second encoding could only drift from it.

Details (as built, `infrasales/feeds/models.py`, `infrasales/catalog/models.py`):
`source_version.run_id` may be NULL and is set NULL when its job run is pruned: runs are kept
90 days, versions far longer; a run outside the scheduler (a notebook) has none. `http_status`
is NULL, and `metadata.json` has `"fetch": null`, when the Feed itself carried the content (API
items).

**Writing a Source Version** works the same on a disk and on S3:

1. insert the version with state `writing` and no `version_no` yet;
2. write the files, `metadata.json` last;
3. commit, in one transaction: give it `version_no` = the latest committed number + 1, set its
   state to `committed`, set `superseded_at` on the version it replaces, and point
   `source.latest_version_id` to it.

Numbers are given only in step 3, so a crash leaves no gap and the order cannot fork. Commits of
one Source take turns: step 3 first locks the Source's row (`SELECT … FOR UPDATE` on PostgreSQL;
SQLite has one writer at a time), so a second writer numbers after the first instead of failing.
The unique constraint still stops a duplicate number if anything skipped the lock: that
transaction fails and changes nothing. `latest_version_id` makes "the newest version" a plain
lookup. It is changed only in that transaction, it is a foreign key with `ON DELETE SET NULL`,
and a test checks that it always names the highest committed version.

The stages after it read only `committed` versions. A crash leaves a version in `writing`. The
scheduler runs at most one attempt of the scrape job at a time (`uq_job_run_running`), so every
`writing` version found when an attempt starts is left over from a crash: the attempt deletes
those rows and their folders before it begins. If another job ever writes versions, this rule
must change. The sweep marks them `deleted` in one statement, only while still `writing`, then
deletes each folder and row; it also completes deletions a crash interrupted (`deleted` rows).
A worker that froze past its lease and commits later finds its version gone: it discards its
work and deletes its own folder (it may have written files after the sweep). Each attempt
writes into fresh folders and the sink refuses to overwrite a file, so a retry never changes a
stored file.

**A known URL is checked like this:**

1. Ask the server with `If-None-Match` / `If-Modified-Since`, using the values stored on the
   Source. `304 Not Modified`: only the Source's `last_checked_at` changes.
2. Otherwise extract the text and compare its hash with the latest committed version. If the
   extractor version changed in between, re-extract that version's raw file first, so that like
   is compared with like.
3. Same text: only the Source's `last_checked_at` (and its `ETag`/`Last-Modified`) changes.
   Different text: a new Source Version.

We compare text, not raw HTML, so changed ads or timestamps do not create versions. We compare
with the newest version, not with all versions, so a page that changes back (A → B → A) still
records both changes.

As built: a known URL is checked only when it is **due**, because a Feed lists up to 300 URLs
per run (a sitemap holds a month of them) and checking all of them every 3 hours would put
needless load on the sites. Like a cache's heuristic freshness ([RFC 9111 §4.2.2](https://www.rfc-editor.org/rfc/rfc9111#section-4.2.2)),
a Source is due once a tenth of the time its text has stayed the same has passed (from its
latest version's fetch to its last check), at least once a week, with an hour of slack for the
run's timing. A fresh article is checked on every run; a page unchanged for a month, every three
days. The weekly minimum keeps a listed page's current version far from its retention limit.
The cost: a change is seen only at the next due check, so the new version's fetch time (the
date InfraSales has for the change) can be late by up to the re-check interval: up to three
days for a page unchanged for a month, up to a week for one unchanged for longer. A status event
that needs the day of a change must allow for that, or take the date from the page itself.
If the latest version cannot be compared with (it is being deleted, or the extractor cannot
read its raw file any more), the text got now becomes the next version.

**Deleting** goes the other way: mark the version `deleted`, delete its folder, then its row. A
Source without versions is deleted too.

### 4. Storage: fsspec behind a small interface

The sink is reached through an interface of our own with four operations: write a file, read a
file, list a folder, delete a folder. Behind it sits [fsspec](https://filesystem-spec.readthedocs.io/).
One setting chooses the backend:

```
SINK__URI=file:///data/sink         # today: a Docker volume
SINK__URI=s3://infrasales-sink/sources   # later: install s3fs, change the setting
```

fsspec also offers `memory://`, which the tests use. Its local backend is synchronous, so we call
it through `asyncio.to_thread`. Only the interface uses fsspec; the rest of the code never sees
its large API.

**Why atomic writes do not matter here.** A crash in the middle of a write leaves a half-written
file. That would be dangerous if a later stage read folders directly. None does: they read
only Sources whose row is `committed`, and the row is committed after all files are written
(section 3). So the safety comes from the catalog, and fsspec's non-atomic local writes are
acceptable.

**Rules that keep the switch to S3 painless:** keys are `/`-separated strings, never local
paths; files are written once and never renamed, appended to or edited (S3 cannot rename); a
Source Version is deleted as a whole folder.

**The shared volume.** One named Docker volume, mounted read-write into the application and
read-only into consumers. This weakens scaling out (adding
instances): instances on *several machines* need S3 or a network file system. On one VM that is
no limit. If InfraSales ever spans several hosts, we switch to S3 rather than NFS.

S3 notes for later: the MinIO repository is archived, so we do not default to it; whichever
server we use, turn bucket versioning off or add a lifecycle rule, otherwise a delete
only hides the object.

### 5. Choosing the code for a Feed and a document

All mature projects split this into two jobs ([research, Q6](../scraping/scraper-sink.md#q6-choosing-the-scraper-for-a-feed-or-url)).

**Listing (Feed → new items)** is chosen by the Feed's `kind`, stored on the Feed. The address
alone does not tell an RSS feed from a sitemap or an API.

| kind | Lister | First Feeds |
|---|---|---|
| `rss` | reads an RSS or Atom feed | trade press, the news of utilities and municipalities |
| `sitemap` | reads the newest entries of a sitemap | sites without a feed |

Listers for council information systems, procurement data (OCDS) and registers follow
(ADR 06 §5).

**Extraction (document → text)** is chosen in this order, first match wins:

1. an extractor named on the Feed;
2. an ordered list of URL patterns (empty at the start; yt-dlp works this way with about 1,750
   entries and a generic extractor last);
3. by content type: HTML → trafilatura, PDF → a PDF extractor, JSON → kept as it is.

As built: the PDF extractor is pypdf (BSD licence, pure Python, actively maintained, with limits
against decompression bombs). JSON and XML, including `+json`/`+xml` types such as Atom, go to
a `passthrough` extractor that only decodes the bytes. An encrypted PDF that needs a password, or
that forbids copying text, is not read (§6). A document that no extractor can read (a broken file,
an extractor bug) is skipped and counted as failed. Its Feed goes on, and because nothing was
stored, the document is tried again in the next run.

Between the two jobs, **one fetcher** handles everything that must never be skipped: no private
networks, a size cap, `robots.txt`, a pause between requests, conditional requests. "No private
networks" holds for the connection, not just the check: a host is looked up once per
connection, every address must be public (IPv4 inside IPv6 forms, such as NAT64's
`64:ff9b::/96`, checked as IPv4), and the connection goes to the address checked, so a name
cannot answer "public" for the check and an internal address for the connection (DNS
rebinding). TLS still verifies the certificate for the host name.

What adding something costs:

| To add | Work |
|---|---|
| A news site with a feed | One Feed, no code |
| A site the generic extractor reads badly | One extractor class, one URL pattern, one saved page with its expected result as a test ([how](../scraping/extractors.md)) |
| A new API | One Lister class, one entry in the list of kinds |

### 6. Polite fetching, with a way forward

The fetcher obeys `robots.txt` and never gets around a bot wall, paywall or other technical
protection (§ 95a UrhG). A blocked Feed is marked failing with the
reason "blocked" and raises the usual alert; nobody works around it in code.

Paywalled Feeds keep only what the Feed itself gives (title, summary, link, date). Such Source
Versions are marked `partial`.

Browser rendering (Playwright) is not used in the first release. It is not an automatic
fallback for short texts, because a short text is often a paywall or a consent wall.

To leave a path open for later, the fetcher is chosen per Feed, like the Lister. Today there is
one: `http`. If we arrange access (a licence, an allowed user agent, an API key) or a site
needs JavaScript, a new fetcher is added and set on that Feed only. Choosing a fetcher other than
`http` is an admin change that is audited, and it needs the legal question answered first.

**As built.** The rules live in `infrasales/fetch/` and are hooked into the scrape's HTTP
client, so every request and every redirect hop obeys them:

- *robots.txt* (RFC 9309), read with Scrapy's parser Protego (wildcards, `Crawl-delay`) once a
  day per host: kept across runs for 24 hours, the longest RFC 9309 §2.4 allows (an unreachable
  one for the run only). `2xx`: its rules (the first 500 KiB); other `4xx`: none, all allowed;
  `429`, `5xx`, no answer or an unsafe redirect: nothing allowed. A disallowed document is
  skipped; a disallowed Feed fails with "disallowed by robots.txt". `metadata.json` records the
  decision (`allowed`, `allowed: no robots.txt`).
- *Pause*: 3 s between requests to one host (Heritrix's minimum), or the `Crawl-delay` if longer,
  counted from the end of the previous request. Hosts do not wait for each other.
- *Time budget* (job timeout vs. pauses): the scrape has a timeout of its own
  (`SCHEDULER__SCRAPE_TIMEOUT_SECONDS`, 45 min, below the 3 h between runs), as its pauses make
  it the longest job; a run spends at most 2/3 of it on requests; each Feed gets what is left
  divided by the Feeds left, so one slow site cannot starve the others. A Feed whose share runs
  out stops without failing; its unread documents are still unknown, so the next run reads them.
  The run's result lists such Feeds with how many documents wait (`out_of_time`).
- *Bot walls*: a challenge on any request, robots.txt and every document included (Cloudflare,
  Vercel, AWS WAF headers, or an error page naming a wall such as Vercel's `429` "Vercel
  Security Checkpoint"), or a redirect to a wall's access page that answers `200`
  (www.foerderregister.test sends bots to zugang.foerderregister.test "Request Access"; hosts
  `unblock.`/`captcha.`, DataDome, Cloudflare's challenge path); or a block answer (`401`,
  `403`, `451`) to the Feed's own listing requests (its feed, sitemap or API). A block answer
  for one document is that document's failure only (a members-only page, an article withheld in
  one country): it is skipped like a `404`, the Feed goes on, and nobody is alerted. A `4xx`
  for robots.txt itself means "no robots.txt" (RFC 9309), not a wall. A plain
  `429`/`503` is a busy site, not a wall. A wall belongs to the site that was asked (a redirect
  to DataDome is the asking site's), and a site is a host with its subdomains
  (`feeds.heizwerk.test` and `heizwerk.test` are one). A wall on another site than the
  Feed's own (a press release linking to a portal elsewhere) is that document's failure: the
  run asks that site for nothing more, the Feed goes on, and its outcome in the run's result
  names the site (`walled`); nobody is alerted. A wall on the Feed's own
  site blocks the Feed, even when another Feed met it first. The Feed stops at the first such
  wall, is marked `blocked` (state `blocked`, last error "blocked"), and admins get one alert
  through the jobs' alert
  channels when it *becomes* blocked, not on every run. The state `blocked` is recorded only
  after the alert was handed to the channels (or no channel is configured): if that fails, the
  Feed stays `failing` with the reason "blocked", and the next run alerts again.
- *One Feed failing* is recorded and the others go on; the run fails (retries, alerts) only when
  every Feed it read failed. That failing run is how admins hear that the scrape job keeps
  failing: the scheduler's alerts say it keeps failing, then that it failed for good (ADR 01,
  Alerting). A single Feed failing run after run raises no alert; its state and last error show
  in `GET /api/feeds`.
- *Quality gate*: a text is complete with a title (its own, else the Feed's: the Federal
  Register's PDFs name none) and at least 250 characters (trafilatura's own minimum), unless the page marks itself paywalled (`isAccessibleForFree: false` in its JSON-LD,
  as Google asks publishers to). Otherwise the version is `partial`: title, date and author from
  the Feed, and the Feed's summary as its text. Without a summary the short text is kept, so a
  short page still shows when it changes. A scanned PDF without text is `partial` too.

### 7. Schedule

The scrape job runs **every 3 hours** by default; the Weekly Digest stays weekly. Both are
schedules that admins change in the interface. A run is cheap: one
request per Feed plus the documents not seen yet. A schedule can repeat every 1, 2, 3, 4, 6, 8 or
12 hours from its time until midnight (like systemd's `00/3`); the scrape default is every 3 hours
from 00:00 Europe/Berlin. A data migration moves a scrape schedule nobody edited to it.

### 8. Retention

A Source Version is deleted `RETENTION__SOURCE_DAYS` (default 365) after it **stopped being
current** – files and row together, by `infrasales prune`:

- a replaced version: counted from `superseded_at`, when a newer version replaced it;
- the current version: counted from the Source's `last_checked_at`.

So a version is kept as long as it is still true. An authority's page that has not changed for two
years keeps its only version, because every run confirms it. A news article that has left its
Feed is no longer checked and is deleted 365 days after it was last seen.

By default no period is set, and Source Versions are kept for good (ADR 06 §7): they are the
evidence of every claim. `retain_until` lets a later stage keep a version past a period that is
set (`infrasales.catalog.versions.retain`: it extends `retain_until`, never
shortens it; no endpoint yet). Backups and S3 versions must follow the same period.

As built: the current version goes only together with the last of its Source's other
versions. While an older one is kept (`retain_until`) or a run is writing a new one, the
current one stays, so the latest pointer still names the highest committed version (§3).
`infrasales prune` marks a batch of expired versions `deleted` in one transaction with its audit
record (it locks their Sources first, as a commit does, so a run checking one of them at the
same time either comes first or waits). Then it deletes the folders and rows through the
catalog's one delete operation, the same one the crash sweep uses. A round cut off in between
leaves `deleted` versions, and the next round completes them. The Sources left empty are
audited after their deletion. Last, a round deletes the version folders in the sink that no
row's `storage_key` names: a row is written before its folder and deleted after it, so such a
folder is a leftover (an attempt that froze past its lease, was swept, wrote on and crashed).
The sink is listed before the rows are read, so a version started meanwhile is kept.
`RETENTION__SOURCE_DAYS` is at least 8, longer than the weekly re-check of a page its Feed still
lists.

### 9. Managing Feeds

For now the API only, no interface (since changed: the interface lists the Feeds, see
[ADR 04](04_adr_frontend_application_stack.md#what-this-changes-in-adr-03-a-feeds-page)):

| Method and path | What it does | Access |
|---|---|---|
| `GET /api/feeds` | Lists the Feeds with their kind, state and last error | admin |
| `POST /api/feeds` | Adds a Feed: name, kind, address, settings of its kind | admin, audited |
| `POST /api/feeds/suggest` | For an address, suggests a kind and the feed or sitemap address (the draft's discovery) | admin |

Adding a Feed takes its slug from its name (`heizwerk-journal`, then `heizwerk-journal-2`, …). A second
Feed at the same address is a conflict (409). The kind must have a Lister, and that Lister's
settings model checks the settings, so a new kind is accepted as soon as its Lister is
registered. The audit event is `feed.created`, with the slug as its target. A suggestion fetches
through the `http` fetcher (public addresses only, size cap) and obeys robots.txt (the sitemaps
it names taken from the copy already read). Its requests are 1 s apart, not the scrape's 3 s: a
suggestion is about 12 requests an admin waits for, not a run of hundreds (a longer
`Crawl-delay` still counts). It gives up after 20 seconds (504), at once if the site's
`Crawl-delay` cannot fit. It stores nothing; the admin then adds the suggested Feed.

No Feed is seeded: admins add them on the Feeds page.

### 10. First release

The `rss` and `sitemap` Listers; the `http` fetcher; the HTML and PDF extractors; the sink, the catalog and the Feed endpoints. The
URL pattern list starts empty.

## Alternatives

| Option | Why not |
|---|---|
| Text only, in the database (the draft) | No re-extraction, PDFs and API answers lose their structure, an extractor upgrade looks like a content change |
| WARC files (the web-archive standard) | Deleting one Source means rewriting a whole file; a later stage would need `warcio` plus separate text and metadata anyway; S3 cannot append. We can still export to WARC later with `warcio` |
| Files only, no catalog | De-duplication, versions, completeness and retention all become folder scans |
| Everything in PostgreSQL | Raw pages and PDFs bloat the database; no path to S3 |
| Own storage code with stdlib writes, or obstore | fsspec gives local, memory and S3 with one setting; atomic writes are not needed (section 4); obstore is pre-1.0 |
| Scrapy or Crawlee as framework | They would own the storage and the dispatch; Crawlee's file storage is single-process only. We take their ideas, not the framework |

**Cost:** a catalog and a sink that must be kept consistent (the states in section 3 and the
cleanup task do that); one more dependency (fsspec, later s3fs); the Lister, extractor and
fetcher classes are our own code to maintain.
