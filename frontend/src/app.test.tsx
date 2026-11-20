import { screen, waitFor, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { listAuditEvents } from "#/client/sdk.gen.ts";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { inTurn, stubApi, unavailableOnce } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { alice, anonymous, signedIn, vera } from "#/test/users.ts";

const aliceMenu = { name: "User menu: alice (admin)" };

test.each(["/", "/jobs", "/runs", "/jobs/scrape", "/audit", "/feeds", "/settings"])(
  "anonymous visitors opening %s are asked to sign in",
  async (url) => {
    stubApi({ "GET /api/auth/session": anonymous });

    const { container, router } = renderApp(url);

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(await violations(container)).toEqual([]);
  },
);

test("a failed built-in sign-in, reported to /, is announced on the sign-in page", async () => {
  stubApi({ "GET /api/auth/session": anonymous });

  const { router } = renderApp("/?signin=failed"); // where the backend sends a failed sign-in

  expect((await screen.findByRole("alert")).textContent).toBe(
    "Sign-in failedCheck your details and try again.",
  );
  expect(router.state.location.pathname).toBe("/sign-in");
});

test("signed-in admins see their user menu, the jobs and the audit log link", async () => {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [weekly] },
    "GET /api/jobs/runs": { body: [] },
  });

  const { container } = renderApp("/jobs");

  expect(await screen.findByRole("button", aliceMenu)).toBeTruthy();
  const pages = within(screen.getByRole("navigation", { name: "Pages" }));
  expect(pages.getByRole("link", { name: "Job runs" })).toBeTruthy(); // admins only
  expect(pages.getByRole("link", { name: "Jobs" }).getAttribute("aria-current")).toBe("page");
  expect(await violations(container)).toEqual([]);
});

test("admins follow the link to the audit log", async () => {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [weekly] },
    "GET /api/audit-events": { body: [] },
  });
  const { container, router } = renderApp("/jobs");

  await userEvent.click(await screen.findByRole("link", { name: "Audit log" }));

  expect(await screen.findByText("No events yet")).toBeTruthy();
  expect(router.state.location.pathname).toBe("/audit");
  expect(screen.queryByRole("heading", { name: "Jobs" })).toBeNull();
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Audit log");
  expect(await violations(container)).toEqual([]);
});

test("viewers see the jobs, and neither their runs nor the audit log", async () => {
  stubApi({
    "GET /api/auth/session": signedIn(vera),
    "GET /api/config": { body: [weekly] },
  });

  renderApp("/jobs");

  expect(
    await within(await screen.findByRole("main")).findByRole("link", { name: "Source Collection" }),
  ).toBeTruthy();
  expect(screen.queryByRole("link", { name: "Job runs" })).toBeNull();
  expect(screen.queryByRole("link", { name: "Audit log" })).toBeNull();
});

test("viewers opening the audit log land on the Dashboard", async () => {
  stubApi({
    "GET /api/auth/session": signedIn(vera),
    "GET /api/config": { body: [weekly] },
  });

  const { router } = renderApp("/audit");

  expect(await screen.findByRole("heading", { level: 1, name: "Dashboard" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/");
  expect(screen.queryByText("Audit log")).toBeNull();
});

test("when a screen's request finds the session ended, the app returns to signing in and says why", async () => {
  stubApi({
    "GET /api/auth/session": inTurn(signedIn(alice), anonymous),
    "GET /api/config": { status: 401 }, // the session timed out meanwhile (generated client)
  });

  const { container, router } = renderApp("/jobs");

  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toBe(
    "Your session has endedSign in again to continue.",
  );
  expect(router.state.location.pathname).toBe("/sign-in");
  expect(screen.queryByRole("button", aliceMenu)).toBeNull();
  expect(await violations(container)).toEqual([]);
});

test("a forbidden request leaves the user signed in", async () => {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [weekly] },
    "GET /api/audit-events": { status: 403 },
  });
  renderApp("/jobs");
  await screen.findByRole("button", aliceMenu);

  await listAuditEvents();

  expect(screen.getByRole("button", aliceMenu)).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
});

test.each(["error", "offline"] as const)(
  "a failed session check shows the unavailable screen, and trying again recovers (%s)",
  async (how) => {
    stubApi({ "GET /api/auth/session": unavailableOnce(anonymous, how) });
    const { container } = renderApp("/jobs");

    const retry = await screen.findByRole("button", { name: "Try again" });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("InfraSales");
    expect(screen.getByRole("alert").textContent).toBe(
      "Service unavailableInfraSales cannot reach its service right now. Try again in a moment.",
    );
    expect(await violations(container)).toEqual([]);
    await userEvent.click(retry);

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  },
);

test("a session check the server refuses is not taken for an ended session", async () => {
  const calls = stubApi({ "GET /api/auth/session": { status: 401 } });

  const { router } = renderApp("/");

  expect(await screen.findByRole("button", { name: "Try again" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/");
  expect(calls).toHaveLength(1);
});

test("no session state is kept in browser storage", async () => {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/config": { body: [weekly] },
  });

  renderApp("/jobs");
  await screen.findByRole("button", aliceMenu);

  await waitFor(() => expect(localStorage).toHaveLength(0));
  expect(sessionStorage).toHaveLength(0);
});
