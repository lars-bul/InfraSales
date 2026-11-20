import { expect, test } from "vitest";
import { everyFeed, heizwerk, tiefbauAktuell } from "#/test/feeds.ts";
import { needsAttention, notRead } from "./states.ts";

test("the Feeds not read are the failing and blocked ones that are on", () => {
  expect(notRead(everyFeed).map((feed) => feed.name)).toEqual(["Energieatlas", "Tiefbau Aktuell"]);
});

test("a disabled Feed is not counted, whatever its state", () => {
  expect(notRead([{ ...heizwerk, state: "failing", enabled: false }])).toEqual([]);
});

test("a Feed needs attention while it is on and not OK", () => {
  expect(needsAttention(tiefbauAktuell)).toBe(true);
  expect(needsAttention(heizwerk)).toBe(false);
  expect(needsAttention({ ...tiefbauAktuell, enabled: false })).toBe(false);
});
