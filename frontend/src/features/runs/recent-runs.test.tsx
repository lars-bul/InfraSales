import { screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { stalled, stubApi, unavailableOnce } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { entryAs } from "#/test/runs.ts";
import { alice, signedIn } from "#/test/users.ts";

// The jobs list's Recent runs column, as an admin reads it: a job's last five runs as icons.
const RECENT = "The last runs of Source Collection, oldest first";
const RUNS = "GET /api/jobs/runs";
const OCTOBER_1 = /^Succeeded: Oct 1, 2026/;
const OCTOBER_2 = /^Failed: Oct 2, 2026/;
const OCTOBER_3 = /^Running: Oct 3, 2026/;

function jobsList(runs: Parameters<typeof stubApi>[0][string]) {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [weekly] },
    [RUNS]: runs,
  });
  return { calls, ...renderApp("/jobs") };
}

// Each place's name, as the icon is named for screen readers.
function places(list: HTMLElement): (string | null)[] {
  return within(list)
    .getAllByRole("img")
    .map((icon) => icon.getAttribute("aria-label"));
}

test("a job's last runs read oldest first, each with how it went and when; missing ones are dashes", async () => {
  const { calls, container } = jobsList({
    body: [
      entryAs("running", { id: "3", scheduled_for: "2026-10-03T08:00:00Z" }),
      entryAs("failed", { id: "2", scheduled_for: "2026-10-02T08:00:00Z" }),
      entryAs("succeeded", { id: "1", scheduled_for: "2026-10-01T08:00:00Z" }),
    ],
  });

  const list = await screen.findByRole("list", { name: RECENT });

  expect(places(list)).toEqual([
    "No run",
    "No run",
    expect.stringMatching(OCTOBER_1),
    expect.stringMatching(OCTOBER_2),
    expect.stringMatching(OCTOBER_3),
  ]);
  const asked = new URL(calls.find((call) => call.url.includes("/api/jobs/runs"))?.url ?? "");
  expect(asked.searchParams.get("job")).toBe("scrape");
  expect(asked.searchParams.get("limit")).toBe("5");
  expect(await violations(container)).toEqual([]);
});

test("while the runs load, it says so", async () => {
  const { container } = jobsList(stalled);

  const row = (
    await within(await screen.findByRole("main")).findByRole("link", { name: "Source Collection" })
  ).closest("tr");

  expect(within(row as HTMLElement).getByRole("status").textContent).toBe("Loading…");
  expect(await violations(container)).toEqual([]);
});

test("runs that could not load say so, without holding up the list", async () => {
  jobsList(unavailableOnce({ body: [] }, "error"));

  expect(await screen.findByText("Unavailable")).toBeTruthy();
  expect(
    within(screen.getByRole("main")).getByRole("link", { name: "Source Collection" }),
  ).toBeTruthy();
  expect(screen.queryByRole("list", { name: RECENT })).toBeNull();
});

test("viewers see no Recent runs, and none are asked for", async () => {
  const calls = stubApi({
    "GET /api/auth/session": signedIn({ subject: "basic:vera", name: "vera", role: "viewer" }),
    "GET /api/config": { body: [weekly] },
  });
  renderApp("/jobs");

  await within(await screen.findByRole("main")).findByRole("link", { name: "Source Collection" });

  expect(screen.queryByRole("columnheader", { name: "Recent runs" })).toBeNull();
  expect(calls.filter((call) => call.url.includes("/api/jobs/"))).toEqual([]);
});
