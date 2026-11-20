import { expect, test } from "vitest";
import { aroundChanges, wordDiff } from "./word-diff.ts";

const words = (count: number, word: string) => Array.from({ length: count }, () => word).join(" ");

test("it marks the words added and removed in the newer text, and counts them", () => {
  const diff = wordDiff("Es wird im Süden allein gebaut.", "Es wird jetzt auch im Norden gebaut.");

  expect(
    diff.stretches.filter((s) => s.change !== "kept").map((s) => [s.change, s.text.trim()]),
  ).toEqual([
    ["added", "jetzt auch"],
    ["removed", "Süden allein"],
    ["added", "Norden"],
  ]);
  expect([diff.added, diff.removed]).toEqual([3, 2]);
});

test("the stretches together give the newer text back, the removed ones left out", () => {
  const before = "One two three.\n\nFour five.";
  const after = "One three.\n\nFour five six.";

  const { stretches } = wordDiff(before, after);

  const newer = stretches.filter((s) => s.change !== "removed").map((s) => s.text);
  expect(newer.join("")).toBe(after);
});

test("the same text has no changes", () => {
  const diff = wordDiff("Same words here.", "Same words here.");

  expect([diff.added, diff.removed]).toEqual([0, 0]);
  expect(diff.stretches.every((stretch) => stretch.change === "kept")).toBe(true);
});

test("long unchanged stretches fold to the words around each change", () => {
  const before = `${words(100, "lead")} old ${words(100, "middle")} gone ${words(100, "end")}`;
  const after = `${words(100, "lead")} new ${words(100, "middle")} came ${words(100, "end")}`;

  const pieces = aroundChanges(wordDiff(before, after).stretches, 5);

  expect(pieces.map((piece) => piece.change)).toEqual([
    "skipped", // the lead: up to its last 5 words
    "kept",
    "removed",
    "added",
    "kept", // the middle: 5 words after the change, 5 before the next
    "skipped",
    "kept",
    "removed",
    "added",
    "kept",
    "skipped", // the end: after its first 5 words
  ]);
  expect(pieces[0]).toEqual({ change: "skipped", words: 95 });
  expect(pieces[4]).toEqual({ change: "kept", text: ` ${words(5, "middle")} ` });
  expect(pieces[5]).toEqual({ change: "skipped", words: 90 });
});

test("short unchanged stretches stay whole", () => {
  const { stretches } = wordDiff("one two three old four five", "one two three new four five");

  expect(aroundChanges(stretches, 5)).toEqual(stretches);
});
