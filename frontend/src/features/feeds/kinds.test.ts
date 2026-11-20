import { expect, test } from "vitest";
import { en } from "#/i18n/locales/en.ts";
import { ENTERED_BY_HAND, KINDS } from "./kinds.ts";

test("every kind has a label in the locale", () => {
  expect(Object.values(KINDS).map((key) => en.feeds.kinds[key])).toEqual(["RSS", "Sitemap"]);
});

test("a Feed entered by hand is RSS or Sitemap: kinds with settings are added through the API", () => {
  expect(ENTERED_BY_HAND).toEqual(["rss", "sitemap"]);
});
