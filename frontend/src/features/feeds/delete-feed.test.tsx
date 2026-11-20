// The question is portalled into the body: axe checks the body while it is open.
import { screen, waitFor, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import type { FeedRead } from "#/client/types.gen.ts";
import { violations } from "#/test/axe.ts";
import {
  chooseCategory,
  feedsAdminPage,
  heizwerk,
  ratsinfo,
  requestsTo,
  waermewende,
} from "#/test/feeds.ts";
import { inTurn, unavailableOnce } from "#/test/fetch.ts";

const DELETE = `DELETE /api/feeds/${waermewende.id}`;
const QUESTION = "Delete the Feed waermewende?";
const DELETED = "waermewende is deleted.";
const UNREACHABLE = "InfraSales could not be reached. Please try again.";
const NOTHING_LOST = /It has collected no Sources yet, so nothing else is lost/u;
const ADDED = /is added/u;

async function askToDelete(name = "waermewende") {
  await userEvent.click(await screen.findByRole("button", { name: `Delete ${name}` }));
  return await screen.findByRole("alertdialog", { name: `Delete the Feed ${name}?` });
}

// The Feed's name in its row (the address follows it in the same cell); behind a question too.
function listedAs(name: string, how: "get" | "query" = "get") {
  return how === "get"
    ? screen.getByText(name, { selector: "td *" })
    : screen.queryByText(name, { selector: "td *" });
}

function listed(...feeds: FeedRead[]) {
  return { body: feeds };
}

test("only Feeds that have collected no Sources can be deleted", async () => {
  const { container } = feedsAdminPage([ratsinfo, heizwerk, waermewende]);

  await screen.findByRole("table", { name: "3 Feeds" });

  expect(screen.getByRole("button", { name: "Delete Ratsinfo Ulm" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Delete waermewende" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Delete Heizwerk Journal" })).toBeNull();
  expect(await violations(container)).toEqual([]);
});

test("a Feed just added is deleted once confirmed: the list loses it, the status says so", async () => {
  const { calls, container } = feedsAdminPage([heizwerk, waermewende], {
    [DELETE]: { status: 204 },
    "GET /api/feeds": inTurn(listed(heizwerk, waermewende), listed(heizwerk)),
  });

  const question = await askToDelete();

  expect(within(question).getByText(NOTHING_LOST)).toBeTruthy();
  expect(await violations(document.body)).toEqual([]);
  await userEvent.click(within(question).getByRole("button", { name: "Delete Feed" }));

  expect(await screen.findByRole("table", { name: "1 Feed" })).toBeTruthy();
  await waitFor(() => expect(question.isConnected).toBe(false));
  expect(listedAs("waermewende", "query")).toBeNull();
  expect(screen.getByText(DELETED).getAttribute("role")).toBe("status");
  // its row is gone: focus is on Add Feed
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Add Feed" })),
  );
  expect(requestsTo(calls, DELETE)).toHaveLength(1);
  expect(await violations(container)).toEqual([]);
});

test("cancelled, nothing is deleted, and focus is back on Delete", async () => {
  const { calls } = feedsAdminPage([heizwerk, waermewende]);
  const question = await askToDelete();

  await userEvent.click(within(question).getByRole("button", { name: "Cancel" }));

  await waitFor(() => expect(question.isConnected).toBe(false));
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Delete waermewende" })),
  );
  expect(calls.filter((call) => call.method === "DELETE")).toEqual([]);
});

test("a Feed that collected Sources meanwhile stays, and loses Delete once the question closes", async () => {
  feedsAdminPage([heizwerk, waermewende], {
    [DELETE]: { status: 409, body: { detail: "The Feed has collected Sources, so it stays" } },
    "GET /api/feeds": inTurn(
      listed(heizwerk, waermewende),
      listed(heizwerk, { ...waermewende, has_sources: true }),
    ),
  });
  const question = await askToDelete();

  await userEvent.click(within(question).getByRole("button", { name: "Delete Feed" }));

  expect((await within(question).findByRole("alert")).textContent).toBe(
    "It has collected Sources meanwhile, so it stays.",
  );
  expect(await violations(document.body)).toEqual([]);
  await userEvent.click(within(question).getByRole("button", { name: "Cancel" }));

  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Delete waermewende" })).toBeNull(),
  );
  expect(listedAs("waermewende")).toBeTruthy();
});

test("a Feed someone else deleted first counts as deleted", async () => {
  feedsAdminPage([heizwerk, waermewende], {
    [DELETE]: { status: 404, body: { detail: "No Feed has that ID" } },
    "GET /api/feeds": inTurn(listed(heizwerk, waermewende), listed(heizwerk)),
  });
  const question = await askToDelete();

  await userEvent.click(within(question).getByRole("button", { name: "Delete Feed" }));

  expect(await screen.findByText(DELETED)).toBeTruthy();
  expect(await screen.findByRole("table", { name: "1 Feed" })).toBeTruthy();
});

test.each([
  ["left without answer, and still listed", unavailableOnce({ status: 204 }, "offline")],
  ["refused by InfraSales", { status: 500, body: {} }],
])("a delete %s says so, and the Feed stays", async (_, reply) => {
  const { calls } = feedsAdminPage([heizwerk, waermewende], { [DELETE]: reply });
  const question = await askToDelete();

  await userEvent.click(within(question).getByRole("button", { name: "Delete Feed" }));

  expect((await within(question).findByRole("alert")).textContent).toBe(UNREACHABLE);
  // behind the open question, the page is hidden from assistive technology
  expect(listedAs("waermewende")).toBeTruthy();
  expect(requestsTo(calls, DELETE)).toHaveLength(1); // never sent again on its own
});

test("a delete left without answer, but done, counts as deleted", async () => {
  feedsAdminPage([heizwerk, waermewende], {
    [DELETE]: unavailableOnce({ status: 204 }, "offline"),
    "GET /api/feeds": inTurn(listed(heizwerk, waermewende), listed(heizwerk)),
  });
  const question = await askToDelete();

  await userEvent.click(within(question).getByRole("button", { name: "Delete Feed" }));

  expect(await screen.findByText(DELETED)).toBeTruthy();
  expect(await screen.findByRole("table", { name: "1 Feed" })).toBeTruthy();
});

test("a Feed added a moment ago can be deleted at once", async () => {
  feedsAdminPage([heizwerk], {
    "POST /api/feeds": { status: 201, body: waermewende },
    [DELETE]: { status: 204 },
    "GET /api/feeds": inTurn(listed(heizwerk), listed(heizwerk, waermewende), listed(heizwerk)),
  });
  await userEvent.click(await screen.findByRole("button", { name: "Add Feed" }));
  const dialog = within(await screen.findByRole("dialog", { name: "Add Feed" }));
  await userEvent.click(dialog.getByRole("button", { name: "Enter the Feed yourself" }));
  await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "waermewende");
  await chooseCategory(dialog);
  await userEvent.type(dialog.getByRole("textbox", { name: "Feed address" }), waermewende.url);
  await userEvent.click(dialog.getByRole("button", { name: "Add Feed" }));
  expect(await screen.findByText("waermewende is added. The next Source Collection reads it."));

  const question = await askToDelete();
  expect(question.textContent).toContain(QUESTION);
  await userEvent.click(within(question).getByRole("button", { name: "Delete Feed" }));

  expect(await screen.findByText(DELETED)).toBeTruthy(); // in place of "is added"
  expect(screen.queryByText(ADDED)).toBeNull();
  expect(await screen.findByRole("table", { name: "1 Feed" })).toBeTruthy();
});
