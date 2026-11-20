import { within } from "@testing-library/react";
import { expect, test } from "vitest";
import type { FeedUnderway, SourceCollectionProgress } from "#/client/types.gen.ts";
import { inTurn } from "#/test/fetch.ts";
import {
  announced,
  fakeTheClock,
  POLL,
  progressOf,
  setUp,
  status,
  violationsOf,
  wait,
} from "#/test/run-now.ts";
import { feedRead, queuedRun, runAs } from "#/test/runs.ts";

// While Run now follows a Source Collection, how far it got: Feed by Feed, and within each.
fakeTheClock();

const NAME = "Source Collection";
const QUEUE = "POST /api/jobs/scrape/runs";
const CHECK = `GET /api/jobs/scrape/runs/${queuedRun.id}`;
const queued = runAs("pending", { job: "scrape" });

function running(reported: SourceCollectionProgress | null) {
  return { body: runAs("running", { job: "scrape", attempts: 1, progress: reported }) };
}

function progress(changes: Partial<SourceCollectionProgress> = {}): SourceCollectionProgress {
  return {
    feeds_total: 21,
    feeds_done: 0,
    versions_new: 0,
    current: null,
    latest: null,
    ...changes,
  };
}

function reading(feed: string, changes: Partial<FeedUnderway> = {}): FeedUnderway {
  return { feed, items: null, done: 0, new: 0, ...changes };
}

const bar = () => within(progressOf(NAME)).queryByRole("progressbar", { name: "Feeds read" });
const area = () => bar()?.parentElement;
const lines = () => [...(area()?.querySelectorAll("p") ?? [])];

/** What the two lines say: line 1's parts (where it is, how much is done), line 2 as read. */
function shown() {
  const [first, second] = lines();
  return [...[...(first?.children ?? [])].map((part) => part.textContent), second?.textContent];
}

test("a running Source Collection shows where it is, Feed by Feed and item by item", async () => {
  const heizwerk = feedRead("heizwerk-journal-test", { items: 20, new: 14, known: 6 });
  const { view, runNow } = await setUp(
    {
      [QUEUE]: { status: 202, body: queued },
      [CHECK]: inTurn(
        running(null),
        running(progress({ current: reading("heizwerk-journal-test") })),
        running(
          progress({ current: reading("heizwerk-journal-test", { items: 40, done: 12, new: 3 }) }),
        ),
        running(progress({ feeds_done: 1, versions_new: 14, latest: heizwerk })),
        running(progress({ feeds_done: 1, current: reading("netzbau-de"), latest: heizwerk })),
        { body: runAs("succeeded", { job: "scrape", attempts: 1 }) },
      ),
    },
    "scrape",
  );

  await runNow();
  expect(bar()).toBeNull(); // queued: nothing read yet
  await wait(POLL);
  expect(shown()).toEqual(["Starting…", "0%", "Looking up the enabled Feeds"]);
  await wait(POLL);

  expect(shown()).toEqual([
    "Feed 1 of 21",
    "0%",
    "heizwerk-journal-test · getting its list of items…",
  ]);
  expect(bar()?.getAttribute("aria-valuetext")).toBe(
    "Feed 1 of 21: heizwerk-journal-test, getting its list of items…",
  );
  await wait(POLL);

  expect(shown()).toEqual(["Feed 1 of 21", "1%", "heizwerk-journal-test · 12 of 40 items · 3 new"]);
  expect(bar()?.getAttribute("aria-valuetext")).toBe(
    "Feed 1 of 21: heizwerk-journal-test, 12 of 40 items, 3 new",
  );
  // 12 of 40 items of the first of 21 Feeds: the bar moves within a Feed
  expect([bar()?.getAttribute("aria-valuenow"), bar()?.getAttribute("aria-valuemax")]).toEqual([
    "1",
    "100",
  ]);
  expect(status(NAME)).toBe("Running…"); // what is announced stays put: no chatter per item
  expect(await violationsOf(view.container)).toEqual([]);
  await wait(POLL);

  expect(shown()).toEqual(["Feed 1 of 21", "4%", "heizwerk-journal-test · 14 new"]); // between two Feeds
  await wait(POLL);
  expect(shown()).toEqual(["Feed 2 of 21", "4%", "netzbau-de · getting its list of items…"]);
  await wait(POLL);

  await announced("The run finished successfully.", NAME);
  expect(bar()).toBeNull(); // the result is in the run history
  expect(await violationsOf(view.container)).toEqual([]);
});

test("a Feed that failed or ran out of time says so in words", async () => {
  const gone = feedRead("trassenbau-report", { reason: "http 404" });
  const slow = feedRead("slow", { items: 3, new: 1, unread: 2, out_of_time: true });
  const { runNow } = await setUp(
    {
      [QUEUE]: { status: 202, body: queued },
      [CHECK]: inTurn(
        running(progress({ feeds_total: 2, feeds_done: 1, latest: gone })),
        running(progress({ feeds_total: 2, feeds_done: 2, versions_new: 1, latest: slow })),
      ),
    },
    "scrape",
  );

  await runNow();
  await wait(POLL);
  expect(shown()).toEqual(["Feed 1 of 2", "50%", "trassenbau-report · failed (http 404)"]);
  await wait(POLL);

  expect(shown()).toEqual(["Feed 2 of 2", "100%", "slow · 1 new · out of time, the rest waits"]);
});

// Its size, laid out by a browser: e2e/run-progress.e2e.ts. Here, what keeps it: two lines in
// every state, and a name cut short still whole in its title.
test("the progress is two lines in every state, a long name whole in its title", async () => {
  const long = "bundesministerium-fuer-wirtschaft-und-energie-pressemitteilungen";
  const { runNow } = await setUp(
    {
      [QUEUE]: { status: 202, body: queued },
      [CHECK]: inTurn(
        running(null),
        running(progress({ current: reading(long, { items: 300, done: 120 }) })),
        running(progress({ feeds_done: 1, latest: feedRead(long) })),
      ),
    },
    "scrape",
  );

  await runNow();
  const counted: number[] = [];
  for (const _ of [1, 2, 3]) {
    // biome-ignore lint/performance/noAwaitInLoops: one state after another
    await wait(POLL);
    counted.push(lines().length);
  }

  expect(counted).toEqual([2, 2, 2]);
  const name = within(lines()[1] as HTMLElement).getByText(long);
  expect(name.getAttribute("title")).toBe(long); // the whole name, where it is cut short
});
