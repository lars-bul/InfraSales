import { screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { dashboard, nextScrape } from "#/test/dashboard.ts";
import { vera } from "#/test/users.ts";

const LAST_RUNS = /^The last runs of/;

afterEach(() => {
  vi.useRealTimers();
});

// Each job in the card, as its lines read: name (and its recent runs), then its countdown.
async function jobs() {
  const card = within(await screen.findByRole("region", { name: "Next Job Runs" }));
  await card.findAllByRole("listitem");
  return {
    card,
    items: card.getAllByRole("listitem").filter((item) => item.closest("ol") === null),
  };
}

test("the job that runs next comes first, each with its countdown and a link to its page", async () => {
  dashboard(vera);

  const { card, items } = await jobs();
  expect(items.map((item) => item.textContent)).toEqual(["Source Collectionin 2 h"]);
  expect(card.getByRole("link", { name: "Source Collection" }).getAttribute("href")).toBe(
    "/jobs/scrape",
  );
  expect(card.getByRole("link", { name: "All jobs" }).getAttribute("href")).toBe("/jobs");
});

test("a paused job is not scheduled", async () => {
  dashboard(vera, {
    entries: [{ ...nextScrape, value: { ...nextScrape.value, enabled: false } }],
  });

  const { items } = await jobs();
  expect(items.map((item) => item.textContent)).toEqual(["Source CollectionNot scheduled"]);
});

test("admins see how each job's last runs went; viewers do not", async () => {
  dashboard();

  const { card } = await jobs();
  expect(
    await card.findByRole("list", { name: "The last runs of Source Collection, oldest first" }),
  ).toBeTruthy();
});

test("viewers do not see the jobs' last runs", async () => {
  dashboard(vera);

  const { card } = await jobs();
  expect(card.queryByRole("list", { name: LAST_RUNS })).toBeNull();
});
