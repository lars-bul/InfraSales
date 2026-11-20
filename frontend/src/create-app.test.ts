import { createMemoryHistory } from "@tanstack/react-router";
import { expect, test } from "vitest";
import { ApiError } from "#/api/errors.ts";
import { listConfig } from "#/client/sdk.gen.ts";
import { stubApi } from "#/test/fetch.ts";
import { createApp } from "./create-app.ts";

const history = () => createMemoryHistory({ initialEntries: ["/"] });

test("while connected, error answers carry their status", async () => {
  stubApi({ "GET /api/config": { status: 503, body: { detail: "down" } } });
  const app = createApp({ history: history() });

  const connected = await listConfig();
  app.disconnect();
  const disconnected = await listConfig();

  expect(connected.error).toEqual(new ApiError(503, { detail: "down" }));
  expect(disconnected.error).toEqual({ detail: "down" }); // the generated client's own error
});

test("once disconnected, a 401 no longer leads to signing in", async () => {
  const calls = stubApi({ "GET /api/config": { status: 401 } });
  const app = createApp({ history: history() });
  app.disconnect();

  await listConfig();
  await new Promise((settled) => setTimeout(settled)); // time to navigate, were it connected

  expect(calls).toHaveLength(1); // no session check
  expect(app.router.state.location.search).toEqual({});
});
