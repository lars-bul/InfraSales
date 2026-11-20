import { afterEach, expect, test, vi } from "vitest";
import { DEADLINE_MS, withDeadline } from "./deadline.ts";

afterEach(() => {
  vi.useRealTimers();
});

test("a request is aborted once the deadline passes, not before", async () => {
  vi.useFakeTimers();
  const request = withDeadline(new Request("https://infrasales.test/api/config"));

  await vi.advanceTimersByTimeAsync(DEADLINE_MS - 1);
  expect(request.signal.aborted).toBe(false);
  await vi.advanceTimersByTimeAsync(1);

  expect(request.signal.aborted).toBe(true);
  expect(request.signal.reason).toMatchObject({
    name: "TimeoutError",
    message: "No answer in time",
  });
});

test("the caller's own signal still aborts the request", () => {
  const caller = new AbortController();
  const request = withDeadline(
    new Request("https://infrasales.test/api/config", { signal: caller.signal }),
  );

  caller.abort();

  expect(request.signal.aborted).toBe(true);
});
