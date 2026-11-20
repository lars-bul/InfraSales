import { screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import type { AuditEventRead } from "#/client/types.gen.ts";
import { violations } from "#/test/axe.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { alice, signedIn } from "#/test/users.ts";

let ids = 0;

function event(fields: Partial<AuditEventRead>): AuditEventRead {
  ids += 1;
  return {
    id: `event-${ids}`,
    created_at: "2026-10-02T06:37:51Z",
    actor: "basic:bob",
    action: "auth.login",
    outcome: "success",
    target: null,
    details: {},
    ...fields,
  };
}

// The log as alice, an admin, sees it with `events` in it.
async function logWith(...events: AuditEventRead[]) {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/audit-events": { body: events },
  });
  const view = renderApp("/audit");
  await screen.findByRole("table");
  return view;
}

function sentences() {
  return within(screen.getByRole("table"))
    .getAllByRole("button", { expanded: false })
    .map((button) => button.textContent?.trim());
}

test("each known event reads as a sentence that names its job or Feed", async () => {
  const { container } = await logWith(
    event({ action: "auth.login" }),
    event({ action: "auth.login", outcome: "failure" }),
    event({ action: "auth.login", outcome: "failure", actor: null }),
    event({ action: "auth.logout" }),
    event({ action: "auth.revoked", actor: null, target: "oidc:carol", details: { sessions: 2 } }),
    event({ action: "config.updated", target: "scrape_schedule" }),
    event({ action: "config.updated", target: "scrape_schedule" }),
    event({ action: "config.updated", target: "retention_days" }),
    event({ action: "job.triggered", target: "scrape" }),
    event({ action: "job.triggered", target: "scrape" }),
    event({ action: "job.triggered", target: "forecast" }),
    event({ action: "forecast.model_activated", target: "logistic-2026-01-01-abc123" }),
    event({ action: "feed.created", target: "tiefbau-aktuell", details: { kind: "rss" } }),
    event({ action: "feed.deleted", target: "tiefbau-aktuell", details: { kind: "rss" } }),
    event({ action: "retention.pruned", actor: null, details: { source: 3 } }),
    event({ action: "retention.deleted", actor: null, target: "source_version" }),
    event({ action: "retention.deleted", actor: null, target: "some_table" }),
    event({ action: "audit.read" }),
  );

  expect(sentences()).toEqual([
    "bob signed in",
    "Sign-in failed for bob",
    "Sign-in failed for an unknown user",
    "bob signed out",
    "system ended the sessions of carol",
    "bob changed the Source Collection schedule",
    "bob changed the Source Collection schedule",
    "bob changed the setting retention_days",
    "bob started Source Collection manually",
    "bob started Source Collection manually",
    "bob started Forecast manually",
    "bob made logistic-2026-01-01-abc123 the forecast model",
    "bob added the Feed tiefbau-aktuell",
    "bob deleted the Feed tiefbau-aktuell",
    "system deleted the data past its retention period",
    "system deleted expired Source Versions",
    "system deleted expired some_table",
    "bob read the audit log",
  ]);
  expect(await violations(container)).toEqual([]);
});

test("a failure is worded as one, whatever the action", async () => {
  await logWith(event({ action: "job.triggered", target: "scrape", outcome: "failure" }));

  expect(sentences()).toEqual(["bob started Source Collection manually (failed)"]);
});

test("an event the interface does not know yet still reads, by its code", async () => {
  const { container } = await logWith(
    event({ action: "some.action", target: "x" }),
    event({ action: "other.thing", actor: null }),
  );

  expect(sentences()).toEqual(["bob: some.action", "system: other.thing"]);
  expect(await violations(container)).toEqual([]);
});

test("people show without their provider, the reader as themselves", async () => {
  const { container } = await logWith(
    event({ action: "auth.logout", actor: "basic:alice" }),
    event({ action: "auth.logout", actor: "oidc:4f2a-91" }),
    event({ action: "auth.revoked", actor: null, target: "basic:alice" }),
    event({ action: "auth.logout", actor: "no-provider" }),
  );

  expect(sentences()).toEqual([
    "alice (you) signed out",
    "4f2a-91 signed out",
    "system ended the sessions of alice (you)",
    "no-provider signed out",
  ]);
  expect(await violations(container)).toEqual([]);
});
