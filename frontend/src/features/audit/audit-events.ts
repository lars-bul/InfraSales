import { infiniteQueryOptions, type skipToken } from "@tanstack/react-query";
import { listAuditEventsInfiniteOptions } from "#/client/@tanstack/react-query.gen.ts";
import type { AuditEventRead } from "#/client/types.gen.ts";

function text(value: unknown): string | undefined {
  return typeof value === "string" && value !== "" ? value : undefined;
}

/** Events per page. */
export const LIMIT = 50;

/**
 * The person filter's value for what nobody did. No subject can take it: a subject always
 * names its provider ("basic:alice").
 */
export const SYSTEM = "system";

/** Which events to show: one person's (a subject, or `SYSTEM`), one action's, or both. */
export interface AuditFilters {
  actor?: string | undefined;
  action?: string | undefined;
}

/** The filters in a URL's search parameters; anything else is ignored. */
export function filtersIn({ actor, action }: Record<string, unknown>): AuditFilters {
  return { actor: text(actor), action: text(action) };
}

/**
 * The audit events, newest first, a page at a time: the next page holds the events before the
 * last one shown, and a short page is the last. Reading them is audited, so they are read only
 * when asked for (opening the page, loading older ones, refreshing), never in the background.
 *
 * The API filters by exact actor and action. It has no filter for events without an actor, so
 * for `SYSTEM` every actor's events are read and the page picks the system's (`byActor`).
 */
export function auditEventsQuery({ actor, action }: AuditFilters = {}) {
  const generated = listAuditEventsInfiniteOptions({
    query: {
      limit: LIMIT,
      ...(actor && actor !== SYSTEM && { actor }),
      ...(action && { action }),
    },
  });
  return infiniteQueryOptions({
    ...generated,
    // The helper always reads; its type merely allows `skipToken`, which suspense refuses.
    queryFn: generated.queryFn as Exclude<typeof generated.queryFn, typeof skipToken | undefined>,
    initialPageParam: {}, // the newest page: no cursor
    getNextPageParam: (page: AuditEventRead[]) =>
      page.length < LIMIT ? undefined : page.at(-1)?.id,
    staleTime: Number.POSITIVE_INFINITY,
  });
}

/** The events of the chosen person: the API picked a subject's already, the system's are left. */
export function byActor(events: AuditEventRead[], actor: string | undefined): AuditEventRead[] {
  return actor === SYSTEM ? events.filter((event) => event.actor === null) : events;
}
