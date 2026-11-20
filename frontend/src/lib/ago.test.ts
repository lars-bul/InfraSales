import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ago } from "./ago.ts";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-16T12:00:00Z") });
});
afterEach(() => {
  vi.useRealTimers();
});

test.each([
  ["2026-10-16T11:59:30Z", "30 seconds ago"],
  ["2026-10-16T11:58:00Z", "2 minutes ago"],
  ["2026-10-16T11:00:20Z", "1 hour ago"], // not "60 minutes"
  ["2026-10-15T12:00:00Z", "yesterday"],
  ["2026-08-16T12:00:00Z", "2 months ago"],
  ["2023-10-16T12:00:00Z", "3 years ago"],
])("%s was %s", (at, said) => {
  expect(ago(at, "en")).toBe(said);
});
