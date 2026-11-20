import { fireEvent, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { inTurn } from "#/test/fetch.ts";
import {
  alerts,
  announced,
  fakeTheClock,
  POLL,
  progressOf,
  setUp,
  status,
  steps,
  until,
  violationsOf,
  wait,
} from "#/test/run-now.ts";
import { queuedRun, runAs } from "#/test/runs.ts";

// The step list Run now shows while it follows a run: Queued → Running → Finished (or Failed).
fakeTheClock();

const QUEUE = "POST /api/jobs/scrape/runs";
const CHECK = `GET /api/jobs/scrape/runs/${queuedRun.id}`;
const HISTORY = "GET /api/jobs/runs";
const DISMISS = "Dismiss the progress of this run of Source Collection";
const SESSION = `https://langfuse.test/project/p1/sessions/${queuedRun.id}`;
const LANGFUSE = "Open this run of Source Collection in Langfuse (new tab)";
const WATCH = 15_000; // how often a run under way is looked for while none is followed

test("the steps show where the run is, from queued until it finished", async () => {
  const { view, runNow } = await setUp({
    [QUEUE]: { status: 202, body: queuedRun },
    [CHECK]: inTurn({ body: runAs("running", { attempts: 1 }) }, { body: runAs("succeeded") }),
  });
  expect(steps()).toEqual([]); // nothing followed yet

  await runNow();
  await announced("Run queued: it starts in a moment.");
  expect(steps()).toEqual([
    ["in progress", "Queued"],
    ["not started", "Running"],
    ["not started", "Finished"],
  ]);
  expect(await violationsOf(view.container)).toEqual([]);
  await wait(POLL);
  expect(steps()).toEqual([
    ["done", "Queued"],
    ["in progress", "Running"],
    ["not started", "Finished"],
  ]);
  expect(status()).toBe("Running…");
  expect(await violationsOf(view.container)).toEqual([]);
  await wait(POLL);

  expect(steps()).toEqual([
    ["done", "Queued"],
    ["done", "Running"],
    ["done", "Finished"],
  ]);
  expect(status()).toBe("The run finished successfully.");
  expect(await violationsOf(view.container)).toEqual([]);
});

test("what the steps say already is announced, not shown twice below them", async () => {
  const { runNow } = await setUp({
    [QUEUE]: { status: 202, body: queuedRun },
    [CHECK]: inTurn({ body: runAs("running", { attempts: 1 }) }, { body: runAs("succeeded") }),
  });
  const said = () => within(progressOf()).getByRole("status").firstElementChild;

  await runNow();
  await announced("Run queued: it starts in a moment.");
  expect(said()?.className).not.toContain("sr-only"); // the steps do not say when it starts
  await wait(POLL);
  expect(status()).toBe("Running…");
  expect(said()?.className).toContain("sr-only"); // the step "Running" says it
  await wait(POLL);

  expect(status()).toBe("The run finished successfully.");
  expect(said()?.className).toContain("sr-only"); // the step "Finished" says it
});

test("the current step is marked as such for screen readers", async () => {
  const { runNow } = await setUp({
    [QUEUE]: { status: 202, body: queuedRun },
    [CHECK]: { body: runAs("running", { attempts: 1 }) },
  });

  await runNow();
  await wait(POLL);

  const items = within(progressOf()).getAllByRole("listitem");
  expect(items.map((item) => item.getAttribute("aria-current"))).toEqual([null, "step", null]);
});

test("a retry shows its attempt on the current step", async () => {
  const { view, runNow } = await setUp({
    [QUEUE]: { status: 202, body: queuedRun },
    [CHECK]: inTurn(
      { body: runAs("pending", { attempts: 1, error: "TimeoutError" }) },
      { body: runAs("running", { attempts: 2 }) },
    ),
  });

  await runNow();
  await wait(POLL); // the first attempt failed: the run waits for the next
  expect(steps()).toEqual([
    ["done", "Queued"],
    ["waiting to retry", "Running", "Attempt 2 of 3"],
    ["not started", "Finished"],
  ]);
  expect(status()).toBe("An attempt failed: the run is retried shortly.");
  expect(await violationsOf(view.container)).toEqual([]);
  await wait(POLL);

  expect(steps()).toEqual([
    ["done", "Queued"],
    ["in progress", "Running", "Attempt 2 of 3"],
    ["not started", "Finished"],
  ]);
  expect(status()).toBe("Running: attempt 2 of 3…");
  expect(await violationsOf(view.container)).toEqual([]);
});

test("a failed run ends on Failed, with its error announced", async () => {
  const { view, runNow } = await setUp({
    [QUEUE]: { status: 202, body: queuedRun },
    [CHECK]: { body: runAs("failed", { attempts: 3, error: "MailNotDeliveredError" }) },
  });

  await runNow();
  await wait(POLL);

  expect(steps()).toEqual([
    ["done", "Queued"],
    ["done", "Running"],
    ["failed", "Failed"],
  ]);
  expect(alerts()).toEqual(["The run failed (MailNotDeliveredError)."]);
  expect(await violationsOf(view.container)).toEqual([]);
});

test("the finished steps stay until dismissed", async () => {
  const { view, runNow } = await setUp({
    [QUEUE]: { status: 202, body: queuedRun },
    [CHECK]: { body: runAs("succeeded", { attempts: 1 }) },
  });

  await runNow();
  expect(screen.queryByRole("button", { name: DISMISS })).toBeNull(); // not while it runs
  await wait(POLL);
  await wait(20 * POLL); // finished: it stays

  expect(steps()).toHaveLength(3);
  fireEvent.click(screen.getByRole("button", { name: DISMISS }));
  await wait(0);
  expect(steps()).toEqual([]);
  expect(status()).toBe("");
  expect(await violationsOf(view.container)).toEqual([]);
});

test("a dismissed run makes way for the next one", async () => {
  const next = runAs("pending", { id: "0192f0c4-7e1a-7c3e-8a52-6f0e4c3b2a11" });
  const { runNow } = await setUp({
    [QUEUE]: inTurn({ status: 202, body: runAs("succeeded") }, { status: 202, body: next }),
  });
  await runNow();
  await until(() => expect(steps()).toHaveLength(3));
  fireEvent.click(screen.getByRole("button", { name: DISMISS }));
  await wait(0);

  await runNow();

  await announced("Run queued: it starts in a moment.");
  expect(steps()[0]).toEqual(["in progress", "Queued"]);
});

test("a traced run links to its session in Langfuse once it finished", async () => {
  const { view, runNow } = await setUp({
    [QUEUE]: { status: 202, body: { ...queuedRun, langfuse_url: SESSION } },
    [CHECK]: inTurn(
      { body: runAs("running", { attempts: 1, langfuse_url: SESSION }) },
      { body: runAs("succeeded", { attempts: 1, langfuse_url: SESSION }) },
    ),
  });
  const link = () => screen.queryByRole("link", { name: LANGFUSE });

  await runNow();
  expect(link()).toBeNull(); // queued: nothing to look into yet
  await wait(POLL);
  expect(link()).toBeNull(); // running
  await wait(POLL);

  expect(within(progressOf()).getByRole("link", { name: LANGFUSE })).toBeTruthy();
  expect(link()?.getAttribute("href")).toBe(SESSION);
  expect(link()?.getAttribute("target")).toBe("_blank");
  expect(link()?.textContent).toBe("Open in Langfuse");
  expect(await violationsOf(view.container)).toEqual([]);
});

test("an untraced run has no Langfuse link", async () => {
  const { runNow } = await setUp({
    [QUEUE]: { status: 202, body: queuedRun },
    [CHECK]: { body: runAs("succeeded", { attempts: 1 }) },
  });

  await runNow();
  await wait(POLL);

  expect(status()).toBe("The run finished successfully.");
  expect(screen.queryByRole("link", { name: LANGFUSE })).toBeNull();
});

test("a reloaded page shows the steps of the run still in progress", async () => {
  const { view } = await setUp({
    "GET /api/jobs/scrape/runs/active": { body: runAs("running", { attempts: 1 }) },
    [CHECK]: { body: runAs("running", { attempts: 1 }) },
  });

  await announced("Running…"); // without pressing anything

  expect(steps()).toEqual([
    ["done", "Queued"],
    ["in progress", "Running"],
    ["not started", "Finished"],
  ]);
  expect(await violationsOf(view.container)).toEqual([]);
});

test("a run that starts on its schedule while the page is open shows its steps", async () => {
  const scheduled = runAs("running", { attempts: 1, trigger: "schedule" });
  const underWay = [null, scheduled];
  const { calls } = await setUp({
    "GET /api/jobs/scrape/runs/active": () => ({ body: underWay.shift() ?? null }),
    [CHECK]: { body: scheduled },
  });
  const looks = () => calls.filter((call) => call.url.endsWith("/runs/active"));
  expect(steps()).toEqual([]); // nothing under way yet

  await wait(WATCH);
  await announced("Running…"); // without pressing anything

  expect(steps()).toEqual([
    ["done", "Queued"],
    ["in progress", "Running"],
    ["not started", "Finished"],
  ]);
  await wait(WATCH);
  expect(looks()).toHaveLength(2); // while one is followed, no other is looked for
});

test("Run history shows the new run at the top, once queued and once finished", async () => {
  const listed = [[], [queuedRun], [runAs("succeeded", { attempts: 1 })]];
  const { calls, runNow } = await setUp({
    [QUEUE]: { status: 202, body: queuedRun },
    [CHECK]: { body: runAs("succeeded", { attempts: 1 }) },
    [HISTORY]: () => ({ body: listed.shift() ?? [] }),
  });
  const history = () => calls.filter((call) => new URL(call.url).pathname.endsWith("/runs"));
  await until(() => expect(screen.getByText("No runs yet")).toBeTruthy());

  await runNow();
  await until(() => expect(history().filter((c) => c.method === "GET")).toHaveLength(2));
  await until(() => expect(screen.getByRole("cell", { name: "Waiting" })).toBeTruthy());
  await wait(POLL);

  await until(() => expect(history().filter((c) => c.method === "GET")).toHaveLength(3));
  await until(() => expect(screen.getByRole("cell", { name: "Succeeded" })).toBeTruthy());
});
