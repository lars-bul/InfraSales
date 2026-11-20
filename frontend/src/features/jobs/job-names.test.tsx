import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { scrape } from "#/test/entries.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { summaries } from "#/test/summaries.ts";
import { alice, signedIn } from "#/test/users.ts";
import { isJob, JOB_NAMES, JOBS, jobNameKey, SCHEDULES } from "./job-names.ts";

test("each schedule starts its own job", () => {
  expect(JOB_NAMES).toEqual(["scrape", "forecast"]);
  for (const job of JOB_NAMES) {
    expect(JOBS[SCHEDULES[job]]).toBe(job);
  }
});

test("a job is named by its schedule", () => {
  expect(jobNameKey("scrape")).toBe("schedules.scrape_schedule");
  expect(jobNameKey("forecast")).toBe("schedules.forecast_schedule");
});

test.each([
  ["scrape", true],
  ["forecast", true],
  ["archive", false], // a job of an older release: its runs may still be listed
  ["weather", false],
  ["toString", false], // not a job, though every object has it
  [undefined, false],
])("%s is a job the app knows: %s", (value, known) => {
  expect(isJob(value)).toBe(known);
});

// A job's page asks the API about that job, and no other.
test("the schedule's page follows its own job", async () => {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [scrape] },
    "GET /api/jobs/scrape/runs/active": { body: null },
    "GET /api/jobs/runs": { body: [] },
    ...summaries,
  });
  renderApp("/jobs/scrape");

  await screen.findByRole("heading", { level: 1, name: "Source Collection" });
  await screen.findByRole("group", { name: "Last 24 h" });

  const asked = calls
    .map((call) => new URL(call.url))
    .filter((url) => url.pathname.startsWith("/api/jobs/"));
  const jobs = asked.map((url) =>
    url.pathname === "/api/jobs/runs" ? url.searchParams.get("job") : url.pathname.split("/")[3],
  );
  expect(new Set(jobs)).toEqual(new Set(["scrape"]));
});

test("an address naming no job leads to the jobs", async () => {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [scrape] },
    "GET /api/jobs/runs": { body: [] },
    ...summaries,
  });
  const { router } = renderApp("/jobs/archive");

  await screen.findByRole("heading", { level: 1, name: "Jobs" });
  expect(router.state.location.pathname).toBe("/jobs");
});
