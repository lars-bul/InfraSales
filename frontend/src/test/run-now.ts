import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import type { JobName } from "#/client/types.gen.ts";
import { violations } from "#/test/axe.ts";
import { forecast, scrape } from "#/test/entries.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { noRuns, queuedRun } from "#/test/runs.ts";
import { summaries } from "#/test/summaries.ts";
import { alice, signedIn } from "#/test/users.ts";

// Run now on a job's page, as an admin uses it. Every wait is on the test's clock (Vitest's fake
// timers): what is checked when never depends on how fast the machine is.
const REAL_LIMIT_MS = 10_000; // how long (in real time) to wait for something to show (a busy machine)
const SETTLE_TURNS = 5;
const NAMES = { scrape: "Source Collection", forecast: "Forecast" } as const;
// The schedules the jobs page reads.
const ENTRIES = { scrape: [scrape], forecast: [forecast] } as const;

// Kept before the clock is faked: real time passes for React and for code to load (`settle`).
const realTimeout = globalThis.setTimeout;

export const POLL = 2000; // how often Run now checks a run it follows

/** Fakes the clock for each test of the file that calls it. */
export function fakeTheClock() {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });
}

export interface Reply {
  status?: number;
  body?: unknown;
}

/**
 * Lets what is due now run, and what that starts (an answer, a render). The clock moves a
 * millisecond a turn: the fake clock runs a timer set for "now" while it is ticking a moment
 * later. React renders and runs effects on its own schedule, in real time: each turn lets it.
 */
export async function settle() {
  for (let turn = 0; turn < SETTLE_TURNS; turn += 1) {
    // biome-ignore lint/performance/noAwaitInLoops: one turn after another, by design
    await act(() => vi.advanceTimersByTimeAsync(1));
    await new Promise((resolve) => realTimeout(resolve, 0));
  }
}

/** Lets `ms` pass on the test's clock, with everything due meanwhile done. */
export async function wait(ms: number) {
  await settle();
  await act(() => vi.advanceTimersByTimeAsync(ms));
  await settle();
}

/**
 * Waits until `check` passes, and returns its result. The test's clock stands still meanwhile:
 * only what is due now runs, while real time passes for the page's code to load (its routes are
 * split into chunks, imported on demand).
 */
export async function until<T>(check: () => T): Promise<T> {
  const giveUp = performance.now() + REAL_LIMIT_MS;
  while (performance.now() < giveUp) {
    try {
      return check();
    } catch {
      // biome-ignore lint/performance/noAwaitInLoops: checked again once the page moved on
      await settle();
    }
  }
  return check();
}

/** The page's accessibility violations. axe takes turns on the clock, too: it moves meanwhile. */
export async function violationsOf(container: Element): Promise<string[]> {
  let found: string[] | undefined;
  const checking = violations(container).then((ids) => {
    found = ids;
  });
  await until(() => {
    if (found === undefined) {
      throw new Error("axe is still checking");
    }
  });
  await checking;
  return found ?? [];
}

/** `job`'s page as alice (an admin) opens it. */
export async function setUp(replies: Parameters<typeof stubApi>[0], job: JobName = "scrape") {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: ENTRIES[job] },
    [`GET /api/jobs/${job}/runs/active`]: { body: null },
    ...summaries,
    "GET /api/jobs/runs": noRuns,
    ...replies,
  });
  const view = renderApp(`/jobs/${job}`);
  const button = await until(() => screen.getByRole("button", { name: `Run ${NAMES[job]} now` }));
  await settle(); // its checks start
  /** Presses Run now. */
  const runNow = async () => {
    fireEvent.click(button);
    await wait(0); // the request is sent, and an answer at hand handled
  };
  const checks = () => calls.filter((call) => call.url.endsWith(queuedRun.id));
  const keys = () =>
    calls.filter((call) => call.method === "POST").map((c) => c.headers.get("idempotency-key"));
  return { calls, checks, keys, view, button, runNow };
}

/** The progress of `job`'s run: its steps, and what is announced about it. */
export function progressOf(name = "Source Collection"): HTMLElement {
  return screen.getByRole("group", { name: `${name}: run progress` });
}

export function status(name?: string) {
  return within(progressOf(name)).getByRole("status").textContent;
}

export function alerts(name?: string) {
  return within(progressOf(name))
    .queryAllByRole("alert")
    .map((alert) => alert.textContent);
}

/** Each step shown: its state (as its icon is named), its word and, on retries, its attempt. */
export function steps(name?: string): string[][] {
  const list = within(progressOf(name)).queryByRole("list");
  if (!list) {
    return [];
  }
  return within(list)
    .getAllByRole("listitem")
    .map((item) =>
      [...item.children].map((part) => part.getAttribute("aria-label") ?? part.textContent ?? ""),
    );
}

/** Waits until `text` is announced. */
export function announced(text: string, name?: string) {
  return until(() => {
    if (status(name) !== text) {
      throw new Error(`announced "${status(name)}", not "${text}"`);
    }
  });
}

/** A reply that comes once `answer` is called. */
export function later() {
  let answer: (reply: Reply) => void = () => undefined;
  const reply = new Promise<Reply>((resolve) => {
    answer = resolve;
  });
  return { reply: () => reply, answer };
}

export const offline = (): Reply => {
  throw new TypeError("Failed to fetch"); // as fetch does without a connection
};
