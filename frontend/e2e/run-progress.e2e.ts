import type { Page } from "@playwright/test";
import type {
  FeedOutcome,
  FeedUnderway,
  RunProgress,
  SourceCollectionProgress,
} from "../src/client/types.gen.ts";
import { en } from "../src/i18n/locales/en.ts";
import { expect, test } from "./fixtures.ts";
import { sessionOf } from "./users.ts";

// Run now follows a Source Collection from Feed to Feed: its box keeps its size, laid out by a
// real browser. The run is the API's answers, stubbed: the test profile reads no Feeds.

test.use({ storageState: sessionOf("alice") });

const RUN_ID = "0192f0c4-7e1a-7c3e-8a52-6f0e4c3b2a10";
const LONG = "bundesministerium-fuer-wirtschaft-und-energie-pressemitteilungen";
const WIDTHS = { phone: 390, desktop: 1280 };

function underway(feed: string, changes: Partial<FeedUnderway> = {}): FeedUnderway {
  return { feed, items: null, done: 0, new: 0, ...changes };
}

function read(feed: string, changes: Partial<FeedOutcome> = {}): FeedOutcome {
  const counts = { items: 0, new: 0, unchanged: 0, known: 0, seen: 0, failed: 0, unread: 0 };
  return { feed, ...counts, reason: null, out_of_time: false, seconds: 1, ...changes };
}

function progress(changes: Partial<SourceCollectionProgress>): SourceCollectionProgress {
  return {
    feeds_total: 23,
    feeds_done: 0,
    versions_new: 0,
    current: null,
    latest: null,
    ...changes,
  };
}

// Each state in turn, and a word of what it shows: before the first report, a Feed listed, a
// long name item by item, that Feed failed.
const STATES: [SourceCollectionProgress | null, string][] = [
  [null, en.jobs.feedProgress.starting],
  [progress({ current: underway("heizwerk-journal-test") }), "heizwerk-journal-test"],
  [progress({ current: underway(LONG, { items: 300, done: 120, new: 12 }) }), "120 of 300 items"],
  [progress({ feeds_done: 1, latest: read(LONG, { reason: "http 404" }) }), "http 404"],
];

function running(reported: SourceCollectionProgress | null): RunProgress {
  return {
    id: RUN_ID,
    job: "scrape",
    trigger: "manual",
    status: "running",
    scheduled_for: "2026-10-02T08:00:00Z",
    attempts: 1,
    finished_at: null,
    error: null,
    max_attempts: 3,
    progress: reported,
  };
}

// The run in progress as the page loads, then each state on the next check.
async function followRun(page: Page): Promise<(state: number) => void> {
  let shown = 0;
  await page.route("**/api/jobs/scrape/runs/active", (route) =>
    route.fulfill({ json: running(STATES[0]?.[0] ?? null) }),
  );
  await page.route(`**/api/jobs/scrape/runs/${RUN_ID}`, (route) =>
    route.fulfill({ json: running(STATES[shown]?.[0] ?? null) }),
  );
  return (state) => {
    shown = state;
  };
}

for (const [device, width] of Object.entries(WIDTHS)) {
  test(`a running Source Collection's progress keeps its size, on a ${device}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const show = await followRun(page);
    await page.goto("/jobs/scrape");
    const box = page.getByRole("group", {
      name: en.jobs.steps.label.replace("{{name}}", "Source Collection"),
    });
    const bar = box.getByRole("progressbar", { name: en.jobs.feedProgress.label });

    const sizes: string[] = [];
    for (const [state, [, word]] of STATES.entries()) {
      show(state);
      // biome-ignore lint/performance/noAwaitInLoops: one state after another, as checked
      await expect(bar).toHaveAttribute("aria-valuetext", new RegExp(word, "u"));
      const [outer, inner] = await Promise.all([box.boundingBox(), bar.boundingBox()]);
      sizes.push(JSON.stringify([outer?.width, outer?.height, inner?.width]));
    }

    expect(new Set(sizes).size).toBe(1); // the same in every state: nothing jumps
    const [measured] = sizes;
    expect(JSON.parse(measured ?? "[]")[0]).toBeLessThanOrEqual(width); // no sideways scroll
  });
}
