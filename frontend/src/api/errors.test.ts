import { expect, test } from "vitest";
import { ApiError, withStatus } from "./errors.ts";

test("an error answer keeps its status and body", () => {
  const error = withStatus({ detail: "stale" }, new Response(null, { status: 412 }));

  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({ status: 412, body: { detail: "stale" } });
  expect(String(error)).toBe("ApiError: The API answered 412");
});

test("a request without an answer keeps its own error", () => {
  const offline = new TypeError("Failed to fetch");

  expect(withStatus(offline, undefined)).toBe(offline);
});
