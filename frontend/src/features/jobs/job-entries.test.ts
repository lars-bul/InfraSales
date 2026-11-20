import { act, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { weekly } from "#/test/entries.ts";
import { inTurn, stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { signedIn, vera } from "#/test/users.ts";
import { untilNextRun } from "./job-entries.ts";

// Monday 2026-10-05, 05:50 in Berlin.
const NOW = new Date("2026-10-05T03:50:00Z");

afterEach(() => {
  vi.useRealTimers();
});

const at = (next: string | null) => ({ ...weekly, next_run_at: next });

test("the schedules are read again just after the earliest next run shown", () => {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });

  expect(untilNextRun([at("2026-10-05T04:00:00Z"), at("2026-10-05T03:55:00Z")])).toBe(
    5 * 60_000 + 5000,
  );
});

test("nothing is waited for without a next run ahead: paused, passed, or not read yet", () => {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });

  expect(untilNextRun(undefined)).toBe(false);
  expect(untilNextRun([at(null)])).toBe(false);
  expect(untilNextRun([at("2026-10-05T03:00:00Z")])).toBe(false);
});

test("a next run far ahead is waited for a day at most (timers take no longer)", () => {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });

  expect(untilNextRun([at("2026-12-01T00:00:00Z")])).toBe(86_400_000);
});

test("once the next run is due, the one after it is read afresh", async () => {
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"], now: NOW });
  stubApi({
    "GET /api/auth/session": signedIn(vera),
    "GET /api/config": inTurn({ body: [at("2026-10-05T03:55:00Z")] }, { body: [weekly] }),
  });
  renderApp("/jobs");
  const link = await within(await screen.findByRole("main")).findByRole("link", {
    name: "Source Collection",
  });
  const row = within(link.closest("tr") as HTMLElement);
  expect(row.getByText("in 5 min")).toBeTruthy();

  await act(() => vi.advanceTimersByTimeAsync(6 * 60_000));

  expect(await row.findByText("in 2 h 4 min")).toBeTruthy();
});
