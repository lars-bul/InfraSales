import { act, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { ConfigEntryRead } from "#/client/types.gen.ts";
import { violations } from "#/test/axe.ts";
import { scrape, weekly } from "#/test/entries.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { signedIn, vera } from "#/test/users.ts";

// Monday 2026-10-05, 05:50 in Berlin: the Source Collection (08:00) runs in 2 h 10 min.
const NOW = new Date("2026-10-05T03:50:00Z");

afterEach(() => {
  vi.useRealTimers();
});

function weeklyWith(changes: Partial<ConfigEntryRead["value"]>, nextRunAt: string | null) {
  return { ...weekly, value: { ...weekly.value, ...changes }, next_run_at: nextRunAt };
}

// The Source Collection's row on the Jobs page, as a viewer reads it.
async function scheduleRow(entry: ConfigEntryRead) {
  stubApi({ "GET /api/auth/session": signedIn(vera), "GET /api/config": { body: [entry] } });
  const view = renderApp("/jobs");
  const link = await within(await screen.findByRole("main")).findByRole("link", {
    name: "Source Collection",
  });
  return { row: within(link.closest("tr") as HTMLElement), ...view };
}

test.each([
  ["once a day", weekly, "Mon at 08:00 (Europe/Berlin)", "in 2 h 10 min"],
  [
    "repeating",
    { ...scrape, key: "scrape_schedule" as const },
    "Every day, every 3 hours (Europe/Berlin)",
    "in 10 min",
  ],
  [
    "repeating from another time than midnight",
    weeklyWith(
      { days: ["mon", "tue", "wed", "thu", "fri"], time: "06:00", every_hours: 3 },
      "2026-10-05T07:00:00Z",
    ),
    "Mon–Fri, every 3 hours from 06:00 (Europe/Berlin)",
    "in 3 h 10 min",
  ],
  [
    "on days apart",
    weeklyWith({ days: ["mon", "wed", "fri"], time: "07:00" }, "2026-10-07T05:00:00Z"),
    "Mon, Wed and Fri at 07:00 (Europe/Berlin)",
    "in 2 d 1 h",
  ],
])("a job says when it runs, %s, and when next", async (_, entry, sentence, next) => {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
  const { row, container } = await scheduleRow(entry);

  expect(row.getByText(sentence)).toBeTruthy();
  const countdown = row.getByText(next);
  expect(countdown.tagName).toBe("TIME");
  expect(countdown.getAttribute("dateTime")).toBe(entry.next_run_at);
  expect(await violations(container)).toEqual([]);
});

test("a run due or just passed is a minute away until the one after it is read", async () => {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
  const { row } = await scheduleRow(weeklyWith({}, "2026-10-05T03:49:00Z"));

  expect(row.getByText("in 1 min")).toBeTruthy();
});

test("the time to the next run counts down", async () => {
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"], now: NOW });
  const { row } = await scheduleRow(weekly);
  expect(row.getByText("in 2 h 10 min")).toBeTruthy();

  await act(() => vi.advanceTimersByTimeAsync(60_000));

  expect(row.getByText("in 2 h 9 min")).toBeTruthy();
});
