import { expect, test } from "vitest";
import { en } from "#/i18n/locales/en.ts";
import { CATEGORIES } from "./categories.ts";

test("every category has a label and a hint in the locale, the press first", () => {
  expect(CATEGORIES.map((category) => en.feeds.categories[category])).toEqual([
    "Press",
    "Municipality",
    "Utility",
    "Procurement",
    "Authority",
  ]);
  expect(CATEGORIES.every((category) => en.feeds.categoryHints[category])).toBe(true);
});
