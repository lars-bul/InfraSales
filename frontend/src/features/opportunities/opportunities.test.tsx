import { screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import type { OpportunityRead } from "#/client/types.gen.ts";
import { violations } from "#/test/axe.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { alice, signedIn, vera } from "#/test/users.ts";

const OPPORTUNITIES = "GET /api/company/opportunities";

const open: OpportunityRead = {
  kind: "open",
  tender_id: "0190e1c8-0000-7000-8000-000000000009",
  title: "Fernwärme Bahnstadt Süd",
  municipality_ags: "08221000",
  municipality: "Heidelberg",
  buyer: "Stadtwerke Heidelberg GmbH",
  distance_km: 11.2,
  win_chance: 0.31,
  tender_chance: null,
  forecast_rank: null,
  deadline_on: "2026-12-15",
  value_eur: 900_000,
  expected_offers: 4,
  form: {
    basis: "buyer",
    tenders: 5,
    procedure: "open",
    procedure_share: 0.8,
    lots_median: 1,
    framework_share: 0,
    price_only_share: 0.6,
    duration_months_median: 12,
    value_eur_median: 800_000,
    offers_median: 4,
  },
  reasons: ["near", "won_with_buyer"],
};

const expected: OpportunityRead = {
  ...open,
  kind: "expected",
  tender_id: null,
  title: "Walldorf",
  municipality_ags: "08226095",
  municipality: "Walldorf",
  deadline_on: null,
  win_chance: 0.12,
  forecast_rank: 14,
  reasons: ["no_public_wins"],
};

function cells(row: HTMLElement | undefined) {
  return within(row as HTMLElement)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
}

test("a member sees the company's chances, open tenders first, with form and reasons", async () => {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    [OPPORTUNITIES]: { body: [open, expected] },
  });
  const { container } = renderApp("/opportunities");

  const table = await screen.findByRole("table", { name: "2 opportunities, best chance first" });

  const [, first, second] = within(table).getAllByRole("row");
  expect(cells(first)).toEqual([
    "31%",
    "Open tender",
    "Fernwärme Bahnstadt SüdHeidelberg",
    "11.2 km",
    "Dec 15, 2026",
    "€900,000",
    "4",
    "open · lots 1 · price only 60%",
    "NearWon with this buyer",
  ]);
  expect(cells(second)?.[1]).toBe("Expected");
  expect(within(table).getByRole("link", { name: "Walldorf" }).getAttribute("href")).toBe(
    "/forecast/08226095",
  );
  expect(await violations(container)).toEqual([]);
});

test("a user of no company is told to ask for an invitation", async () => {
  stubApi({
    "GET /api/auth/session": signedIn(vera),
    [OPPORTUNITIES]: { status: 403, body: { detail: "No company" } },
  });
  renderApp("/opportunities");

  expect(await screen.findByText("No company yet")).toBeTruthy();
});

test("without anything in reach the page says how to widen it", async () => {
  stubApi({ "GET /api/auth/session": signedIn(alice), [OPPORTUNITIES]: { body: [] } });
  renderApp("/opportunities");

  expect(await screen.findByText("No opportunities in reach")).toBeTruthy();
});

test("the service unavailable, the page offers to try again", async () => {
  stubApi({ "GET /api/auth/session": signedIn(alice), [OPPORTUNITIES]: { status: 503 } });
  renderApp("/opportunities");

  expect(await screen.findByRole("button", { name: "Try again" })).toBeTruthy();
});
