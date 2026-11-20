import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import type { ConfigEntryRead, RunHistoryEntry } from "#/client/types.gen.ts";
import { violations } from "#/test/axe.ts";
import { scrape, weekly } from "#/test/entries.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { collected, entryAs } from "#/test/runs.ts";
import { summaries } from "#/test/summaries.ts";
import { alice, signedIn } from "#/test/users.ts";

// What each row of a job's run history tells an admin, and what it tells once expanded.
const JOBS = { scrape_schedule: "scrape", forecast_schedule: "forecast" } as const;
const CAPTION = /most recent runs/;
const OCTOBER_2 = /Oct 2, 2026/;
const LANGFUSE = /Open in Langfuse/;

/** One job's page as alice (an admin) opens it, with its runs. */
async function showRuns(entry: ConfigEntryRead, runs: RunHistoryEntry[]) {
  const job = JOBS[entry.key];
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [entry] },
    [`GET /api/jobs/${job}/runs/active`]: { body: null },
    "GET /api/jobs/runs": { body: runs },
    ...summaries,
  });
  const view = renderApp(`/jobs/${job}`);
  const table = await screen.findByRole("table", { name: CAPTION });
  const [header, ...rows] = within(table).getAllByRole("row");
  return { view, table, header: header as HTMLElement, rows };
}

const columns = (header: HTMLElement) =>
  within(header)
    .getAllByRole("columnheader")
    .map((name) => name.textContent);

function cell(row: HTMLElement | undefined, column: number) {
  return within(row as HTMLElement).getAllByRole("cell")[column] as HTMLElement;
}

const STATUS = 2;
const RESULT = 3;

test("each status reads as an icon and a word, and failed runs are tinted", async () => {
  const { view, header, rows } = await showRuns(weekly, [
    entryAs("running", { id: "4" }),
    entryAs("pending", { id: "3" }),
    entryAs("failed", { id: "2", error: "MailNotDeliveredError", attempts: 3 }),
    entryAs("succeeded", { id: "1", attempts: 1 }),
  ]);

  expect(columns(header)).toEqual(["Scheduled for", "Started by", "Status", "Result", "Attempts"]);
  expect(rows.map((row) => cell(row, STATUS).textContent)).toEqual([
    "Running",
    "Waiting",
    "Failed",
    "Succeeded",
  ]);
  for (const row of rows) {
    const icon = cell(row, STATUS).querySelector("svg");
    expect(icon?.getAttribute("aria-hidden")).toBe("true"); // the word says it
  }
  expect(cell(rows[0], STATUS).querySelector("svg")?.classList).toContain("animate-spin");
  const tinted = rows.filter((row) => row.className.includes("bg-destructive"));
  expect(tinted).toEqual([rows[2]]);
  expect(cell(rows[2], RESULT + 1).textContent).toBe("3"); // attempts, after the result
  expect(await violations(view.container)).toEqual([]);
});

test("Started by names the schedule, or Run now and who used it without their provider", async () => {
  const { view, rows } = await showRuns(weekly, [
    entryAs("succeeded", { id: "3", triggered_by: "oidc:a1b2c3" }),
    entryAs("succeeded", { id: "2", trigger: "schedule", triggered_by: null }),
    entryAs("succeeded", { id: "1", triggered_by: "basic:alice" }),
  ]);

  expect(rows.map((row) => cell(row, 1).textContent)).toEqual([
    "Run now · a1b2c3",
    "the schedule",
    "Run now · alice",
  ]);
  expect(await violations(view.container)).toEqual([]);
});

test("Source Collection runs summarise their result; failed Feeds of a success get a badge", async () => {
  const { view, header, rows } = await showRuns(scrape, [
    entryAs("running", { id: "4", job: "scrape" }),
    entryAs("failed", { id: "3", job: "scrape", error: "AllFeedsFailedError" }),
    entryAs("succeeded", {
      id: "2",
      job: "scrape",
      result: collected({
        versions_new: 42,
        failed_feeds: [
          { feed: "tiefbau-aktuell", reason: "blocked" },
          { feed: "trassenbau-report", reason: "http 404" },
          { feed: "stadtwerk-news", reason: "timeout" },
        ],
      }),
    }),
    entryAs("succeeded", { id: "1", job: "scrape", result: collected({ versions_new: 1 }) }),
  ]);

  expect(columns(header)).toEqual(["Scheduled for", "Started by", "Status", "Result", "Attempts"]);
  expect(rows.map((row) => cell(row, RESULT).textContent)).toEqual([
    "",
    "",
    "42 new Source Versions · 3 Feeds failed",
    "1 new Source Version",
  ]);
  expect(cell(rows[2], STATUS).textContent).toBe("SucceededFeeds failed");
  expect(within(cell(rows[2], STATUS)).getByText("Feeds failed").getAttribute("data-variant")).toBe(
    "warning",
  );
  expect(cell(rows[3], STATUS).textContent).toBe("Succeeded"); // no Feed failed: no badge
  expect(await violations(view.container)).toEqual([]);
});

test("a row expands by keyboard to the error, the times, the failed Feeds and Langfuse", async () => {
  const langfuse = "https://langfuse.test/project/p1/sessions/2";
  const { view, rows } = await showRuns(scrape, [
    entryAs("failed", {
      id: "2",
      job: "scrape",
      error: "AllFeedsFailedError",
      finished_at: "2026-10-02T08:05:00Z",
    }),
    entryAs("succeeded", {
      id: "1",
      job: "scrape",
      finished_at: "2026-10-02T08:04:00Z",
      langfuse_url: langfuse,
      result: collected({
        failed_feeds: [
          { feed: "tiefbau-aktuell", reason: "blocked" },
          { feed: "trassenbau-report", reason: "http 404" },
        ],
      }),
    }),
  ]);
  const toggle = within(rows[1] as HTMLElement).getByRole("button", { expanded: false });
  expect(screen.queryByText("tiefbau-aktuell")).toBeNull(); // collapsed

  toggle.focus();
  await userEvent.keyboard("{Enter}");

  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  const details = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
  const shown = within(details as HTMLElement);
  expect(shown.getByText("Failed Feeds")).toBeTruthy();
  expect(shown.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
    "tiefbau-aktuell: blocked",
    "trassenbau-report: http 404",
  ]);
  expect(shown.getByText("Scheduled for")).toBeTruthy();
  expect(shown.getByText("Finished")).toBeTruthy();
  const finished = "time[datetime='2026-10-02T08:04:00Z']";
  expect(shown.getByText(OCTOBER_2, { selector: finished })).toBeTruthy();
  expect(shown.getByRole("link", { name: LANGFUSE }).getAttribute("href")).toBe(langfuse);
  expect(shown.queryByText("Error")).toBeNull(); // it succeeded
  expect(await violations(view.container)).toEqual([]);

  const failed = within(rows[0] as HTMLElement).getByRole("button", { expanded: false });
  await userEvent.click(failed);
  const error = document.getElementById(failed.getAttribute("aria-controls") ?? "");
  expect(within(error as HTMLElement).getByText("AllFeedsFailedError")).toBeTruthy();
  expect(within(error as HTMLElement).queryByRole("link")).toBeNull(); // not traced

  await userEvent.keyboard("{Enter}"); // the focused toggle again: collapsed
  expect(failed.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByText("AllFeedsFailedError")).toBeNull();
  expect(await violations(view.container)).toEqual([]);
});

test("every job's runs name their job, linked to its page; a job no longer known by its code", async () => {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [weekly] },
    "GET /api/jobs/runs": {
      body: [
        entryAs("succeeded", { id: "3", job: "scrape", result: collected() }),
        entryAs("succeeded", { id: "2", job: "scrape" }),
        entryAs("failed", { id: "1", job: "weather" }),
      ],
    },
    "GET /api/jobs/scrape/runs/active": { body: null }, // its page, once followed
    ...summaries,
  });
  const view = renderApp("/runs");
  const table = await screen.findByRole("table", { name: CAPTION });
  const [header, ...rows] = within(table).getAllByRole("row");

  expect(columns(header as HTMLElement)).toEqual([
    "Scheduled for",
    "Job",
    "Started by",
    "Status",
    "Result",
    "Attempts",
  ]);
  const jobs = rows.map((row) => cell(row, 1));
  expect(jobs.map((job) => job.textContent)).toEqual([
    "Source Collection",
    "Source Collection",
    "weather",
  ]);
  const link = within(jobs[0] as HTMLElement).getByRole("link", { name: "Source Collection" });
  expect(link.getAttribute("href")).toBe("/jobs/scrape");
  expect(within(jobs[2] as HTMLElement).queryByRole("link")).toBeNull();
  expect(await violations(view.container)).toEqual([]);

  await userEvent.click(link);

  expect(await screen.findByRole("heading", { level: 1, name: "Source Collection" })).toBeTruthy();
});

test("a Source Collection run that collected Sources links to them", async () => {
  const user = userEvent.setup();
  const found = entryAs("succeeded", { id: "found", job: "scrape", result: collected() });
  const none = entryAs("succeeded", {
    id: "none",
    job: "scrape",
    result: collected({ versions_new: 0 }),
  });
  const { rows } = await showRuns(scrape, [found, none]);
  const [first, second] = within(rows[0] as HTMLElement)
    .getAllByRole("button", { expanded: false })
    .concat(within(rows[1] as HTMLElement).getAllByRole("button", { expanded: false }));

  await user.click(first as HTMLElement);
  await user.click(second as HTMLElement);

  const links = screen.getAllByRole("link", { name: "Show the Sources it collected" });
  expect(links.map((link) => link.getAttribute("href"))).toEqual(["/sources?run=found"]);
});
