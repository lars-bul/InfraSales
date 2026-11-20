import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import type { AuditEventRead } from "#/client/types.gen.ts";
import { violations } from "#/test/axe.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { alice, signedIn } from "#/test/users.ts";

const change: AuditEventRead = {
  id: "01a0fb55-5e22-70be-8476-7b4f76fa0835",
  created_at: "2026-10-02T06:37:51Z",
  actor: "basic:alice",
  action: "config.updated",
  outcome: "success",
  target: "scrape_schedule",
  details: { before: { enabled: true }, after: { enabled: false } },
};
const failedSignIn: AuditEventRead = {
  id: "01a0fb55-31b7-7585-b5ae-fab914dc1a2f",
  created_at: "2026-10-02T06:37:39Z",
  actor: null,
  action: "auth.login",
  outcome: "failure",
  target: null,
  details: { reason: "OAuthError" },
};

function logWith(...events: AuditEventRead[]) {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/audit-events": { body: events },
  });
  return renderApp("/audit");
}

// The key–value pairs an expanded event shows, in order.
function pairs(details: HTMLElement) {
  return within(details)
    .getAllByRole("term")
    .map((term) => [term.textContent, term.nextElementSibling?.textContent]);
}

function detailsOf(event: HTMLElement) {
  return document.getElementById(event.getAttribute("aria-controls") ?? "") as HTMLElement;
}

test("an event expands to its details as key–value pairs, by keyboard, and folds again", async () => {
  const { container } = logWith(change, failedSignIn);
  const event = await screen.findByRole("button", {
    name: "alice (you) changed the Source Collection schedule",
    expanded: false,
  });

  event.focus();
  await userEvent.keyboard("{Enter}");

  expect(event.getAttribute("aria-expanded")).toBe("true");
  expect(pairs(detailsOf(event))).toEqual([
    ["Outcome", "success"],
    ["Action", "config.updated"],
    ["Target", "scrape_schedule"],
    ["Actor", "basic:alice"], // the full subject
    ["before", '{"enabled":true}'],
    ["after", '{"enabled":false}'],
  ]);
  expect(await violations(container)).toEqual([]);

  await userEvent.keyboard(" ");

  expect(event.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByRole("term")).toBeNull();
});

test("an event by nobody names the system as its actor, and a missing target as none", async () => {
  const { container } = logWith(change, failedSignIn);

  const event = await screen.findByRole("button", { name: "Sign-in failed for an unknown user" });
  await userEvent.click(event);

  expect(pairs(detailsOf(event))).toEqual([
    ["Outcome", "failure"],
    ["Action", "auth.login"],
    ["Target", "none"],
    ["Actor", "system"],
    ["reason", "OAuthError"],
  ]);
  // The other event stays folded.
  expect(
    screen.getByRole("button", { name: "alice (you) changed the Source Collection schedule" }),
  ).toHaveProperty("ariaExpanded", "false");
  expect(await violations(container)).toEqual([]);
});
