import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { stalled, stubApi, unavailableOnce } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { noRuns } from "#/test/runs.ts";
import { scrapeSummary, summaries } from "#/test/summaries.ts";
import { alice, signedIn } from "#/test/users.ts";

const base = {
  "GET /api/auth/session": signedIn(alice),
  "GET /api/config": { body: [weekly] },
  "GET /api/jobs/scrape/runs/active": { body: null },
  "GET /api/jobs/runs": noRuns,
};

// A tile's counts, each with what it counts: [["Succeeded", "3"], ["Failed", "1"]].
function counts(tile: HTMLElement): [string | null, string | null][] {
  const values = within(tile).getAllByRole("definition");
  return within(tile)
    .getAllByRole("term")
    .map((term, index) => [term.textContent, values[index]?.textContent ?? null]);
}

// The Runs tab of the job's page, open as the page opens.
async function historyTab() {
  return within(await screen.findByRole("tabpanel", { name: "Runs" }));
}

test.each([["scrape", [3, 1], [18, 2]]] as const)(
  "%s's page opens its runs with how they went in the last day and week",
  async (job, day, week) => {
    stubApi({ ...base, ...summaries });
    const { container } = renderApp(`/jobs/${job}`);

    const history = await historyTab();

    const last24h = await history.findByRole("group", { name: "Last 24 h" });
    expect(counts(last24h)).toEqual([
      ["Succeeded", String(day[0])],
      ["Failed", String(day[1])],
    ]);
    expect(counts(history.getByRole("group", { name: "Last 7 days" }))).toEqual([
      ["Succeeded", String(week[0])],
      ["Failed", String(week[1])],
    ]);
    expect(await violations(container)).toEqual([]);
  },
);

test("tiles that could not load can be tried again in place", async () => {
  stubApi({
    ...base,
    ...summaries,
    "GET /api/jobs/scrape/runs/summary": unavailableOnce({ body: scrapeSummary }, "error"),
  });
  const { container } = renderApp("/jobs/scrape");
  const history = await historyTab();

  const retry = await history.findByRole("button", { name: "Try again" });
  expect(await violations(container)).toEqual([]);
  await userEvent.click(retry);

  expect(counts(await history.findByRole("group", { name: "Last 24 h" }))).toEqual([
    ["Succeeded", "3"],
    ["Failed", "1"],
  ]);
});

test("while the summary loads, the tiles say so", async () => {
  stubApi({ ...base, ...summaries, "GET /api/jobs/scrape/runs/summary": stalled });
  const { container } = renderApp("/jobs/scrape");

  const history = await historyTab();

  expect(history.getAllByRole("status").map((status) => status.textContent)).toContain("Loading…");
  expect(await violations(container)).toEqual([]);
});
