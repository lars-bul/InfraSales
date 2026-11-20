import type { FeedCategory } from "#/client/types.gen.ts";

// Who publishes what a Feed lists: the press, a municipality, a utility, a procurement portal or
// an authority; in the order the filters offer them and the grouped lists show them on both the
// Feeds and the Sources page.
export const CATEGORIES = [
  "press",
  "municipality",
  "utility",
  "procurement",
  "authority",
] as const satisfies readonly FeedCategory[];
