import { QueryClient } from "@tanstack/react-query";
import { expect, test } from "vitest";
import type { SourceListed } from "#/client/types.gen.ts";
import { stubApi } from "#/test/fetch.ts";
import { listed } from "#/test/sources.ts";
import {
  countsBack,
  hostOf,
  isNarrowed,
  LIMIT,
  shortUrl,
  sourceCountQuery,
  sourceFiltersIn,
  sourceParams,
  sourcesQuery,
} from "./source-query.ts";

const NOW = new Date("2026-10-25T12:00:00Z");

test("the filters are read from the URL; blanks and anything else are dropped", () => {
  expect(sourceFiltersIn({ feed: "heizwerk-journal", run: "r1", q: "  bahnstadt " })).toEqual({
    feed: "heizwerk-journal",
    run: "r1",
    q: "bahnstadt",
  });
  expect(
    sourceFiltersIn({ feed: { a: 1 }, q: "   ", x: "y", period: "1y", partial: "maybe" }),
  ).toEqual({});
  expect(sourceFiltersIn({ feed: 3 })).toEqual({ feed: "3" }); // the router reads "?feed=3" as a number
});

test("several Feeds and categories are one parameter each; a category there is not is dropped", () => {
  expect(
    sourceFiltersIn({ feed: ["zfk", "energieatlas"], category: "authority,blogs,press" }),
  ).toEqual({ feed: "zfk,energieatlas", category: "authority,press" });
  expect(sourceFiltersIn({ category: "blogs" })).toEqual({});
});

test("the last change is a preset or days of one's own; yes and no as the bar writes them", () => {
  expect(sourceFiltersIn({ period: "7d", changed: true, partial: "false" })).toEqual({
    period: "7d",
    changed: "yes",
    partial: "no",
  });
  expect(sourceFiltersIn({ period: "2026-10-01..2026-10-20" })).toEqual({
    period: "2026-10-01..2026-10-20",
  });
  expect(sourceFiltersIn({ period: "2026-10-01.." })).toEqual({ period: "2026-10-01.." });
});

test("the API is asked for each filter: a preset counted back from now, days from midnight", () => {
  expect(sourceParams({}, NOW)).toEqual({});
  expect(
    sourceParams(
      {
        q: "bahnstadt",
        feed: "trassenbau-report,bnetza",
        category: "press",
        period: "7d",
        changed: "yes",
        partial: "no",
        run: "r1",
      },
      NOW,
    ),
  ).toEqual({
    q: "bahnstadt",
    feed: ["trassenbau-report", "bnetza"],
    category: ["press"],
    since: "2026-10-18T12:00:00.000Z",
    changed: true,
    partial: false,
    run: "r1",
  });
  const days = sourceParams({ period: "2026-10-01..2026-10-20" }, NOW);
  expect(days).toEqual({
    since: new Date(2026, 9, 1).toISOString(), // the browser's midnight
    until: new Date(2026, 9, 21).toISOString(), // the day after the last, which is not included
  });
});

test("only a preset counts back from now; anything set narrows the Sources", () => {
  expect([countsBack({ period: "24h" }), countsBack({ period: "..2026-10-20" })]).toEqual([
    true,
    false,
  ]);
  expect([isNarrowed({}), isNarrowed({ q: undefined }), isNarrowed({ run: "r1" })]).toEqual([
    false,
    false,
    true,
  ]);
});

test("an address is shortened for display, and its host named without www", () => {
  expect(shortUrl("https://www.heizwerk-journal.test/news/story.html")).toBe(
    "heizwerk-journal.test/news/story.html",
  );
  expect(shortUrl("http://policy.test/guidance/")).toBe("policy.test/guidance");
  expect(hostOf("https://www.heizwerk-journal.test/news/story.html")).toBe("heizwerk-journal.test");
});

test("a full page asks for the next one from its last listed version", async () => {
  const page: SourceListed[] = Array.from({ length: LIMIT }, (_, n) => ({
    ...listed(),
    version: { ...listed().version, id: `v${n}` },
  }));
  const calls = stubApi({ "GET /api/sources": { body: page } });
  const client = new QueryClient();

  const sources = await client.fetchInfiniteQuery(
    sourcesQuery({ feed: ["heizwerk-journal", "bnetza"] }),
  );
  const next = sourcesQuery({}).getNextPageParam(page, sources.pages, {}, [{}]);
  const short = sourcesQuery({}).getNextPageParam(page.slice(1), sources.pages, {}, [{}]);

  const asked = new URL(calls[0]?.url ?? "").searchParams;
  expect([asked.get("limit"), asked.getAll("feed"), asked.has("run")]).toEqual([
    "20",
    ["heizwerk-journal", "bnetza"],
    false,
  ]);
  expect([next, short]).toEqual([`v${LIMIT - 1}`, undefined]);
});

test("the count is asked for with the same filters", async () => {
  const calls = stubApi({ "GET /api/sources/count": { body: { count: 34 } } });
  const client = new QueryClient();

  const counted = await client.fetchQuery(
    sourceCountQuery({ category: ["press", "utility"], partial: true }),
  );

  const asked = new URL(calls[0]?.url ?? "").searchParams;
  expect(counted).toEqual({ count: 34 });
  expect([asked.getAll("category"), asked.get("partial"), asked.has("limit")]).toEqual([
    ["press", "utility"],
    "true",
    false,
  ]);
});
