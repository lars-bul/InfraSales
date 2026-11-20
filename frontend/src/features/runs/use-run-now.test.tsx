import { expect, test } from "vitest";
import { DEADLINE_MS } from "#/api/deadline.ts";
import { listJobRunsQueryKey } from "#/client/@tanstack/react-query.gen.ts";
import { inTurn, stalled } from "#/test/fetch.ts";
import {
  alerts,
  announced,
  fakeTheClock,
  later,
  offline,
  POLL,
  type Reply,
  setUp,
  status,
  until,
  violationsOf,
  wait,
} from "#/test/run-now.ts";
import { queuedRun, runAs } from "#/test/runs.ts";

// How Run now follows a run it queued, or found in progress: checked every POLL ms until it
// finished, through failed checks.
fakeTheClock();

const MAX_POLL = 30_000;
const ACTIVE = "GET /api/jobs/scrape/runs/active";
const QUEUE = "POST /api/jobs/scrape/runs";
const CHECK = `GET /api/jobs/scrape/runs/${queuedRun.id}`;
const QUEUED = "Run queued: it starts in a moment.";
const RUNNING = "Running…";
const SUCCEEDED = "The run finished successfully.";
const RECONNECTING = "Connection problem: checking the run again shortly.";

test("a run is queued, then followed through its progress until it finished", async () => {
  const { checks, view, runNow } = await setUp({
    [QUEUE]: { status: 202, body: queuedRun },
    [CHECK]: inTurn({ body: runAs("running", { attempts: 1 }) }, { body: runAs("succeeded") }),
  });

  await runNow();
  await announced(QUEUED);
  await wait(POLL);
  expect(status()).toBe(RUNNING);
  await wait(POLL);
  expect(status()).toBe(SUCCEEDED);
  await wait(4 * POLL); // finished: no further checks

  expect(checks()).toHaveLength(2);
  expect(alerts()).toEqual([]);
  expect(await violationsOf(view.container)).toEqual([]);
});

test("a queued run makes every list of runs read again: any job, any filter", async () => {
  const { view, runNow } = await setUp({ [QUEUE]: { status: 202, body: queuedRun } });
  // e.g. Source Collection's last runs in the jobs list, cached from before
  const elsewhere = listJobRunsQueryKey({ query: { job: "scrape", limit: 5 } });
  view.queryClient.setQueryData(elsewhere, []);

  await runNow();
  await announced(QUEUED);

  expect(view.queryClient.getQueryState(elsewhere)?.isInvalidated).toBe(true);
});

test("a reloaded page picks up the run still in progress", async () => {
  const { checks } = await setUp({
    [ACTIVE]: { body: runAs("running", { attempts: 1 }) },
    [CHECK]: { body: runAs("succeeded") },
  });

  await announced(RUNNING); // without pressing anything
  expect(checks()).toHaveLength(0); // known already: checked after the usual wait
  await wait(POLL);

  expect(status()).toBe(SUCCEEDED);
  expect(checks()).toHaveLength(1);
});

test.each([
  ["an error status", (): Reply => ({ status: 503 }), 0],
  ["no connection", offline, 0],
  ["no answer in time", stalled, DEADLINE_MS], // a stalled check fails at its deadline
])(
  "failed checks (%s) are retried, waiting longer each time, until one succeeds",
  async (_, fail, deadline) => {
    const answers = [fail, fail, (): Reply => ({ body: runAs("running", { attempts: 1 }) })];
    const { checks, view, runNow } = await setUp({
      [QUEUE]: { status: 202, body: queuedRun },
      [CHECK]: (request) => (answers.shift() ?? fail)(request),
    });

    await runNow();
    await announced(QUEUED);
    await wait(POLL + deadline); // the first check fails
    expect(checks()).toHaveLength(1);
    expect(status()).toBe(RECONNECTING);
    expect(await violationsOf(view.container)).toEqual([]);
    await wait(POLL); // the next check waits twice as long
    expect(checks()).toHaveLength(1);
    await wait(POLL + deadline); // and fails too
    expect(checks()).toHaveLength(2);
    expect(status()).toBe(RECONNECTING);
    await wait(2 * POLL); // the next one waits four times as long
    expect(checks()).toHaveLength(2);
    await wait(2 * POLL);

    expect(checks()).toHaveLength(3);
    expect(status()).toBe(RUNNING); // back on track
    await wait(POLL); // and checked as usual again
    expect(checks()).toHaveLength(4);
  },
);

test("through a longer outage, checks are at most 30 s apart", async () => {
  const { checks, runNow } = await setUp({
    [QUEUE]: { status: 202, body: queuedRun },
    [CHECK]: { status: 503 },
  });
  const counts: number[] = [];

  await runNow();
  await announced(QUEUED);
  await wait(POLL); // the first check fails
  for (const gap of [2 * POLL, 4 * POLL, 8 * POLL, MAX_POLL, MAX_POLL, MAX_POLL]) {
    // biome-ignore lint/performance/noAwaitInLoops: the clock moves on, one gap after another
    await wait(gap / 2);
    counts.push(checks().length); // not yet
    await wait(gap / 2);
    counts.push(checks().length);
  }

  expect(counts).toEqual([1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7]);
  expect(status()).toBe(RECONNECTING);
});

test.each([
  ["MailNotDeliveredError", "The run failed (MailNotDeliveredError)."],
  [null, "The run failed (no details)."],
])("retries and a failure (%s) are announced", async (error, message) => {
  const { checks, runNow } = await setUp({
    [QUEUE]: { status: 202, body: queuedRun },
    [CHECK]: inTurn(
      { body: runAs("pending", { attempts: 1, error: "TimeoutError" }) },
      { body: runAs("failed", { attempts: 3, error }) },
    ),
  });

  await runNow();
  await announced(QUEUED);
  await wait(POLL);
  expect(status()).toBe("An attempt failed: the run is retried shortly.");
  await wait(POLL);

  expect(alerts()).toEqual([message]);
  expect(status()).toBe("");
  await wait(4 * POLL); // failed is finished, too
  expect(checks()).toHaveLength(2);
});

test("a run that no longer exists is reported lost and no longer followed", async () => {
  const { checks, view, runNow } = await setUp({
    [QUEUE]: { status: 202, body: queuedRun },
    [CHECK]: { status: 404 },
  });

  await runNow();
  await announced(QUEUED);
  await wait(POLL);
  await wait(4 * POLL);

  expect(alerts()).toEqual(["The run can no longer be found."]);
  expect(status()).toBe("");
  expect(checks()).toHaveLength(1);
  expect(await violationsOf(view.container)).toEqual([]);
});

const nextRun = runAs("pending", { id: "0192f0c4-7e1a-7c3e-8a52-6f0e4c3b2a11" });
const NEXT_CHECK = `GET /api/jobs/scrape/runs/${nextRun.id}`;

test("a late answer about a run no longer followed is dropped", async () => {
  const check = later();
  const { checks, runNow } = await setUp({
    [ACTIVE]: { body: runAs("running") }, // followed since the page loaded
    [CHECK]: check.reply,
    [QUEUE]: { status: 202, body: nextRun }, // it finished meanwhile: a new run is queued
    [NEXT_CHECK]: { body: runAs("running", { id: nextRun.id }) },
  });
  await announced(RUNNING);
  await wait(POLL); // the old run's check is under way

  await runNow();
  await announced(QUEUED);
  check.answer({ body: runAs("succeeded") }); // about the old run, after the new one is followed
  await wait(0);

  expect(status()).toBe(QUEUED);
  expect(checks()[0]?.signal.aborted).toBe(true);
  await wait(POLL); // the new run is followed as usual
  expect(status()).toBe(RUNNING);
});

test("a new run is followed afresh: the last one's loss is forgotten", async () => {
  const { runNow } = await setUp({
    [ACTIVE]: { body: runAs("running") },
    [CHECK]: { status: 404 },
    [QUEUE]: { status: 202, body: nextRun },
  });
  await announced(RUNNING);
  await wait(POLL);
  expect(alerts()).toEqual(["The run can no longer be found."]);

  await runNow();

  await announced(QUEUED);
  expect(alerts()).toEqual([]);
});

test("leaving the page stops following the run", async () => {
  const { checks, view, runNow } = await setUp({ [QUEUE]: { status: 202, body: queuedRun } });

  await runNow();
  await announced(QUEUED);
  view.unmount();
  await wait(4 * POLL);

  expect(checks()).toHaveLength(0);
});

test("nothing to resume when the check for a run in progress fails", async () => {
  const { calls } = await setUp({ [ACTIVE]: offline });
  await until(() => expect(calls.some((call) => call.url.endsWith("/active"))).toBe(true));
  await wait(POLL);

  expect(status()).toBe("");
  expect(alerts()).toEqual([]);
});
