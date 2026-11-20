import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import type { AuditEventRead } from "#/client/types.gen.ts";
import { violations } from "#/test/axe.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { alice, signedIn } from "#/test/users.ts";

const ONE = /The 1 most recent events/u;
const FOUR = /The 4 most recent events/u;

const base = {
  created_at: "2026-10-02T06:37:51Z",
  outcome: "success",
  target: null,
  details: {},
} as const;
const aliceRead: AuditEventRead = { ...base, id: "e5", actor: "basic:alice", action: "audit.read" };
const bobIn: AuditEventRead = { ...base, id: "e4", actor: "oidc:bob", action: "auth.login" };
const pruned: AuditEventRead = { ...base, id: "e3", actor: null, action: "retention.pruned" };
const bobOut: AuditEventRead = { ...base, id: "e2", actor: "oidc:bob", action: "auth.logout" };
const all = [aliceRead, bobIn, pruned, bobOut];

// The API's exact-match filters, applied to `all`.
function api(request: Request) {
  const asked = new URL(request.url).searchParams;
  const body = all.filter(
    (event) =>
      (!asked.has("actor") || event.actor === asked.get("actor")) &&
      (!asked.has("action") || event.action === asked.get("action")),
  );
  return { body };
}

function auditQueries(calls: Request[]) {
  return calls
    .filter((call) => new URL(call.url).pathname === "/api/audit-events")
    .map((call) => Object.fromEntries(new URL(call.url).searchParams));
}

async function openLog() {
  const calls = stubApi({ "GET /api/auth/session": signedIn(alice), "GET /api/audit-events": api });
  const view = renderApp("/audit");
  await screen.findByRole("table");
  return { calls, ...view };
}

function shown() {
  return within(screen.getByRole("table"))
    .getAllByRole("button")
    .map((event) => event.textContent);
}

function options(select: HTMLElement) {
  return within(select)
    .getAllByRole("option")
    .map((option) => option.textContent);
}

test("the person filter offers the people in the log and the system, and asks the API", async () => {
  const { calls, container } = await openLog();
  const person = screen.getByRole("combobox", { name: "Person" });
  expect(options(person)).toEqual(["All people", "alice (you)", "bob", "system"]);

  await userEvent.selectOptions(person, "bob");

  expect(await screen.findByRole("button", { name: "bob signed out" })).toBeTruthy();
  expect(shown()).toEqual(["bob signed in", "bob signed out"]);
  expect(auditQueries(calls).at(-1)).toEqual({ limit: "50", actor: "oidc:bob" });
  // The people seen before stay on offer, to switch to.
  expect(options(screen.getByRole("combobox", { name: "Person" }))).toEqual([
    "All people",
    "alice (you)",
    "bob",
    "system",
  ]);
  expect(await violations(container)).toEqual([]);
});

test("the event-type filter offers every known action and asks the API", async () => {
  const { calls, container } = await openLog();
  const type = screen.getByRole("combobox", { name: "Event type" });
  expect(options(type)).toEqual([
    "All event types",
    "Sign-in",
    "Sign-out",
    "Sessions ended",
    "Setting changed",
    "Run started manually",
    "Forecast model activated",
    "Feed added",
    "Feed deleted",
    "Retention round",
    "Expired data deleted",
    "Audit log read",
  ]);

  await userEvent.selectOptions(type, "Sign-out");

  expect(await screen.findByRole("table", { name: ONE })).toBeTruthy();
  expect(shown()).toEqual(["bob signed out"]);
  expect(auditQueries(calls).at(-1)).toEqual({ limit: "50", action: "auth.logout" });
  expect(await violations(container)).toEqual([]);
});

test("both filters narrow together, and choosing all again lifts them", async () => {
  const { calls } = await openLog();

  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Person" }), "bob");
  await screen.findByRole("button", { name: "bob signed out" });
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Event type" }), "Sign-in");
  await screen.findByRole("table", { name: ONE });
  expect(auditQueries(calls).at(-1)).toEqual({
    limit: "50",
    actor: "oidc:bob",
    action: "auth.login",
  });

  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Person" }), "All people");
  await userEvent.selectOptions(
    screen.getByRole("combobox", { name: "Event type" }),
    "All event types",
  );

  expect(await screen.findByRole("table", { name: FOUR })).toBeTruthy();
});

test("the system's events are picked from the loaded ones: the API has no filter for nobody", async () => {
  const { calls, container } = await openLog();

  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Person" }), "system");

  expect(await screen.findByRole("table", { name: ONE })).toBeTruthy();
  expect(shown()).toEqual(["system deleted the data past its retention period"]);
  expect(auditQueries(calls).every((query) => !("actor" in query))).toBe(true);
  expect(await violations(container)).toEqual([]);
});

test("filters that match nothing say so, and keep the filters to change", async () => {
  const { container } = await openLog();

  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Event type" }), "Feed added");

  expect(await screen.findByText("No matching events")).toBeTruthy();
  expect(screen.getByText("No event matches these filters. Choose other ones.")).toBeTruthy();
  expect(screen.getByRole("combobox", { name: "Event type" })).toHaveProperty(
    "value",
    "feed.created",
  );
  expect(screen.queryByRole("table")).toBeNull();
  expect(await violations(container)).toEqual([]);
});

test("a link to filtered events opens with the filters chosen", async () => {
  const calls = stubApi({ "GET /api/auth/session": signedIn(alice), "GET /api/audit-events": api });

  renderApp(`/audit?${new URLSearchParams({ actor: "oidc:bob", action: "auth.login" })}`);

  expect(await screen.findByRole("button", { name: "bob signed in" })).toBeTruthy();
  expect(auditQueries(calls)).toEqual([{ limit: "50", actor: "oidc:bob", action: "auth.login" }]);
  expect(screen.getByRole("combobox", { name: "Person" })).toHaveProperty("value", "oidc:bob");
});

test("older events load with the filters still applied", async () => {
  const page = Array.from({ length: 50 }, (_, n) => ({ ...bobIn, id: `bob-${n}` }));
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/audit-events": (request: Request) =>
      new URL(request.url).searchParams.has("before") ? { body: [bobOut] } : { body: page },
  });
  renderApp("/audit?actor=oidc%3Abob");

  await userEvent.click(await screen.findByRole("button", { name: "Load older events" }));

  expect(await screen.findByRole("button", { name: "bob signed out" })).toBeTruthy();
  expect(auditQueries(calls)).toEqual([
    { limit: "50", actor: "oidc:bob" },
    { limit: "50", actor: "oidc:bob", before: "bob-49" },
  ]);
});
