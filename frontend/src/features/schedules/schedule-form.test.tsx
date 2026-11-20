import { fireEvent } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { inTurn } from "#/test/fetch.ts";
import { SAVE_SCHEDULE, savesOf, scheduleAdminPage, scheduleForm } from "#/test/schedules.ts";

const reads = (calls: Request[]) => calls.filter((call) => call.url.endsWith("/api/config"));

test("admins save the whole schedule over the revision shown, and the page shows it", async () => {
  const { calls, container } = scheduleAdminPage();
  const user = userEvent.setup();
  const schedule = await scheduleForm();

  await user.click(schedule.getByRole("radio", { name: "Friday" }));
  fireEvent.change(schedule.getByLabelText("Time"), { target: { value: "17:30" } });
  await user.click(schedule.getByRole("button", { name: "Save" }));

  expect((await schedule.findByRole("status")).textContent).toBe("Saved.");
  expect(document.activeElement).toBe(schedule.getByRole("button", { name: "Save" }));
  expect(await savesOf(calls)).toEqual([
    {
      method: "PUT",
      path: "/api/config/scrape_schedule",
      ifMatch: '"1"',
      body: {
        days: ["fri"],
        time: "17:30",
        timezone: "Europe/Berlin",
        enabled: true,
        every_hours: null,
      },
    },
  ]);
  expect(schedule.getByText("Fri at 17:30 (Europe/Berlin)")).toBeTruthy(); // the preview
  expect(reads(calls)).toHaveLength(1); // the answer is the stored schedule: nothing to reread
  expect(await violations(container)).toEqual([]);
});

test("a save over a changed schedule says so, and the form shows their change", async () => {
  const theirs = { ...weekly, revision: 2, value: { ...weekly.value, time: "09:00" } };
  const { calls, container } = scheduleAdminPage(weekly, {
    [SAVE_SCHEDULE]: inTurn({ status: 412 }, { body: theirs }),
    "GET /api/config": inTurn({ body: [weekly] }, { body: [theirs] }),
  });
  const user = userEvent.setup();
  const schedule = await scheduleForm();

  fireEvent.change(schedule.getByLabelText("Time"), { target: { value: "17:30" } });
  await user.click(schedule.getByRole("button", { name: "Save" }));

  expect((await schedule.findByRole("alert")).textContent).toBe(
    "Not saved: someone changed this schedule meanwhile. Their change is shown now.",
  );
  expect((schedule.getByLabelText("Time") as HTMLInputElement).value).toBe("09:00");
  expect(document.activeElement).toBe(schedule.getByRole("button", { name: "Save" }));
  expect(await violations(container)).toEqual([]);
  await user.click(schedule.getByRole("button", { name: "Save" })); // over their revision
  expect((await savesOf(calls)).map((save) => save.ifMatch)).toEqual(['"1"', '"2"']);
});

test("each save names the revision it edits, the latest after a save", async () => {
  const { calls } = scheduleAdminPage();
  const user = userEvent.setup();
  const schedule = await scheduleForm();

  await user.click(schedule.getByRole("button", { name: "Save" }));
  await schedule.findByText("Saved.");
  await user.click(schedule.getByRole("button", { name: "Save" }));
  await schedule.findByText("Saved.");

  expect((await savesOf(calls)).map((save) => save.ifMatch)).toEqual(['"1"', '"2"']);
});

test("a save while one is in flight is ignored, and progress is announced", async () => {
  let answer: (reply: { body: unknown }) => void = () => undefined;
  const later = new Promise<{ body: unknown }>((resolve) => {
    answer = resolve;
  });
  const { calls } = scheduleAdminPage(weekly, { [SAVE_SCHEDULE]: () => later });
  const user = userEvent.setup();
  const schedule = await scheduleForm();

  await user.click(schedule.getByRole("button", { name: "Save" }));
  await user.click(schedule.getByRole("button", { name: "Save" })); // a double click

  expect(schedule.getByRole("status").textContent).toBe("Saving…");
  expect(schedule.getByLabelText("Time").matches(":disabled")).toBe(true); // nothing to edit
  answer({ body: weekly });
  await schedule.findByText("Saved.");
  expect(await savesOf(calls)).toHaveLength(1);
  expect(schedule.getByLabelText("Time").matches(":disabled")).toBe(false);
  expect(document.activeElement).toBe(schedule.getByRole("button", { name: "Save" })); // back
});

test.each([
  [422, "Not saved: choose at least one day, a time and a time zone."],
  [503, "Not saved: the service is unavailable. Please try again."],
])("a rejected save (%i) is announced, and never retried", async (status, message) => {
  const { calls, container } = scheduleAdminPage(weekly, {
    [SAVE_SCHEDULE]: { status },
  });
  const schedule = await scheduleForm();

  await userEvent.click(schedule.getByRole("button", { name: "Save" }));

  expect((await schedule.findByRole("alert")).textContent).toBe(message);
  expect(document.activeElement).toBe(schedule.getByRole("button", { name: "Save" }));
  expect(await savesOf(calls)).toHaveLength(1);
  expect(await violations(container)).toEqual([]);
});
