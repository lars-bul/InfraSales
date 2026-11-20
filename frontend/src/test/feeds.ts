import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import type { FeedRead, Suggestion } from "#/client/types.gen.ts";
import { stubApi } from "./fetch.ts";
import { renderApp } from "./render.tsx";
import { alice, signedIn } from "./users.ts";

// Feeds as `GET /api/feeds` lists them, by name: one of each kind and state.

const base = {
  settings: {},
  fetcher: "http",
  extractor: null,
  enabled: true,
  state: "ok",
  last_error: null,
  created_at: "2026-10-01T06:00:00Z",
  has_sources: true,
  sources: 12,
  category: "press",
} as const satisfies Partial<FeedRead>;

export const heizwerk: FeedRead = {
  ...base,
  id: "0199f0a1-0000-7000-8000-000000000001",
  name: "Heizwerk Journal",
  slug: "heizwerk-journal",
  kind: "rss",
  url: "https://www.heizwerk-journal.test/rss/heizwerk-atom.xml",
  last_scraped_at: "2026-10-16T09:00:00Z",
};

export const tiefbauAktuell: FeedRead = {
  ...base,
  id: "0199f0a1-0000-7000-8000-000000000002",
  name: "Tiefbau Aktuell",
  slug: "tiefbau-aktuell",
  kind: "sitemap",
  url: "https://tiefbau-aktuell.test/sitemap.xml",
  state: "failing",
  last_error: "http 404",
  last_scraped_at: "2026-10-15T12:00:00Z",
};

export const energieatlas: FeedRead = {
  ...base,
  id: "0199f0a1-0000-7000-8000-000000000003",
  name: "Energieatlas",
  slug: "energieatlas",
  kind: "sitemap",
  category: "authority",
  url: "https://energieatlas.test/sitemap.xml",
  state: "blocked",
  last_error: "blocked",
  last_scraped_at: "2026-10-14T12:00:00Z",
};

export const ratsinfo: FeedRead = {
  ...base,
  id: "0199f0a1-0000-7000-8000-000000000004",
  name: "Ratsinfo Ulm",
  slug: "ratsinfo-ulm",
  kind: "rss",
  category: "municipality",
  url: "https://ratsinfo-ulm.test/feed.xml",
  enabled: false,
  last_scraped_at: null,
  has_sources: false, // never read: it may be deleted
  sources: 0,
};

export const stadtwerke: FeedRead = {
  ...base,
  id: "0199f0a1-0000-7000-8000-000000000005",
  name: "Stadtwerke Heidelberg",
  slug: "stadtwerke-heidelberg",
  kind: "rss",
  category: "utility",
  url: "https://stadtwerke-heidelberg.test/news.xml",
  last_scraped_at: "2026-10-16T11:58:00Z",
};

export const everyFeed = [energieatlas, ratsinfo, stadtwerke, heizwerk, tiefbauAktuell];

// Adding a Feed: what InfraSales suggests for waermewende.test, and the Feed it then stores.

export const SUGGEST = "POST /api/feeds/suggest";
export const ADD = "POST /api/feeds";
export const SITE = "https://waermewende.test";

export const suggestion: Suggestion = {
  name: "waermewende.test",
  kind: "rss",
  url: "https://waermewende.test/feed/",
};

export const waermewende: FeedRead = {
  ...base,
  id: "0199f0a1-0000-7000-8000-000000000006",
  name: "waermewende",
  slug: "waermewende",
  kind: "rss",
  url: "https://waermewende.test/feed/",
  last_scraped_at: null,
  has_sources: false,
  sources: 0,
};

/** The Feeds page as an admin, listing `feeds`; `replies` add or replace answers. */
export function feedsAdminPage(
  feeds: FeedRead[] = [heizwerk],
  replies: Parameters<typeof stubApi>[0] = {},
) {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/feeds": { body: feeds },
    ...replies,
  });
  return { calls, ...renderApp("/feeds") };
}

/** Opens the Add Feed dialog: its trigger, and the dialog to look within. */
export async function openAddFeed() {
  const trigger = await screen.findByRole("button", { name: "Add Feed" });
  await userEvent.click(trigger);
  const dialog = await screen.findByRole("dialog", { name: "Add Feed" });
  return { trigger, dialog, within: within(dialog) };
}

/** Enters the site's address and asks for its Feed. */
export async function findFeed(dialog: ReturnType<typeof within>, site = SITE) {
  await userEvent.type(dialog.getByRole("textbox", { name: "Site address" }), site);
  await userEvent.click(dialog.getByRole("button", { name: "Find Feed" }));
}

/** Chooses the Feed's category in the dialog's second step (it has none until chosen). */
export async function chooseCategory(dialog: ReturnType<typeof within>, category = "Press") {
  await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Category" }), category);
}

/** The requests made to `route` ("METHOD /path"), in order. */
export function requestsTo(calls: Request[], route: string): Request[] {
  return calls.filter((call) => `${call.method} ${new URL(call.url).pathname}` === route);
}

/** The bodies sent to `route` ("METHOD /path"), in order. */
export async function sentTo(calls: Request[], route: string): Promise<unknown[]> {
  return await Promise.all(requestsTo(calls, route).map(async (call) => await call.clone().json()));
}
