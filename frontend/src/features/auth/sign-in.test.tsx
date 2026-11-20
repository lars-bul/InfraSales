import { screen, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";

const basic = { body: { user: null, provider: "basic" } };
const oidc = { body: { user: null, provider: "oidc" } };

test("the basic card offers only the user name and password", async () => {
  stubApi({ "GET /api/auth/session": basic });

  const { container } = renderApp("/sign-in");

  const card = await screen.findByRole("region", { name: "Sign in" });
  expect(within(card).queryByRole("link")).toBeNull();
  const form = within(card).getByRole("button", { name: "Sign in" }).closest("form");
  expect(form?.getAttribute("action")).toBe("/api/auth/login");
  expect(form?.getAttribute("method")).toBe("post");
  expect(screen.getByLabelText("User name").getAttribute("autocomplete")).toBe("username");
  expect(screen.getByLabelText("Password").getAttribute("type")).toBe("password");
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("InfraSales");
  expect(screen.queryByRole("alert")).toBeNull();
  expect(await violations(container)).toEqual([]);
});

test("the OpenID Connect card offers only the company account", async () => {
  stubApi({ "GET /api/auth/session": oidc });

  const { container } = renderApp("/sign-in");

  const card = await screen.findByRole("region", { name: "Sign in" });
  const link = within(card).getByRole("link", { name: "Continue with your company account" });
  expect(link.getAttribute("href")).toBe("/api/auth/login");
  expect(within(card).queryByRole("textbox")).toBeNull();
  expect(within(card).queryByLabelText("Password")).toBeNull();
  expect(within(card).queryByRole("button")).toBeNull();
  expect(await violations(container)).toEqual([]);
});

// The callout opens the card, above the way to sign in, so it is read first.
function first(card: HTMLElement): HTMLElement | null {
  return card.querySelector("[role=alert], a, input, button");
}

const callouts = [
  ["?ended=true", "Your session has ended", "Sign in again to continue."],
  ["?signin=denied", "Access denied", "Your account has no access to this application."],
  ["?signin=failed", "Sign-in failed", "Check your details and try again."],
  [
    "?signin=unavailable",
    "Sign-in unavailable",
    "Signing in does not work right now. Please try again later.",
  ],
] as const;

describe.each([
  ["basic", basic],
  ["oidc", oidc],
])("the %s card", (_provider, session) => {
  test.each(callouts)("opens with a callout (%s)", async (search, title, line) => {
    stubApi({ "GET /api/auth/session": session });

    const { container } = renderApp(`/sign-in${search}`);

    const card = await screen.findByRole("region", { name: "Sign in" });
    const callout = within(card).getByRole("alert");
    expect(callout.textContent).toBe(`${title}${line}`);
    expect(first(card)).toBe(callout);
    expect(await violations(container)).toEqual([]);
  });
});

test("a failed sign-in after the session ended shows one callout, the failure", async () => {
  stubApi({ "GET /api/auth/session": basic });

  renderApp("/sign-in?signin=failed&ended=true");

  const card = await screen.findByRole("region", { name: "Sign in" });
  expect(
    within(card)
      .getAllByRole("alert")
      .map((callout) => callout.textContent),
  ).toEqual(["Sign-in failedCheck your details and try again."]);
});

test.each(["/sign-in?signin=script", "/sign-in?ended=yes", "/?signin=unknown"])(
  "unknown reasons are ignored (%s)",
  async (url) => {
    stubApi({ "GET /api/auth/session": basic });

    renderApp(url);

    expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  },
);

test("signed-in users opening the sign-in page land on the Dashboard", async () => {
  stubApi({
    "GET /api/auth/session": {
      body: { user: { subject: "basic:alice", name: "alice", role: "admin" }, provider: "basic" },
    },
    "GET /api/config": { body: [weekly] },
  });

  const { router } = renderApp("/sign-in?signin=failed");

  expect(await screen.findByRole("heading", { level: 1, name: "Dashboard" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/");
  expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
});
