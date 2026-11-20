import { infiniteQueryOptions } from "@tanstack/react-query";
import {
  listJobRunsInfiniteOptions,
  listJobRunsOptions,
  readRunActivityOptions,
} from "#/client/@tanstack/react-query.gen.ts";
import type { JobName, JobStatus, RunHistoryEntry, RunTrigger } from "#/client/types.gen.ts";
import { isJob } from "#/features/jobs/job-names.ts";
import { browserTimeZone } from "./run-summary.ts";

// A date and time as a date-time input holds it, in the browser's time zone: "2026-07-20T10:00".
const LOCAL_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

function oneOf<T extends string>(values: readonly T[], value: unknown): T | undefined {
  return values.find((known) => known === value);
}

// The filters as the API takes them: what is chosen, the times as instants.
function asked({ job, status, trigger, start, end }: RunFilters) {
  return {
    ...(job && { job }),
    ...(status && { status }),
    ...(trigger && { trigger }),
    ...(start && { start: instant(start) }),
    ...(end && { end: instant(end) }),
  };
}

function localTime(value: unknown): string | undefined {
  return typeof value === "string" && LOCAL_TIME.test(value) && !Number.isNaN(Date.parse(value))
    ? value
    : undefined;
}

/** Runs per page. */
export const LIMIT = 20;

/** The statuses and triggers the filters offer, in the order they offer them. */
export const RUN_STATUSES = [
  "succeeded",
  "failed",
  "running",
  "pending",
] as const satisfies JobStatus[];
export const RUN_TRIGGERS = ["schedule", "manual", "follow_up"] as const satisfies RunTrigger[];

/**
 * Which runs to list: one job's, one status's, one trigger's, scheduled from a start until an
 * end (local dates and times, as the inputs hold them), or any combination.
 */
export interface RunFilters {
  job?: JobName | undefined;
  status?: JobStatus | undefined;
  trigger?: RunTrigger | undefined;
  start?: string | undefined;
  end?: string | undefined;
}

/** The filters in a URL's search parameters; anything else is ignored, an end not after the start too. */
export function runFiltersIn({
  job,
  status,
  trigger,
  start,
  end,
}: Record<string, unknown>): RunFilters {
  const from = localTime(start);
  const until = localTime(end);
  return {
    job: isJob(job) ? job : undefined,
    status: oneOf(RUN_STATUSES, status),
    trigger: oneOf(RUN_TRIGGERS, trigger),
    start: from,
    end: until && (!from || Date.parse(until) > Date.parse(from)) ? until : undefined,
  };
}

/** The instant a local date and time names (in the browser's time zone), as the API takes it. */
export function instant(local: string): string {
  return new Date(local).toISOString();
}

/**
 * The runs, newest first, a page at a time: a full page means older runs may follow, and the
 * next page starts after the last run shown.
 */
export function runsQuery(filters: RunFilters) {
  return infiniteQueryOptions({
    ...listJobRunsInfiniteOptions({ query: { limit: LIMIT, ...asked(filters) } }),
    initialPageParam: {}, // the newest page: no cursor
    getNextPageParam: (page: RunHistoryEntry[]) =>
      page.length === LIMIT ? page.at(-1)?.id : undefined,
  });
}

/**
 * How the runs the filters list ended over time, per hour or per day of the browser's time zone:
 * from the start until the end; without an end until now, without a start over the last 7 days.
 */
export function activityQuery(filters: RunFilters) {
  return readRunActivityOptions({ query: { timezone: browserTimeZone(), ...asked(filters) } });
}

/** Source Collection's last run that went through, for what it found. */
export function lastCollectionQuery() {
  return listJobRunsOptions({ query: { job: "scrape", status: "succeeded", limit: 1 } });
}
