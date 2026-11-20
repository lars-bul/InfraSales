import { describe, expect, test } from "vitest";
import type { FeedRead } from "#/client/types.gen.ts";
import {
  energieatlas,
  everyFeed,
  heizwerk,
  ratsinfo,
  stadtwerke,
  tiefbauAktuell,
} from "#/test/feeds.ts";
import {
  barSearchOf,
  barValuesOf,
  type FeedFilters,
  feedFiltersOf,
  feedSearchIn,
  groupedBy,
  inView,
  isStale,
  matches,
  narrowed,
  shownFeeds,
  sorted,
} from "./feed-filters.ts";

// Friday 2026-10-16, 12:00 UTC.
const NOW = new Date("2026-10-16T12:00:00Z");
const NONE: FeedFilters = feedFiltersOf({});

const names = (feeds: FeedRead[]) => feeds.map((feed) => feed.name);
const where = (filters: Partial<FeedFilters>) =>
  names(everyFeed.filter((feed) => matches(feed, { ...NONE, ...filters }, NOW)));

test("the URL's search parameters keep what they know, in the known order, once each", () => {
  expect(
    feedSearchIn({
      view: "attention",
      q: "  heizwerk ",
      state: "blocked,failing,blocked",
      kind: "sitemap,api:made-up",
      category: ["authority", "press"],
      sources: "none",
      read: "never,stale",
      sort: "sources",
      group: "category",
    }),
  ).toEqual({
    view: "attention",
    q: "heizwerk",
    state: "failing,blocked",
    kind: "sitemap",
    category: "press,authority",
    sources: "none",
    read: "stale,never",
    sort: "sources",
    group: "category",
  });
});

test("the URL's search parameters drop values they do not know, and the defaults", () => {
  expect(
    feedSearchIn({
      view: "all",
      q: "   ",
      state: "broken",
      kind: "html,rss",
      category: "blog",
      sources: "yes",
      read: "today",
      sort: "name",
      group: "feed",
      other: "kept out",
    }),
  ).toEqual({
    view: undefined,
    q: undefined,
    state: undefined,
    kind: "rss",
    category: undefined,
    sources: undefined,
    read: undefined,
    sort: undefined,
    group: undefined,
  });
});

test("the URL's search parameters take words the router read as a number", () => {
  expect(feedSearchIn({ q: 2026 }).q).toBe("2026");
});

test("the URL's search parameters become filters: lists, a yes or no, the view and order by default", () => {
  expect(feedFiltersOf({})).toEqual({
    view: "all",
    q: undefined,
    state: [],
    kind: [],
    category: [],
    sources: undefined,
    read: [],
    sort: "name",
    group: undefined,
  });
  expect(
    feedFiltersOf({ state: "ok,failing", sources: "has", sort: "read", group: "kind" }),
  ).toMatchObject({ state: ["ok", "failing"], sources: true, sort: "read", group: "kind" });
  expect(feedFiltersOf({ sources: "none" }).sources).toBe(false);
});

describe("the filter bar's values", () => {
  test("hold only the filters set", () => {
    expect(barValuesOf(NONE)).toEqual({});
    expect(
      barValuesOf({
        ...NONE,
        kind: ["rss"],
        category: ["utility"],
        sources: false,
        read: ["never"],
      }),
    ).toEqual({ kind: ["rss"], category: ["utility"], sources: false, read: ["never"] });
  });

  test("go back to the URL with every field, those not set undefined", () => {
    expect(barSearchOf({ state: ["blocked", "ok"], sources: true })).toEqual({
      state: "ok,blocked",
      kind: undefined,
      category: undefined,
      sources: "has",
      read: undefined,
    });
    expect(barSearchOf({ sources: false, kind: ["made-up"] })).toMatchObject({
      sources: "none",
      kind: undefined,
    });
  });

  test("survive the round trip", () => {
    const search = feedSearchIn({ state: "failing", kind: "rss,sitemap", sources: "has" });
    expect(barSearchOf(barValuesOf(feedFiltersOf(search)))).toEqual({
      state: "failing",
      kind: "rss,sitemap",
      category: undefined,
      sources: "has",
      read: undefined,
    });
  });
});

describe("the views", () => {
  test("needs attention: on, and failing or blocked", () => {
    expect(names(everyFeed.filter((feed) => inView(feed, "attention")))).toEqual([
      "Energieatlas",
      "Tiefbau Aktuell",
    ]);
    expect(inView({ ...tiefbauAktuell, enabled: false }, "attention")).toBe(false);
  });

  test("disabled: the Feeds switched off, whatever their state", () => {
    expect(names(everyFeed.filter((feed) => inView(feed, "disabled")))).toEqual(["Ratsinfo Ulm"]);
    expect(everyFeed.every((feed) => inView(feed, "all"))).toBe(true);
  });
});

describe("the filters", () => {
  test("search the name and the address, any case, every word", () => {
    expect(where({ q: "HEIZWERK" })).toEqual(["Heizwerk Journal"]);
    expect(where({ q: "tiefbau-aktuell.test sitemap" })).toEqual(["Tiefbau Aktuell"]);
    expect(where({ q: "ulm feed" })).toEqual(["Ratsinfo Ulm"]);
    expect(where({ q: "heizwerk sitemap" })).toEqual([]);
  });

  test("of one field match any of its values; of several fields, all of them", () => {
    expect(where({ state: ["failing", "blocked"] })).toEqual(["Energieatlas", "Tiefbau Aktuell"]);
    expect(where({ kind: ["sitemap"] })).toEqual(["Energieatlas", "Tiefbau Aktuell"]);
    expect(where({ kind: ["sitemap"], state: ["failing"] })).toEqual(["Tiefbau Aktuell"]);
  });

  test("by category", () => {
    const feeds = [heizwerk, { ...energieatlas, category: "authority" as const }];
    const filters = { ...NONE, category: ["authority" as const] };
    expect(names(feeds.filter((feed) => matches(feed, filters, NOW)))).toEqual(["Energieatlas"]);
  });

  test("by Sources: some collected, or none yet", () => {
    expect(where({ sources: false })).toEqual(["Ratsinfo Ulm"]);
    expect(where({ sources: true })).toHaveLength(4);
  });

  test("none yet are those Delete is offered for, though no Source is listed under one", () => {
    const moved = { ...heizwerk, sources: 0 }; // its Sources' latest versions came from other Feeds
    const filters = { ...NONE, sources: false };
    expect(matches(moved, filters, NOW)).toBe(false);
    expect(matches(moved, { ...filters, sources: true }, NOW)).toBe(true);
  });

  test("never read: whether on or not", () => {
    expect(where({ read: ["never"] })).toEqual(["Ratsinfo Ulm"]);
  });

  test("stale: a Feed on that was never read, or not for more than 24 hours", () => {
    const never = { ...heizwerk, last_scraped_at: null };
    expect(isStale(never, NOW)).toBe(true);
    expect(isStale({ ...heizwerk, last_scraped_at: "2026-10-15T12:00:00Z" }, NOW)).toBe(false); // 24 h
    expect(isStale({ ...heizwerk, last_scraped_at: "2026-10-15T11:59:59Z" }, NOW)).toBe(true);
    expect(isStale({ ...never, enabled: false }, NOW)).toBe(false); // off: nobody waits for it
    expect(where({ read: ["stale"] })).toEqual(["Energieatlas"]);
    expect(where({ read: ["stale", "never"] })).toEqual(["Energieatlas", "Ratsinfo Ulm"]);
  });

  test("stale depends on now", () => {
    const later = new Date("2026-10-17T12:00:00Z");
    expect(isStale(heizwerk, NOW)).toBe(false);
    expect(isStale(heizwerk, later)).toBe(true);
  });

  test("narrow the list once any is set", () => {
    expect(narrowed(NONE)).toBe(false);
    expect(narrowed({ ...NONE, view: "disabled", sort: "state", group: "state" })).toBe(false);
    expect(narrowed({ ...NONE, q: "heizwerk" })).toBe(true);
    expect(narrowed({ ...NONE, sources: false })).toBe(true);
  });
});

describe("the order", () => {
  const order = (sort: FeedFilters["sort"], feeds = everyFeed) => names(sorted(feeds, sort));

  test("is by name unless chosen otherwise, any case", () => {
    expect(order("name", [tiefbauAktuell, heizwerk, ratsinfo])).toEqual([
      "Heizwerk Journal",
      "Ratsinfo Ulm",
      "Tiefbau Aktuell",
    ]);
  });

  test("least recently read: never read first, then the oldest", () => {
    expect(order("read")).toEqual([
      "Ratsinfo Ulm",
      "Energieatlas",
      "Tiefbau Aktuell",
      "Heizwerk Journal",
      "Stadtwerke Heidelberg",
    ]);
  });

  test("failing first, then blocked, then OK by name", () => {
    expect(order("state")).toEqual([
      "Tiefbau Aktuell",
      "Energieatlas",
      "Heizwerk Journal",
      "Ratsinfo Ulm",
      "Stadtwerke Heidelberg",
    ]);
  });

  test("most Sources first, ties by name", () => {
    expect(
      order("sources", [ratsinfo, tiefbauAktuell, { ...heizwerk, sources: 40 }, stadtwerke]),
    ).toEqual(["Heizwerk Journal", "Stadtwerke Heidelberg", "Tiefbau Aktuell", "Ratsinfo Ulm"]);
  });
});

test("the Feeds shown: the view's, narrowed by the filters, in the order chosen", () => {
  const { inView: viewed, shown } = shownFeeds(
    everyFeed,
    { ...NONE, view: "attention", state: ["failing"], sort: "state" },
    NOW,
  );
  expect(names(viewed)).toEqual(["Energieatlas", "Tiefbau Aktuell"]);
  expect(names(shown)).toEqual(["Tiefbau Aktuell"]);
});

test("grouped, the Feeds come under their categories in order, an empty one left out", () => {
  const utility = { ...heizwerk, name: "Stadtwerke Nord", category: "utility" as const };
  const authority = { ...energieatlas, category: "authority" as const };
  const groups = groupedBy([authority, heizwerk, utility], "category");
  expect(groups.map(({ value, feeds }) => [value, names(feeds)])).toEqual([
    ["press", ["Heizwerk Journal"]],
    ["utility", ["Stadtwerke Nord"]],
    ["authority", ["Energieatlas"]],
  ]);
  expect(groupedBy([heizwerk], "category").map(({ value }) => value)).toEqual(["press"]);
});

test("grouped by state, the failing Feeds come first, then the blocked, then those OK", () => {
  const failing = { ...heizwerk, name: "Failing", state: "failing" as const };
  const blocked = { ...heizwerk, name: "Blocked", state: "blocked" as const };
  expect(
    groupedBy([heizwerk, blocked, failing], "state").map(({ value, feeds }) => [
      value,
      names(feeds),
    ]),
  ).toEqual([
    ["failing", ["Failing"]],
    ["blocked", ["Blocked"]],
    ["ok", ["Heizwerk Journal"]],
  ]);
});

test("grouped by kind, the Feeds come under their kinds in the kinds' order", () => {
  const kinds = groupedBy([energieatlas, tiefbauAktuell, heizwerk], "kind").map(
    ({ value }) => value,
  );
  expect(kinds).toEqual(["rss", "sitemap"]);
});
