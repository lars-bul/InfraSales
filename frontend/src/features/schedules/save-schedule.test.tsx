import { act, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { DEADLINE_MS } from "#/api/deadline.ts";
import { weekly } from "#/test/entries.ts";
import { inTurn, unavailableOnce } from "#/test/fetch.ts";
import { SAVE_SCHEDULE, savesOf, scheduleAdminPage, scheduleForm } from "#/test/schedules.ts";

// A save left without answer (no connection, the deadline) may or may not have been stored: the
// form and the switch reread the schedule to find out, and never send it again on their own.

afterEach(() => {
  vi.useRealTimers();
});

test("a failed connection is announced once rereading shows nothing was saved", async () => {
  const { calls } = scheduleAdminPage(weekly, {
    [SAVE_SCHEDULE]: unavailableOnce({ body: weekly }, "offline"),
  });
  const schedule = await scheduleForm();

  await userEvent.click(schedule.getByRole("button", { name: "Save" }));

  expect((await schedule.findByRole("alert")).textContent).toContain("unavailable");
  expect(await savesOf(calls)).toHaveLength(1);
});

const changedElsewhere = { ...weekly.value, time: "09:00" };

test.each([
  ["saved after all", { ...weekly, revision: 2 }, "Saved.", '"2"'],
  [
    "saved by someone else",
    { ...weekly, revision: 2, value: changedElsewhere },
    "meanwhile",
    '"2"', // their change is in the form now
  ],
  ["not saved", weekly, "unavailable", '"1"'],
])("a save left without answer is resolved by rereading (%s)", async (_, stored, message, next) => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const { calls } = scheduleAdminPage(weekly, {
    [SAVE_SCHEDULE]: unavailableOnce({ body: weekly }, "stalled"),
    "GET /api/config": inTurn({ body: [weekly] }, { body: [stored] }),
  });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  const schedule = await scheduleForm();

  await user.click(schedule.getByRole("button", { name: "Save" }));
  await act(() => vi.advanceTimersByTimeAsync(DEADLINE_MS / 2));
  expect(schedule.getByLabelText("Time").matches(":disabled")).toBe(true); // locked meanwhile
  await act(() => vi.advanceTimersByTimeAsync(DEADLINE_MS / 2));

  expect((await schedule.findByText(new RegExp(message))).textContent).toContain(message);
  await user.click(schedule.getByRole("button", { name: "Save" })); // over what the reread found
  expect((await savesOf(calls))[1]?.ifMatch).toBe(next);
});

test("a switch left without answer, but stored, is announced as saved", async () => {
  const pausedNow = { ...weekly, revision: 2, value: { ...weekly.value, enabled: false } };
  const { calls } = scheduleAdminPage(weekly, {
    [SAVE_SCHEDULE]: unavailableOnce({ body: weekly }, "offline"),
    "GET /api/config": inTurn({ body: [weekly] }, { body: [pausedNow] }),
  });
  await screen.findByRole("heading", { level: 1, name: "Source Collection" });
  const job = screen; // the switch sits in the job page's header
  const onOff = job.getByRole("switch", { name: "Run Source Collection on its schedule" });

  await userEvent.click(onOff);

  expect(await job.findByText("The Source Collection is paused.")).toBeTruthy();
  expect(onOff.getAttribute("aria-checked")).toBe("false");
  expect(await savesOf(calls)).toHaveLength(1);
});
