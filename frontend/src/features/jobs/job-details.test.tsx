import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import type { ConfigEntryRead } from "#/client/types.gen.ts";
import { violations } from "#/test/axe.ts";
import { scrape, weekly } from "#/test/entries.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { summaries } from "#/test/summaries.ts";
import { alice, signedIn, vera } from "#/test/users.ts";

// Monday 2026-10-05, 05:50 in Berlin: Source Collection (every 3 hours) runs in 10 min.
const NOW = new Date("2026-10-05T03:50:00Z");

afterEach(() => {
  vi.useRealTimers();
});

function detailsOf(user: typeof alice | typeof vera, entry: ConfigEntryRead) {
  stubApi({
    "GET /api/auth/session": signedIn(user),
    "GET /api/config": { body: [entry, weekly] },
    "GET /api/jobs/scrape/runs/active": { body: null },
    "GET /api/jobs/runs": { body: [] },
    ...summaries,
  });
  return renderApp("/jobs/scrape");
}

// The panel's terms and what each says: [["Job ID", "scrape"], ...].
function described(panel: HTMLElement): [string | null, string | null][] {
  const values = within(panel).getAllByRole("definition");
  return within(panel)
    .getAllByRole("term")
    .map((term, index) => [term.textContent, values[index]?.textContent ?? null]);
}

test("the panel says what the job is and does, when it runs and next, and that it is on", async () => {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
  const { container } = detailsOf(vera, scrape);

  const panel = await screen.findByRole("complementary", { name: "Job details" });

  expect(described(panel)).toEqual([
    ["Job ID", "scrape"],
    ["Description", "Reads every Feed and records the new Source Versions."],
    ["Schedule", "Every day, every 3 hours (Europe/Berlin)"],
    ["Next run", "in 10 min"],
    ["Status", "On"],
  ]);
  expect(within(panel).queryByRole("link")).toBeNull(); // viewers may not read the runs
  expect(await violations(container)).toEqual([]);
});

test("a paused job is not scheduled", async () => {
  const off = { ...scrape, value: { ...scrape.value, enabled: false }, next_run_at: null };
  detailsOf(vera, off);

  const panel = await screen.findByRole("complementary", { name: "Job details" });

  expect(described(panel).slice(3)).toEqual([
    ["Next run", "Not scheduled"],
    ["Status", "Paused"],
  ]);
});

test("admins follow the panel's link to the job's runs in the Job runs list", async () => {
  const { router } = detailsOf(alice, scrape);
  const panel = await screen.findByRole("complementary", { name: "Job details" });

  await userEvent.click(within(panel).getByRole("link", { name: "All runs of Source Collection" }));

  expect(router.state.location.pathname).toBe("/runs");
  expect(router.state.location.search).toEqual({ job: "scrape" });
  expect(await screen.findByRole("combobox", { name: "Job" })).toHaveProperty("value", "scrape");
});
