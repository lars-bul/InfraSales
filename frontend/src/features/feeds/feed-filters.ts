import type { FeedCategory, FeedKind, FeedRead, FeedState } from "#/client/types.gen.ts";
import { booleanOf, type FilterValues, optionsOf } from "#/components/filter-bar/filter-values.ts";
import { CATEGORIES } from "./categories.ts";
import { KINDS } from "./kinds.ts";
import { needsAttention, STATE_BADGES } from "./states.ts";

const LIST = ","; // the URL lists several values with commas, as the filter bar does
const WORDS = /\s+/;
const HOUR_MS = 3_600_000;
const STALE_HOURS = 24; // a Feed that is on and has not been read for a day is stale
const KIND_VALUES = Object.keys(KINDS) as FeedKind[];
const SOURCES = { has: true, none: false } as const; // the URL's words for the yes or no
const LISTED = ["state", "kind", "category", "read"] as const; // the fields of several values

// The states that need a look first: failing, then blocked, then OK.
const STATE_ORDER: Record<FeedState, number> = { failing: 0, blocked: 1, ok: 2 };

// Each grouping's values, in the order their groups show: failing Feeds' group first.
const GROUP_ORDERS: { [G in FeedGroup]: readonly FeedRead[G][] } = {
  category: CATEGORIES,
  state: Object.keys(STATE_ORDER) as FeedState[],
  kind: KIND_VALUES,
};

// Each "last read" filter's test.
const READ_TESTS = { stale: isStale, never: neverRead } as const satisfies Record<
  ReadFilter,
  (feed: FeedRead, now: Date) => boolean
>;

// Words as the router hands them: it reads "2026" as a number.
function text(value: unknown): string | undefined {
  const words = typeof value === "number" ? String(value) : value;
  return typeof words === "string" && words.trim() ? words.trim() : undefined;
}

// The value if it is one of `known`; anything else: undefined.
function oneOf<T extends string>(value: unknown, known: readonly T[]): T | undefined {
  return known.find((each) => each === text(value));
}

// "failing,blocked" (or the router's list) as the values known, in their own order, once each.
function listOf<T extends string>(value: unknown, known: readonly T[]): T[] {
  const parts = Array.isArray(value) ? value.map(text) : (text(value)?.split(LIST) ?? []);
  const given = parts.map((part) => part?.trim());
  return known.filter((each) => given.includes(each));
}

// The values as one search parameter; none: undefined, so the parameter goes.
function joined(values: readonly string[]): string | undefined {
  return values.length > 0 ? values.join(LIST) : undefined;
}

// Has Sources or none yet, in the URL's words.
function sourcesWord(sources: boolean | undefined): keyof typeof SOURCES | undefined {
  if (sources === undefined) {
    return undefined;
  }
  return sources ? "has" : "none";
}

// When a Feed was last read, as a number to order by: never comes before the oldest.
function readAt(feed: FeedRead): number {
  return feed.last_scraped_at === null
    ? Number.NEGATIVE_INFINITY
    : Date.parse(feed.last_scraped_at);
}

/** The views of the Feeds, as tabs: all of them, those that need attention, the disabled ones. */
export const VIEWS = ["all", "attention", "disabled"] as const;
export type FeedView = (typeof VIEWS)[number];

/** How the Feeds may be ordered; by name unless chosen otherwise. */
export const SORTS = ["name", "read", "state", "sources"] as const;
export type FeedSort = (typeof SORTS)[number];

/** What the Feeds may be grouped by; not grouped unless chosen. */
export const GROUPS = ["category", "state", "kind"] as const;
export type FeedGroup = (typeof GROUPS)[number];

/** How a Feed was last read: stale (on, and not read for a day or never), or never at all. */
export const READS = ["stale", "never"] as const;
export type ReadFilter = (typeof READS)[number];

/** Every state, in the order the filter offers them. */
export const STATES = Object.keys(STATE_BADGES) as FeedState[];

/** The Feeds page's search parameters, as the URL holds them; a default is left out. */
export interface FeedSearch {
  view?: Exclude<FeedView, "all"> | undefined;
  q?: string | undefined; // words in the name or the address
  state?: string | undefined; // "failing,blocked"
  kind?: string | undefined; // "rss,sitemap"
  category?: string | undefined; // "press,company"
  sources?: keyof typeof SOURCES | undefined; // has Sources, or none yet
  read?: string | undefined; // "stale", "never"
  sort?: Exclude<FeedSort, "name"> | undefined;
  group?: FeedGroup | undefined; // the Feeds under their categories, states or kinds
}

/** The filter bar's part of the search parameters: one for each of its fields. */
export type BarSearch = Pick<FeedSearch, "state" | "kind" | "category" | "sources" | "read">;

/** The filters the search parameters set, as lists and a yes or no. */
export interface FeedFilters {
  view: FeedView;
  q?: string | undefined;
  state: FeedState[];
  kind: FeedKind[];
  category: FeedCategory[];
  sources?: boolean | undefined; // true: has Sources; false: none yet
  read: ReadFilter[];
  sort: FeedSort;
  group?: FeedGroup | undefined;
}

/** The search parameters in a URL, for the route: a value it does not know is dropped. */
export function feedSearchIn(search: Record<string, unknown>): FeedSearch {
  const { view, q, state, kind, category, sources, read, sort, group } = search;
  return {
    view: oneOf(view, ["attention", "disabled"] as const),
    q: text(q),
    state: joined(listOf(state, STATES)),
    kind: joined(listOf(kind, KIND_VALUES)),
    category: joined(listOf(category, CATEGORIES)),
    sources: oneOf(sources, ["has", "none"] as const),
    read: joined(listOf(read, READS)),
    sort: oneOf(sort, ["read", "state", "sources"] as const),
    group: oneOf(group, GROUPS),
  };
}

/** The filters the search parameters set. */
export function feedFiltersOf(search: FeedSearch): FeedFilters {
  return {
    view: search.view ?? "all",
    q: search.q,
    state: listOf(search.state, STATES),
    kind: listOf(search.kind, KIND_VALUES),
    category: listOf(search.category, CATEGORIES),
    sources: search.sources === undefined ? undefined : SOURCES[search.sources],
    read: listOf(search.read, READS),
    sort: search.sort ?? "name",
    group: search.group,
  };
}

/** The filters as the filter bar holds them, by field id; one not set is left out. */
export function barValuesOf(filters: FeedFilters): FilterValues {
  const lists = LISTED.filter((id) => filters[id].length > 0).map((id) => [id, filters[id]]);
  return {
    ...Object.fromEntries(lists),
    ...(filters.sources !== undefined && { sources: filters.sources }),
  };
}

/**
 * The search parameters for what the filter bar holds: each of its fields, undefined when not
 * set, so spreading them into the URL's search lifts the filters removed.
 */
export function barSearchOf(values: FilterValues): BarSearch {
  return {
    state: joined(listOf(optionsOf(values, "state"), STATES)),
    kind: joined(listOf(optionsOf(values, "kind"), KIND_VALUES)),
    category: joined(listOf(optionsOf(values, "category"), CATEGORIES)),
    sources: sourcesWord(booleanOf(values, "sources")),
    read: joined(listOf(optionsOf(values, "read"), READS)),
  };
}

/** Whether `feed` belongs in a view: every Feed, one that needs attention, or one switched off. */
export function inView(feed: FeedRead, view: FeedView): boolean {
  if (view === "attention") {
    return needsAttention(feed);
  }
  return view === "disabled" ? !feed.enabled : true;
}

/** Whether a Feed has never been read. */
export function neverRead(feed: FeedRead): boolean {
  return feed.last_scraped_at === null;
}

/** Whether a Feed that is on was never read, or not for more than a day before `now`. */
export function isStale(feed: FeedRead, now: Date): boolean {
  if (!feed.enabled) {
    return false;
  }
  return (
    feed.last_scraped_at === null ||
    now.getTime() - Date.parse(feed.last_scraped_at) > STALE_HOURS * HOUR_MS
  );
}

/** Whether `q`'s words (any case) are all in the Feed's name or its address; no words: yes. */
export function matchesWords(feed: FeedRead, q: string | undefined, locale?: string): boolean {
  const words = q?.trim().toLocaleLowerCase(locale).split(WORDS).filter(Boolean) ?? [];
  const haystack = `${feed.name} ${feed.url}`.toLocaleLowerCase(locale);
  return words.every((word) => haystack.includes(word));
}

/**
 * Whether `feed` passes every filter set (the view aside): several values of one filter, any of
 * them. `now` tells which Feeds are stale. "None yet" holds the Feeds that have collected nothing,
 * as Delete tells them (`has_sources`), so each of them may be deleted.
 */
export function matches(feed: FeedRead, filters: FeedFilters, now: Date, locale?: string): boolean {
  const any = <T>(chosen: T[], value: T) => chosen.length === 0 || chosen.includes(value);
  return (
    matchesWords(feed, filters.q, locale) &&
    any(filters.state, feed.state) &&
    any(filters.kind, feed.kind) &&
    any(filters.category, feed.category) &&
    (filters.sources === undefined || filters.sources === feed.has_sources) &&
    (filters.read.length === 0 || filters.read.some((read) => READ_TESTS[read](feed, now)))
  );
}

/**
 * The Feeds in the order chosen, ties by name: by name, the least recently read first (never
 * read before all), the failing then blocked first, or the most Sources first.
 */
export function sorted(feeds: FeedRead[], sort: FeedSort, locale?: string): FeedRead[] {
  const byName = new Intl.Collator(locale, { sensitivity: "base", numeric: true });
  const first: Record<FeedSort, (a: FeedRead, b: FeedRead) => number> = {
    name: () => 0,
    read: (a, b) => readAt(a) - readAt(b),
    state: (a, b) => STATE_ORDER[a.state] - STATE_ORDER[b.state],
    sources: (a, b) => b.sources - a.sources,
  };
  return feeds.toSorted((a, b) => first[sort](a, b) || byName.compare(a.name, b.name));
}

/** The Feeds a view holds, then those of them every filter leaves, in the order chosen. */
export function shownFeeds(
  feeds: FeedRead[],
  filters: FeedFilters,
  now: Date,
  locale?: string,
): { inView: FeedRead[]; shown: FeedRead[] } {
  const viewed = feeds.filter((feed) => inView(feed, filters.view));
  const shown = viewed.filter((feed) => matches(feed, filters, now, locale));
  return { inView: viewed, shown: sorted(shown, filters.sort, locale) };
}

/** Whether a search or a filter narrows the view (the order and the grouping do not). */
export function narrowed(filters: FeedFilters): boolean {
  return (
    filters.q !== undefined ||
    filters.sources !== undefined ||
    LISTED.some((id) => filters[id].length > 0)
  );
}

/** The Feeds under each value of `group` (a category, state or kind); a value none has is left out. */
export function groupedBy<G extends FeedGroup>(
  feeds: FeedRead[],
  group: G,
): { value: FeedRead[G]; feeds: FeedRead[] }[] {
  return GROUP_ORDERS[group]
    .map((value) => ({ value, feeds: feeds.filter((feed) => feed[group] === value) }))
    .filter((each) => each.feeds.length > 0);
}
