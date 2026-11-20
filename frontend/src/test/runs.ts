import type {
  FeedOutcome,
  RunHistoryEntry,
  RunProgress,
  SourceCollectionResult,
} from "#/client/types.gen.ts";

export const queuedRun: RunProgress = {
  id: "0192f0c4-7e1a-7c3e-8a52-6f0e4c3b2a10",
  job: "scrape",
  trigger: "manual",
  status: "pending",
  scheduled_for: "2026-10-02T08:00:00Z",
  attempts: 0,
  finished_at: null,
  error: null,
  max_attempts: 3,
};

export function runAs(
  status: RunProgress["status"],
  changes: Partial<RunProgress> = {},
): RunProgress {
  return { ...queuedRun, status, ...changes };
}

/** A run as the run history lists it: started by alice with Run now, no result yet. */
export function entryAs(
  status: RunHistoryEntry["status"],
  changes: Partial<RunHistoryEntry> = {},
): RunHistoryEntry {
  return { ...queuedRun, triggered_by: "basic:alice", result: null, status, ...changes };
}

/** What a Source Collection run did: no Feed failed, unless `changes` says so. */
export function collected(changes: Partial<SourceCollectionResult> = {}): SourceCollectionResult {
  return {
    feeds_read: 40,
    versions_new: 42,
    versions_unchanged: 120,
    documents_failed: 0,
    failed_feeds: [],
    ...changes,
  };
}

/** What a Source Collection run did with one Feed: read, its items new, unless `changes` say. */
export function feedRead(feed: string, changes: Partial<FeedOutcome> = {}): FeedOutcome {
  return {
    feed,
    items: 0,
    new: 0,
    unchanged: 0,
    known: 0,
    seen: 0,
    failed: 0,
    unread: 0,
    reason: null,
    out_of_time: false,
    seconds: 0,
    ...changes,
  };
}

/** A run list without runs, for pages that show the run history on the way. */
export const noRuns = { body: [] };
