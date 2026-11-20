import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import type { ConfigEntryRead } from "#/client/types.gen.ts";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { stubApi, unavailableOnce } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { entryAs } from "#/test/runs.ts";
import { alice, signedIn, vera } from "#/test/users.ts";

// Monday 2026-10-05, 05:50 in Berlin: the Source Collection (08:00) runs in 2 h 10 min.
const NOW = new Date("2026-10-05T03:50:00Z");
const CAPTION = /^\d+ (of \d+ )?jobs?$/;
const COUNTDOWN = /^in /;
const SUCCEEDED_OCT_2 = /^Succeeded: Oct 2, 2026/;
const FAILED_OCT_3 = /^Failed: Oct 3, 2026/;

afterEach(() => {
  vi.useRealTimers();
});

const paused: ConfigEntryRead = {
  ...weekly,
  value: { ...weekly.value, enabled: false },
  next_run_at: null,
};

/** The Jobs page as `user` opens it; every job's last runs are none, unless `runs` says. */
function jobsPage(
  user: typeof alice | typeof vera,
  entries: ConfigEntryRead[],
  runs: Parameters<typeof stubApi>[0][string] = { body: [] },
) {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(user),
    "GET /api/config": { body: entries },
    "GET /api/jobs/runs": runs,
  });
  return { calls, ...renderApp("/jobs") };
}

const table = () => screen.findByRole("table", { name: CAPTION });

function rowOf(name: string): HTMLElement {
  const link = within(screen.getByRole("table")).getByRole("link", { name });
  return link.closest("tr") as HTMLElement;
}

function headers(): (string | null)[] {
  return screen.getAllByRole("columnheader").map((header) => header.textContent);
}

test("the jobs are one table: each named to its page, with when it runs, next, and its state", async () => {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
  const { container } = jobsPage(vera, [weekly]);

  expect((await table()).querySelector("caption")?.textContent).toBe("1 job");
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Jobs");
  expect(headers()).toEqual(["Name", "Schedule", "Next run", "Status", "More"]);
  const row = within(rowOf("Source Collection"));
  expect(row.getByText("Reads every Feed and records the new Source Versions.")).toBeTruthy();
  expect(row.getByText("Mon at 08:00 (Europe/Berlin)")).toBeTruthy();
  expect(row.getByText("in 2 h 10 min")).toBeTruthy();
  expect(row.getByText("On")).toBeTruthy();
  expect(
    within(screen.getByRole("main"))
      .getByRole("link", { name: "Source Collection" })
      .getAttribute("href"),
  ).toBe("/jobs/scrape");
  expect(screen.getByRole("link", { name: "Source Collection" }).getAttribute("href")).toBe(
    "/jobs/scrape",
  );
  expect(await violations(container)).toEqual([]);
});

test("a paused job says so, and that it is not scheduled", async () => {
  const { container } = jobsPage(vera, [paused]);
  await table();

  const row = within(rowOf("Source Collection"));

  expect(row.getByText("Paused")).toBeTruthy();
  expect(row.getByText("Not scheduled")).toBeTruthy();
  expect(row.queryByText(COUNTDOWN)).toBeNull();
  expect(await violations(container)).toEqual([]);
});

test("viewers get neither the recent runs nor the Job runs tab, and no runs are asked for", async () => {
  const { calls } = jobsPage(vera, [weekly]);
  await table();

  expect(headers()).not.toContain("Recent runs");
  expect(screen.queryByRole("navigation", { name: "Jobs and job runs" })).toBeNull();
  expect(calls.filter((call) => call.url.includes("/api/jobs/"))).toEqual([]);
});

test("admins see each job's last five runs, oldest first, the places without a run as dashes", async () => {
  const { calls, container } = jobsPage(alice, [weekly], (request) => {
    const job = new URL(request.url).searchParams.get("job");
    return {
      body:
        job === "scrape"
          ? [
              entryAs("failed", { id: "newer", scheduled_for: "2026-10-03T08:00:00Z" }),
              entryAs("succeeded", { id: "older", scheduled_for: "2026-10-02T08:00:00Z" }),
            ]
          : [],
    };
  });
  await table();

  expect(headers()).toEqual(["Name", "Schedule", "Next run", "Status", "Recent runs", "More"]);
  const recent = await screen.findByRole("list", {
    name: "The last runs of Source Collection, oldest first",
  });
  const runs = within(recent)
    .getAllByRole("img")
    .map((run) => run.getAttribute("aria-label"));
  expect(runs).toEqual([
    "No run",
    "No run",
    "No run",
    expect.stringMatching(SUCCEEDED_OCT_2),
    expect.stringMatching(FAILED_OCT_3),
  ]);
  const asked = calls
    .filter((call) => new URL(call.url).pathname === "/api/jobs/runs")
    .map((call) => Object.fromEntries(new URL(call.url).searchParams));
  expect(asked).toEqual(
    expect.arrayContaining([
      { job: "scrape", limit: "5" },
      { job: "scrape", limit: "5" },
    ]),
  );
  expect(await violations(container)).toEqual([]);
});

test("a job's runs that cannot load say so in its row only", async () => {
  jobsPage(alice, [weekly], { status: 503 });
  await table();

  expect(await within(rowOf("Source Collection")).findByText("Unavailable")).toBeTruthy();
});

test("admins switch between the jobs and every job's runs by the tabs under the heading", async () => {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [weekly] },
    "GET /api/jobs/runs": { body: [] },
    "GET /api/jobs/scrape/runs/summary": { status: 503 },
  });
  const { router } = renderApp("/jobs");
  const tabs = within(await screen.findByRole("navigation", { name: "Jobs and job runs" }));
  expect(tabs.getByRole("link", { name: "Jobs" }).getAttribute("aria-current")).toBe("page");

  await userEvent.click(tabs.getByRole("link", { name: "Job runs" }));

  expect(router.state.location.pathname).toBe("/runs");
  expect(tabs.getByRole("link", { name: "Job runs" }).getAttribute("aria-current")).toBe("page");
  expect(tabs.getByRole("link", { name: "Jobs" }).getAttribute("aria-current")).toBeNull();
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Jobs");
});

test("the jobs filter by name or ID as typed, and the count says how far", async () => {
  const { container } = jobsPage(vera, [weekly]);
  await table();
  const search = screen.getByRole("searchbox", { name: "Filter by name or ID" });
  const main = () => within(screen.getByRole("main"));

  await userEvent.type(search, "COLLECT");

  expect(main().getByRole("link", { name: "Source Collection" })).toBeTruthy();
  expect(screen.getByRole("status").textContent).toBe("1 job");
  expect(await violations(container)).toEqual([]);

  await userEvent.clear(search);
  await userEvent.type(search, "SCRAPE"); // the ID, in any case

  expect(main().getByRole("link", { name: "Source Collection" })).toBeTruthy();

  await userEvent.clear(search);
  await userEvent.type(search, "report");

  expect(screen.getByText("No jobs match")).toBeTruthy();
  expect(screen.getByRole("status").textContent).toBe("0 of 1 job");
});

test("the jobs filter by state, one toggle pressed at a time; none left says so", async () => {
  const { container } = jobsPage(vera, [paused]);
  await table();
  const states = within(screen.getByRole("group", { name: "Show jobs" }));
  expect(states.getByRole("button", { name: "All" }).getAttribute("aria-pressed")).toBe("true");

  await userEvent.click(states.getByRole("button", { name: "Paused" }));

  expect(states.getByRole("button", { name: "Paused" }).getAttribute("aria-pressed")).toBe("true");
  expect(states.getByRole("button", { name: "All" }).getAttribute("aria-pressed")).toBe("false");
  expect(
    within(screen.getByRole("main")).getByRole("link", { name: "Source Collection" }),
  ).toBeTruthy();

  await userEvent.click(states.getByRole("button", { name: "On" }));

  expect(screen.getByText("No jobs match")).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.getByRole("status").textContent).toBe("0 of 1 job");
  expect(await violations(container)).toEqual([]);
});

test.each(["error", "offline"] as const)(
  "unavailable jobs can be tried again in place (%s)",
  async (how) => {
    stubApi({
      "GET /api/auth/session": signedIn(vera),
      "GET /api/config": unavailableOnce({ body: [weekly] }, how),
    });
    const { container } = renderApp("/jobs");

    const retry = await screen.findByRole("button", { name: "Try again" });
    expect(screen.getByRole("alert").textContent).toContain("unavailable");
    expect(await violations(container)).toEqual([]);
    await userEvent.click(retry);

    expect(
      await within(await screen.findByRole("main")).findByRole("link", {
        name: "Source Collection",
      }),
    ).toBeTruthy();
  },
);
