import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { dashboard } from "#/test/dashboard.ts";
import { vera } from "#/test/users.ts";

afterEach(() => {
  vi.useRealTimers();
});

test("a card's link onward leads to the page it summarises, its arrow hidden from screen readers", async () => {
  const { router } = dashboard(vera, undefined, { "GET /api/jobs/runs": { body: [] } });

  const card = within(await screen.findByRole("region", { name: "Next Job Runs" }));
  const onward = card.getByRole("link", { name: "All jobs" });
  expect(onward.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  await userEvent.click(onward);

  expect(await screen.findByRole("heading", { level: 1, name: "Jobs" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/jobs");
});
