import { expect, test } from "vitest";
import { heidelberg, ulm } from "#/test/forecast.ts";
import { rankingCsv } from "./csv.ts";

const HEADER = ["Rank", "AGS", "Municipality", "Population", "Score", "Why"];

test("each municipality is a row, its reasons by name, for German spreadsheets", () => {
  const csv = rankingCsv([heidelberg, ulm], HEADER, (feature) => feature.toUpperCase());

  expect(csv.startsWith("\ufeff")).toBe(true);
  expect(csv.slice(1).split("\r\n")).toEqual([
    "Rank;AGS;Municipality;Population;Score;Why",
    "1;08221000;Heidelberg;162000;0.0123;RECENT_COUNCIL_DECISION | RECENT_FUNDING_GRANTED",
    "2;08421000;Ulm;128000;0.0040;",
    "",
  ]);
});

test("cells with separators or quotes are quoted, unknown values empty", () => {
  const odd = { ...ulm, name: 'Stadt "Am See"; Nord', population: null };

  const [, row] = rankingCsv([odd], HEADER, String).slice(1).split("\r\n");

  expect(row).toBe('2;08421000;"Stadt ""Am See""; Nord";;0.0040;');
});
