import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { stubApi, unavailableOnce } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { bahnstadt, firstText, SOURCE_ID, secondText } from "#/test/sources.ts";
import { alice, signedIn } from "#/test/users.ts";

const BYLINE = /^By Jane Doe · Published Oct 16, 2026$/;
const SHOWING = /^Version 2 of 2, fetched Oct 17, 2026/;
const VERSION_1 = /^Version 1/;
const VERSION_2 = /^Version 2/;

const SOURCE = `GET /api/sources/${SOURCE_ID}`;
const TEXTS = {
  [`GET /api/sources/${SOURCE_ID}/versions/1`]: { body: firstText },
  [`GET /api/sources/${SOURCE_ID}/versions/2`]: { body: secondText },
};

function sourcePage(url: string, replies: Parameters<typeof stubApi>[0] = {}) {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    [SOURCE]: { body: bahnstadt },
    ...TEXTS,
    ...replies,
  });
  return renderApp(url);
}

test("a Source opens at its latest version: its title, text, details and every version", async () => {
  const { container } = sourcePage(`/sources/${SOURCE_ID}`);

  const title = await screen.findByRole("heading", { level: 1 });
  expect(title.textContent).toBe("Wärmenetz-Ausbau, jetzt auch im Norden");
  expect(await screen.findByText(secondText.text)).toBeTruthy();
  expect(screen.getByText(BYLINE)).toBeTruthy();
  expect(screen.getByText(SHOWING)).toBeTruthy();
  const versions = screen.getByRole("list", { name: "Every version of this Source, newest first" });
  const links = within(versions).getAllByRole("link");
  expect(links.map((link) => link.querySelector("span")?.textContent)).toEqual([
    "Version 2Latest",
    "Version 1",
  ]);
  expect(links[0]?.getAttribute("aria-current")).toBe("page");
  const original = screen.getByRole("link", { name: "Open the original page (new tab)" });
  expect(original.getAttribute("href")).toBe(bahnstadt.url);
  expect(screen.getByText("HTTP 200 · text/html; charset=utf-8")).toBeTruthy();
  expect(await violations(container)).toEqual([]);
});

test("its raw file downloads from the API, for the version shown", async () => {
  sourcePage(`/sources/${SOURCE_ID}?v=1`);

  const download = await screen.findByRole("link", {
    name: "Download the raw file of version 1",
  });

  expect(download.getAttribute("href")).toBe(`/api/sources/${SOURCE_ID}/versions/1/raw`);
  expect(download.hasAttribute("download")).toBe(true);
});

test("an earlier version is one click away, and what changed then one more", async () => {
  const user = userEvent.setup();
  const { container, router } = sourcePage(`/sources/${SOURCE_ID}`);
  await screen.findByText(secondText.text);

  await user.click(screen.getByRole("link", { name: VERSION_1 }));

  expect(await screen.findByText(firstText.text)).toBeTruthy();
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Wärmenetz-Ausbau");

  await user.click(screen.getByRole("link", { name: VERSION_2 }));
  await user.click(screen.getByRole("tab", { name: "Changes" }));

  expect(await screen.findByText("Changed from version 1: 3 words added, 2 removed")).toBeTruthy();
  const added = [...container.querySelectorAll("ins")].map((ins) => ins.textContent);
  const removed = [...container.querySelectorAll("del")].map((del) => del.textContent);
  expect(added).toEqual(["[added: jetzt auch ]", "[added: Norden]"]);
  expect(removed).toEqual(["[removed: Süden allein]"]);
  expect(router.state.location.search).toEqual({ v: 2, view: "changes" });
  expect(await violations(container)).toEqual([]);
});

test("the first version has nothing to compare with", async () => {
  sourcePage(`/sources/${SOURCE_ID}?v=1&view=changes`);

  expect(
    await screen.findByText(
      "This is the first version: there is nothing earlier to compare it with.",
    ),
  ).toBeTruthy();
});

test("a version whose files retention deleted says so", async () => {
  sourcePage(`/sources/${SOURCE_ID}?v=1`, {
    [`GET /api/sources/${SOURCE_ID}/versions/1`]: { status: 410, body: { detail: "gone" } },
  });

  expect(await screen.findByText("This version's files are no longer kept.")).toBeTruthy();
});

test("a Source that is gone, or a version it lacks, leads back to the Sources", async () => {
  sourcePage(`/sources/${SOURCE_ID}?v=7`);

  expect(await screen.findByText("No such Source")).toBeTruthy();
  const back = within(screen.getByRole("navigation", { name: "Where you are" }));
  expect(back.getByRole("link", { name: "Sources" }).getAttribute("href")).toBe("/sources");
});

test("an unknown Source is not found", async () => {
  sourcePage(`/sources/${SOURCE_ID}`, { [SOURCE]: { status: 404, body: { detail: "none" } } });

  expect(await screen.findByText("No such Source")).toBeTruthy();
});

test("if the Source cannot load, it offers to try again", async () => {
  const user = userEvent.setup();
  sourcePage(`/sources/${SOURCE_ID}`, { [SOURCE]: unavailableOnce({ body: bahnstadt }, "error") });

  await user.click(await screen.findByRole("button", { name: "Try again" }));

  expect(await screen.findByText(secondText.text)).toBeTruthy();
});
