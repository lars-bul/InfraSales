import { type QueryClient, useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "#/api/errors.ts";
import {
  listConfigOptions,
  listConfigQueryKey,
  updateConfigMutation,
} from "#/client/@tanstack/react-query.gen.ts";
import type { ConfigEntryRead, Schedule } from "#/client/types.gen.ts";

const PRECONDITION_FAILED = 412; // changed since the revision the card shows
const UNPROCESSABLE = 422; // the server rejected the values

type Outcome = "saved" | "invalid" | "stale" | "failed";

interface Saved {
  outcome: Outcome;
  // The schedule as stored now, when it is known: saved, or someone else's change.
  stored?: ConfigEntryRead | undefined;
}

function sameSchedule(a: Schedule, b: Schedule): boolean {
  return (
    a.days.join() === b.days.join() &&
    a.time === b.time &&
    a.timezone === b.timezone &&
    a.enabled === b.enabled &&
    (a.every_hours ?? null) === (b.every_hours ?? null)
  );
}

// The schedule as stored, read afresh: the job cards show it too.
async function reread(queryClient: QueryClient, entry: ConfigEntryRead) {
  const entries = await queryClient.fetchQuery(listConfigOptions()).catch(() => []);
  return entries.find((candidate) => candidate.key === entry.key);
}

// Saved after all if the stored schedule moved on to what was sent; moved on to anything else,
// someone else saved. Unchanged, or unreadable too: not saved, try again (the revision a save
// names keeps a retry from overwriting anything).
async function resolve(queryClient: QueryClient, entry: ConfigEntryRead, sent: Schedule) {
  const stored = await reread(queryClient, entry);
  if (stored === undefined || stored.revision === entry.revision) {
    return { outcome: "failed", stored } as const;
  }
  return { outcome: sameSchedule(stored.value, sent) ? "saved" : "stale", stored } as const;
}

// A save the API answered with an error status was not saved, and says why: a change someone
// made first is read afresh, so it shows. Left without answer (no connection, the deadline),
// whether it was saved is unknown: reread to find out.
async function rejected(
  error: unknown,
  queryClient: QueryClient,
  entry: ConfigEntryRead,
  sent: Schedule,
): Promise<Saved> {
  if (!(error instanceof ApiError)) {
    return await resolve(queryClient, entry, sent);
  }
  if (error.status === PRECONDITION_FAILED) {
    return { outcome: "stale", stored: await reread(queryClient, entry) };
  }
  return { outcome: error.status === UNPROCESSABLE ? "invalid" : "failed" };
}

/**
 * Saves a whole schedule over the revision `entry` shows (`If-Match`), so a change someone else
 * made first is reported instead of overwritten. The job card's switch and its form both save
 * through it: each saves over the revision the other left. Never retried: the caller says what
 * happened.
 */
function useSaveSchedule(entry: ConfigEntryRead): (schedule: Schedule) => Promise<Saved> {
  const queryClient = useQueryClient();
  const { mutateAsync } = useMutation(updateConfigMutation());

  return async (schedule) => {
    const body = { ...schedule, every_hours: schedule.every_hours ?? null };
    return await mutateAsync({
      path: { key: entry.key },
      headers: { "if-match": `"${entry.revision}"` },
      body,
    }).then(
      (stored): Saved => {
        queryClient.setQueryData<ConfigEntryRead[]>(listConfigQueryKey(), (entries) =>
          entries?.map((each) => (each.key === stored.key ? stored : each)),
        );
        return { outcome: "saved", stored };
      },
      (error: unknown) => rejected(error, queryClient, entry, body),
    );
  };
}

export { type Outcome, useSaveSchedule };
