import { screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { weekly } from "#/test/entries.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { noRuns } from "#/test/runs.ts";
import { summaries } from "#/test/summaries.ts";
import { alice, signedIn } from "#/test/users.ts";

// The summary's days are the person's calendar days: a job's is asked for in the browser's time
// zone, by its page's tiles.

test("the summary is asked for in the browser's time zone", async () => {
  const { resolvedOptions } = Intl.DateTimeFormat.prototype;
  vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockImplementation(function inZone(
    this: Intl.DateTimeFormat,
  ) {
    return { ...resolvedOptions.call(this), timeZone: "America/New_York" };
  });
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [weekly] },
    "GET /api/jobs/scrape/runs/active": { body: null },
    "GET /api/jobs/runs": noRuns,
    ...summaries,
  });
  renderApp("/jobs/scrape");

  await screen.findByRole("group", { name: "Last 7 days" });

  const asked = calls
    .map((call) => new URL(call.url))
    .filter((url) => url.pathname.endsWith("/runs/summary"))
    .map((url) => `${url.pathname} ${url.searchParams.get("timezone")}`);
  expect(asked).toEqual(["/api/jobs/scrape/runs/summary America/New_York"]);
});
