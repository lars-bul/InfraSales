import { screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { violations } from "#/test/axe.ts";
import { asked, dashboard } from "#/test/dashboard.ts";
import { vera } from "#/test/users.ts";

afterEach(() => {
  vi.useRealTimers();
});

// The cards' headings, in the order they show.
function cards(): string[] {
  return screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent ?? "");
}

// The strip's stages, by the name each leads with.
function stages(): string[] {
  return within(screen.getByRole("list", { name: "How collecting works" }))
    .getAllByRole("listitem")
    .map((stage) => within(stage).getAllByRole("link")[0]?.textContent ?? "");
}

test("admins see where InfraSales stands: today, the stages of collecting, and every card", async () => {
  const { container } = dashboard();

  expect(await screen.findByRole("heading", { level: 1, name: "Dashboard" })).toBeTruthy();
  expect(screen.getByText("Friday, October 16, 2026").getAttribute("datetime")).toBe("2026-10-16");
  expect(stages()).toEqual(["Feeds", "Sources"]);
  expect(cards()).toEqual(["Source Collection health", "Next Job Runs"]);
  await screen.findByText("42"); // the stages and cards have loaded
  expect(await violations(container)).toEqual([]);
});

test("viewers see the cards they may open, and ask for nothing only admins may read", async () => {
  const { calls, container } = dashboard(vera);

  await screen.findByRole("heading", { level: 1, name: "Dashboard" });
  expect(screen.queryByRole("list", { name: "How collecting works" })).toBeNull();
  expect(cards()).toEqual(["Next Job Runs"]);
  await screen.findByText("in 2 h");
  expect(asked(calls)).toEqual(["/api/config"]);
  expect(await violations(container)).toEqual([]);
});
