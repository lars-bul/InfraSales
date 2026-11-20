import { screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { summaries } from "#/test/summaries.ts";
import { alice, signedIn } from "#/test/users.ts";

// The Jobs page's two lists as tabs: links, each to its own address, the current one marked.
test.each([
  ["/jobs", "Jobs"],
  ["/runs", "Job runs"],
  ["/runs?job=scrape", "Job runs"], // filtered, still the same tab
])("on %s, the %s tab is the current page", async (url, current) => {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [weekly] },
    "GET /api/jobs/runs": { body: [] },
    ...summaries,
  });
  const { container } = renderApp(url);

  const tabs = within(await screen.findByRole("navigation", { name: "Jobs and job runs" }));

  expect(
    tabs.getAllByRole("link").map((tab) => [tab.textContent, tab.getAttribute("href")]),
  ).toEqual([
    ["Jobs", "/jobs"],
    ["Job runs", "/runs"],
  ]);
  const marked = tabs.getAllByRole("link").filter((tab) => tab.getAttribute("aria-current"));
  expect(marked.map((tab) => tab.textContent)).toEqual([current]);
  expect(await violations(container)).toEqual([]);
});
