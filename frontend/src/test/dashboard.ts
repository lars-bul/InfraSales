import { vi } from "vitest";
import type { ConfigEntryRead, FeedRead, RunHistoryEntry } from "#/client/types.gen.ts";
import { scrape } from "./entries.ts";
import { everyFeed } from "./feeds.ts";
import { stubApi } from "./fetch.ts";
import { renderApp } from "./render.tsx";
import { collected, entryAs } from "./runs.ts";
import { summaries } from "./summaries.ts";
import { alice, signedIn, type vera } from "./users.ts";

interface Data {
  entries?: ConfigEntryRead[];
  feeds?: FeedRead[];
  collections?: RunHistoryEntry[]; // what the last-collection query lists
}

/** The Dashboard's "now": Friday 16 October 2026, noon UTC. */
export const NOW = new Date("2026-10-16T12:00:00Z");

// Source Collection's next run from NOW: in 2 hours.
export const nextScrape: ConfigEntryRead = { ...scrape, next_run_at: "2026-10-16T14:00:00Z" };

/** Source Collection's last run that went through: 2 hours before NOW, 42 new Source Versions. */
export const lastCollection = entryAs("succeeded", {
  job: "scrape",
  trigger: "schedule",
  scheduled_for: "2026-10-16T09:00:00Z",
  finished_at: "2026-10-16T10:00:00Z",
  result: collected(),
});

/**
 * The Dashboard as `user` (alice, the admin, unless said) opens it at NOW, with the data given
 * (by default every Feed, the job scheduled and one collection); `replies` add or replace
 * answers. Other run lists (a job's recent runs) are empty.
 */
export function dashboard(
  user: typeof alice | typeof vera = alice,
  { entries = [nextScrape], feeds = everyFeed, collections = [lastCollection] }: Data = {},
  replies: Parameters<typeof stubApi>[0] = {},
) {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
  const calls = stubApi({
    "GET /api/auth/session": signedIn(user),
    "GET /api/config": { body: entries },
    "GET /api/feeds": { body: feeds },
    "GET /api/jobs/runs": (request) => ({
      body: new URL(request.url).searchParams.get("status") === "succeeded" ? collections : [],
    }),
    ...summaries,
    ...replies,
  });
  return { calls, ...renderApp("/") };
}

/** The paths of the requests made, without the session check. */
export function asked(calls: Request[]): string[] {
  return [...new Set(calls.map((call) => new URL(call.url).pathname))].filter(
    (path) => path !== "/api/auth/session",
  );
}
