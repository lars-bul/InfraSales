import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { energieatlas, everyFeed } from "#/test/feeds.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { FIRST_RUN, listed } from "#/test/sources.ts";
import { alice, signedIn } from "#/test/users.ts";

const FILTERED = `/sources?${new URLSearchParams({
  feed: "tiefbau-aktuell,heizwerk-journal",
  category: "press",
  period: "7d",
  partial: "yes",
  q: "bahnstadt",
})}`;

// The Feeds of every category: two press, a municipality's, a utility's, an authority's.
const FEEDS = everyFeed.map((feed) =>
  feed === energieatlas ? { ...feed, category: "authority" as const } : feed,
);

function sourcesPage(url: string, replies: Parameters<typeof stubApi>[0] = {}) {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/feeds": { body: FEEDS },
    "GET /api/sources": { body: [listed()] },
    "GET /api/sources/count": { body: { count: 3 } },
    ...replies,
  });
  const asked = (path: string) =>
    calls
      .filter((call) => new URL(call.url).pathname === path)
      .map((call) => new URL(call.url).searchParams);
  return { calls, asked, ...renderApp(url) };
}

async function openFilter(user: ReturnType<typeof userEvent.setup>, label: string) {
  await user.click(screen.getByRole("button", { name: label }));
  return await screen.findByRole("dialog", { name: label });
}

test("the filters in the URL show as chips, and the API is asked for each", async () => {
  const { container, asked } = sourcesPage(FILTERED);

  // The Feeds load on the way: until then a chip names a Feed by its slug.
  expect(
    await screen.findByRole("button", { name: "Feed: Heizwerk Journal, Tiefbau Aktuell" }),
  ).toBeTruthy();
  for (const chip of [
    "Category: Press",
    "Last change: Last 7 days",
    "Partial: Cut off by a paywall",
  ]) {
    expect(screen.getByRole("button", { name: chip })).toBeTruthy();
  }
  expect((screen.getByRole("searchbox", { name: "Search" }) as HTMLInputElement).value).toBe(
    "bahnstadt",
  );
  const [list] = asked("/api/sources");
  expect([
    list?.getAll("feed"),
    list?.getAll("category"),
    list?.get("partial"),
    list?.get("q"),
    list?.has("since"),
    list?.has("until"),
  ]).toEqual([
    ["tiefbau-aktuell", "heizwerk-journal"],
    ["press"],
    "true",
    "bahnstadt",
    true,
    false,
  ]);
  expect(asked("/api/sources/count")[0]?.get("since")).toBe(list?.get("since"));
  await screen.findByRole("table");
  expect(await violations(container)).toEqual([]);
});

test("the Feeds are offered under their categories, with their Sources, and can be searched", async () => {
  const user = userEvent.setup();
  sourcesPage("/sources");
  await screen.findByRole("table");

  const picker = await openFilter(user, "Feed");

  const authority = within(picker).getByRole("group", { name: "Authority" });
  expect(within(authority).getByRole("checkbox", { name: "Energieatlas 12" })).toBeTruthy();
  const press = within(picker).getByRole("group", { name: "Press" });
  expect(within(press).getAllByRole("checkbox")).toHaveLength(2);
  await user.type(within(picker).getByRole("searchbox", { name: "Search Feed" }), "tief");
  expect(within(picker).getAllByRole("checkbox")).toHaveLength(1);
  expect(within(picker).getByRole("checkbox", { name: "Tiefbau Aktuell 12" })).toBeTruthy();
});

test("a category counts the Sources of its Feeds", async () => {
  const user = userEvent.setup();
  const { router, asked } = sourcesPage("/sources");
  await screen.findByRole("table");

  const picker = await openFilter(user, "Category");
  expect(within(picker).getByRole("checkbox", { name: "Press 24" })).toBeTruthy(); // 2 × 12
  await user.click(within(picker).getByRole("checkbox", { name: "Authority 12" }));

  await expect.poll(() => router.state.location.search).toEqual({ category: "authority" });
  await expect.poll(() => asked("/api/sources").at(-1)?.getAll("category")).toEqual(["authority"]);
});

test("whether a Source changed and whether it is partial are asked as yes or no", async () => {
  const user = userEvent.setup();
  const { router, asked } = sourcesPage("/sources");
  await screen.findByRole("table");

  const changed = await openFilter(user, "Changed");
  await user.click(within(changed).getByRole("button", { name: "More than one version" }));
  const partial = await openFilter(user, "Partial");
  await user.click(within(partial).getByRole("button", { name: "Whole" }));

  await expect.poll(() => router.state.location.search).toEqual({ changed: "yes", partial: "no" });
  const last = asked("/api/sources").at(-1);
  expect([last?.get("changed"), last?.get("partial")]).toEqual(["true", "false"]);
  expect(screen.getByRole("button", { name: "Changed: More than one version" })).toBeTruthy();
});

test("days of one's own run from midnight of the first until midnight after the last", async () => {
  const user = userEvent.setup();
  const { router, asked } = sourcesPage("/sources");
  await screen.findByRole("table");

  const picker = await openFilter(user, "Last change");
  await user.type(within(picker).getByLabelText("From"), "2026-10-01");
  await user.type(within(picker).getByLabelText("To"), "2026-10-20");

  await expect
    .poll(() => router.state.location.search)
    .toEqual({ period: "2026-10-01..2026-10-20" });
  await expect
    .poll(() => {
      const last = asked("/api/sources").at(-1);
      return [last?.get("since"), last?.get("until")];
    })
    .toEqual([new Date(2026, 9, 1).toISOString(), new Date(2026, 9, 21).toISOString()]);
});

test("the search waits for a pause in typing, then asks once", async () => {
  const user = userEvent.setup();
  const { calls, router } = sourcesPage("/sources");
  await screen.findByRole("table");

  await user.type(screen.getByRole("searchbox", { name: "Search" }), "fernwaerme satzung");

  await expect.poll(() => router.state.location.search).toEqual({ q: "fernwaerme satzung" });
  const searched = calls.filter(
    (call) =>
      new URL(call.url).pathname === "/api/sources" && new URL(call.url).searchParams.has("q"),
  );
  expect(searched.map((call) => new URL(call.url).searchParams.get("q"))).toEqual([
    "fernwaerme satzung",
  ]);
});

test("Clear filters lifts the filters, the search and the run at once", async () => {
  const user = userEvent.setup();
  const { router } = sourcesPage(`${FILTERED}&run=${FIRST_RUN}`, {
    [`GET /api/jobs/scrape/runs/${FIRST_RUN}`]: { status: 404, body: { detail: "none" } },
  });
  await screen.findByRole("table");
  const before = router.history.length;

  await user.click(screen.getByRole("button", { name: "Clear filters" }));

  await expect.poll(() => router.state.location.search).toEqual({});
  expect(router.history.length).toBe(before); // one change, in place
  expect((screen.getByRole("searchbox", { name: "Search" }) as HTMLInputElement).value).toBe("");
});

test("a run the service does not know is named as not found", async () => {
  sourcesPage(`/sources?run=${FIRST_RUN}`, {
    [`GET /api/jobs/scrape/runs/${FIRST_RUN}`]: { status: 404, body: { detail: "none" } },
  });

  expect(await screen.findByRole("button", { name: "Job Run: Not found" })).toBeTruthy();
  // The run is no filter to set: it comes from a run's details, and shows only then.
  const filters = screen.getByRole("group", { name: "Filters" });
  expect(within(filters).queryByRole("button", { name: "Job Run" })).toBeNull();
});
