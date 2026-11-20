import { useSuspenseQuery } from "@tanstack/react-query";
import { listConfigOptions } from "#/client/@tanstack/react-query.gen.ts";
import type { ConfigEntryRead } from "#/client/types.gen.ts";

const SLACK_MS = 5000; // the run is planned by then: its successor is the next run
const MAX_WAIT_MS = 86_400_000; // timers take at most ~24 days; a day keeps far runs exact enough
const FRESH_MS = 60_000;

// How long until the earliest next run shown has come: then the one after it is read. Nothing
// to wait for while every job is paused, or every next run shown has passed (a clock ahead of
// the server's would read the same again and again).
export function untilNextRun(entries: ConfigEntryRead[] | undefined): number | false {
  const waits = (entries ?? [])
    .flatMap((entry) => (entry.next_run_at ? [Date.parse(entry.next_run_at) - Date.now()] : []))
    .filter((wait) => wait > 0);
  return waits.length === 0 ? false : Math.min(Math.min(...waits) + SLACK_MS, MAX_WAIT_MS);
}

// The jobs' schedules, as the route's loader fetched them (loading and failing are the router's),
// read again once a next run shown has come.
export function useJobEntries(): ConfigEntryRead[] {
  const { data } = useSuspenseQuery({
    ...listConfigOptions(),
    staleTime: FRESH_MS, // as the loader just read it, however long the page took to show
    refetchInterval: (query) => untilNextRun(query.state.data),
  });
  return data;
}
