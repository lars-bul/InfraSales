import type { SourceListed, SourceRead, VersionRead, VersionText } from "#/client/types.gen.ts";

// One Source as the Source API shows it: an article the news Feed listed, read twice by Source
// Collection, its text changed in between.

export const SOURCE_ID = "0199f0b2-0000-7000-8000-000000000001";
export const FIRST_RUN = "0199f0c4-0000-7000-8000-000000000001";
export const SECOND_RUN = "0199f0c4-0000-7000-8000-000000000002";

export const firstVersion: VersionRead = {
  id: "0199f0b3-0000-7000-8000-000000000001",
  number: 1,
  fetched_at: "2026-10-16T06:02:00Z",
  run_id: FIRST_RUN,
  feed: { slug: "heizwerk-journal", name: "Heizwerk Journal" },
  http_status: 200,
  media_type: "text/html; charset=utf-8",
  partial: false,
  title: "Wärmenetz-Ausbau",
  published_at: "2026-10-16T05:00:00Z",
  extractor: "html",
  extractor_version: "1",
  superseded_at: "2026-10-17T06:03:00Z",
};

export const secondVersion: VersionRead = {
  ...firstVersion,
  id: "0199f0b3-0000-7000-8000-000000000002",
  number: 2,
  fetched_at: "2026-10-17T06:03:00Z",
  run_id: SECOND_RUN,
  title: "Wärmenetz-Ausbau, jetzt auch im Norden",
  superseded_at: null,
};

export const bahnstadt: SourceRead = {
  id: SOURCE_ID,
  url: "https://www.heizwerk-journal.test/news/bahnstadt-rollout.html",
  first_seen_at: "2026-10-16T06:02:00Z",
  last_checked_at: "2026-10-17T06:03:00Z",
  versions: [secondVersion, firstVersion],
};

/** The Source as the list shows it: by its latest version, or by `version`. */
export function listed(version: VersionRead = secondVersion): SourceListed {
  const { versions, ...source } = bahnstadt;
  return { ...source, versions: versions.length, version };
}

/** A Source with no title, only its address, in the list. */
export const untitled: SourceListed = {
  id: "0199f0b2-0000-7000-8000-000000000002",
  url: "https://policy.test/oberste-baubehoerde-guidance/",
  first_seen_at: "2026-10-15T09:00:00Z",
  last_checked_at: "2026-10-17T06:03:00Z",
  versions: 1,
  version: {
    ...firstVersion,
    id: "0199f0b3-0000-7000-8000-000000000003",
    title: null,
    partial: true,
    feed: { slug: "oberste-baubehoerde", name: "Oberste Baubehörde" },
  },
};

export const firstText: VersionText = {
  number: 1,
  title: "Wärmenetz-Ausbau",
  author: "Jane Doe",
  published_at: "2026-10-16T05:00:00Z",
  text: "Der Wärmenetz-Ausbau beginnt heute. Es wird im Süden allein gebaut.",
};

export const secondText: VersionText = {
  ...firstText,
  number: 2,
  title: "Wärmenetz-Ausbau, jetzt auch im Norden",
  text: "Der Wärmenetz-Ausbau beginnt heute. Es wird jetzt auch im Norden gebaut.",
};
