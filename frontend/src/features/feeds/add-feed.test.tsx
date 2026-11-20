// The dialog is portalled into the body: axe checks the body while it is open.
import { screen, waitFor, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import {
  ADD,
  chooseCategory,
  feedsAdminPage,
  findFeed,
  heizwerk,
  openAddFeed,
  requestsTo,
  SITE,
  SUGGEST,
  sentTo,
  suggestion,
  waermewende,
} from "#/test/feeds.ts";
import { inTurn } from "#/test/fetch.ts";

const ADDED = "waermewende is added. The next Source Collection reads it.";
const NOTHING_FOUND = "Neither a feed nor a sitemap was found there";

test("a Feed found for a site is renamed and added: the list shows it, the status says so", async () => {
  const { calls, container } = feedsAdminPage([heizwerk], {
    [SUGGEST]: { body: suggestion },
    [ADD]: { status: 201, body: waermewende },
    "GET /api/feeds": inTurn({ body: [heizwerk] }, { body: [heizwerk, waermewende] }),
  });
  const { trigger, dialog, within: inDialog } = await openAddFeed();
  expect(document.activeElement).toBe(inDialog.getByRole("textbox", { name: "Site address" }));
  expect(await violations(document.body)).toEqual([]);

  await findFeed(inDialog);

  const name = await inDialog.findByRole("textbox", { name: "Name" });
  expect((name as HTMLInputElement).value).toBe("waermewende.test");
  expect(document.activeElement).toBe(name);
  expect(inDialog.getByText("RSS")).toBeTruthy();
  expect(inDialog.getByText("https://waermewende.test/feed/")).toBeTruthy();
  expect(inDialog.queryByRole("combobox", { name: "Kind" })).toBeNull(); // kept as found
  expect(await violations(document.body)).toEqual([]);

  await userEvent.clear(name);
  await userEvent.type(name, "waermewende");
  await chooseCategory(inDialog);
  await userEvent.click(inDialog.getByRole("button", { name: "Add Feed" }));

  await waitFor(() => expect(dialog.isConnected).toBe(false));
  const table = await screen.findByRole("table", { name: "2 Feeds" });
  expect(within(table).getByText("waermewende")).toBeTruthy();
  expect(screen.getByText(ADDED).getAttribute("role")).toBe("status");
  await waitFor(() => expect(document.activeElement).toBe(trigger));
  expect(await sentTo(calls, SUGGEST)).toEqual([{ url: SITE }]);
  expect(await sentTo(calls, ADD)).toEqual([
    { name: "waermewende", kind: "rss", url: "https://waermewende.test/feed/", category: "press" },
  ]);
  // the loader read the list (on a slow machine the page may read it once more as it opens),
  // and once added it is read again, once
  const reads = calls
    .map((call) => `${call.method} ${new URL(call.url).pathname}`)
    .filter((route) => route === ADD || route === "GET /api/feeds");
  expect(reads.slice(reads.indexOf(ADD))).toEqual([ADD, "GET /api/feeds"]);
  expect(await violations(container)).toEqual([]); // closed: the page alone
});

test("a site address without a scheme is asked for as https", async () => {
  const { calls } = feedsAdminPage([heizwerk], { [SUGGEST]: { body: suggestion } });
  const { within: inDialog } = await openAddFeed();

  await findFeed(inDialog, "  waermewende.test ");

  expect(await inDialog.findByRole("textbox", { name: "Name" })).toBeTruthy();
  expect(await sentTo(calls, SUGGEST)).toEqual([{ url: "https://waermewende.test" }]);
});

test("when nothing is found, the Feed is entered by hand: name, RSS or Sitemap, address", async () => {
  const { calls } = feedsAdminPage([heizwerk], {
    [SUGGEST]: { status: 422, body: { detail: NOTHING_FOUND } },
    [ADD]: { status: 201, body: { ...waermewende, kind: "sitemap" } },
  });
  const { dialog, within: inDialog } = await openAddFeed();

  await findFeed(inDialog);

  expect((await inDialog.findByRole("alert")).textContent).toBe(NOTHING_FOUND);
  expect(await violations(document.body)).toEqual([]);
  await userEvent.click(inDialog.getByRole("button", { name: "Enter the Feed yourself" }));

  const name = inDialog.getByRole("textbox", { name: "Name" });
  expect(document.activeElement).toBe(name);
  const kind = inDialog.getByRole("combobox", { name: "Kind" });
  expect(
    within(kind)
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual(["RSS", "Sitemap"]);
  expect(await violations(document.body)).toEqual([]);
  await userEvent.type(name, "waermewende");
  await chooseCategory(inDialog, "Utility");
  await userEvent.selectOptions(kind, "Sitemap");
  await userEvent.type(
    inDialog.getByRole("textbox", { name: "Feed address" }),
    "https://waermewende.test/sitemap.xml",
  );
  await userEvent.click(inDialog.getByRole("button", { name: "Add Feed" }));

  await waitFor(() => expect(dialog.isConnected).toBe(false));
  expect(screen.getByText(ADDED)).toBeTruthy();
  expect(await sentTo(calls, ADD)).toEqual([
    {
      name: "waermewende",
      kind: "sitemap",
      url: "https://waermewende.test/sitemap.xml",
      category: "utility",
    },
  ]);
});

test.each([
  "That address is not allowed",
  "That site blocks InfraSales' bot",
  "That address could not be read",
  NOTHING_FOUND,
])("a site InfraSales refuses shows the API's reason as it comes: %s", async (detail) => {
  feedsAdminPage([heizwerk], { [SUGGEST]: { status: 422, body: { detail } } });
  const { within: inDialog } = await openAddFeed();

  await findFeed(inDialog);

  expect((await inDialog.findByRole("alert")).textContent).toBe(detail);
  const site = inDialog.getByRole("textbox", { name: "Site address" });
  expect(site.getAttribute("aria-invalid")).toBe("true");
  expect(site.getAttribute("aria-describedby")).toBe(inDialog.getByRole("alert").id);
  expect(await violations(document.body)).toEqual([]);
});

const malformed = {
  detail: [{ type: "url_parsing", loc: ["body", "url"], msg: "Input should be a valid URL" }],
};

test.each([
  ["a malformed address", { status: 422, body: malformed }, "That isn't a valid address."],
  [
    "no answer from the site in time",
    { status: 504, body: {} },
    "The site did not answer in time.",
  ],
  [
    "InfraSales failing",
    { status: 500, body: {} },
    "InfraSales could not be reached. Please try again.",
  ],
])("finding a Feed tells %s", async (_, reply, message) => {
  feedsAdminPage([heizwerk], { [SUGGEST]: reply });
  const { within: inDialog } = await openAddFeed();

  await findFeed(inDialog, "https://exa mple.org");

  expect((await inDialog.findByRole("alert")).textContent).toBe(message);
  expect(await violations(document.body)).toEqual([]);
  // the address stays, to correct it and try again
  expect((inDialog.getByRole("textbox", { name: "Site address" }) as HTMLInputElement).value).toBe(
    "https://exa mple.org",
  );
});

test.each([
  [
    "already a Feed",
    { status: 409, body: { detail: "A Feed has that address already" } },
    "A Feed with that address exists already.",
  ],
  ["a malformed address", { status: 422, body: malformed }, "That isn't a valid address."],
])(
  "adding a Feed tells when its address is %s, and the dialog stays",
  async (_, reply, message) => {
    feedsAdminPage([heizwerk], { [ADD]: reply });
    const { within: inDialog } = await openAddFeed();
    await userEvent.click(inDialog.getByRole("button", { name: "Enter the Feed yourself" }));
    await userEvent.type(inDialog.getByRole("textbox", { name: "Name" }), "heizwerk again");
    await chooseCategory(inDialog);
    await userEvent.type(inDialog.getByRole("textbox", { name: "Feed address" }), heizwerk.url);

    await userEvent.click(inDialog.getByRole("button", { name: "Add Feed" }));

    expect((await inDialog.findByRole("alert")).textContent).toBe(message);
    expect(screen.getByRole("dialog", { name: "Add Feed" })).toBeTruthy();
    expect(await violations(document.body)).toEqual([]);
  },
);

test("Back returns to the site's address as entered; closing starts the dialog afresh", async () => {
  feedsAdminPage([heizwerk], { [SUGGEST]: { body: suggestion } });
  const first = await openAddFeed();
  await findFeed(first.within);
  await first.within.findByRole("textbox", { name: "Name" });

  await userEvent.click(first.within.getByRole("button", { name: "Back" }));

  const site = first.within.getByRole("textbox", { name: "Site address" });
  expect((site as HTMLInputElement).value).toBe(SITE);
  expect(document.activeElement).toBe(site);

  await userEvent.keyboard("{Escape}");
  await waitFor(() => expect(first.dialog.isConnected).toBe(false));
  await waitFor(() => expect(document.activeElement).toBe(first.trigger));
  const again = await openAddFeed();
  expect(
    (again.within.getByRole("textbox", { name: "Site address" }) as HTMLInputElement).value,
  ).toBe("");
});

test("with no Feeds yet, Add Feed is there, and the first Feed replaces the empty state", async () => {
  feedsAdminPage([], {
    [SUGGEST]: { body: suggestion },
    [ADD]: { status: 201, body: waermewende },
    "GET /api/feeds": inTurn({ body: [] }, { body: [waermewende] }),
  });
  expect(await screen.findByText("No Feeds yet")).toBeTruthy();
  const { within: inDialog } = await openAddFeed();
  await findFeed(inDialog);
  await inDialog.findByRole("textbox", { name: "Name" });
  await chooseCategory(inDialog);

  await userEvent.click(inDialog.getByRole("button", { name: "Add Feed" }));

  expect(await screen.findByRole("table", { name: "1 Feed" })).toBeTruthy();
  expect(screen.queryByText("No Feeds yet")).toBeNull();
  expect(screen.getByText(ADDED)).toBeTruthy(); // named as stored
});

test("the category is chosen for every Feed: none is set before, and its hint says what belongs there", async () => {
  const { calls } = feedsAdminPage([heizwerk], { [SUGGEST]: { body: suggestion } });
  const { within: inDialog } = await openAddFeed();
  await findFeed(inDialog);
  await inDialog.findByRole("textbox", { name: "Name" });

  const category = inDialog.getByRole("combobox", { name: "Category" }) as HTMLSelectElement;
  expect(
    within(category)
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual(["Choose a category", "Press", "Municipality", "Utility", "Procurement", "Authority"]);
  expect(category.value).toBe("");
  expect(category.required).toBe(true);

  await userEvent.click(inDialog.getByRole("button", { name: "Add Feed" }));

  expect(requestsTo(calls, ADD)).toEqual([]); // nothing is sent without a category
  expect(screen.getByRole("dialog", { name: "Add Feed" })).toBeTruthy();

  await chooseCategory(inDialog, "Authority");

  expect(category.getAttribute("aria-describedby")).toBeTruthy();
  expect(
    inDialog.getByText("A state or federal authority: energy atlases, funding, registers.").id,
  ).toBe(category.getAttribute("aria-describedby"));
  expect(await violations(document.body)).toEqual([]);
});
