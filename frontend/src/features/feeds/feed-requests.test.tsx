import { act, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { DEADLINE_MS } from "#/api/deadline.ts";
import {
  ADD,
  chooseCategory,
  feedsAdminPage,
  findFeed,
  heizwerk,
  openAddFeed,
  SUGGEST,
  sentTo,
  suggestion,
  waermewende,
} from "#/test/feeds.ts";
import { inTurn, unavailableOnce } from "#/test/fetch.ts";

// An add left without answer (no connection, the deadline) may or may not have been stored: the
// dialog reads the Feeds to find out, and never sends it again on its own.

const LOOKING = /Looking for the site's feed or sitemap/u;
const UNREACHABLE = "InfraSales could not be reached. Please try again.";

afterEach(() => {
  vi.useRealTimers();
});

async function foundAndAdd() {
  const { dialog, within: inDialog } = await openAddFeed();
  await findFeed(inDialog);
  await inDialog.findByRole("textbox", { name: "Name" });
  await chooseCategory(inDialog);
  await userEvent.click(inDialog.getByRole("button", { name: "Add Feed" }));
  return { dialog, inDialog };
}

test("an add left without answer, but stored, counts as added", async () => {
  const { calls } = feedsAdminPage([heizwerk], {
    [SUGGEST]: { body: suggestion },
    [ADD]: unavailableOnce({ status: 201, body: waermewende }, "offline"),
    "GET /api/feeds": inTurn({ body: [heizwerk] }, { body: [heizwerk, waermewende] }),
  });

  const { dialog } = await foundAndAdd();

  await waitFor(() => expect(dialog.isConnected).toBe(false));
  expect(
    screen.getByText("waermewende is added. The next Source Collection reads it."),
  ).toBeTruthy();
  expect(await screen.findByRole("table", { name: "2 Feeds" })).toBeTruthy();
  expect(await sentTo(calls, ADD)).toHaveLength(1);
});

test("an add left without answer, and not stored, says so and keeps the dialog", async () => {
  const { calls } = feedsAdminPage([heizwerk], {
    [SUGGEST]: { body: suggestion },
    [ADD]: unavailableOnce({ status: 201, body: waermewende }, "offline"),
  });

  const { inDialog } = await foundAndAdd();

  expect((await inDialog.findByRole("alert")).textContent).toBe(UNREACHABLE);
  expect(await sentTo(calls, ADD)).toHaveLength(1);
});

test("an add InfraSales cannot take (a server error) is not added", async () => {
  feedsAdminPage([heizwerk], { [SUGGEST]: { body: suggestion }, [ADD]: { status: 500, body: {} } });

  const { inDialog } = await foundAndAdd();

  expect((await inDialog.findByRole("alert")).textContent).toBe(UNREACHABLE);
});

test("finding a Feed locks the dialog while it waits, and an unanswered search says so", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  feedsAdminPage([heizwerk], { [SUGGEST]: unavailableOnce({ body: suggestion }, "stalled") });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  const trigger = await screen.findByRole("button", { name: "Add Feed" });
  await user.click(trigger);
  const dialog = await screen.findByRole("dialog", { name: "Add Feed" });
  const site = screen.getByRole("textbox", { name: "Site address" });
  await user.type(site, "https://waermewende.test");
  await user.click(screen.getByRole("button", { name: "Find Feed" }));

  expect(site.matches(":disabled")).toBe(true);
  expect(screen.getByText(LOOKING).getAttribute("role")).toBe("status");
  await act(() => vi.advanceTimersByTimeAsync(DEADLINE_MS));

  expect((await screen.findByRole("alert")).textContent).toBe(UNREACHABLE);
  expect(site.matches(":disabled")).toBe(false);
  expect(dialog.isConnected).toBe(true);
});
