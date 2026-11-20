import { expect, test } from "vitest";
import { forecastSearchIn, regionOf } from "./search.ts";

test("a region is an AGS prefix of up to eight digits", () => {
  expect(regionOf("08")).toBe("08");
  expect(regionOf("08221000")).toBe("08221000");
  expect(regionOf("082210001")).toBeUndefined();
  expect(regionOf("BW")).toBeUndefined();
  expect(regionOf(8)).toBeUndefined();
});

test("the search keeps a valid region and a later page only", () => {
  expect(forecastSearchIn({ region: "09", page: "3" })).toEqual({ region: "09", page: 3 });
  expect(forecastSearchIn({ region: "x", page: "1" })).toEqual({
    region: undefined,
    page: undefined,
  });
  expect(forecastSearchIn({ page: "2.5" }).page).toBeUndefined();
});

test("a region the router read as a number gets its leading zero back", () => {
  expect(forecastSearchIn({ region: 8 }).region).toBe("08");
});
