import { QueryClient } from "@tanstack/react-query";
import { expect, test, vi } from "vitest";
import {
  listConfigOptions,
  readSessionOptions,
  readSessionQueryKey,
} from "#/client/@tanstack/react-query.gen.ts";
import { listConfig, readSession } from "#/client/sdk.gen.ts";
import { stalled, stubApi } from "#/test/fetch.ts";
import { DEADLINE_MS } from "./deadline.ts";

test("generated calls go to the app's own origin, with the session cookie", async () => {
  const calls = stubApi({ "GET /api/auth/session": { body: { user: null, provider: "basic" } } });

  const { data } = await readSession();

  expect(data).toEqual({ user: null, provider: "basic" });
  expect(new URL(calls[0]?.url ?? "").origin).toBe(globalThis.location.origin);
  expect(calls[0]?.credentials).toBe("same-origin");
});

test("the generated query helpers are named after the operations", async () => {
  stubApi({ "GET /api/auth/session": { body: { user: null, provider: "oidc" } } });
  const queries = new QueryClient();

  const session = await queries.fetchQuery(readSessionOptions());

  expect(session).toEqual({ user: null, provider: "oidc" });
  expect(queries.getQueryData(readSessionQueryKey())).toEqual(session);
});

test("a query still unanswered at the deadline fails", async () => {
  vi.useFakeTimers();
  stubApi({ "GET /api/config": stalled });
  const queries = new QueryClient();

  const failure = expect(queries.fetchQuery(listConfigOptions())).rejects.toThrow(
    "No answer in time",
  );
  await vi.advanceTimersByTimeAsync(DEADLINE_MS - 1);
  expect(queries.getQueryState(listConfigOptions().queryKey)?.status).toBe("pending");
  await vi.advanceTimersByTimeAsync(1);

  await failure;
  vi.useRealTimers();
});

test("the caller can still abort a generated call", async () => {
  const calls = stubApi({ "GET /api/config": stalled });
  const caller = new AbortController();

  const failure = expect(listConfig({ signal: caller.signal, throwOnError: true })).rejects.toThrow(
    "aborted",
  );
  await vi.waitFor(() => expect(calls).toHaveLength(1));
  caller.abort();

  await failure;
});
