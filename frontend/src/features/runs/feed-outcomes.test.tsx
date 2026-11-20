import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import type { RunHistoryEntry } from "#/client/types.gen.ts";
import { violations } from "#/test/axe.ts";
import { scrape } from "#/test/entries.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { collected, entryAs, feedRead } from "#/test/runs.ts";
import { summaries } from "#/test/summaries.ts";
import { alice, signedIn } from "#/test/users.ts";

// What a Source Collection run did, Feed by Feed, in its expanded row of the run history.
const CAPTION = /most recent runs/;
const FEEDS_READ = /Feeds? read/;

/** Source Collection's page as alice (an admin) opens it, with `run` expanded. */
async function expanded(run: RunHistoryEntry) {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [scrape] },
    "GET /api/jobs/scrape/runs/active": { body: null },
    "GET /api/jobs/runs": { body: [run] },
    ...summaries,
  });
  const view = renderApp("/jobs/scrape");
  const table = await screen.findByRole("table", { name: CAPTION });
  const [, row] = within(table).getAllByRole("row");
  await userEvent.click(within(row as HTMLElement).getByRole("button", { expanded: false }));
  return view;
}

/** Each row's parts as text: its header, then its cells. */
const texts = (row: HTMLElement) =>
  [...within(row).queryAllByRole("rowheader"), ...within(row).queryAllByRole("cell")].map(
    (part) => part.textContent,
  );

test("a Source Collection run's details tell what each Feed gave, in words and numbers", async () => {
  const heizwerk = { items: 20, new: 14, unchanged: 2, known: 3, seen: 1, seconds: 61.25 };
  const result = collected({
    feeds_read: 3,
    failed_feeds: [{ feed: "trassenbau-report", reason: "http 404" }],
    feeds: [
      feedRead("heizwerk-journal-test", heizwerk),
      feedRead("trassenbau-report", { reason: "http 404", seconds: 0.4 }),
      feedRead("slow", { items: 3, new: 1, unread: 2, out_of_time: true, seconds: 150 }),
    ],
  });
  const view = await expanded(entryAs("succeeded", { id: "1", job: "scrape", result }));

  const feeds = screen.getByRole("table", {
    name: "The 3 Feeds read, in order, and what each gave",
  });
  const [header, ...read] = within(feeds).getAllByRole("row");
  expect(
    within(header as HTMLElement)
      .getAllByRole("columnheader")
      .map((c) => c.textContent),
  ).toEqual([
    "Feed",
    "Outcome",
    "Listed",
    "New",
    "Unchanged",
    "Not due",
    "Duplicates",
    "Skipped",
    "Time",
  ]);
  expect(read.map(texts)).toEqual([
    ["heizwerk-journal-test", "Read", "20", "14", "2", "3", "1", "0", "61.3s"],
    ["trassenbau-report", "Failed: http 404", "0", "0", "0", "0", "0", "0", "0.4s"],
    ["slow", "Out of time: 2 left", "3", "1", "0", "0", "0", "0", "150s"],
  ]);
  const icons = read.map((row) => within(row).getAllByRole("cell")[0]?.querySelector("svg"));
  expect(icons.map((icon) => icon?.getAttribute("aria-hidden"))).toEqual(["true", "true", "true"]);
  expect(screen.queryByText("Failed Feeds")).toBeNull(); // the table says which failed
  // Nine columns: in the shared frame, which scrolls sideways within reach of the keyboard.
  const frame = feeds.closest("section");
  expect([frame?.tabIndex, frame?.getAttribute("aria-labelledby")]).toEqual([
    0,
    feeds.querySelector("caption")?.id,
  ]);
  expect(await violations(view.container)).toEqual([]);
});

test("a Feed out of time before it was listed says so", async () => {
  const slow = feedRead("slow", { unread: null, out_of_time: true });
  await expanded(
    entryAs("succeeded", { id: "1", job: "scrape", result: collected({ feeds: [slow] }) }),
  );

  const feeds = screen.getByRole("table", { name: "The one Feed read, and what it gave" });
  expect(within(feeds).getByRole("cell", { name: "Out of time: not listed" })).toBeTruthy();
});

test("a Source Collection result stored before Feeds were kept lists only the failed ones", async () => {
  const result = collected({ failed_feeds: [{ feed: "stadtwerk-news", reason: "timeout" }] }); // no `feeds`
  await expanded(entryAs("succeeded", { id: "1", job: "scrape", result }));

  expect(screen.getByText("stadtwerk-news: timeout")).toBeTruthy();
  expect(screen.queryByRole("table", { name: FEEDS_READ })).toBeNull();
});

test("a Feed that met other sites' bot walls is read, and names those sites", async () => {
  const hn = feedRead("stadtwerke-heidelberg", {
    items: 50,
    new: 40,
    failed: 6,
    walled: ["medium.com", "neowin.net"],
  });
  await expanded(
    entryAs("succeeded", { id: "1", job: "scrape", result: collected({ feeds: [hn] }) }),
  );

  const feeds = screen.getByRole("table", { name: "The one Feed read, and what it gave" });
  expect(
    within(feeds).getByRole("cell", { name: "Read Bot wall: medium.com and neowin.net" }),
  ).toBeTruthy();
});
