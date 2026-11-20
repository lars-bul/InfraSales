import { expect, test } from "vitest";
import { personOf } from "./person.ts";

test.each([
  ["basic:alice", "alice"],
  ["oidc:a1b2c3", "a1b2c3"],
  ["oidc:issuer:sub", "issuer:sub"], // only the provider's prefix goes
  ["alice", "alice"], // no prefix: as it is
])("%s is shown as %s", (subject, shown) => {
  expect(personOf(subject)).toBe(shown);
});
