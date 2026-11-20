import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import type { AuditEventRead } from "#/client/types.gen.ts";
import { violations } from "#/test/axe.ts";
import { stubApi, unavailableOnce } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { alice, signedIn } from "#/test/users.ts";

const ONE = /The 1 most recent events/u;
const FIFTY = /The 50 most recent events/u;
const FIFTY_ONE = /The 51 most recent events/u;
const EVENTS_APPEAR_HERE = "Sign-ins, schedule changes and runs started by hand are recorded here.";

const newest: AuditEventRead = {
  id: "01a0fb55-5e22-70be-8476-7b4f76fa0835",
  created_at: "2026-10-02T06:37:51Z",
  actor: "basic:alice",
  action: "config.updated",
  outcome: "success",
  target: "scrape_schedule",
  details: { after: { enabled: false } },
};
const older: AuditEventRead = {
  id: "01a0fb55-31b7-7585-b5ae-fab914dc1a2f",
  created_at: "2026-10-02T06:37:39Z",
  actor: null,
  action: "auth.login",
  outcome: "failure",
  target: null,
  details: {},
};

// A full page: there may be older events behind it.
const fullPage = Array.from({ length: 50 }, (_, n) => ({ ...newest, id: `event-${n}` }));

function query(request: Request | undefined) {
  return Object.fromEntries(new URL(request?.url ?? "http://x/").searchParams);
}

function auditCalls(calls: Request[]) {
  return calls.filter((call) => new URL(call.url).pathname === "/api/audit-events");
}

test("opening the audit log shows the newest events at once", async () => {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/audit-events": { body: [newest, older] },
  });

  const { container } = renderApp("/audit");

  const table = await screen.findByRole("table", {
    name: "The 2 most recent events, newest first",
  });
  expect(screen.getByRole("heading", { level: 1, name: "Audit log" })).toBeTruthy();
  const [first] = auditCalls(calls);
  expect(query(first)).toEqual({ limit: "50" }); // the newest page: no cursor
  expect(
    within(table)
      .getAllByRole("columnheader")
      .map((head) => head.textContent),
  ).toEqual(["Activity", "Time"]);
  const sentences = within(table)
    .getAllByRole("button", { expanded: false })
    .map((sentence) => sentence.textContent);
  expect(sentences).toEqual([
    "alice (you) changed the Source Collection schedule",
    "Sign-in failed for an unknown user",
  ]);
  expect(table.textContent).not.toContain("config.updated"); // codes only in the details
  expect(screen.queryByRole("button", { name: "Load older events" })).toBeNull(); // a short page
  expect(await violations(container)).toEqual([]);
});

test("an empty log says so", async () => {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/audit-events": { body: [] },
  });

  const { container } = renderApp("/audit");

  expect(await screen.findByText("No events yet")).toBeTruthy();
  expect(screen.getByText(EVENTS_APPEAR_HERE)).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByRole("button", { name: "Load older events" })).toBeNull();
  expect(await violations(container)).toEqual([]);
});

test("older events load on request, before the last one shown", async () => {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/audit-events": (request: Request) =>
      new URL(request.url).searchParams.has("before") ? { body: [older] } : { body: fullPage },
  });
  const { container } = renderApp("/audit");

  await userEvent.click(await screen.findByRole("button", { name: "Load older events" }));

  const table = await screen.findByRole("table", { name: FIFTY_ONE });
  expect(auditCalls(calls).map(query)).toEqual([
    { limit: "50" },
    { limit: "50", before: "event-49" },
  ]);
  expect(
    within(table).getByRole("button", { name: "Sign-in failed for an unknown user" }),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Load older events" })).toBeNull(); // the end
  expect(await violations(container)).toEqual([]);
});

test.each(["error", "offline"] as const)(
  "older events that fail to load can be tried again in place (%s)",
  async (how) => {
    const olderOnce = unavailableOnce({ body: [older] }, how);
    let pages = 0;
    stubApi({
      "GET /api/auth/session": signedIn(alice),
      "GET /api/audit-events": (request: Request) => {
        pages += 1;
        return pages === 1 ? { body: fullPage } : olderOnce(request);
      },
    });
    const { container } = renderApp("/audit");

    await userEvent.click(await screen.findByRole("button", { name: "Load older events" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("table", { name: FIFTY })).toBeTruthy();
    expect(await violations(container)).toEqual([]);

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("table", { name: FIFTY_ONE })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  },
);

test("an unavailable log shows the unavailable screen, and trying again loads it", async () => {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/audit-events": unavailableOnce({ body: [newest] }, "error"),
  });
  const { container } = renderApp("/audit");

  const retry = await screen.findByRole("button", { name: "Try again" });
  expect(await violations(container)).toEqual([]); // inside the shell's own <main>
  await userEvent.click(retry);

  expect(await screen.findByRole("table", { name: ONE })).toBeTruthy();
  expect(await violations(container)).toEqual([]);
});

test("refresh reads the newest events again, from the first page", async () => {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/audit-events": (request: Request) =>
      new URL(request.url).searchParams.has("before") ? { body: [older] } : { body: fullPage },
  });
  renderApp("/audit");
  await userEvent.click(await screen.findByRole("button", { name: "Load older events" }));
  await screen.findByRole("table", { name: FIFTY_ONE });

  await userEvent.click(screen.getByRole("button", { name: "Refresh" }));

  expect(await screen.findByRole("table", { name: FIFTY })).toBeTruthy();
  expect(auditCalls(calls).map(query)).toEqual([
    { limit: "50" },
    { limit: "50", before: "event-49" },
    { limit: "50" },
  ]);
});
