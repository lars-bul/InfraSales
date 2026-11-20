import { screen, waitFor, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { entryAs } from "#/test/runs.ts";
import { summaries } from "#/test/summaries.ts";
import { alice, signedIn, vera } from "#/test/users.ts";

// Monday 2026-10-05, 05:50 in Berlin: the Source Collection (08:00) runs in 2 h 10 min.
const NOW = new Date("2026-10-05T03:50:00Z");
const OCT_3 = /^Oct 3, 2026/;
const OCT_2 = /^Oct 2, 2026/;
const FAILED = /^Failed/;
const SUCCEEDED = /^Succeeded/;

afterEach(() => {
  vi.useRealTimers();
});

/** The Jobs page as `user` opens it, the Source Collection's last runs as `runs` says. */
function jobsPage(
  user: typeof alice | typeof vera,
  runs: Parameters<typeof stubApi>[0][string] = { body: [] },
) {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(user),
    "GET /api/config": { body: [weekly] },
    "GET /api/jobs/runs": runs,
    "GET /api/jobs/scrape/runs/active": { body: null },
    ...summaries,
  });
  return { calls, ...renderApp("/jobs") };
}

/** Opens the Source Collection's sheet by its row's "…". */
async function openSheet(): Promise<HTMLElement> {
  await userEvent.click(
    await screen.findByRole("button", { name: "More about Source Collection" }),
  );
  return screen.findByRole("dialog", { name: "Source Collection" });
}

// The sheet's terms and what each says: [["Job ID", "scrape"], ...].
function described(sheet: HTMLElement): [string | null, string | null][] {
  const values = within(sheet).getAllByRole("definition");
  return within(sheet)
    .getAllByRole("term")
    .map((term, index) => [term.textContent, values[index]?.textContent ?? null]);
}

test("viewers' sheet says what the job is, when it runs and next, and leads to its page", async () => {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
  const { calls, container, router } = jobsPage(vera);

  const sheet = await openSheet();

  const description = document.getElementById(sheet.getAttribute("aria-describedby") ?? "");
  expect(description?.textContent).toBe("Reads every Feed and records the new Source Versions.");
  expect(described(sheet)).toEqual([
    ["Job ID", "scrape"],
    ["Schedule", "Mon at 08:00 (Europe/Berlin)"],
    ["Next run", "in 2 h 10 min"],
    ["Status", "On"],
  ]);
  expect(within(sheet).queryByRole("button", { name: "Run Source Collection now" })).toBeNull();
  expect(within(sheet).queryByRole("switch")).toBeNull();
  expect(within(sheet).queryByRole("link", { name: "All runs of Source Collection" })).toBeNull();
  expect(calls.filter((call) => call.url.includes("/api/jobs/"))).toEqual([]);
  expect(await violations(container.ownerDocument.body)).toEqual([]);

  await userEvent.click(within(sheet).getByRole("link", { name: "Open the job's page" }));

  expect(router.state.location.pathname).toBe("/jobs/scrape");
});

test("the sheet closes by its close button or Escape, focus back on the row's …", async () => {
  jobsPage(vera);
  const more = await screen.findByRole("button", { name: "More about Source Collection" });

  await userEvent.click(more);
  await userEvent.click(
    within(await screen.findByRole("dialog")).getByRole("button", { name: "Close" }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

  await userEvent.click(more);
  await screen.findByRole("dialog");
  await userEvent.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(document.activeElement).toBe(more);
});

test("admins' sheet has Run now, the switch, the run health and the last runs, newest first", async () => {
  const { container } = jobsPage(alice, (request) => {
    const job = new URL(request.url).searchParams.get("job");
    return {
      body:
        job === "scrape"
          ? [
              entryAs("failed", { id: "newer", scheduled_for: "2026-10-03T08:00:00Z" }),
              entryAs("succeeded", {
                id: "older",
                trigger: "schedule",
                triggered_by: null,
                scheduled_for: "2026-10-02T08:00:00Z",
              }),
            ]
          : [],
    };
  });

  const sheet = await openSheet();

  expect(within(sheet).getByRole("button", { name: "Run Source Collection now" })).toBeTruthy();
  expect(
    (
      within(sheet).getByRole("switch", {
        name: "Run Source Collection on its schedule",
      }) as HTMLElement
    ).getAttribute("aria-checked"),
  ).toBe("true");
  const health = within(within(sheet).getByRole("region", { name: "Run health" }));
  expect((await health.findByRole("group", { name: "Last 7 days" })).textContent).toContain("18");
  const latest = within(sheet).getByRole("region", { name: "Latest runs" });
  const runs = (await within(latest).findAllByRole("listitem")).map((run) => run.textContent);
  expect(runs).toEqual([expect.stringMatching(FAILED), expect.stringMatching(SUCCEEDED)]);
  expect(within(latest).getAllByRole("listitem")[0]?.textContent).toContain("Run now · alice");
  expect(within(latest).getAllByRole("listitem")[1]?.textContent).toContain("the schedule");
  const times = within(latest)
    .getAllByRole("listitem")
    .map((run) => run.querySelector("time")?.textContent);
  expect(times).toEqual([expect.stringMatching(OCT_3), expect.stringMatching(OCT_2)]);
  expect(
    within(sheet).getByRole("link", { name: "All runs of Source Collection" }).getAttribute("href"),
  ).toBe("/runs?job=scrape");
  expect(await violations(container.ownerDocument.body)).toEqual([]);
});

test("admins' sheet says a job without runs has none yet", async () => {
  jobsPage(alice);

  const sheet = await openSheet();

  const latest = within(sheet).getByRole("region", { name: "Latest runs" });
  expect(await within(latest).findByText("No runs yet")).toBeTruthy();
});

test("the last runs that cannot load can be tried again in the sheet", async () => {
  jobsPage(alice, { status: 503 });

  const sheet = await openSheet();

  const latest = within(within(sheet).getByRole("region", { name: "Latest runs" }));
  expect((await latest.findByRole("alert")).textContent).toContain("unavailable");
  expect(latest.getByRole("button", { name: "Try again" })).toBeTruthy();
});
