import { expect, test } from "vitest";
import { en } from "./en.ts";

function leaves(messages: object): unknown[] {
  return Object.values(messages).flatMap((value: unknown) =>
    typeof value === "object" && value !== null ? leaves(value) : [value],
  );
}

test("every message is non-empty text", () => {
  expect(leaves(en).every((message) => typeof message === "string" && message.trim())).toBe(true);
});
