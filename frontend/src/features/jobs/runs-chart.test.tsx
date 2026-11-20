import { screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { allActivity, summaries } from "#/test/summaries.ts";
import { alice, signedIn } from "#/test/users.ts";

const STRIP = "All jobs, last 7 days";

// The Job runs page as alice (an admin) opens it: the strip above every job's runs, none yet.
const admin = {
  "GET /api/auth/session": signedIn(alice),
  "GET /api/jobs/runs": { body: [] },
};

test("the chart has a table for those who cannot see it, a day a row, split by result", async () => {
  stubApi({ ...admin, ...summaries });
  renderApp("/runs");

  const strip = await screen.findByRole("region", { name: STRIP });
  const table = await within(strip).findByRole("table", { name: "Runs per day" });

  const rows = within(table)
    .getAllByRole("row")
    .map((row) => Array.from((row as HTMLTableRowElement).cells, (cell) => cell.textContent));
  expect(rows).toEqual([
    ["Day", "Succeeded", "Failed"],
    ["Sat, Oct 10", "3", "0"],
    ["Sun, Oct 11", "2", "1"],
    ["Mon, Oct 12", "3", "0"],
    ["Tue, Oct 13", "2", "0"],
    ["Wed, Oct 14", "3", "1"],
    ["Thu, Oct 15", "2", "0"],
    ["Fri, Oct 16", "3", "0"],
  ]);
});

test("up to two days are counted an hour a bar, each hour named", async () => {
  const hour = (time: string) => new Date(`2026-10-16T${time}`).toISOString();
  const buckets = [
    { start: hour("10:00"), succeeded: 1, failed: 0 },
    { start: hour("11:00"), succeeded: 0, failed: 2 },
  ];
  stubApi({
    ...admin,
    "GET /api/jobs/runs/activity": { body: { ...allActivity, unit: "hour", buckets } },
  });
  renderApp("/runs");

  const strip = await screen.findByRole("region", { name: STRIP });
  const table = await within(strip).findByRole("table", { name: "Runs per hour" });

  const rows = within(table)
    .getAllByRole("row")
    .map((row) => Array.from((row as HTMLTableRowElement).cells, (cell) => cell.textContent));
  expect(rows).toEqual([
    ["Hour", "Succeeded", "Failed"],
    ["Fri, Oct 16, 10 AM", "1", "0"],
    ["Fri, Oct 16, 11 AM", "0", "2"],
  ]);
  expect(within(strip).getByText("Runs per hour", { selector: "p" })).toBeTruthy();
});

test("the bars are a picture only: screen readers get the table instead", async () => {
  stubApi({ ...admin, ...summaries });
  const { container } = renderApp("/runs");

  const strip = await screen.findByRole("region", { name: STRIP });
  await within(strip).findByRole("table");

  const chart = strip.querySelector("svg");
  expect(chart?.getAttribute("aria-hidden")).toBe("true");
  expect(chart?.querySelectorAll("rect[style]")).toHaveLength(0); // the CSP forbids inline styles
  expect(await violations(container)).toEqual([]);
});
