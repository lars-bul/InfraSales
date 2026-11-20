import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import type { ConfigEntryRead } from "#/client/types.gen.ts";
import { aiSettings } from "#/test/ai.ts";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { inTurn, stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { noRuns } from "#/test/runs.ts";
import { savesOf } from "#/test/schedules.ts";
import { summaries } from "#/test/summaries.ts";
import { alice, signedIn, vera } from "#/test/users.ts";

const SAVE = "PUT /api/config/scrape_schedule";
const SWITCH = "Run Source Collection on its schedule";
const paused: ConfigEntryRead = {
  ...weekly,
  value: { ...weekly.value, enabled: false },
  next_run_at: null,
};

// Stores what is sent as the next revision, as the API does.
async function stored(request: Request) {
  return { body: { ...weekly, revision: 2, value: await request.clone().json() } };
}

// The Source Collection's page: the switch in its header, its state in the Job details beside its tabs.
function jobPage(
  replies: Parameters<typeof stubApi>[0],
  user: typeof alice | typeof vera = alice,
  url = "/jobs/scrape",
) {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(user),
    "GET /api/config": { body: [weekly] },
    "GET /api/ai": { body: aiSettings },
    "GET /api/jobs/scrape/runs/active": { body: null },
    "GET /api/jobs/runs": noRuns,
    ...summaries,
    [SAVE]: stored,
    ...replies,
  });
  return { calls, ...renderApp(url) };
}

async function page() {
  await screen.findByRole("heading", { level: 1, name: "Source Collection" });
  return screen;
}

test("the switch pauses a job at once, sending the whole schedule over its revision", async () => {
  const { calls, container } = jobPage({});
  const job = await page();
  const toggle = job.getByRole("switch", { name: SWITCH });
  expect(toggle.getAttribute("aria-checked")).toBe("true");

  await userEvent.click(toggle);

  expect((await job.findByText("The Source Collection is paused.")).getAttribute("role")).toBe(
    "status",
  );
  expect(await savesOf(calls)).toEqual([
    {
      method: "PUT",
      path: "/api/config/scrape_schedule",
      ifMatch: '"1"',
      body: { ...weekly.value, enabled: false },
    },
  ]);
  expect(toggle.getAttribute("aria-checked")).toBe("false");
  expect(job.getByText("Paused")).toBeTruthy();
  expect(await violations(container)).toEqual([]);
});

test("the switch turns a paused job on", async () => {
  const { calls } = jobPage({ "GET /api/config": { body: [paused] } });
  const job = await page();

  await userEvent.click(job.getByRole("switch", { name: SWITCH }));

  expect(await job.findByText("The Source Collection is on.")).toBeTruthy();
  expect((await savesOf(calls))[0]?.body.enabled).toBe(true);
});

test("the form saves over the revision the switch left, keeping what the switch set", async () => {
  const { calls } = jobPage({});
  const user = userEvent.setup();
  await page();

  await user.click(screen.getByRole("switch", { name: SWITCH }));
  await screen.findByText("The Source Collection is paused.");
  await user.click(screen.getByRole("tab", { name: "Settings" }));
  const form = within(await screen.findByRole("form", { name: "Source Collection" }));
  await user.click(form.getByRole("button", { name: "Save" }));
  await form.findByText("Saved.");

  const [, save] = await savesOf(calls);
  expect(save?.ifMatch).toBe('"2"');
  expect(save?.body.enabled).toBe(false);
});

test("Enabled is no longer part of the form", async () => {
  jobPage({});
  await page();

  await userEvent.click(screen.getByRole("tab", { name: "Settings" }));
  const form = within(await screen.findByRole("form", { name: "Source Collection" }));

  expect(form.queryByLabelText("Enabled")).toBeNull();
  expect(form.queryByRole("switch")).toBeNull();
});

test("a switch over a changed schedule says so and shows the change", async () => {
  const theirs = { ...weekly, revision: 2, value: { ...weekly.value, time: "09:00" } };
  const { calls, container } = jobPage({
    [SAVE]: { status: 412 },
    "GET /api/config": inTurn({ body: [weekly] }, { body: [theirs] }),
  });
  const job = await page();

  await userEvent.click(job.getByRole("switch", { name: SWITCH }));

  expect((await job.findByRole("alert")).textContent).toBe(
    "Not saved: someone changed this schedule meanwhile. Their change is shown now.",
  );
  expect(await job.findByText("Mon at 09:00 (Europe/Berlin)")).toBeTruthy();
  expect(job.getByRole("switch", { name: SWITCH }).getAttribute("aria-checked")).toBe("true");
  expect(await savesOf(calls)).toHaveLength(1);
  expect(await violations(container)).toEqual([]);
});

test("a switch the service could not save is announced, and the job stays as it was", async () => {
  jobPage({ [SAVE]: { status: 503 } });
  const job = await page();

  await userEvent.click(job.getByRole("switch", { name: SWITCH }));

  expect((await job.findByRole("alert")).textContent).toBe(
    "Not saved: the service is unavailable. Please try again.",
  );
  expect(job.getByRole("switch", { name: SWITCH }).getAttribute("aria-checked")).toBe("true");
});

test("viewers get no switch", async () => {
  jobPage({}, vera);
  const job = await page();

  expect(job.getByText("On")).toBeTruthy();
  expect(job.queryByRole("switch")).toBeNull();
});
