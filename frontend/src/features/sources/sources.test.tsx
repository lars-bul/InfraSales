import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { everyFeed } from "#/test/feeds.ts";
import { stubApi, unavailableOnce } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { entryAs } from "#/test/runs.ts";
import { FIRST_RUN, listed, SOURCE_ID, secondVersion, untitled } from "#/test/sources.ts";
import { alice, signedIn, vera } from "#/test/users.ts";

const OCTOBER_17 = /^Oct 17, 2026/;
const RUN_OF_OCTOBER_16 = /^Job Run: Oct 16, 2026/;

const SOURCES = "GET /api/sources";
const COUNT = "GET /api/sources/count";

// Every Source counted: 1,171; with any filter, 34 of them.
function counted(request: Request) {
  return { body: { count: new URL(request.url).search ? 34 : 1171 } };
}

function sourcesPage(url: string, replies: Parameters<typeof stubApi>[0]) {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/feeds": { body: everyFeed },
    [COUNT]: counted,
    ...replies,
  });
  const asked = (path = "/api/sources") =>
    calls
      .filter((call) => new URL(call.url).pathname === path)
      .map((call) => new URL(call.url).searchParams);
  return { asked, ...renderApp(url) };
}

function cells(row: HTMLElement | undefined) {
  return within(row as HTMLElement)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
}

test("admins see every Source by its latest version, each leading to its page", async () => {
  const { container, asked } = sourcesPage("/sources", {
    [SOURCES]: { body: [listed(), untitled] },
  });

  const table = await screen.findByRole("table", { name: "2 Sources, newest change first" });

  expect(screen.getByRole("heading", { level: 1, name: "Sources" })).toBeTruthy();
  const [, bahnstadt, obersteBaubehoerde] = within(table).getAllByRole("row");
  expect(cells(bahnstadt)).toEqual([
    "hWärmenetz-Ausbau, jetzt auch im Nordenheizwerk-journal.test",
    "Heizwerk Journal",
    "2",
    expect.stringMatching(OCTOBER_17),
  ]);
  expect(cells(obersteBaubehoerde)?.[0]).toBe(
    "ppolicy.test/oberste-baubehoerde-guidancepolicy.testPartial",
  ); // no title
  const link = within(table).getByRole("link", { name: "Wärmenetz-Ausbau, jetzt auch im Norden" });
  expect(link.getAttribute("href")).toBe(`/sources/${SOURCE_ID}?v=2`);
  expect([asked()[0]?.get("limit"), asked()[0]?.has("q")]).toEqual(["20", false]);
  expect(await screen.findByText("1,171 Sources")).toBeTruthy(); // all of them, not those loaded
  expect(asked("/api/sources/count")).toHaveLength(1);
  expect(await violations(container)).toEqual([]);
});

test("a search and a Feed narrow the Sources, kept in the URL, and say how many match", async () => {
  const user = userEvent.setup();
  const { asked, router } = sourcesPage("/sources", { [SOURCES]: { body: [listed()] } });
  await screen.findByRole("table");

  await user.type(screen.getByRole("searchbox", { name: "Search" }), "bahnstadt");
  await user.click(screen.getByRole("button", { name: "Feed" }));
  await user.click(await screen.findByRole("checkbox", { name: "Heizwerk Journal 12" }));

  await expect
    .poll(() => router.state.location.search)
    .toEqual({ q: "bahnstadt", feed: "heizwerk-journal" });
  const last = asked().at(-1);
  expect([last?.get("q"), last?.getAll("feed")]).toEqual(["bahnstadt", ["heizwerk-journal"]]);
  expect(await screen.findByText("34 of 1,171 Sources")).toBeTruthy();
  expect(asked("/api/sources/count").at(-1)?.getAll("feed")).toEqual(["heizwerk-journal"]);
});

test("a run's Sources say whether the run found each new or changed, and the run can be lifted", async () => {
  const user = userEvent.setup();
  const firstOfTwo = { ...listed(), version: { ...secondVersion, number: 1 } };
  const { asked, router } = sourcesPage(`/sources?run=${FIRST_RUN}`, {
    [SOURCES]: { body: [listed(), firstOfTwo] },
    [`GET /api/jobs/scrape/runs/${FIRST_RUN}`]: {
      body: entryAs("succeeded", { id: FIRST_RUN, scheduled_for: "2026-10-16T06:00:00Z" }),
    },
  });

  const table = await screen.findByRole("table");
  const [, changed, found] = within(table).getAllByRole("row");
  expect(cells(changed)?.[2]).toBe("2Updated");
  expect(cells(found)?.[2]).toBe("2New");
  expect(await screen.findByRole("button", { name: RUN_OF_OCTOBER_16 })).toBeTruthy();
  expect(asked()[0]?.get("run")).toBe(FIRST_RUN);
  expect(asked("/api/sources/count")[0]?.get("run")).toBe(FIRST_RUN);

  await user.click(screen.getByRole("button", { name: "Remove the filter Job Run" }));

  await expect.poll(() => router.state.location.search).toEqual({});
});

test("a Feed's link names one Feed, as it always did", async () => {
  const { asked } = sourcesPage("/sources?feed=tiefbau-aktuell", {
    [SOURCES]: { body: [listed()] },
  });

  expect(await screen.findByRole("button", { name: "Feed: Tiefbau Aktuell" })).toBeTruthy();
  expect(asked()[0]?.getAll("feed")).toEqual(["tiefbau-aktuell"]);
});

test("without Sources it says why; with filters, that none match", async () => {
  sourcesPage("/sources", { [SOURCES]: { body: [] } });
  expect(await screen.findByText("No Sources yet")).toBeTruthy();
});

test("filters without a match say so", async () => {
  sourcesPage("/sources?partial=yes", { [SOURCES]: { body: [] } });
  expect(await screen.findByText("No matching Sources")).toBeTruthy();
});

test("a full page offers older Sources, asked for after its last version", async () => {
  const user = userEvent.setup();
  const page = Array.from({ length: 20 }, (_, n) => ({
    ...listed(),
    id: `s${n}`,
    version: { ...secondVersion, id: `v${n}` },
  }));
  const { asked } = sourcesPage("/sources?category=press", {
    [SOURCES]: (request) =>
      new URL(request.url).searchParams.has("before") ? { body: [untitled] } : { body: page },
  });

  await user.click(await screen.findByRole("button", { name: "Load older Sources" }));

  expect(
    await screen.findByRole("table", { name: "21 Sources, newest change first" }),
  ).toBeTruthy();
  expect([asked().at(-1)?.get("before"), asked().at(-1)?.getAll("category")]).toEqual([
    "v19",
    ["press"],
  ]);
});

test("refreshed, a period counted back from now is asked for from the new now", async () => {
  const user = userEvent.setup();
  const { asked } = sourcesPage(`/sources?period=${"24h"}`, { [SOURCES]: { body: [listed()] } });
  await screen.findByRole("table");
  const since = asked()[0]?.get("since");
  expect(since).toBeTruthy();
  await new Promise((resolve) => setTimeout(resolve, 5)); // time moves on

  await user.click(screen.getByRole("button", { name: "Refresh" }));

  await expect.poll(() => asked().length).toBe(2);
  expect(asked().at(-1)?.get("since")).not.toBe(since);
  expect(asked().at(-1)?.has("before")).toBe(false);
});

test("if the Sources cannot load, it offers to try again", async () => {
  const user = userEvent.setup();
  sourcesPage("/sources", { [SOURCES]: unavailableOnce({ body: [listed()] }, "error") });

  await user.click(await screen.findByRole("button", { name: "Try again" }));

  expect(await screen.findByRole("table")).toBeTruthy();
});

test("viewers are led to the Dashboard instead", async () => {
  stubApi({
    "GET /api/auth/session": signedIn(vera),
    "GET /api/config": { body: [] },
  });
  const { router } = renderApp("/sources");

  await expect.poll(() => router.state.location.pathname).toBe("/");
});
