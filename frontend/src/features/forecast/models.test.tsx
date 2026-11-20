import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { stubApi } from "#/test/fetch.ts";
import { heuristicModel, learnedModel, ranked } from "#/test/forecast.ts";
import { renderApp } from "#/test/render.tsx";
import { alice, signedIn } from "#/test/users.ts";

const ACTIVATE = `POST /api/forecast/models/${learnedModel.id}/activate`;

function modelsPage(activate: Parameters<typeof stubApi>[0][string]) {
  const calls = stubApi({
    "GET /api/auth/session": signedIn(alice),
    "GET /api/forecast/municipalities": { body: ranked },
    "GET /api/forecast/models": { body: [learnedModel, heuristicModel] },
    [ACTIVATE]: activate,
  });
  renderApp("/forecast");
  return calls;
}

function cells(row: HTMLElement | undefined) {
  return within(row as HTMLElement)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
}

test("each version shows its backtest beside the heuristic's, the active one marked", async () => {
  modelsPage({ body: { ...learnedModel, active: true } });

  const table = await screen.findByRole("table", { name: "2 model versions, newest first" });

  const [, learned, heuristic] = within(table).getAllByRole("row");
  expect(cells(learned)).toEqual([
    "logistic-2026-01-01-abc123",
    "Learned",
    "Jan 1, 2026",
    "AUC 0.84 · top 50 34% (heuristic: AUC 0.71)",
    "Activate",
  ]);
  expect(cells(heuristic)).toEqual(["heuristic-1", "Heuristic", "", "—", "Active"]);
});

test("activating a version says it serves from its next run, queued now", async () => {
  const calls = modelsPage({ body: { ...learnedModel, active: true } });
  await screen.findByRole("table", { name: "2 model versions, newest first" });

  await userEvent.click(screen.getByRole("button", { name: "Activate" }));

  expect(
    await screen.findByText(
      "logistic-2026-01-01-abc123 serves the forecast from its next run, queued now.",
    ),
  ).toBeTruthy();
  expect(calls.some((call) => call.method === "POST")).toBe(true);
});

test("an activation that failed says so", async () => {
  modelsPage({ status: 503 });
  await screen.findByRole("table", { name: "2 model versions, newest first" });

  await userEvent.click(screen.getByRole("button", { name: "Activate" }));

  expect(
    await screen.findByText("Not activated: the service is unavailable. Please try again."),
  ).toBeTruthy();
});
