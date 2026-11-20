import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { stalled, stubApi, unavailableOnce } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { allActivity, summaries } from "#/test/summaries.ts";
import { alice, signedIn, vera } from "#/test/users.ts";

const STRIP = "All jobs, last 7 days";
const ACTIVITY = "GET /api/jobs/runs/activity";
const BETWEEN = /^All jobs, Oct 10, 2026.+Oct 12, 2026/;
const SINCE = /^All jobs, since Oct 10, 2026/;
const UNTIL = /^All jobs, 7 days until Oct 12, 2026/;
const SUMMARY_OR_ACTIVITY = /\/summary|\/activity/;

// The Job runs page as alice (an admin) opens it: the strip above every job's runs, none yet.
const admin = {
  "GET /api/auth/session": signedIn(alice),
  "GET /api/jobs/runs": { body: [] },
};

// The strip's figures, each with what it counts: [["Runs", "25"], ...].
function figures(strip: HTMLElement): [string | null, string | null][] {
  const values = within(strip).getAllByRole("definition");
  return within(strip)
    .getAllByRole("term")
    .map((term, index) => [term.textContent, values[index]?.textContent ?? null]);
}

// What the strip asked the API for: the activity's filters, without the time zone.
function activityAsked(calls: Request[]) {
  return calls
    .map((call) => new URL(call.url))
    .filter((url) => url.pathname === "/api/jobs/runs/activity")
    .map((url) => {
      const { timezone: _, ...filters } = Object.fromEntries(url.searchParams);
      return filters;
    });
}

test("admins see the last 7 days of every job added together above the runs", async () => {
  stubApi({ ...admin, ...summaries });
  const { container } = renderApp("/runs");

  const strip = await screen.findByRole("region", { name: STRIP });
  await within(strip).findByRole("table");

  expect(figures(strip)).toEqual([
    ["Runs", "20"],
    ["Succeeded", "18 90%"],
    ["Failed", "2 10%"],
  ]);
  const [first] = screen.getAllByRole("region");
  expect(first).toBe(strip); // above the runs' table
  expect(await violations(container)).toEqual([]);
});

test("a week without runs shows zeros and no shares", async () => {
  const buckets = allActivity.buckets.map((bucket) => ({ ...bucket, succeeded: 0, failed: 0 }));
  stubApi({ ...admin, [ACTIVITY]: { body: { ...allActivity, buckets } } });
  const { container } = renderApp("/runs");

  const strip = await screen.findByRole("region", { name: STRIP });
  await within(strip).findByRole("table");

  expect(figures(strip)).toEqual([
    ["Runs", "0"],
    ["Succeeded", "0"],
    ["Failed", "0"],
  ]);
  expect(await violations(container)).toEqual([]);
});

test("while the activity loads, the strip says so", async () => {
  stubApi({ ...admin, [ACTIVITY]: stalled });
  const { container } = renderApp("/runs");

  const strip = await screen.findByRole("region", { name: STRIP });

  expect(within(strip).getByRole("status").textContent).toBe("Loading…");
  expect(await violations(container)).toEqual([]);
});

test("if the activity fails, the strip can be tried again in place", async () => {
  stubApi({ ...admin, [ACTIVITY]: unavailableOnce({ body: allActivity }, "error") });
  const { container } = renderApp("/runs");
  const strip = await screen.findByRole("region", { name: STRIP });

  const retry = await within(strip).findByRole("button", { name: "Try again" });
  expect(within(strip).queryByRole("table")).toBeNull();
  expect(await violations(container)).toEqual([]);
  await userEvent.click(retry);

  expect(await within(strip).findByRole("table")).toBeTruthy();
  expect(figures(strip)[0]).toEqual(["Runs", "20"]);
});

test("filtered to one job, the strip shows that job's week, named, and asks for it", async () => {
  const calls = stubApi({ ...admin, ...summaries });
  const { container } = renderApp("/runs?job=scrape");

  const strip = await screen.findByRole("region", { name: "Source Collection, last 7 days" });
  await within(strip).findByRole("table");

  expect(figures(strip)).toEqual([
    ["Runs", "20"],
    ["Succeeded", "18 90%"],
    ["Failed", "2 10%"],
  ]);
  expect(activityAsked(calls)).toEqual([{ job: "scrape" }]);
  expect(await violations(container)).toEqual([]);
});

test("a start and an end pick the time the strip counts, named in its title", async () => {
  const calls = stubApi({ ...admin, ...summaries });
  const range = { start: "2026-10-10T10:00", end: "2026-10-12T09:30" };
  renderApp(`/runs?${new URLSearchParams({ ...range, status: "failed" })}`);

  const strip = await screen.findByRole("region", {
    name: BETWEEN,
  });
  await within(strip).findByRole("table");

  expect(activityAsked(calls)).toEqual([
    {
      status: "failed",
      start: new Date(range.start).toISOString(),
      end: new Date(range.end).toISOString(),
    },
  ]);
});

test("with only a start, the strip counts since; with only an end, the 7 days until", async () => {
  stubApi({ ...admin, ...summaries });
  renderApp("/runs?start=2026-10-10T10:00");
  expect(await screen.findByRole("region", { name: SINCE })).toBeTruthy();
});

test("with only an end, the strip counts the 7 days until it", async () => {
  stubApi({ ...admin, ...summaries });
  renderApp("/runs?end=2026-10-12T09:30");
  expect(await screen.findByRole("region", { name: UNTIL })).toBeTruthy();
});

test("viewers opening the Job runs land on the Dashboard: no strip, and no summary is asked for", async () => {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(vera),
    "GET /api/config": { body: [weekly] },
    ...summaries,
  });
  const { container, router } = renderApp("/runs");

  await screen.findByRole("heading", { level: 1, name: "Dashboard" });

  expect(router.state.location.pathname).toBe("/");
  expect(screen.queryByRole("region", { name: STRIP })).toBeNull();
  expect(calls.filter((call) => SUMMARY_OR_ACTIVITY.test(call.url))).toEqual([]);
  expect(await violations(container)).toEqual([]);
});
