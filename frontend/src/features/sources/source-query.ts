import { infiniteQueryOptions } from "@tanstack/react-query";
import {
  countSourcesOptions,
  listSourcesInfiniteOptions,
} from "#/client/@tanstack/react-query.gen.ts";
import type { CountSourcesData, FeedCategory, SourceListed } from "#/client/types.gen.ts";
import {
  booleanOf,
  type FilterField,
  type FilterValues,
  filtersFromSearch,
  filtersToSearch,
  optionsOf,
  periodBounds,
  periodOf,
  withValue,
} from "#/components/filter-bar/filter-values.ts";
import { CATEGORIES } from "#/features/feeds/categories.ts";

const SCHEME = /^https?:\/\/(www\.)?/;
const TRAILING_SLASH = /\/$/;
const WWW = /^www\./;

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

/** Sources per page. */
export const LIMIT = 20;

/**
 * Which Sources to list, as the URL keeps it (`?feed=tiefbau-aktuell,trassenbau-report&period=7d&partial=yes`):
 * one search parameter per filter, each as the filter bar writes it.
 */
export interface SourceSearch {
  q?: string | undefined; // words in the title or the address
  feed?: string | undefined; // Feeds' slugs, by commas
  category?: string | undefined; // Feed categories, by commas
  period?: string | undefined; // the last change: "24h", "7d", "30d" or "2026-10-01..2026-10-20"
  changed?: string | undefined; // "yes": more than one version; "no": just one
  partial?: string | undefined; // "yes": cut off by a paywall; "no": whole
  run?: string | undefined; // a run's ID: the Sources it wrote a version of
}

/** The filters the bar sets, by their kind; the labels and options are the page's. */
export const FILTER_SHAPE: FilterField[] = [
  { id: "feed", label: "", type: "options", options: [] },
  { id: "category", label: "", type: "options", options: [] },
  { id: "period", label: "", type: "period", custom: true },
  { id: "changed", label: "", type: "boolean" },
  { id: "partial", label: "", type: "boolean" },
];

/** How a Source's page shows a version: its text, or what changed from the one before. */
export type View = "text" | "changes";

/**
 * The filters in a URL's search parameters, written the one way the bar writes them; a value that
 * does not parse (or a category there is not) is dropped, and anything else is ignored. A single
 * `?feed=slug`, as the Feeds page links, is one Feed.
 */
export function sourceFiltersIn(search: Record<string, unknown>): SourceSearch {
  const { q, run } = search;
  const values = filtersFromSearch(FILTER_SHAPE, search);
  const known = optionsOf(values, "category").filter((each) =>
    (CATEGORIES as readonly string[]).includes(each),
  );
  return {
    q: text(q),
    ...filtersToSearch(FILTER_SHAPE, withValue(values, "category", known)),
    run: text(run),
  };
}

/** The filters the bar shows, from the URL's (the run aside: the page adds it as a chip). */
export function filterValuesOf(search: SourceSearch): FilterValues {
  return filtersFromSearch(FILTER_SHAPE, search as Record<string, unknown>);
}

/** Whether anything narrows the Sources: a search, a filter or a run. */
export function isNarrowed(search: SourceSearch): boolean {
  return Object.values(search).some((value) => value !== undefined);
}

/** Whether the last change is a period counted back from now ("last 7 days"), not set days. */
export function countsBack(search: SourceSearch): boolean {
  return periodOf(filterValuesOf(search), "period")?.preset !== undefined;
}

/** What the API is asked for: the filters of `search`, a period counted back from `now`. */
export type SourceParams = NonNullable<CountSourcesData["query"]>;

/**
 * The filters of `search` as the Sources API takes them. A preset period ("last 7 days") runs
 * back from `now`, so the page passes the same `now` until the filters change: the query stays
 * the same between renders.
 */
export function sourceParams(search: SourceSearch, now: Date): SourceParams {
  const values = filterValuesOf(search);
  const feed = optionsOf(values, "feed");
  const category = optionsOf(values, "category") as FeedCategory[];
  const period = periodOf(values, "period");
  const { from, to } = period ? periodBounds(period, now) : {};
  const changed = booleanOf(values, "changed");
  const partial = booleanOf(values, "partial");
  return {
    ...(feed.length > 0 && { feed }),
    ...(category.length > 0 && { category }),
    ...(from && { since: from.toISOString() }),
    ...(to && { until: to.toISOString() }),
    ...(changed !== undefined && { changed }),
    ...(partial !== undefined && { partial }),
    ...(search.run && { run: search.run }),
    ...(search.q && { q: search.q }),
  };
}

/**
 * The Sources, the newest change first, a page at a time: a full page means older ones may
 * follow, and the next page starts after the last version listed.
 */
export function sourcesQuery(params: SourceParams) {
  return infiniteQueryOptions({
    ...listSourcesInfiniteOptions({ query: { limit: LIMIT, ...params } }),
    initialPageParam: {}, // the newest page: no cursor
    getNextPageParam: (page: SourceListed[]) =>
      page.length === LIMIT ? page.at(-1)?.version.id : undefined,
  });
}

/** How many Sources the filters leave, all pages together. */
export function sourceCountQuery(params: SourceParams) {
  return countSourcesOptions({ query: params });
}

/** "news.test/2026/10/story": an address without its scheme, for a Source without a title. */
export function shortUrl(url: string): string {
  return url.replace(SCHEME, "").replace(TRAILING_SLASH, "");
}

/** The host a Source is at: "news.test". */
export function hostOf(url: string): string {
  return new URL(url).hostname.replace(WWW, "");
}
