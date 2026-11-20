import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { stubApi, unavailableOnce } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { entryAs } from "#/test/runs.ts";
import { summaries } from "#/test/summaries.ts";
import { alice, signedIn } from "#/test/users.ts";

// A job's run history on its page, as an admin reads it: the page's first tab.
const HISTORY = "GET /api/jobs/runs";
const CAPTION = /most recent runs of Source Collection/;
const LOAD_OLDER = "Load older runs of Source Collection";
const TWENTY = /The 20 most recent runs/;
const TWENTY_ONE = /The 21 most recent runs/;
const OCTOBER_2_AT = /^Oct 2, 2026, \d+:00 [AP]M$/;
const RUNS_APPEAR_HERE = "Runs appear here once the schedule starts one or an admin uses Run now.";

/** The Source Collection's page as alice (an admin) opens it. */
async function setUp(replies: Parameters<typeof stubApi>[0]) {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [weekly] },
    "GET /api/jobs/scrape/runs/active": { body: null },
    ...summaries,
    ...replies,
  });
  const view = renderApp("/jobs/scrape");
  await screen.findByRole("tab", { name: "Runs", selected: true });
  const history = () => calls.filter((call) => new URL(call.url).pathname === "/api/jobs/runs");
  return { history, view };
}

function cells(row: HTMLElement | undefined) {
  return within(row as HTMLElement)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
}

test("it lists the recent runs with their outcome, newest first", async () => {
  const failed = entryAs("failed", {
    id: "older",
    attempts: 3,
    error: "MailNotDeliveredError",
    trigger: "schedule",
    triggered_by: null,
  });
  const { history, view } = await setUp({
    [HISTORY]: { body: [entryAs("succeeded"), failed] },
  });

  const table = await screen.findByRole("table", { name: CAPTION });
  const [, newest, older] = within(table).getAllByRole("row");
  expect(cells(newest)).toEqual([expect.any(String), "Run now · alice", "Succeeded", "", "0"]);
  expect(cells(older).slice(1)).toEqual(["the schedule", "Failed", "", "3"]);
  const scheduled = within(newest as HTMLElement).getByRole("button", { expanded: false });
  expect(scheduled.textContent).toMatch(OCTOBER_2_AT); // in the browser's time zone
  const asked = new URL(history()[0]?.url ?? "").searchParams;
  expect(asked.get("job")).toBe("scrape"); // its own runs only
  expect(asked.get("limit")).toBe("20");
  expect(asked.has("before")).toBe(false);
  expect(screen.queryByRole("button", { name: LOAD_OLDER })).toBeNull(); // a short page: all
  expect(await violations(view.container)).toEqual([]);
});

test("while the runs load, it says so", async () => {
  const { view } = await setUp({ [HISTORY]: () => new Promise(() => undefined) });

  const loading = await screen.findByText("Loading…", { selector: ".sr-only" });
  expect(loading.closest("[role=status]")).toBeTruthy();
  expect(await violations(view.container)).toEqual([]);
});

test("a job without runs says so", async () => {
  const { view } = await setUp({ [HISTORY]: { body: [] } });

  expect(await screen.findByText("No runs yet")).toBeTruthy();
  expect(screen.getByText(RUNS_APPEAR_HERE)).toBeTruthy();
  expect(screen.queryByRole("table", { name: CAPTION })).toBeNull();
  expect(await violations(view.container)).toEqual([]);
});

test.each(["error", "offline"] as const)(
  "an outage can be tried again in place (%s)",
  async (how) => {
    const { view } = await setUp({
      [HISTORY]: unavailableOnce({ body: [entryAs("running")] }, how),
    });

    const retry = await screen.findByRole("button", { name: "Try again" });
    expect(await violations(view.container)).toEqual([]);
    await userEvent.click(retry);

    expect(await screen.findByRole("table", { name: CAPTION })).toBeTruthy();
    expect(screen.getByText("Running")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  },
);

const page = Array.from({ length: 20 }, (_, n) => entryAs("succeeded", { id: `run-${n}` }));

test("older runs load on request, a page at a time, after the last one shown", async () => {
  const { history, view } = await setUp({
    [HISTORY]: (request: Request) =>
      new URL(request.url).searchParams.has("before")
        ? { body: [entryAs("failed", { id: "run-20" })] }
        : { body: page },
  });

  expect(await screen.findByRole("table", { name: TWENTY })).toBeTruthy();
  expect(history()).toHaveLength(1); // only on request
  expect(await violations(view.container)).toEqual([]);
  await userEvent.click(screen.getByRole("button", { name: LOAD_OLDER }));

  const table = await screen.findByRole("table", { name: TWENTY_ONE });
  expect(within(table).getAllByRole("row")).toHaveLength(22); // a header and 21 runs
  expect(cells(within(table).getAllByRole("row").at(-1))[2]).toBe("Failed"); // oldest last
  expect(screen.queryByRole("button", { name: LOAD_OLDER })).toBeNull(); // a short page: no more
  const older = new URL(history()[1]?.url ?? "").searchParams;
  expect(older.get("before")).toBe("run-19");
  expect(older.get("limit")).toBe("20");
  expect(older.get("job")).toBe("scrape");
  expect(await violations(view.container)).toEqual([]);
});

test("older runs that fail to load can be tried again, keeping those shown", async () => {
  let olderAsked = 0;
  await setUp({
    [HISTORY]: (request: Request) => {
      if (!new URL(request.url).searchParams.has("before")) {
        return { body: page };
      }
      olderAsked += 1;
      return olderAsked === 1 ? { status: 503 } : { body: [entryAs("failed", { id: "run-20" })] };
    },
  });
  await userEvent.click(await screen.findByRole("button", { name: LOAD_OLDER }));
  const retry = await screen.findByRole("button", { name: "Try again" });
  expect(screen.getByRole("table", { name: TWENTY })).toBeTruthy(); // still shown

  await userEvent.click(retry);

  expect(await screen.findByRole("table", { name: TWENTY_ONE })).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("refresh reads the newest runs again", async () => {
  const { history } = await setUp({ [HISTORY]: { body: [entryAs("succeeded")] } });
  await screen.findByRole("table", { name: CAPTION });

  await userEvent.click(screen.getByRole("button", { name: "Refresh" }));

  await screen.findByRole("table", { name: CAPTION });
  await expect.poll(() => history()).toHaveLength(2);
  expect(new URL(history()[1]?.url ?? "").searchParams.has("before")).toBe(false);
});

test("viewers see no run history", async () => {
  const calls = stubApi({
    "GET /api/auth/session": signedIn({ subject: "basic:vera", name: "vera", role: "viewer" }),
    "GET /api/config": { body: [weekly] },
  });

  renderApp("/jobs/scrape");

  expect(await screen.findByRole("heading", { level: 1, name: "Source Collection" })).toBeTruthy();
  expect(screen.queryByRole("tab", { name: "Runs" })).toBeNull();
  expect(screen.queryByRole("table")).toBeNull();
  expect(calls.filter((call) => call.url.includes("/api/jobs/"))).toEqual([]);
});
