import { screen, waitFor, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { everyFeed, heizwerk } from "#/test/feeds.ts";
import { feedsPage, feedsRequested, names, statuses } from "#/test/feeds-page.ts";
import { stubApi, unavailableOnce } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { alice, signedIn, vera } from "#/test/users.ts";

// The Feeds page: its views with counts, its empty state, and who may open it.

const FEEDS_APPEAR_HERE = "Feeds appear here once one is added. Source Collection reads each one.";

afterEach(() => {
  vi.useRealTimers();
});

test("an empty list says so, without views, filters or a table", async () => {
  const { container } = feedsPage([]);

  expect(await screen.findByText("No Feeds yet")).toBeTruthy();
  expect(screen.getByText(FEEDS_APPEAR_HERE)).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByRole("tablist", { name: "Which Feeds" })).toBeNull();
  expect(screen.queryByRole("group", { name: "Filters" })).toBeNull();
  expect(screen.getByRole("button", { name: "Add Feed" })).toBeTruthy();
  expect(await violations(container)).toEqual([]);
});

test("admins open the Feeds from the sidebar", async () => {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [weekly] },
    "GET /api/feeds": { body: [heizwerk] },
  });
  const { container, router } = renderApp("/jobs");
  const pages = await screen.findByRole("navigation", { name: "Pages" });

  await userEvent.click(within(pages).getByRole("link", { name: "Feeds" }));

  expect(await screen.findByRole("table", { name: "1 Feed" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/feeds");
  expect(within(pages).getByRole("link", { name: "Feeds" }).getAttribute("aria-current")).toBe(
    "page",
  );
  expect(await violations(container)).toEqual([]);
});

test("viewers find no Feeds link, and opening the Feeds lands them on the Dashboard", async () => {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(vera),
    "GET /api/config": { body: [weekly] },
  });

  const { router } = renderApp("/feeds");

  expect(await screen.findByRole("heading", { level: 1, name: "Dashboard" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/");
  expect(screen.queryByRole("link", { name: "Feeds" })).toBeNull();
  expect(calls.some((call) => new URL(call.url).pathname === "/api/feeds")).toBe(false);
});

test("an unavailable list shows the unavailable screen, and trying again loads it", async () => {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/feeds": unavailableOnce({ body: [heizwerk] }, "error"),
  });
  const { container } = renderApp("/feeds");

  const retry = await screen.findByRole("button", { name: "Try again" });
  expect(await violations(container)).toEqual([]);
  await userEvent.click(retry);

  await waitFor(() => expect(screen.getByRole("table", { name: "1 Feed" })).toBeTruthy());
});

test("the views count their Feeds; Needs attention lists the failing and blocked ones that are on", async () => {
  const { container, router, calls } = feedsPage(everyFeed);
  await screen.findByRole("table", { name: "5 Feeds" });
  const views = screen.getByRole("tablist", { name: "Which Feeds" });

  expect(
    within(views)
      .getAllByRole("tab")
      .map((tab) => tab.textContent),
  ).toEqual(["All 5", "Needs attention 2", "Disabled 1"]);
  expect(within(views).getByRole("tab", { name: "All 5" }).getAttribute("aria-selected")).toBe(
    "true",
  );

  await userEvent.click(within(views).getByRole("tab", { name: "Needs attention 2" }));

  expect(names(await screen.findByRole("table", { name: "2 Feeds" }))).toEqual([
    "Energieatlas",
    "Tiefbau Aktuell",
  ]);
  expect(router.state.location.search).toEqual({ view: "attention" });
  expect(statuses()).toContain("2 Feeds");
  expect(await violations(container)).toEqual([]);

  await userEvent.click(within(views).getByRole("tab", { name: "Disabled 1" }));

  expect(names(await screen.findByRole("table", { name: "1 Feed" }))).toEqual(["Ratsinfo Ulm"]);
  expect(router.state.location.search).toEqual({ view: "disabled" });

  await userEvent.click(within(views).getByRole("tab", { name: "All 5" }));

  expect(await screen.findByRole("table", { name: "5 Feeds" })).toBeTruthy();
  expect(router.state.location.search).toEqual({});
  expect(feedsRequested(calls)).toHaveLength(1);
});

test("the Dashboard's link opens the Feeds that need attention; none: it says so", async () => {
  feedsPage([heizwerk], "/feeds?view=attention");

  const tab = await screen.findByRole("tab", { name: "Needs attention 0" });

  expect(tab.getAttribute("aria-selected")).toBe("true");
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.getByText("Nothing needs attention")).toBeTruthy();
  expect(screen.getByText("Source Collection read every Feed it reads.")).toBeTruthy();
  expect(statuses()).toContain("0 Feeds");
});
