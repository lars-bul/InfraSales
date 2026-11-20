import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { aiSettings } from "#/test/ai.ts";
import { violations } from "#/test/axe.ts";
import { scrape } from "#/test/entries.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { noRuns } from "#/test/runs.ts";
import { summaries } from "#/test/summaries.ts";
import { alice, signedIn } from "#/test/users.ts";

function settingsPage() {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [scrape] },
    "GET /api/ai": { body: aiSettings },
    "GET /api/jobs/runs": noRuns,
    ...summaries,
  });
  return { calls, ...renderApp("/settings") };
}

test("admins find the models and their connections on the Settings page, no schedule", async () => {
  const { container } = settingsPage();

  expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeTruthy();
  expect(await screen.findByRole("region", { name: "Connections" })).toBeTruthy();
  expect(screen.getByRole("region", { name: "Models" })).toBeTruthy();
  expect(screen.queryByRole("form", { name: "Source Collection" })).toBeNull(); // on its job's page
  expect(screen.queryByText("Coming soon")).toBeNull();
  expect(await violations(container)).toEqual([]);
});
