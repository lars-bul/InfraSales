import { expect, test } from "vitest";
import { scrape, weekly } from "#/test/entries.ts";
import { EVERY_JOB, JOB_STATES, matches } from "./job-filter.ts";

const paused = { ...weekly, value: { ...weekly.value, enabled: false } };
const { enabled: _enabled, ...always } = scrape.value;
const stored = { ...scrape, value: always }; // stored before jobs could be paused

test("no filter lists every job", () => {
  expect(matches(weekly, "Source Collection", EVERY_JOB)).toBe(true);
  expect(matches(paused, "Source Collection", EVERY_JOB)).toBe(true);
});

test.each([
  ["part of the name, in any case", "COLLECT", true],
  ["another job's ID", "archive", false],
  ["the job's own ID", "scrape", true],
  ["blanks around it", "  source ", true],
  ["another name", "report", false],
])("a job matches %s", (_, text, expected) => {
  expect(matches(weekly, "Source Collection", { text, state: "all" })).toBe(expected);
});

test("a job matches its ID, typed in any case", () => {
  expect(matches(scrape, "Source Collection", { text: "Scrape", state: "all" })).toBe(true);
  expect(matches(scrape, "Source Collection", { text: "scr", state: "all" })).toBe(true);
});

test("on and paused pick the jobs in that state; a schedule without a state is on", () => {
  expect(matches(weekly, "Source Collection", { text: "", state: "on" })).toBe(true);
  expect(matches(paused, "Source Collection", { text: "", state: "on" })).toBe(false);
  expect(matches(paused, "Source Collection", { text: "", state: "paused" })).toBe(true);
  expect(matches(stored, "Source Collection", { text: "", state: "on" })).toBe(true);
});

test("the states are offered all first", () => {
  expect(JOB_STATES).toEqual(["all", "on", "paused"]);
});
