import { expect, test } from "vitest";
import type { AuditEventRead } from "#/client/types.gen.ts";
import { auditEventsQuery, LIMIT } from "./audit-events.ts";

function page(length: number): AuditEventRead[] {
  return Array.from({ length }, (_, n) => ({
    id: `event-${n}`,
    created_at: "2026-10-02T06:37:51Z",
    actor: null,
    action: "auth.login",
    outcome: "success",
    target: null,
    details: {},
  }));
}

test("a full page is followed by the events before its last one", () => {
  const { getNextPageParam } = auditEventsQuery();

  expect(getNextPageParam(page(LIMIT), [], {}, [])).toBe(`event-${LIMIT - 1}`);
});

test("a short page is the last", () => {
  const { getNextPageParam } = auditEventsQuery();

  expect(getNextPageParam(page(LIMIT - 1), [], {}, [])).toBeUndefined();
  expect(getNextPageParam([], [], {}, [])).toBeUndefined();
});

test("the events are never read again behind the reader's back", () => {
  expect(auditEventsQuery().staleTime).toBe(Number.POSITIVE_INFINITY);
});
