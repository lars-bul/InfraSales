import type { FeedKind } from "#/client/types.gen.ts";

// Each kind's label in the locale (`feeds.kinds.*`; a kind with settings of its own may hold a
// colon in its name, which i18next reads as a namespace); the compiler checks every kind in the
// contract has one.
export const KINDS = {
  rss: "rss",
  sitemap: "sitemap",
} as const satisfies Record<FeedKind, string>;

// The kinds a Feed entered by hand may have: kinds that need settings are added through the API.
export const ENTERED_BY_HAND = ["rss", "sitemap"] as const satisfies readonly FeedKind[];
