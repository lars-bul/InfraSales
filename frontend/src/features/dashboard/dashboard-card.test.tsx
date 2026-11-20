import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { dashboard, nextScrape } from "#/test/dashboard.ts";
import { stalled, unavailableOnce } from "#/test/fetch.ts";
import { vera } from "#/test/users.ts";

afterEach(() => {
  vi.useRealTimers();
});

test("each card is a region named by its heading, its link onward beside it", async () => {
  dashboard(vera);

  const card = await screen.findByRole("region", { name: "Next Job Runs" });
  const heading = within(card).getByRole("heading", { level: 2, name: "Next Job Runs" });
  expect(
    heading.parentElement?.contains(within(card).getByRole("link", { name: "All jobs" })),
  ).toBe(true);
});

test("a card loads on its own: while it loads it says so", async () => {
  dashboard(vera, undefined, { "GET /api/config": stalled });

  const card = within(await screen.findByRole("region", { name: "Next Job Runs" }));
  expect(card.getByRole("status").textContent).toBe("Loading…");
});

test("a card the service cannot answer offers to try again in place", async () => {
  dashboard(vera, undefined, {
    "GET /api/config": unavailableOnce({ body: [nextScrape] }, "error"),
  });

  const card = within(await screen.findByRole("region", { name: "Next Job Runs" }));
  await userEvent.click(await card.findByRole("button", { name: "Try again" }));

  expect(await card.findByRole("link", { name: "Source Collection" })).toBeTruthy();
});
