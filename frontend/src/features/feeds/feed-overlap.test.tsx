import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import type { FeedOverlapReport } from "#/client/types.gen.ts";
import { violations } from "#/test/axe.ts";
import { feedsAdminPage, heizwerk, requestsTo, stadtwerke, tiefbauAktuell } from "#/test/feeds.ts";
import { unavailableOnce } from "#/test/fetch.ts";

const OVERLAP = "GET /api/feeds/overlap";
const SHARES = /lists on its own/;
const PAIRS = /overlap most/;
const COUNTING = /^Counting the runs of the last 30 days/;
const ANY_COUNTING = /^Counting the runs/;
type Reply = NonNullable<Parameters<typeof feedsAdminPage>[1]>[string];

// Two weeks of runs: Tiefbau Aktuell lists mostly what others list too; an archive Feed, gone since,
// had filed some of heizwerk's addresses.
const report: FeedOverlapReport = {
  days: 14,
  runs: 42,
  feeds: [
    { feed: "tiefbau-aktuell", runs: 42, own: 30, shared: 90, own_share: 0.25 },
    { feed: "heizwerk-journal", runs: 42, own: 300, shared: 100, own_share: 0.75 },
    { feed: "stadtwerke-heidelberg", runs: 1, own: 0, shared: 0, own_share: null },
  ],
  pairs: [
    { feed: "heizwerk-journal", other: "tiefbau-aktuell", listings: 80 },
    { feed: "archive", other: "heizwerk-journal", listings: 12 },
  ],
};

// Each body row's cells, its header first, as text.
function rows(table: HTMLElement) {
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) => Array.from(row.querySelectorAll("th, td"), (cell) => cell.textContent));
}

async function openOverlap(reply: Reply = { body: report }) {
  const page = feedsAdminPage([stadtwerke, heizwerk, tiefbauAktuell], { [OVERLAP]: reply });
  await userEvent.click(await screen.findByRole("tab", { name: "Overlap" }));
  return page;
}

test("the overlap is read only once its tab is opened", async () => {
  const { calls } = feedsAdminPage([heizwerk], { [OVERLAP]: { body: report } });

  await screen.findByRole("table", { name: "1 Feed" });

  expect(screen.getByRole("tab", { name: "Feeds", selected: true })).toBeTruthy();
  expect(requestsTo(calls, OVERLAP)).toEqual([]);
});

test("admins see what each Feed lists on its own and the pairs that overlap most", async () => {
  const { container, calls } = await openOverlap();

  const shares = await screen.findByRole("table", {
    name: "What each of the 3 Feeds lists on its own, least first",
  });

  expect(screen.getByText("Counted over 42 Source Collection runs.")).toBeTruthy();
  expect(
    within(shares)
      .getAllByRole("columnheader")
      .map((head) => head.textContent),
  ).toEqual(["Feed", "Runs", "Listings", "Shared", "Own share"]);
  expect(rows(shares)).toEqual([
    ["Tiefbau Aktuell", "42", "120", "90", "25%"],
    ["Heizwerk Journal", "42", "400", "100", "75%"],
    ["Stadtwerke Heidelberg", "1", "0", "0", "Nothing listed"],
  ]);
  const pairs = screen.getByRole("table", {
    name: "The 2 pairs of Feeds that overlap most, most first",
  });
  expect(rows(pairs)).toEqual([
    ["Heizwerk Journal and Tiefbau Aktuell", "80"],
    ["archive and Heizwerk Journal", "12"], // no Feed has that slug any more: the slug shows
  ]);
  const [asked] = requestsTo(calls, OVERLAP);
  expect(new URL(asked?.url ?? "").searchParams.get("days")).toBe("14");
  expect(await violations(container)).toEqual([]);
});

test("another window asks for the runs of that many days, the last one shown busy until then", async () => {
  let answer: ((reply: { body: FeedOverlapReport }) => void) | undefined;
  const month = new Promise<{ body: FeedOverlapReport }>((resolve) => {
    answer = resolve;
  });
  const { calls, container } = await openOverlap((request) =>
    new URL(request.url).searchParams.get("days") === "30" ? month : { body: report },
  );
  await screen.findByText("Counted over 42 Source Collection runs.");

  await userEvent.selectOptions(screen.getByLabelText("Runs of the last"), "30 days");

  const counting = await screen.findByText(COUNTING);
  expect(counting.getAttribute("role")).toBe("status");
  const lastWindow = screen.getByText("Counted over 42 Source Collection runs.");
  expect(lastWindow.closest("[aria-busy]")?.getAttribute("aria-busy")).toBe("true");
  expect(await violations(container)).toEqual([]);

  answer?.({ body: { ...report, days: 30, runs: 90 } });

  expect(await screen.findByText("Counted over 90 Source Collection runs.")).toBeTruthy();
  expect(screen.queryByText(ANY_COUNTING)).toBeNull();
  expect(
    screen
      .getByText("Counted over 90 Source Collection runs.")
      .closest("[aria-busy]")
      ?.getAttribute("aria-busy"),
  ).toBe("false");
  expect(
    requestsTo(calls, OVERLAP).map((call) => new URL(call.url).searchParams.get("days")),
  ).toEqual(["14", "30"]);
});

test("without a run that counted overlap, the tab says so", async () => {
  const { container } = await openOverlap({
    body: { days: 14, runs: 0, feeds: [], pairs: [] } satisfies FeedOverlapReport,
  });

  expect(await screen.findByText("No overlap counted yet")).toBeTruthy();
  expect(screen.queryByRole("table", { name: SHARES })).toBeNull();
  expect(await violations(container)).toEqual([]);
});

test("runs where no two Feeds overlap say so instead of an empty table", async () => {
  await openOverlap({ body: { ...report, pairs: [] } });

  expect(await screen.findByText("No two Feeds overlap")).toBeTruthy();
  expect(screen.queryByRole("table", { name: PAIRS })).toBeNull();
});

test("an overlap that could not be read can be asked for again", async () => {
  await openOverlap(unavailableOnce({ body: report }, "error"));

  await userEvent.click(await screen.findByRole("button", { name: "Try again" }));

  expect(await screen.findByText("Counted over 42 Source Collection runs.")).toBeTruthy();
});
