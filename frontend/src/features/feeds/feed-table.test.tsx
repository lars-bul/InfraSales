import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { violations } from "#/test/axe.ts";
import {
  energieatlas,
  everyFeed,
  heizwerk,
  ratsinfo,
  stadtwerke,
  tiefbauAktuell,
} from "#/test/feeds.ts";
import { cells, feedsPage, feedsRequested, names } from "#/test/feeds-page.ts";

// The Feeds page's rows: name and address, state, kind, category, Sources, last read, and the
// categories' headings when grouped.

const BLOCKED =
  "The site blocks InfraSales. A person must decide what to do (a licence, an allowed user agent); InfraSales never works around it.";

afterEach(() => {
  vi.useRealTimers();
});

test("admins see every Feed: name and address, state, kind, category, Sources, last read", async () => {
  const { container, calls } = feedsPage([heizwerk]);

  const table = await screen.findByRole("table", { name: "1 Feed" });

  expect(screen.getByRole("heading", { level: 1, name: "Feeds" })).toBeTruthy();
  expect(
    within(table)
      .getAllByRole("columnheader")
      .map((head) => head.textContent),
  ).toEqual(["Name", "State", "Kind", "Category", "Sources", "Last read", "Actions"]);
  const [, row] = within(table).getAllByRole("row");
  expect(cells(row as HTMLElement)).toEqual([
    "Heizwerk Journalwww.heizwerk-journal.test/rss/heizwerk-atom.xml",
    "OK",
    "RSS",
    "Press",
    "12",
    "3 hours ago",
    "", // it has collected Sources: no Delete
  ]);
  expect(
    within(table)
      .getByText("www.heizwerk-journal.test/rss/heizwerk-atom.xml")
      .getAttribute("title"),
  ).toBe(heizwerk.url);
  const sources = within(table).getByRole("link", { name: "12 Sources of Heizwerk Journal" });
  expect(sources.getAttribute("href")).toBe("/sources?feed=heizwerk-journal");
  expect(feedsRequested(calls)).toHaveLength(1);
  expect(await violations(container)).toEqual([]);
});

test("a Feed without Sources shows 0, not a link, and may be deleted", async () => {
  feedsPage([ratsinfo]);

  const table = await screen.findByRole("table", { name: "1 Feed" });

  expect(within(table).getAllByRole("cell")[4]?.textContent).toBe("0");
  expect(within(table).queryByRole("link")).toBeNull();
  expect(within(table).getByRole("button", { name: "Delete Ratsinfo Ulm" })).toBeTruthy();
});

test.each([
  ["OK", heizwerk, ["OK"], []],
  ["Failing, the reason under its name", tiefbauAktuell, ["Failing"], ["http 404"]],
  ["Blocked, what it means under its name", energieatlas, ["Blocked"], [BLOCKED]],
  ["disabled", ratsinfo, ["OK", "Disabled"], []],
])("a Feed's state shows as a dot and its name: %s", async (_, feed, states, reasons) => {
  const { container } = feedsPage([feed]);

  const table = await screen.findByRole("table", { name: "1 Feed" });

  const [name, state] = within(table).getAllByRole("cell") as HTMLElement[];
  expect(states.map((text) => within(state as HTMLElement).getByText(text))).toHaveLength(
    states.length,
  );
  expect(reasons.map((text) => within(name as HTMLElement).getByText(text))).toHaveLength(
    reasons.length,
  );
  expect(within(table).queryByText("Disabled")).toEqual(feed.enabled ? null : expect.anything());
  expect(await violations(container)).toEqual([]);
});

test.each([
  ["3 hours ago", heizwerk],
  ["2 minutes ago", stadtwerke],
  ["1 hour ago", { ...heizwerk, last_scraped_at: "2026-10-16T11:00:20Z" }], // not "60 minutes"
  ["yesterday", tiefbauAktuell],
  ["2 days ago", energieatlas],
  ["Never", ratsinfo],
])("when a Feed was last read shows as relative time: %s", async (text, feed) => {
  feedsPage([feed]);

  const table = await screen.findByRole("table", { name: "1 Feed" });

  expect(within(table).getAllByRole("cell")[5]?.textContent).toBe(text);
});

test("a Feed not read for more than a day shows its last read in amber", async () => {
  feedsPage([energieatlas, heizwerk]);

  const table = await screen.findByRole("table", { name: "2 Feeds" });

  expect(within(table).getByText("2 days ago").className).toContain("text-warning");
  expect(within(table).getByText("3 hours ago").className).not.toContain("text-warning");
});

test("every kind of Feed has its label, the Feeds by name", async () => {
  const { container } = feedsPage(everyFeed.toReversed());

  const table = await screen.findByRole("table", { name: "5 Feeds" });

  const [, ...rows] = within(table).getAllByRole("row");
  expect(rows.map((row) => cells(row)[2])).toEqual(["Sitemap", "RSS", "RSS", "RSS", "Sitemap"]);
  expect(names(table)).toEqual([
    "Energieatlas",
    "Heizwerk Journal",
    "Ratsinfo Ulm",
    "Stadtwerke Heidelberg",
    "Tiefbau Aktuell",
  ]);
  expect(await violations(container)).toEqual([]);
});

test("grouped by category, each category heads its Feeds", async () => {
  const { container, router } = feedsPage([
    heizwerk,
    { ...energieatlas, category: "authority" },
    { ...tiefbauAktuell, name: "Stadtwerke Nord", category: "utility" },
  ]);
  await screen.findByRole("table", { name: "3 Feeds" });

  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Group by" }), "Category");

  const table = screen.getByRole("table", { name: "3 Feeds" });
  expect(
    within(table)
      .getAllByRole("rowheader")
      .map((head) => head.textContent),
  ).toEqual(["Press 1", "Utility 1", "Authority 1"]);
  expect(names(table)).toEqual(["Heizwerk Journal", "Stadtwerke Nord", "Energieatlas"]);
  expect(router.state.location.search).toEqual({ group: "category" });
  expect(await violations(container)).toEqual([]);
});

test("grouped by state or kind, each heads its Feeds; Nothing lifts the grouping", async () => {
  const { router } = feedsPage([heizwerk, energieatlas, tiefbauAktuell]);
  await screen.findByRole("table", { name: "3 Feeds" });
  const group = screen.getByRole("combobox", { name: "Group by" });
  const heads = () =>
    within(screen.getByRole("table", { name: "3 Feeds" }))
      .queryAllByRole("rowheader")
      .map((head) => head.textContent);

  await userEvent.selectOptions(group, "State");
  expect(heads()).toEqual(["Failing 1", "Blocked 1", "OK 1"]);
  expect(router.state.location.search).toEqual({ group: "state" });

  await userEvent.selectOptions(group, "Kind");
  expect(heads()).toEqual(["RSS 1", "Sitemap 2"]);

  await userEvent.selectOptions(group, "Nothing");
  expect(heads()).toEqual([]);
  expect(router.state.location.search).toEqual({});
});
