import { expect, test } from "vitest";
import { readSessionQueryKey } from "#/client/@tanstack/react-query.gen.ts";
import { createQueryClient } from "#/lib/query-client.ts";
import { stubApi } from "#/test/fetch.ts";
import { sessionQuery } from "./session.ts";

test("the session is asked for once, until it is invalidated", async () => {
  const calls = stubApi({ "GET /api/auth/session": { body: { user: null, provider: "basic" } } });
  const queries = createQueryClient();

  await queries.fetchQuery(sessionQuery());
  await queries.fetchQuery(sessionQuery());
  expect(calls).toHaveLength(1);

  await queries.invalidateQueries({ queryKey: readSessionQueryKey() });
  expect(await queries.fetchQuery(sessionQuery())).toEqual({ user: null, provider: "basic" });
  expect(calls).toHaveLength(2);
});
