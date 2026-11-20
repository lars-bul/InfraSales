import { useQuery } from "@tanstack/react-query";
import { listConfigOptions } from "#/client/@tanstack/react-query.gen.ts";
import type { ConfigEntryRead } from "#/client/types.gen.ts";
import { untilNextRun } from "#/features/jobs/job-entries.ts";

// The jobs' schedules (everyone may read them), read again once a next run shown has come.
function schedulesQuery<T>(select: (entries: ConfigEntryRead[]) => T) {
  return {
    ...listConfigOptions(),
    refetchInterval: (query: { state: { data: ConfigEntryRead[] | undefined } }) =>
      untilNextRun(query.state.data),
    select,
  };
}

// Soonest first; a job without a next run (paused) after the others.
function bySoonest(entries: ConfigEntryRead[]): ConfigEntryRead[] {
  const next = (entry: ConfigEntryRead) =>
    (entry.value.enabled ?? true) && entry.next_run_at
      ? Date.parse(entry.next_run_at)
      : Number.POSITIVE_INFINITY;
  return entries.toSorted((one, other) => next(one) - next(other));
}

/** Every job's schedule, the one running next first. */
export function useSchedules() {
  return useQuery(schedulesQuery(bySoonest));
}
