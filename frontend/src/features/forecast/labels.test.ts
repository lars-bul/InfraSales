import { expect, test } from "vitest";
import { i18n } from "#/i18n/i18n.ts";
import { featureLabel, LAENDER } from "./labels.ts";

test("a feature is named for a reader, an unknown one keeps its code", () => {
  expect(featureLabel(i18n.t, "recent_council_decision")).toBe("Council decision");
  expect(featureLabel(i18n.t, "new_feature")).toBe("new_feature");
});

test("every Land has its two-digit AGS prefix, in order", () => {
  expect(LAENDER.map(([prefix]) => prefix)).toEqual(
    Array.from({ length: 16 }, (_, i) => String(i + 1).padStart(2, "0")),
  );
});
