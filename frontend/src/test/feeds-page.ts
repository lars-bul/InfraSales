import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { vi } from "vitest";
import type { FeedRead } from "#/client/types.gen.ts";
import { stubApi } from "./fetch.ts";
import { renderApp } from "./render.tsx";
import { alice, signedIn } from "./users.ts";

// The Feeds page as its tests drive it: opened on a fixed "now", and read by its rows.

/** Friday 2026-10-16, 12:00 UTC: "now" for every "last read". */
export const NOW = new Date("2026-10-16T12:00:00Z");

/** The Feeds page at `url` as an admin, listing `feeds`, on `NOW` (the clock alone is fake). */
export function feedsPage(feeds: FeedRead[], url = "/feeds") {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/feeds": { body: feeds },
  });
  return { calls, ...renderApp(url) };
}

/** What each cell of a row says. */
export function cells(row: HTMLElement): (string | null)[] {
  return within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
}

/** The Feeds a table lists, by name (the first line of each row's first cell). */
export function names(table: HTMLElement): (string | null | undefined)[] {
  const [, ...rows] = within(table).getAllByRole("row");
  return rows
    .filter((row) => within(row).queryAllByRole("cell").length > 0) // not a category's heading
    .map((row) => within(row).getAllByRole("cell")[0]?.firstElementChild?.firstChild?.textContent);
}

/** What the page's status regions say (the count, and Add Feed's beside its button). */
export function statuses(): (string | null)[] {
  return screen.getAllByRole("status").map((status) => status.textContent);
}

/** The requests for the Feed list. */
export function feedsRequested(calls: Request[]): Request[] {
  return calls.filter((call) => new URL(call.url).pathname === "/api/feeds");
}

/** Opens the filter `label` (its button is always in view) and returns the picker of its values. */
export async function openFilter(label: string) {
  await userEvent.click(await screen.findByRole("button", { name: label }));
  return within(await screen.findByRole("dialog", { name: label }));
}
