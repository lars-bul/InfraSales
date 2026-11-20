import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { aiSettings } from "#/test/ai.ts";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { summaries } from "#/test/summaries.ts";
import { alice, signedIn, vera } from "#/test/users.ts";

// A job's own page, as Databricks lays it out: breadcrumb and name, its runs and settings as
// tabs, its details at the side.
function jobPage(user: typeof alice | typeof vera, url = "/jobs/scrape") {
  const calls = stubApi({
    "GET /api/ai": { body: aiSettings },
    "GET /api/auth/session": signedIn(user),
    "GET /api/config": { body: [weekly] },
    "GET /api/jobs/scrape/runs/active": { body: null },
    "GET /api/jobs/runs": { body: [] },
    ...summaries,
  });
  return { calls, ...renderApp(url) };
}

test("admins get the job's name under a breadcrumb, Run now and its switch, its runs first", async () => {
  const { calls, container } = jobPage(alice);

  expect(await screen.findByRole("heading", { level: 1, name: "Source Collection" })).toBeTruthy();
  const crumbs = within(screen.getByRole("navigation", { name: "Breadcrumb" }));
  expect(crumbs.getByRole("link", { name: "Jobs" }).getAttribute("href")).toBe("/jobs");
  expect(screen.getByRole("button", { name: "Run Source Collection now" })).toBeTruthy();
  expect(
    screen.getByRole("switch", { name: "Run Source Collection on its schedule" }),
  ).toBeTruthy();
  const views = within(screen.getByRole("tablist", { name: "Source Collection: views" }));
  expect(views.getByRole("tab", { name: "Runs" }).getAttribute("aria-selected")).toBe("true");
  expect(await screen.findByText("No runs yet")).toBeTruthy();
  expect(screen.queryByRole("form", { name: "Source Collection" })).toBeNull();
  const runs = calls.filter((call) => new URL(call.url).pathname === "/api/jobs/runs");
  expect(new URL(runs[0]?.url ?? "").searchParams.get("job")).toBe("scrape"); // its own
  expect(await violations(container)).toEqual([]);
});

test("the Settings tab holds the job's form; Run now stays beside the name", async () => {
  const { container, router } = jobPage(alice, "/jobs/scrape");
  await screen.findByRole("heading", { level: 1, name: "Source Collection" });

  await userEvent.click(screen.getByRole("tab", { name: "Settings" }));

  const form = screen.getByRole("form", { name: "Source Collection" });
  expect(within(form).getByRole("button", { name: "Save" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Run Source Collection now" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/jobs/scrape");
  expect(await violations(container)).toEqual([]);
});

test("the shell's heading gives way to the job's: one level-1 heading, the title in the top bar", async () => {
  jobPage(alice);

  await screen.findByRole("heading", { level: 1, name: "Source Collection" });

  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.queryByText("When InfraSales reads its Feeds, and how each run went.")).toBeNull();
});

test("the breadcrumb leads back to the jobs", async () => {
  const { router } = jobPage(alice);
  const crumbs = within(await screen.findByRole("navigation", { name: "Breadcrumb" }));

  await userEvent.click(crumbs.getByRole("link", { name: "Jobs" }));

  expect(await screen.findByRole("table", { name: "1 job" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/jobs");
});

test("viewers get the job's details only: no tabs, no run controls, no runs asked for", async () => {
  const { calls, container } = jobPage(vera);

  expect(await screen.findByRole("heading", { level: 1, name: "Source Collection" })).toBeTruthy();
  expect(screen.getByRole("complementary", { name: "Job details" })).toBeTruthy();
  expect(screen.queryByRole("tablist")).toBeNull();
  expect(screen.queryByRole("button", { name: "Run Source Collection now" })).toBeNull();
  expect(screen.queryByRole("switch")).toBeNull();
  expect(calls.filter((call) => call.url.includes("/api/jobs/"))).toEqual([]);
  expect(await violations(container)).toEqual([]);
});

test("an address naming no job leads to the jobs", async () => {
  const { router } = jobPage(vera, "/jobs/weather");

  expect(await screen.findByRole("table", { name: "1 job" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/jobs");
});
