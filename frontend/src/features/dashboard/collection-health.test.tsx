import { screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { FeedRead } from "#/client/types.gen.ts";
import { violations } from "#/test/axe.ts";
import { dashboard } from "#/test/dashboard.ts";
import { heizwerk, tiefbauAktuell } from "#/test/feeds.ts";

afterEach(() => {
  vi.useRealTimers();
});

async function health() {
  return within(await screen.findByRole("region", { name: "Source Collection health" }));
}

test("the card counts the week's runs, the failed ones in red, over a bar per day", async () => {
  const { container } = dashboard();
  const card = await health();

  expect(await card.findByText("20 runs in the last 7 days")).toBeTruthy();
  expect(card.getByText("2 failed").className).toContain("text-destructive");
  expect(card.getByRole("table")).toBeTruthy(); // the chart's table for screen readers
  expect(card.getByRole("link", { name: "Job runs" }).getAttribute("href")).toBe(
    "/runs?job=scrape",
  );
  expect(await violations(container)).toEqual([]);
});

test("it names the Feeds the last collection could not read, each with its state", async () => {
  dashboard();
  const card = await health();

  const list = within(await card.findByRole("list"));
  expect(card.getByRole("heading", { name: "Feeds not read" })).toBeTruthy();
  expect(list.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
    "EnergieatlasBlocked",
    "Tiefbau AktuellFailing",
  ]);
  for (const name of ["Tiefbau Aktuell", "Energieatlas"]) {
    const href = list.getByRole("link", { name }).getAttribute("href") ?? "";
    const [path, query] = href.split("?");
    expect(path).toBe("/feeds"); // that Feed among those that need attention
    expect(Object.fromEntries(new URLSearchParams(query))).toEqual({ view: "attention", q: name });
  }
});

test("at most five Feeds are named: the Feeds page lists the rest", async () => {
  const feeds: FeedRead[] = Array.from({ length: 7 }, (_, index) => ({
    ...tiefbauAktuell,
    id: `feed-${index}`,
    name: `Feed ${index}`,
  }));
  dashboard(undefined, { feeds });
  const card = await health();

  expect(within(await card.findByRole("list")).getAllByRole("listitem")).toHaveLength(5);
});

test("while every Feed was read, one calm line says so", async () => {
  dashboard(undefined, { feeds: [heizwerk] });
  const card = await health();

  expect(
    await card.findByText("Source Collection runs smoothly: every Feed was read."),
  ).toBeTruthy();
  expect(card.queryByRole("heading", { name: "Feeds not read" })).toBeNull();
});

test("a week without failures counts them calmly", async () => {
  dashboard(undefined, undefined, {
    "GET /api/jobs/runs/activity": {
      body: {
        start: "2026-10-10T00:00:00Z",
        end: "2026-10-16T12:00:00Z",
        unit: "day",
        buckets: [{ start: "2026-10-16T00:00:00Z", succeeded: 1, failed: 0 }],
      },
    },
  });
  const card = await health();

  expect(await card.findByText("1 run in the last 7 days")).toBeTruthy();
  expect(card.getByText("0 failed").className).toContain("text-muted-foreground");
});
