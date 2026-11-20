import { screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { dashboard, nextScrape } from "#/test/dashboard.ts";
import { vera } from "#/test/users.ts";

afterEach(() => {
  vi.useRealTimers();
});

// The jobs' names in the Next Job Runs card, in order.
async function order(): Promise<string[]> {
  const card = within(await screen.findByRole("region", { name: "Next Job Runs" }));
  return (await card.findAllByRole("link", { name: "Source Collection" })).map(
    (link) => link.textContent ?? "",
  );
}

test("the schedules are read once for the card", async () => {
  const { calls } = dashboard(vera, { entries: [nextScrape] });

  expect(await order()).toEqual(["Source Collection"]);
  expect(calls.filter((call) => new URL(call.url).pathname === "/api/config")).toHaveLength(1);
});

test("a job without a next run is still listed", async () => {
  dashboard(vera, { entries: [{ ...nextScrape, next_run_at: null }] });

  expect(await order()).toEqual(["Source Collection"]);
});
