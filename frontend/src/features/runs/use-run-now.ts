import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "#/api/errors.ts";
import {
  listJobRunsQueryKey,
  readActiveRunOptions,
  readRunOptions,
  runNowMutation,
} from "#/client/@tanstack/react-query.gen.ts";
import type { JobName, RunProgress } from "#/client/types.gen.ts";

const POLL_MS = 2000; // how often a run's progress is checked until it finished
const WATCH_MS = 15_000; // how often a run under way is looked for while none is followed
const MAX_POLL_MS = 30_000; // after failed checks, the wait doubles up to this
const NOT_FOUND = 404;

const finished = (run: RunProgress | undefined) =>
  run?.status === "succeeded" || run?.status === "failed";

const gone = (error: unknown) => error instanceof ApiError && error.status === NOT_FOUND;

// No answer at all (no connection, or none before the deadline): the request may have arrived.
const unanswered = (error: unknown) => !(error instanceof ApiError);

// The newer of two runs: run IDs are time-ordered (UUIDv7).
const newer = (a: RunProgress | undefined, b: RunProgress | undefined) =>
  a === undefined || (b !== undefined && b.id > a.id) ? b : a;

// The run of `job` being followed, checked every POLL_MS until it finished: the newest of the one
// queued here and the one under way, scheduled or manual. A failed check is tried again, waiting
// twice as long each time (up to MAX_POLL_MS), until the service answers; a run that no longer
// exists is lost. Each run is its own query: once another is followed, a check still under way
// for the last one is aborted, and its answer never shown.
function useFollowedRun(job: JobName, queued: RunProgress | undefined, enabled: boolean) {
  const idle = useRef<boolean>(true); // no run followed, or it finished: look for the next one
  // Asked on each visit (never cached across them), then every WATCH_MS while idle: a run that
  // starts on its schedule, or from another tab, is followed too. If the check fails, there is
  // nothing to follow, and the button works as ever.
  const active = useQuery({
    ...readActiveRunOptions({ path: { job } }),
    enabled,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: 0,
    refetchInterval: () => (idle.current ? WATCH_MS : false),
  });
  const start = newer(queued, active.data ?? undefined);
  const followed = useQuery({
    ...readRunOptions({ path: { job, run_id: start?.id ?? "" } }),
    enabled: start !== undefined,
    initialData: () => start, // known already: the first check is due after POLL_MS
    staleTime: Number.POSITIVE_INFINITY,
    refetchInterval: (query) =>
      finished(query.state.data) || gone(query.state.error) ? false : POLL_MS,
    refetchIntervalInBackground: true,
    networkMode: "always", // offline counts as a failed check, as any other
    retry: (_, error) => !gone(error),
    // `failures` before this one: the first failed check is tried again after twice POLL_MS
    retryDelay: (failures) => Math.min(POLL_MS * 2 ** (failures + 1), MAX_POLL_MS),
  });
  idle.current = start === undefined || finished(followed.data) || gone(followed.error);
  return {
    run: followed.data,
    found: active.data?.id, // the run under way when last looked for, if any
    lost: gone(followed.error),
    reconnecting: followed.failureCount > 0 && !gone(followed.error),
  };
}

// Every list of runs is read again (any job, filter, page size and page): the history is one.
function refreshHistory(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: listJobRunsQueryKey() });
}

export interface RunNowState {
  start: () => void; // queues a run (a double click queues once)
  dismiss: () => void; // hides a finished (or lost) run's progress
  run: RunProgress | undefined; // the run followed, until dismissed
  finished: boolean; // it succeeded or failed: nothing more to follow
  lost: boolean;
  reconnecting: boolean;
  notQueued: boolean; // the last request got an answer that queued nothing
}

// Queues a run of `job` at once (admins), e.g. to test the Report, then follows it until it
// finished; a run under way that was not queued here (on its schedule, from another tab) is
// followed as well. Run history is read again once a run is queued or found and once it
// finished, so it is at its top. `enabled` is false for viewers: there is nothing they may follow.
export function useRunNow(job: JobName, enabled: boolean): RunNowState {
  const queryClient = useQueryClient();
  const [queued, setQueued] = useState<RunProgress>();
  const [dismissed, setDismissed] = useState<string>();
  const { run, found, lost, reconnecting } = useFollowedRun(job, queued, enabled);
  const click = useRef<string>(undefined); // the key of a click that got no run yet
  const sending = useRef<boolean>(false); // set at once: a double click sends once
  // An unanswered request is sent once more with the same key: if the first one arrived, the
  // server answers with the run it queued, so the Report is never sent twice. Nothing
  // else is retried: an answer, even an error, is final.
  const queue = useMutation({
    ...runNowMutation(),
    networkMode: "always",
    retry: (failures, error) => failures < 1 && unanswered(error),
    retryDelay: 0,
  });

  const ended = finished(run) ? run?.id : undefined;
  useEffect(() => {
    if (ended !== undefined) {
      refreshHistory(queryClient);
    }
  }, [ended, queryClient]);

  useEffect(() => {
    if (found !== undefined) {
      refreshHistory(queryClient);
    }
  }, [found, queryClient]);

  function start() {
    if (sending.current) {
      return; // a double click queues once (the server, too, returns the active run)
    }
    sending.current = true;
    click.current ??= crypto.randomUUID(); // one per click, kept until a run answers it
    queue.mutate(
      { path: { job }, headers: { "idempotency-key": click.current } },
      {
        onSuccess: (answer) => {
          click.current = undefined; // answered: the next click is a new request
          setQueued(answer);
          setDismissed(undefined);
          refreshHistory(queryClient);
        },
        onSettled: () => {
          sending.current = false;
        },
      },
    );
  }

  const shown = run !== undefined && run.id !== dismissed;
  return {
    start,
    dismiss: () => setDismissed(run?.id),
    run: shown ? run : undefined,
    finished: shown && finished(run),
    lost: shown && lost,
    reconnecting: shown && reconnecting,
    notQueued: queue.isError,
  };
}
