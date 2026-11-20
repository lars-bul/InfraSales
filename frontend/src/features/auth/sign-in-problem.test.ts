import { expect, test } from "vitest";
import { problemIn } from "./sign-in-problem.ts";

test.each(["failed", "denied", "unavailable"])("a reported %s sign-in is kept", (signin) => {
  expect(problemIn({ signin, other: "x" })).toEqual({ signin });
});

test.each([undefined, "", "script", 1])("anything else is dropped (%s)", (signin) => {
  expect(problemIn({ signin })).toEqual({ signin: undefined });
});
