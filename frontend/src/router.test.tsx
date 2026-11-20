import { Link } from "@tanstack/react-router";
import { expect, test } from "vitest";
import { createQueryClient } from "#/lib/query-client.ts";
import { createAppRouter } from "./router.tsx";

test("the router shares the app's query client and preloads on intent", () => {
  const queryClient = createQueryClient();

  const router = createAppRouter(queryClient);

  expect(router.options.context.queryClient).toBe(queryClient);
  expect(router.options.defaultPreload).toBe("intent");
});

test("links lead only to routes that exist: tsc rejects any other", () => {
  const links = [
    <Link key="dashboard" to="/" />,
    <Link key="jobs" to="/jobs" />,
    <Link key="audit" to="/audit" />,
    <Link key="sign-in" to="/sign-in" search={{ ended: true }} />,
    // @ts-expect-error: there is no such route
    <Link key="missing" to="/no-such-page" />,
  ];

  expect(links).toHaveLength(5);
});
