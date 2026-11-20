import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { violations } from "#/test/axe.ts";
import { dashboard, lastCollection } from "#/test/dashboard.ts";
import { heizwerk } from "#/test/feeds.ts";
import { stalled, unavailableOnce } from "#/test/fetch.ts";
import { collected } from "#/test/runs.ts";

afterEach(() => {
  vi.useRealTimers();
});

// A stage of the strip, found by its name, as the text it shows: name, figure, line.
async function stage(name: string): Promise<string[]> {
  const strip = within(await screen.findByRole("list", { name: "How collecting works" }));
  const found = strip.getAllByRole("listitem").find((item) => item.textContent?.startsWith(name));
  if (!found) {
    throw new Error(`no stage ${name}`);
  }
  await within(found).findAllByRole("paragraph");
  return within(found)
    .getAllByRole("paragraph")
    .map((line) => line.textContent ?? "");
}

test("the Feeds stage counts the Feeds and, in red, those the last collection could not read", async () => {
  dashboard();

  await screen.findByText("2 not read");
  expect(await stage("Feeds")).toEqual(["5", "2 not read"]);
  expect(screen.getByText("2 not read").className).toContain("text-destructive");
});

test.each([
  [[heizwerk], ["1", "All read"]],
  [[], ["0", "No Feeds yet"]],
])("with Feeds %#, the stage reads calm", async (feeds, shown) => {
  dashboard(undefined, { feeds });

  await screen.findByText(shown[1] ?? "");
  expect(await stage("Feeds")).toEqual(shown);
});

test("the Sources stage shows what the last collection found, and how long ago", async () => {
  dashboard();

  await screen.findByText("new Source Versions, 2 hours ago");
  expect(await stage("Sources")).toEqual(["42", "new Source Versions, 2 hours ago"]);
});

test("one new Source Version reads in the singular; a run still going counts from when it was due", async () => {
  dashboard(undefined, {
    collections: [{ ...lastCollection, finished_at: null, result: collected({ versions_new: 1 }) }],
  });

  expect(await screen.findByText("new Source Version, 3 hours ago")).toBeTruthy();
});

test("before any collection, the Sources stage says so", async () => {
  dashboard(undefined, { collections: [] });

  await screen.findByText("No collection yet");
  expect(await stage("Sources")).toEqual(["–", "No collection yet"]);
});

test("a stage the service cannot answer offers to try again, and then shows its figure", async () => {
  const { container } = dashboard(undefined, undefined, {
    "GET /api/feeds": unavailableOnce({ body: [heizwerk] }, "error"),
  });

  const strip = within(await screen.findByRole("list", { name: "How collecting works" }));
  const retry = await strip.findByRole("button", { name: "Try again" });
  expect(await violations(container)).toEqual([]);
  await userEvent.click(retry);

  expect(await strip.findByText("All read")).toBeTruthy();
});

test("while a stage loads, it says so", async () => {
  dashboard(undefined, undefined, { "GET /api/feeds": stalled });

  const strip = within(await screen.findByRole("list", { name: "How collecting works" }));
  const feeds = strip
    .getAllByRole("listitem")
    .find((item) => item.textContent?.startsWith("Feeds"));
  expect(within(feeds as HTMLElement).getByRole("status").textContent).toBe("Loading…");
});
