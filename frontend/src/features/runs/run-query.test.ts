import { expect, test } from "vitest";
import { activityQuery, instant, LIMIT, runFiltersIn, runsQuery } from "./run-query.ts";

test("the filters are read from the URL; anything unknown is ignored", () => {
  expect(runFiltersIn({ job: "scrape", status: "failed", trigger: "manual" })).toEqual({
    job: "scrape",
    status: "failed",
    trigger: "manual",
  });
  expect(runFiltersIn({ job: "weather", status: "lost", trigger: 1, page: "2" })).toEqual({
    job: undefined,
    status: undefined,
    trigger: undefined,
    start: undefined,
    end: undefined,
  });
});

test("a start and an end are local dates and times; an end not after the start is ignored", () => {
  const range = { start: "2026-10-10T10:00", end: "2026-10-12T09:30" };
  expect(runFiltersIn(range)).toMatchObject(range);
  expect(runFiltersIn({ start: "2026-10-12T09:30", end: "2026-10-12T09:30" })).toMatchObject({
    start: "2026-10-12T09:30",
    end: undefined,
  });
  expect(runFiltersIn({ start: "2026-10-10", end: "2026-13-40T10:00" })).toMatchObject({
    start: undefined, // a date without a time
    end: undefined, // no such day
  });
  expect(runFiltersIn({ end: "2026-10-12T09:30" })).toMatchObject({ end: "2026-10-12T09:30" });
});

test("the runs are asked for a page at a time, with the filters chosen only", () => {
  const [all] = runsQuery({}).queryKey;
  const [failed] = runsQuery({ job: "scrape", status: "failed" }).queryKey;

  expect(all.query).toEqual({ limit: LIMIT });
  expect(failed.query).toEqual({ limit: LIMIT, job: "scrape", status: "failed" });
});

test("a start and an end are asked for as instants, in the browser's time zone", () => {
  const [between] = runsQuery({ start: "2026-10-10T10:00", end: "2026-10-12T09:30" }).queryKey;

  expect(between.query).toEqual({
    limit: LIMIT,
    start: new Date(2026, 9, 10, 10).toISOString(),
    end: new Date(2026, 9, 12, 9, 30).toISOString(),
  });
  expect(instant("2026-10-10T10:00")).toBe(new Date(2026, 9, 10, 10).toISOString());
});

test("the activity is asked for with the same filters, in the browser's time zone", () => {
  const { timeZone } = Intl.DateTimeFormat().resolvedOptions();
  const [every] = activityQuery({}).queryKey;
  const [failed] = activityQuery({
    job: "scrape",
    status: "failed",
    end: "2026-10-12T09:30",
  }).queryKey;

  expect(every.query).toEqual({ timezone: timeZone });
  expect(failed.query).toEqual({
    timezone: timeZone,
    job: "scrape",
    status: "failed",
    end: new Date(2026, 9, 12, 9, 30).toISOString(),
  });
});

test("a full page may have older runs after it, from its last one; a short page is the last", () => {
  const { getNextPageParam } = runsQuery({});
  const run = (id: string) => ({ id }) as Parameters<typeof getNextPageParam>[0][number];
  const full = Array.from({ length: LIMIT }, (_, n) => run(`run-${n}`));

  expect(getNextPageParam(full, [full], {}, [{}])).toBe(`run-${LIMIT - 1}`);
  expect(getNextPageParam(full.slice(1), [full.slice(1)], {}, [{}])).toBeUndefined();
});
