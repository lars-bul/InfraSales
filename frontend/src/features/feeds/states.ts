import type { FeedRead, FeedState } from "#/client/types.gen.ts";

// Each state's badge: red while a Feed fails, amber while a site blocks InfraSales.
export const STATE_BADGES = {
  ok: "success",
  failing: "destructive",
  blocked: "warning",
} as const satisfies Record<FeedState, string>;

// Each state's dot in the Feeds list, in the badges' colours; a Feed switched off is grey.
export const STATE_DOTS = {
  ok: "bg-success",
  failing: "bg-destructive",
  blocked: "bg-warning",
} as const satisfies Record<FeedState, string>;

/** Whether Source Collection should read a Feed but could not: failing or blocked, not disabled. */
export function needsAttention(feed: FeedRead): boolean {
  return feed.enabled && feed.state !== "ok";
}

/** The Feeds Source Collection should read but could not: failing or blocked, not disabled. */
export function notRead(feeds: FeedRead[]): FeedRead[] {
  return feeds.filter(needsAttention);
}
