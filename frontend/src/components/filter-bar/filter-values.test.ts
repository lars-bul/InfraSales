import { describe, expect, test } from "vitest";
import {
  activeFields,
  booleanOf,
  type FilterField,
  filtersFromSearch,
  filtersToSearch,
  groupsOf,
  isActive,
  labelsOf,
  matching,
  type OptionsField,
  optionsOf,
  periodBounds,
  periodOf,
  summarise,
  withValue,
} from "./filter-values.ts";

const KIND: OptionsField = {
  id: "kind",
  label: "Kind",
  type: "options",
  options: [
    { value: "rss", label: "RSS", count: 12 },
    { value: "sitemap", label: "Sitemap", count: 3 },
    { value: "html", label: "Web page", count: 1 },
  ],
};
const FIELDS: FilterField[] = [
  KIND,
  { id: "partial", label: "Partial", type: "boolean" },
  { id: "changed", label: "Last change", type: "period", custom: true },
  { id: "read", label: "Last read", type: "period" },
];
const NOW = new Date("2026-10-25T12:00:00Z");

test("a filter is set when it narrows anything", () => {
  expect(isActive(undefined)).toBe(false);
  expect(isActive([])).toBe(false);
  expect(isActive(["rss"])).toBe(true);
  expect(isActive(false)).toBe(true);
  expect(isActive({})).toBe(false);
  expect(isActive({ preset: "7d" })).toBe(true);
  expect(isActive({ to: "2026-10-20" })).toBe(true);
});

test("setting a filter to nothing removes it, and the fields set keep their order", () => {
  const values = withValue({ changed: { preset: "7d" } }, "kind", ["rss"]);

  expect(values).toEqual({ changed: { preset: "7d" }, kind: ["rss"] });
  expect(activeFields(FIELDS, values).map((field) => field.id)).toEqual(["kind", "changed"]);
  expect(withValue(values, "kind", [])).toEqual({ changed: { preset: "7d" } });
});

test("each kind of value is read back as its own type", () => {
  const values = { kind: ["rss"], partial: false, changed: { preset: "24h" as const } };

  expect(optionsOf(values, "kind")).toEqual(["rss"]);
  expect(optionsOf(values, "partial")).toEqual([]);
  expect(booleanOf(values, "partial")).toBe(false);
  expect(booleanOf(values, "kind")).toBeUndefined();
  expect(periodOf(values, "changed")).toEqual({ preset: "24h" });
  expect(periodOf(values, "kind")).toBeUndefined();
});

test("a chip names two values and counts the rest", () => {
  expect(summarise(["A"])).toEqual({ shown: ["A"], more: 0 });
  expect(summarise(["A", "B", "C", "D"])).toEqual({ shown: ["A", "B"], more: 2 });
  expect(summarise(["A", "B", "C"], 1)).toEqual({ shown: ["A"], more: 2 });
});

test("values are named in the field's order; one it does not offer keeps its value", () => {
  expect(labelsOf(KIND, ["html", "gone", "rss"])).toEqual(["RSS", "Web page", "gone"]);
});

test("options group under their group, in the order the groups first appear", () => {
  const groups = groupsOf([
    { value: "a", label: "A", group: "Press" },
    { value: "b", label: "B" },
    { value: "c", label: "C", group: "Press" },
  ]);

  expect(groups).toEqual([
    {
      group: "Press",
      options: [
        { value: "a", label: "A", group: "Press" },
        { value: "c", label: "C", group: "Press" },
      ],
    },
    { options: [{ value: "b", label: "B" }] },
  ]);
});

test("a search finds options by any part of their label, in any case", () => {
  expect(matching(KIND.options, " WEB ").map((option) => option.value)).toEqual(["html"]);
  expect(matching(KIND.options, "")).toBe(KIND.options);
});

describe("periods", () => {
  test("a preset reaches back from now and has no end", () => {
    expect(periodBounds({ preset: "24h" }, NOW)).toEqual({
      from: new Date("2026-10-24T12:00:00Z"),
    });
    expect(periodBounds({ preset: "30d" }, NOW).from).toEqual(new Date("2026-09-25T12:00:00Z"));
  });

  test("a custom range runs from its first day's midnight to the midnight after its last", () => {
    expect(periodBounds({ from: "2026-10-01", to: "2026-10-20" })).toEqual({
      from: new Date(2026, 9, 1),
      to: new Date(2026, 9, 21),
    });
    expect(periodBounds({ to: "2026-10-31" })).toEqual({ to: new Date(2026, 10, 1) });
    expect(periodBounds({})).toEqual({});
  });
});

describe("search parameters", () => {
  test("each field is one parameter; one not set is undefined, so spreading lifts it", () => {
    const search = filtersToSearch(FIELDS, {
      kind: ["rss", "sitemap"],
      partial: true,
      changed: { from: "2026-10-01", to: "2026-10-20" },
    });

    expect(search).toEqual({
      kind: "rss,sitemap",
      partial: "yes",
      changed: "2026-10-01..2026-10-20",
      read: undefined,
    });
  });

  test("what was written reads back the same", () => {
    const values = {
      kind: ["html"],
      partial: false,
      changed: { from: "2026-10-01" },
      read: { preset: "30d" as const },
    };

    expect(filtersFromSearch(FIELDS, filtersToSearch(FIELDS, values))).toEqual({
      ...values,
      changed: { from: "2026-10-01", to: undefined },
    });
  });

  test("the router's own types are read too, and what does not parse is ignored", () => {
    expect(
      filtersFromSearch(FIELDS, {
        kind: ["rss", 3, " "],
        partial: true,
        changed: "..2026-10-20",
        read: "2026-10-01..", // this field offers no custom range
        other: "x",
      }),
    ).toEqual({
      kind: ["rss", "3"],
      partial: true,
      changed: { from: undefined, to: "2026-10-20" },
    });
    expect(
      filtersFromSearch(FIELDS, { kind: " , ", partial: "maybe", changed: "1d", read: 7 }),
    ).toEqual({});
    expect(filtersFromSearch(FIELDS, { partial: "no", changed: "soon..later" })).toEqual({
      partial: false,
    });
  });
});
