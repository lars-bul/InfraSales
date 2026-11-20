import { MutationObserver } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ApiError } from "#/api/errors.ts";
import { listConfigOptions, runNowMutation } from "#/client/@tanstack/react-query.gen.ts";
import { createApp } from "#/create-app.ts";
import { weekly } from "#/test/entries.ts";
import { stalled, stubApi, unavailableOnce } from "#/test/fetch.ts";

// The app as it starts in the browser (default retry rules), driven through the generated helpers.
let app: ReturnType<typeof createApp>;
beforeEach(() => {
  vi.useFakeTimers();
  app = createApp({ history: createMemoryHistory() });
});
afterEach(() => {
  app.disconnect();
  vi.useRealTimers();
});

async function outcome(): Promise<unknown> {
  const settled = app.queryClient.fetchQuery(listConfigOptions()).then(
    () => "answered",
    (error: unknown) => error,
  );
  await vi.runAllTimersAsync(); // the retry delays and the request deadline
  return settled;
}

const offline = () => {
  throw new TypeError("Failed to fetch"); // as fetch does without a connection
};

test.each([
  ["a server error", { status: 503 }],
  ["no connection", offline],
  ["no answer in time", stalled],
])("a query is retried twice on %s, then fails", async (_, reply) => {
  const calls = stubApi({ "GET /api/config": reply });

  const failure = await outcome();

  expect(calls).toHaveLength(3);
  expect(failure).not.toBe("answered");
});

test.each([400, 401, 403, 404, 412, 422])("a query is not retried on %i", async (status) => {
  const calls = stubApi({
    "GET /api/config": { status, body: { detail: "no" } },
    "GET /api/auth/session": { body: { user: null, provider: "basic" } }, // after a 401
  });

  const failure = await outcome();

  expect(calls.filter((call) => call.url.endsWith("/api/config"))).toHaveLength(1);
  expect(failure).toEqual(new ApiError(status, { detail: "no" }));
});

test.each(["error", "offline", "stalled"] as const)(
  "a query that fails once (%s) recovers on its retry",
  async (how) => {
    const calls = stubApi({ "GET /api/config": unavailableOnce({ body: [weekly] }, how) });

    expect(await outcome()).toBe("answered");
    expect(calls).toHaveLength(2);
  },
);

test("a failed write is never retried on its own", async () => {
  const calls = stubApi({ "POST /api/jobs/scrape/runs": { status: 503 } });
  const write = new MutationObserver(app.queryClient, runNowMutation());

  const failure = write.mutate({ path: { job: "scrape" } }).catch((error: unknown) => error);
  await vi.runAllTimersAsync();

  expect(await failure).toBeInstanceOf(ApiError);
  expect(calls).toHaveLength(1);
});
