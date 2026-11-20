import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { violations } from "#/test/axe.ts";
import { stubApi } from "#/test/fetch.ts";
import { heuristicModel, learnedRanking, noForecast, ranked } from "#/test/forecast.ts";
import { renderApp } from "#/test/render.tsx";
import { alice, signedIn, vera } from "#/test/users.ts";

const RANKING = "GET /api/forecast/municipalities";
const IN_BW = `/forecast?${new URLSearchParams({ region: "08" })}`; // Baden-Württemberg
const IN_BREMEN = `/forecast?${new URLSearchParams({ region: "04" })}`;
const ORDER_NOT_SCORE = /The order matters, not the score/;
const WITHIN_24_MONTHS = /within 24 months/;

afterEach(() => {
  vi.restoreAllMocks();
});

function forecastPage(
  url: string,
  replies: Parameters<typeof stubApi>[0],
  user: typeof alice | typeof vera = vera,
) {
  const calls = stubApi({ "GET /api/auth/session": signedIn(user), ...replies });
  const asked = () =>
    calls
      .filter((call) => new URL(call.url).pathname === "/api/forecast/municipalities")
      .map((call) => Object.fromEntries(new URL(call.url).searchParams));
  return { asked, ...renderApp(url) };
}

function cells(row: HTMLElement | undefined) {
  return within(row as HTMLElement)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
}

test("the forecast ranks the municipalities with their reasons, each leading to its file", async () => {
  const { container, asked } = forecastPage("/forecast", { [RANKING]: { body: ranked } });

  const table = await screen.findByRole("table", {
    name: "2 municipalities of 2, most likely first",
  });

  expect(screen.getByRole("heading", { level: 1, name: "Forecast" })).toBeTruthy();
  const [, first, second] = within(table).getAllByRole("row");
  expect(cells(first)).toEqual(["1", "Heidelberg", "162,000", "Council decisionFunding granted"]);
  expect(cells(second)).toEqual(["2", "Ulm", "128,000", "Nothing stands out"]);
  const link = within(table).getByRole("link", { name: "Heidelberg" });
  expect(link.getAttribute("href")).toBe("/forecast/08221000");
  expect(screen.getByText(ORDER_NOT_SCORE)).toBeTruthy();
  expect(asked()).toEqual([{ region: "", limit: "50", offset: "0" }]);
  expect(screen.queryByRole("region", { name: "Models" })).toBeNull(); // admins only
  expect(await violations(container)).toEqual([]);
});

test("a learned model's scores show as probabilities within its horizon", async () => {
  forecastPage("/forecast", { [RANKING]: { body: learnedRanking } });

  const table = await screen.findByRole("table");

  expect(within(table).getByRole("columnheader", { name: "Probability" })).toBeTruthy();
  expect(cells(within(table).getAllByRole("row")[1])).toContain("37%");
  expect(screen.getByText(WITHIN_24_MONTHS)).toBeTruthy();
});

test("a region narrows the list and is kept in the address", async () => {
  const { asked, router } = forecastPage("/forecast", { [RANKING]: { body: ranked } });
  await screen.findByRole("table");

  await userEvent.selectOptions(screen.getByLabelText("Region"), "Baden-Württemberg");

  await vi.waitFor(() =>
    expect(asked().at(-1)).toEqual({ region: "08", limit: "50", offset: "0" }),
  );
  expect(router.state.location.search).toEqual({ region: "08" });
});

test("pages follow each other, and the page is kept in the address", async () => {
  const many = { ...ranked, total: 120 };
  const { asked, router } = forecastPage(IN_BW, { [RANKING]: { body: many } });
  await screen.findByRole("table");

  expect(screen.getByText("1–2 of 120")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Previous" }).hasAttribute("disabled")).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "Next" }));

  await vi.waitFor(() =>
    expect(asked().at(-1)).toEqual({ region: "08", limit: "50", offset: "50" }),
  );
  expect(router.state.location.search).toEqual({ region: "08", page: 2 });
});

test("before any forecast ran, the page says how one comes about", async () => {
  forecastPage("/forecast", { [RANKING]: { body: noForecast } });

  expect(await screen.findByText("No forecast yet")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Export CSV" }).hasAttribute("disabled")).toBe(true);
});

test("a model activated but not run yet is announced as being computed", async () => {
  const pending = { ...ranked, as_of: null, total: 0, items: [] };
  forecastPage("/forecast", { [RANKING]: { body: pending } });

  expect(await screen.findByText("The forecast is being computed")).toBeTruthy();
});

test("a region without municipalities says so", async () => {
  const empty = { ...ranked, total: 0, items: [] };
  forecastPage(IN_BREMEN, { [RANKING]: { body: empty } });

  expect(await screen.findByText("No municipality here")).toBeTruthy();
});

test("the export saves the region's list as CSV, up to 500 municipalities", async () => {
  const saved: Blob[] = [];
  vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
    saved.push(blob as Blob);
    return "blob:forecast";
  });
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  const { asked } = forecastPage(IN_BW, { [RANKING]: { body: ranked } });
  await screen.findByRole("table");

  await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));

  await vi.waitFor(() => expect(click).toHaveBeenCalled());
  expect(asked().at(-1)).toEqual({ region: "08", limit: "500", offset: "0" });
  const text = await saved[0]?.text();
  expect(text?.split("\r\n")[1]).toBe(
    "1;08221000;Heidelberg;162000;0.0123;Council decision | Funding granted",
  );
});

test("the service unavailable, the list offers to try again", async () => {
  forecastPage("/forecast", { [RANKING]: { status: 503 } });

  expect(await screen.findByRole("button", { name: "Try again" })).toBeTruthy();
});

test("admins see the model versions below the list", async () => {
  forecastPage(
    "/forecast",
    { [RANKING]: { body: ranked }, "GET /api/forecast/models": { body: [heuristicModel] } },
    alice,
  );

  expect(await screen.findByRole("region", { name: "Models" })).toBeTruthy();
});
