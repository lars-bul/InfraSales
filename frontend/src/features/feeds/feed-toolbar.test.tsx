import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { violations } from "#/test/axe.ts";
import { everyFeed, stadtwerke } from "#/test/feeds.ts";
import { feedsPage, feedsRequested, names, openFilter, statuses } from "#/test/feeds-page.ts";

// Over the Feeds: the search, the filters, Clear filters and the order, all in the URL, all
// applied in place.

afterEach(() => {
  vi.useRealTimers();
});

test("a filter narrows the list in place, without asking the API again, and lives in the URL", async () => {
  const { container, calls, router } = feedsPage(everyFeed);
  await screen.findByRole("table", { name: "5 Feeds" });

  const states = await openFilter("State");
  const counted = ["OK 3", "Failing 1", "Blocked 1"]; // each state, with how many it leaves
  expect(counted.map((name) => states.getByRole("checkbox", { name }))).toHaveLength(3);
  expect(states.getAllByRole("checkbox")).toHaveLength(3);
  await userEvent.click(states.getByRole("checkbox", { name: "Failing 1" }));
  await userEvent.click(states.getByRole("checkbox", { name: "Blocked 1" }));
  await userEvent.keyboard("{Escape}");

  const table = await screen.findByRole("table", { name: "2 of 5 Feeds" });
  expect(names(table)).toEqual(["Energieatlas", "Tiefbau Aktuell"]);
  expect(screen.getByRole("button", { name: "State: Failing, Blocked" })).toBeTruthy();
  expect(router.state.location.search).toEqual({ state: "failing,blocked" });
  expect(statuses()).toContain("2 of 5 Feeds");
  expect(await violations(container)).toEqual([]);

  const kinds = await openFilter("Kind");
  await userEvent.click(kinds.getByRole("checkbox", { name: "Sitemap 2" }));
  await userEvent.keyboard("{Escape}");

  expect(names(await screen.findByRole("table", { name: "2 of 5 Feeds" }))).toEqual([
    "Energieatlas",
    "Tiefbau Aktuell",
  ]);
  expect(router.state.location.search).toEqual({ state: "failing,blocked", kind: "sitemap" });

  await userEvent.click(screen.getByRole("button", { name: "Remove the filter State" }));
  await userEvent.click(screen.getByRole("button", { name: "Kind: Sitemap" }));
  await userEvent.click(await screen.findByRole("checkbox", { name: "RSS 3" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "Sitemap 2" }));
  await userEvent.keyboard("{Escape}");

  expect(names(await screen.findByRole("table", { name: "3 of 5 Feeds" }))).toEqual([
    "Heizwerk Journal",
    "Ratsinfo Ulm",
    "Stadtwerke Heidelberg",
  ]);
  expect(router.state.location.search).toEqual({ kind: "rss" });
  expect(feedsRequested(calls)).toHaveLength(1);
});

test("Sources and last read filter by yes or no and by staleness", async () => {
  const { router } = feedsPage(everyFeed);
  await screen.findByRole("table", { name: "5 Feeds" });

  const sources = await openFilter("Sources");
  await userEvent.click(sources.getByRole("button", { name: "None yet" }));

  expect(names(await screen.findByRole("table", { name: "1 of 5 Feeds" }))).toEqual([
    "Ratsinfo Ulm",
  ]);
  expect(screen.getByRole("button", { name: "Sources: None yet" })).toBeTruthy();
  expect(router.state.location.search).toEqual({ sources: "none" });

  await userEvent.click(screen.getByRole("button", { name: "Remove the filter Sources" }));
  const read = await openFilter("Last read");
  await userEvent.click(read.getByRole("checkbox", { name: "Not read in 24 hours 1" }));
  await userEvent.keyboard("{Escape}");

  expect(names(await screen.findByRole("table", { name: "1 of 5 Feeds" }))).toEqual([
    "Energieatlas",
  ]);
  expect(router.state.location.search).toEqual({ read: "stale" });
});

test("filters in the URL show as chips; values the page does not know are dropped", async () => {
  const { router } = feedsPage(
    everyFeed,
    "/feeds?kind=rss,html,sitemap&category=press&sources=has&sort=nonsense",
  );

  const table = await screen.findByRole("table", { name: "2 of 5 Feeds" });

  expect(names(table)).toEqual(["Heizwerk Journal", "Tiefbau Aktuell"]);
  expect(screen.getByRole("button", { name: "Kind: RSS, Sitemap" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Category: Press" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Sources: Has Sources" })).toBeTruthy();
  expect(router.state.location.search).toEqual({
    kind: "rss,sitemap",
    category: "press",
    sources: "has",
  });
});

test("the search finds Feeds by name or address after a pause in typing", async () => {
  const { router } = feedsPage(everyFeed);
  await screen.findByRole("table", { name: "5 Feeds" });

  await userEvent.type(screen.getByRole("searchbox", { name: "Search" }), "sitemap");

  expect(names(await screen.findByRole("table", { name: "2 of 5 Feeds" }))).toEqual([
    "Energieatlas",
    "Tiefbau Aktuell",
  ]);
  expect(router.state.location.search).toEqual({ q: "sitemap" });
});

test("nothing matching says so; Clear filters lifts the filters and the search at once", async () => {
  const { container, router } = feedsPage(
    everyFeed,
    `/feeds?${new URLSearchParams({ q: "heizwerk", state: "blocked" })}`,
  );

  expect(await screen.findByText("No Feeds match")).toBeTruthy();
  expect(screen.getByText("Change the search or the filters to see more Feeds.")).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
  expect(statuses()).toContain("0 of 5 Feeds");
  expect(await violations(container)).toEqual([]);

  await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));

  expect(await screen.findByRole("table", { name: "5 Feeds" })).toBeTruthy();
  expect(router.state.location.search).toEqual({});
  expect((screen.getByRole("searchbox", { name: "Search" }) as HTMLInputElement).value).toBe("");
});

test("the Feeds can be sorted, each order named with its direction", async () => {
  const { router } = feedsPage([
    ...everyFeed,
    { ...stadtwerke, id: "x", name: "Ars", sources: 90 },
  ]);
  const sort = await screen.findByRole("combobox", { name: "Sort by" });
  expect(
    within(sort)
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual([
    "Name (A–Z)",
    "Last read (oldest first)",
    "State (failing first)",
    "Sources (most first)",
  ]);

  await userEvent.selectOptions(sort, "Last read (oldest first)");

  const table = screen.getByRole("table", { name: "6 Feeds" });
  expect(names(table)).toEqual([
    "Ratsinfo Ulm",
    "Energieatlas",
    "Tiefbau Aktuell",
    "Heizwerk Journal",
    "Ars",
    "Stadtwerke Heidelberg",
  ]);
  expect(router.state.location.search).toEqual({ sort: "read" });

  await userEvent.selectOptions(sort, "State (failing first)");
  expect(names(table).slice(0, 2)).toEqual(["Tiefbau Aktuell", "Energieatlas"]);

  await userEvent.selectOptions(sort, "Sources (most first)");
  expect(names(table)[0]).toBe("Ars");

  await userEvent.selectOptions(sort, "Name (A–Z)");
  expect(router.state.location.search).toEqual({});
});
