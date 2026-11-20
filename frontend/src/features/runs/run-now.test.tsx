import { fireEvent, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { DEADLINE_MS } from "#/api/deadline.ts";
import type { RunProgress } from "#/client/types.gen.ts";
import { weekly } from "#/test/entries.ts";
import { inTurn, stubApi, unavailableOnce } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import {
  alerts,
  announced,
  fakeTheClock,
  later,
  offline,
  POLL,
  setUp,
  until,
  violationsOf,
  wait,
} from "#/test/run-now.ts";
import { queuedRun, runAs } from "#/test/runs.ts";
import { signedIn, vera } from "#/test/users.ts";

// How Run now queues a run: where it asks first, and how a request is sent (once, and again
// with the same key when its answer was lost).
fakeTheClock();

const QUEUE = "POST /api/jobs/scrape/runs";
const UUID = /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/;
const QUEUED = "Run queued: it starts in a moment.";
const SUCCEEDED = "The run finished successfully.";
const NOT_QUEUED = "The run could not be queued. Please try again.";
const ANY_RUN_NOW = /^Run .* now$/;

test("Run now sits beside the name on the job's page, for admins", async () => {
  const name = "Source Collection";
  await setUp({});

  const header = screen.getByRole("heading", { level: 1, name }).closest("header");
  const button = within(header as HTMLElement).getByRole("button", { name: `Run ${name} now` });
  expect(button.textContent).toBe("Run now");
});

test("viewers get no Run now", async () => {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(vera),
    "GET /api/config": { body: [weekly] },
  });
  renderApp("/jobs/scrape");
  await until(() => screen.getByRole("heading", { level: 1, name: "Source Collection" }));
  await wait(POLL);

  expect(screen.queryByRole("button", { name: ANY_RUN_NOW })).toBeNull();
  expect(calls.filter((call) => call.url.includes("/api/jobs/"))).toEqual([]); // nothing to follow
});

test("Source Collection is queued at once, without a question", async () => {
  const scrapeRun = { ...queuedRun, job: "scrape" };
  const { keys, view, button } = await setUp(
    {
      "POST /api/jobs/scrape/runs": { status: 202, body: scrapeRun },
      [`GET /api/jobs/scrape/runs/${queuedRun.id}`]: { body: { ...scrapeRun, status: "running" } },
    },
    "scrape",
  );

  fireEvent.click(button);
  await wait(0);

  expect(screen.queryByRole("alertdialog")).toBeNull();
  await announced(QUEUED, "Source Collection");
  expect(keys()).toHaveLength(1);
  expect(keys()[0]).toMatch(UUID);
  expect(await violationsOf(view.container)).toEqual([]);
});

test("a double click queues once", async () => {
  const queue = later();
  const { keys, runNow } = await setUp({ [QUEUE]: queue.reply });

  await runNow();
  await runNow();
  queue.answer({ status: 202, body: queuedRun satisfies RunProgress });

  await announced(QUEUED);
  expect(keys()).toHaveLength(1);
});

test.each([
  ["a client error", { status: 403 }],
  ["a server error", { status: 503 }],
])("an answer that queued nothing (%s) is announced, never retried", async (_, reply) => {
  const { keys, view, runNow } = await setUp({ [QUEUE]: reply });

  await runNow();

  await until(() => expect(alerts()).toEqual([NOT_QUEUED]));
  await wait(4 * POLL);
  expect(keys()).toHaveLength(1); // an answer is final: nothing is sent again on its own
  expect(await violationsOf(view.container)).toEqual([]);
});

test("without a connection, the request is sent once more, then the failure announced", async () => {
  const { keys, runNow } = await setUp({ [QUEUE]: offline });

  await runNow();

  await until(() => expect(alerts()).toEqual([NOT_QUEUED]));
  const [first, again] = keys();
  expect(keys()).toHaveLength(2);
  expect(again).toBe(first);
});

test("a lost answer is asked for again with the same key, even after the run finished", async () => {
  const finished = { status: 202, body: runAs("succeeded") }; // what the server answers again
  const { keys, runNow } = await setUp({ [QUEUE]: unavailableOnce(finished, "stalled") });

  await runNow();
  expect(keys()).toHaveLength(1); // sent: its deadline runs
  await wait(DEADLINE_MS); // no answer by then: asked again

  await announced(SUCCEEDED);
  const [first, again] = keys();
  expect(first).toMatch(UUID);
  expect(again).toBe(first);
  expect(alerts()).toEqual([]);
});

test("a click keeps its key until a run answers it; the next click gets a new one", async () => {
  const { keys, runNow } = await setUp({
    [QUEUE]: inTurn({ status: 503 }, { status: 202, body: runAs("succeeded") }, { status: 403 }),
  });

  await runNow(); // no run: the outcome may still be unknown to the user
  await until(() => expect(alerts()).toEqual([NOT_QUEUED]));
  await runNow(); // the same click, as far as the server can tell
  await announced(SUCCEEDED);
  await runNow(); // a new click
  await until(() => expect(alerts()).toEqual([NOT_QUEUED]));

  const [first, again, next] = keys();
  expect(again).toBe(first);
  expect(next).toMatch(UUID);
  expect(next).not.toBe(first);
});
