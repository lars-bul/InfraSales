import { screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { stubApi, unavailableOnce } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { bahnstadt, firstText, SOURCE_ID, secondText } from "#/test/sources.ts";
import { alice, signedIn } from "#/test/users.ts";

const BYLINE = /^By /;
const CHANGED = /^Changed from version 1/;

const FIRST = `GET /api/sources/${SOURCE_ID}/versions/1`;
const SECOND = `GET /api/sources/${SOURCE_ID}/versions/2`;

function sourcePage(url: string, replies: Parameters<typeof stubApi>[0] = {}) {
  stubApi({
    "GET /api/auth/session": signedIn(alice),
    [`GET /api/sources/${SOURCE_ID}`]: { body: bahnstadt },
    [FIRST]: { body: firstText },
    [SECOND]: { body: secondText },
    ...replies,
  });
  return renderApp(url);
}

test("a text without byline or date is shown alone", async () => {
  sourcePage(`/sources/${SOURCE_ID}`, {
    [SECOND]: { body: { ...secondText, author: null, published_at: null } },
  });

  await screen.findByText(secondText.text);

  expect(screen.queryByText(BYLINE)).toBeNull();
});

test("only whitespace changed: it says so", async () => {
  sourcePage(`/sources/${SOURCE_ID}?view=changes`, {
    [SECOND]: { body: { ...firstText, number: 2, text: `${firstText.text}\n` } },
  });

  expect(await screen.findByText("Only whitespace changed from version 1.")).toBeTruthy();
});

test("while a text loads it says so; if it cannot load, it offers to try again", async () => {
  const user = userEvent.setup();
  sourcePage(`/sources/${SOURCE_ID}?view=changes`, {
    [FIRST]: unavailableOnce({ body: firstText }, "error"),
  });

  await user.click(await screen.findByRole("button", { name: "Try again" }));

  expect(await screen.findByText(CHANGED)).toBeTruthy();
});

test("a long text's changes show with the words around them; the whole text is a click away", async () => {
  const user = userEvent.setup();
  const long = (word: string) =>
    `${Array.from({ length: 200 }, () => "unchanged").join(" ")} ${word}.`;
  sourcePage(`/sources/${SOURCE_ID}?view=changes`, {
    [FIRST]: { body: { ...firstText, text: long("before") } },
    [SECOND]: { body: { ...secondText, text: long("after") } },
  });

  expect(await screen.findByText("175 unchanged words")).toBeTruthy();

  await user.click(screen.getByRole("button", { name: "Show the whole text" }));

  expect(screen.queryByText("175 unchanged words")).toBeNull();
  expect(screen.getByRole("button", { name: "Show only the changes" })).toBeTruthy();
});
