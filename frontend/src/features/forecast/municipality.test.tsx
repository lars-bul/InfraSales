import { screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { stubApi } from "#/test/fetch.ts";
import { heidelbergFile } from "#/test/forecast.ts";
import { renderApp } from "#/test/render.tsx";
import { signedIn, vera } from "#/test/users.ts";

const FILE = "GET /api/forecast/municipalities/08221000";
const FACTS = /AGS 08221000 · 162,000 inhabitants/;

function filePage(reply: Parameters<typeof stubApi>[0][string]) {
  stubApi({ "GET /api/auth/session": signedIn(vera), [FILE]: reply });
  return renderApp("/forecast/08221000");
}

function cells(row: HTMLElement | undefined) {
  return within(row as HTMLElement)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
}

test("a municipality's file shows its rank, reasons, signals, tenders and features", async () => {
  const { container } = filePage({ body: heidelbergFile });

  expect(await screen.findByRole("heading", { level: 1, name: "Heidelberg" })).toBeTruthy();
  expect(screen.getByText("Rank 1 of 2")).toBeTruthy();
  expect(screen.getByText(FACTS)).toBeTruthy();
  const breadcrumb = screen.getByRole("navigation", { name: "Back to the forecast" });
  const back = within(breadcrumb).getByRole("link", { name: "Forecast" });
  expect(back.getAttribute("href")).toBe("/forecast");

  const reasons = screen.getByRole("region", { name: "Why it ranks here" });
  expect(
    within(reasons)
      .getAllByRole("listitem")
      .map((item) => item.textContent),
  ).toEqual(["Council decision0.69", "Funding granted0.69"]);
  const signals = screen.getByRole("table", { name: "2 signals" });
  expect(cells(within(signals).getAllByRole("row")[1])).toEqual([
    "Funding granted",
    "",
    "Sep 1, 2025",
    "BEW Modul 2",
    "",
  ]);
  expect(within(signals).getByRole("link", { name: "Open the source" })).toBeTruthy();
  const tenders = screen.getByRole("table", { name: "1 tender" });
  expect(cells(within(tenders).getAllByRole("row")[1])).toEqual([
    "Planung Wärmenetz Bahnstadt SüdStadtwerke Heidelberg",
    "Planning",
    "Awarded",
    "Mar 1, 2024",
    "€480,000",
    "Ingenieurbüro Nord",
  ]);
  expect(screen.getByRole("table", { name: "2 runs" })).toBeTruthy();
  expect(screen.getByRole("table", { name: "2 features" })).toBeTruthy();
  expect(await violations(container)).toEqual([]);
});

test("a municipality not scored yet shows its evidence and says no forecast ran", async () => {
  filePage({
    body: {
      ...heidelbergFile,
      model: null,
      as_of: null,
      rank: null,
      total: 0,
      score: null,
      reasons: [],
      features: [],
      history: [],
      signals: [],
      tenders: [],
    },
  });

  expect(await screen.findByText("Not scored yet")).toBeTruthy();
  expect(screen.getByText("No forecast yet")).toBeTruthy();
  expect(screen.getByText("No signals known yet.")).toBeTruthy();
  expect(screen.getByText("No tenders known yet.")).toBeTruthy();
  expect(screen.queryByRole("table", { name: "2 features" })).toBeNull();
});

test("a learned model's probability shows beside the rank", async () => {
  filePage({
    body: {
      ...heidelbergFile,
      score: 0.37,
      model: { version: "logistic-1", kind: "logistic", horizon_months: 24, calibrated: true },
    },
  });

  expect(await screen.findByText("Probability 37%")).toBeTruthy();
});

test("an unknown AGS has no file", async () => {
  filePage({ status: 404, body: { detail: "No such municipality" } });

  expect(await screen.findByText("No such municipality")).toBeTruthy();
});

test("the service unavailable, the file offers to try again", async () => {
  filePage({ status: 503 });

  expect(await screen.findByRole("button", { name: "Try again" })).toBeTruthy();
});
