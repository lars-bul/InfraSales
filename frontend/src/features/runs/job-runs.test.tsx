import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { entryAs, noRuns } from "#/test/runs.ts";
import { summaries } from "#/test/summaries.ts";
import { alice, signedIn, vera } from "#/test/users.ts";

// The Job runs page, as an admin uses it: every job's runs, filtered in the URL, under the runs
// filtered at a glance (the last 7 days, unless a start or an end is chosen).
const RUNS = "/api/jobs/runs";
const SINCE = /^All jobs, since Oct 10, 2026/;

function jobRuns(address: string, replies: Parameters<typeof stubApi>[0] = {}) {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    [`GET ${RUNS}`]: noRuns,
    ...summaries,
    ...replies,
  });
  const asked = () =>
    calls
      .map((call) => new URL(call.url))
      .filter((url) => url.pathname === RUNS)
      .map((url) => Object.fromEntries(url.searchParams));
  return { asked, ...renderApp(address) };
}

test("every job's runs are listed, newest first, under every job's last 7 days", async () => {
  const { asked, container } = jobRuns("/runs", {
    [`GET ${RUNS}`]: {
      body: [entryAs("succeeded", { id: "2", job: "scrape" }), entryAs("failed", { id: "1" })],
    },
  });

  const table = await screen.findByRole("table", { name: "The 2 most recent runs, newest first" });

  expect(
    within(table)
      .getAllByRole("link")
      .map((link) => link.textContent),
  ).toEqual(["Source Collection", "Source Collection"]);
  expect(asked()).toEqual([{ limit: "20" }]); // no filter: every job's
  const overview = screen.getByRole("region", { name: "All jobs, last 7 days" });
  expect(within(overview).getByText("20")).toBeTruthy(); // every job's runs
  const tabs = within(screen.getByRole("navigation", { name: "Jobs and job runs" }));
  expect(tabs.getByRole("link", { name: "Job runs" }).getAttribute("aria-current")).toBe("page");
  expect(await violations(container)).toEqual([]);
});

test("the filters in the URL pick the runs asked for, and the overview names the job", async () => {
  const { asked } = jobRuns(
    `/runs?${new URLSearchParams({ job: "scrape", status: "failed", trigger: "manual" })}`,
  );

  await screen.findByText("No matching runs");

  expect(asked()).toEqual([{ limit: "20", job: "scrape", status: "failed", trigger: "manual" }]);
  const overview = screen.getByRole("region", { name: "Source Collection, last 7 days" });
  expect(within(overview).getByText("20")).toBeTruthy(); // the Source Collection's runs
});

test("a filter chosen asks for its runs and goes in the URL, to be linked to", async () => {
  const { asked, router } = jobRuns("/runs");
  const trigger = await screen.findByRole("combobox", { name: "Started by" });

  await userEvent.selectOptions(trigger, "The schedule");

  await expect.poll(() => asked().at(-1)).toEqual({ limit: "20", trigger: "schedule" });
  expect(router.state.location.search).toEqual({ trigger: "schedule" });
});

test("a start and an end narrow the runs listed and the strip alike, in the URL", async () => {
  const { asked } = jobRuns(`/runs?${new URLSearchParams({ start: "2026-10-10T10:00" })}`);

  await screen.findByText("No matching runs");

  expect(asked()).toEqual([{ limit: "20", start: new Date("2026-10-10T10:00").toISOString() }]);
  expect(screen.getByRole("region", { name: SINCE })).toBeTruthy();
});

test("without any runs and without filters, it says no runs yet", async () => {
  const { container } = jobRuns("/runs");

  expect(await screen.findByText("No runs yet")).toBeTruthy();
  expect(await violations(container)).toEqual([]);
});

test("viewers are led to the Dashboard instead", async () => {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(vera),
    "GET /api/config": { body: [] },
  });
  const { router } = renderApp("/runs?job=scrape");

  await expect.poll(() => router.state.location.pathname).toBe("/");
  expect(calls.filter((call) => call.url.includes("/api/jobs/"))).toEqual([]);
});
