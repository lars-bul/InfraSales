import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import type { ConfigEntryRead } from "#/client/types.gen.ts";
import { weekly } from "./entries.ts";
import { stubApi } from "./fetch.ts";
import { renderApp } from "./render.tsx";
import { noRuns } from "./runs.ts";
import { summaries } from "./summaries.ts";
import { alice, signedIn } from "./users.ts";

export const SAVE_SCHEDULE = "PUT /api/config/scrape_schedule";

/**
 * Source Collection's page as an admin, with its schedule `entry`. A save stores what is sent as
 * the next revision, as the API does; `replies` add or replace answers.
 */
export function scheduleAdminPage(
  entry: ConfigEntryRead = weekly,
  replies: Parameters<typeof stubApi>[0] = {},
) {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [entry] },
    "GET /api/jobs/scrape/runs/active": { body: null },
    "GET /api/jobs/runs": noRuns,
    "GET /api/jobs/scrape/runs": noRuns,
    ...summaries,
    [SAVE_SCHEDULE]: async (request) => ({
      body: { ...entry, revision: entry.revision + 1, value: await request.clone().json() },
    }),
    ...replies,
  });
  return { calls, ...renderApp("/jobs/scrape") };
}

/** Source Collection's schedule form, in its page's Settings tab. */
export async function scheduleForm() {
  const settings = await screen.findByRole("tab", { name: "Settings" });
  if (settings.getAttribute("aria-selected") !== "true") {
    await userEvent.click(settings);
  }
  return within(await screen.findByRole("form", { name: "Source Collection" }));
}

/** The saves made: method, path, `If-Match` and body of each. */
export async function savesOf(calls: Request[]) {
  return await Promise.all(
    calls
      .filter((call) => call.method === "PUT")
      .map(async (call) => ({
        method: call.method,
        path: new URL(call.url).pathname,
        ifMatch: call.headers.get("if-match"),
        body: await call.clone().json(),
      })),
  );
}
