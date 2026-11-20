import { screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { bahnstadt, firstText, SOURCE_ID, secondText, secondVersion } from "#/test/sources.ts";
import { alice, signedIn } from "#/test/users.ts";

const VERSION_1 = /^Version 1/;
const VERSION_2 = /^Version 2/;

function sourcePage(url: string, source = bahnstadt) {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    [`GET /api/sources/${SOURCE_ID}`]: { body: source },
    [`GET /api/sources/${SOURCE_ID}/versions/1`]: { body: firstText },
    [`GET /api/sources/${SOURCE_ID}/versions/2`]: { body: secondText },
    [`GET /api/sources/${SOURCE_ID}/versions/3`]: { body: { ...secondText, number: 3 } },
  });
  return renderApp(url);
}

test("versions are grouped by the day they were fetched, newest first", async () => {
  const third = { ...secondVersion, id: "v3", number: 3, fetched_at: "2026-10-17T09:03:00Z" };
  sourcePage(`/sources/${SOURCE_ID}`, { ...bahnstadt, versions: [third, ...bahnstadt.versions] });

  const history = await screen.findByRole("list", {
    name: "Every version of this Source, newest first",
  });

  const days = within(history)
    .getAllByRole("listitem")
    .filter((item) => item.parentElement === history);
  expect(days.map((day) => day.querySelector("p")?.textContent)).toEqual([
    "Oct 17, 2026",
    "Oct 16, 2026",
  ]);
  expect(within(days[0] as HTMLElement).getAllByRole("link")).toHaveLength(2);
});

test("each version keeps the view open: from the changes, to another version's changes", async () => {
  sourcePage(`/sources/${SOURCE_ID}?v=2&view=changes`);

  const first = await screen.findByRole("link", { name: VERSION_1 });

  expect(first.getAttribute("href")).toBe(`/sources/${SOURCE_ID}?v=1&view=changes`);
});

test("a partial version says so", async () => {
  const partial = { ...secondVersion, partial: true };
  sourcePage(`/sources/${SOURCE_ID}`, { ...bahnstadt, versions: [partial] });

  const latest = await screen.findByRole("link", { name: VERSION_2 });

  expect(within(latest).getByText("Partial")).toBeTruthy();
});
